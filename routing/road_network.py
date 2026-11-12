"""NetworkX road-network builder from imported OpenStreetMap road features."""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

import networkx as nx
from shapely.errors import GEOSException
from shapely.geometry import LineString, box

from core.geo_utils import calculate_linestring_length_m, haversine_distance_m
from core.models import GridCell, OSMFeature
from services.osm_service import classify_road_category

logger = logging.getLogger(__name__)


def _coord_key(lon: float, lat: float) -> tuple[float, float]:
    """Snap geographic vertex key to ~0.1 m (6 decimals) for genuine intersection detection."""
    return (round(float(lat), 6), round(float(lon), 6))


def _is_valid_coord(pt: Any) -> bool:
    if not isinstance(pt, (list, tuple)) or len(pt) < 2:
        return False
    try:
        lon = float(pt[0])
        lat = float(pt[1])
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(lat)
        and math.isfinite(lon)
        and -90.0 <= lat <= 90.0
        and -180.0 <= lon <= 180.0
    )


def _extract_linestrings(feature: OSMFeature) -> list[list[list[float]]]:
    geom = feature.geometry or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    lines: list[list[list[float]]] = []
    if gtype == "LineString" and isinstance(coords, list):
        clean = [[float(p[0]), float(p[1])] for p in coords if _is_valid_coord(p)]
        if len(clean) >= 2:
            lines.append(clean)
    elif gtype == "MultiLineString" and isinstance(coords, list):
        for part in coords:
            if isinstance(part, list):
                clean = [[float(p[0]), float(p[1])] for p in part if _is_valid_coord(p)]
                if len(clean) >= 2:
                    lines.append(clean)
    return lines


def _feature_center_point(feature: OSMFeature) -> tuple[float, float] | None:
    geom = feature.geometry or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return None
    try:
        if gtype == "Point" and _is_valid_coord(coords):
            return float(coords[1]), float(coords[0])
        if gtype == "LineString" and len(coords) >= 1:
            pts = [p for p in coords if _is_valid_coord(p)]
            if pts:
                mid = pts[len(pts) // 2]
                return float(mid[1]), float(mid[0])
        if gtype == "Polygon" and coords and isinstance(coords[0], list):
            pts = [p for p in coords[0] if _is_valid_coord(p)]
            if pts:
                return (
                    sum(float(p[1]) for p in pts) / len(pts),
                    sum(float(p[0]) for p in pts) / len(pts),
                )
        if gtype == "MultiPolygon" and coords and coords[0] and coords[0][0]:
            pts = [p for p in coords[0][0] if _is_valid_coord(p)]
            if pts:
                return (
                    sum(float(p[1]) for p in pts) / len(pts),
                    sum(float(p[0]) for p in pts) / len(pts),
                )
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return None


@dataclass(slots=True)
class RoadNode:
    """Graph intersection / endpoint node derived from real OSM road coordinates."""

    node_id: int
    neighbourhood_id: int
    osm_id: int | None
    latitude: float
    longitude: float
    label: str = ""
    source: str = "OpenStreetMap"
    connected_roads: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RoadEdge:
    """Graph road segment connecting two intersection nodes along a real OSM geometry."""

    edge_id: int
    neighbourhood_id: int
    osm_feature_id: int | None
    osm_id: int | None
    edge_key: str
    start_node_id: int
    end_node_id: int
    road_name: str
    road_type: str
    distance_m: float
    geometry: dict[str, Any]
    grid_cell_ids: list[int] = field(default_factory=list)
    source: str = "OpenStreetMap"

    # Dynamic evaluation attributes attached by Phase 5 exposure/condition modules
    max_depth_m: float | None = None
    avg_depth_m: float | None = None
    exposure_category: str = "Unknown"
    manual_status: str = "Normal"
    status_source: str = "imported"


@dataclass(slots=True)
class EvacuationDestination:
    """Candidate destination derived from registered shelters, OSM features, or map selection."""

    label: str
    category: str
    latitude: float
    longitude: float
    nearest_node_id: int | None
    snap_distance_m: float
    source: str
    is_verified_shelter: bool = False
    osm_feature_id: int | None = None
    shelter_id: int | None = None
    address: str = ""
    available_capacity: int | None = None
    total_capacity: int | None = None
    shelter_status: str = ""
    facilities: str = ""


class RoadNetworkGraph:
    """Undirected NetworkX MultiGraph preserving parallel streets and split intersections."""

    def __init__(
        self,
        neighbourhood_id: int,
        graph: nx.MultiGraph,
        nodes_by_id: dict[int, RoadNode],
        edges_by_id: dict[int, RoadEdge],
        skipped_feature_count: int = 0,
        warnings: list[str] | None = None,
    ) -> None:
        self.neighbourhood_id = neighbourhood_id
        self.graph = graph
        self.nodes_by_id = nodes_by_id
        self.edges_by_id = edges_by_id
        self.skipped_feature_count = skipped_feature_count
        self.warnings = warnings or []

    @property
    def node_count(self) -> int:
        return len(self.nodes_by_id)

    @property
    def edge_count(self) -> int:
        return len(self.edges_by_id)

    def get_connected_components(self) -> list[set[int]]:
        if self.graph.number_of_nodes() == 0:
            return []
        return sorted(nx.connected_components(self.graph), key=len, reverse=True)

    def are_connected(self, start_node_id: int, end_node_id: int) -> bool:
        if start_node_id not in self.graph or end_node_id not in self.graph:
            return False
        return bool(nx.has_path(self.graph, start_node_id, end_node_id))

    def find_nearest_node(
        self,
        latitude: float,
        longitude: float,
        max_distance_m: float | None = None,
    ) -> tuple[RoadNode, float] | None:
        if not self.nodes_by_id:
            return None
        best_node: RoadNode | None = None
        best_dist = float("inf")
        for node in self.nodes_by_id.values():
            d = haversine_distance_m(latitude, longitude, node.latitude, node.longitude)
            if d < best_dist:
                best_dist = d
                best_node = node
        if best_node is None:
            return None
        if max_distance_m is not None and best_dist > max_distance_m:
            return None
        return best_node, best_dist

    def find_nearest_edge(
        self,
        latitude: float,
        longitude: float,
        max_distance_m: float | None = None,
    ) -> tuple[RoadEdge, float] | None:
        if not self.edges_by_id:
            return None
        best_edge: RoadEdge | None = None
        best_dist = float("inf")
        for edge in self.edges_by_id.values():
            coords = (edge.geometry or {}).get("coordinates") or []
            if not coords:
                continue
            d_pts = [
                haversine_distance_m(latitude, longitude, float(pt[1]), float(pt[0]))
                for pt in coords
            ]
            # Also sample midpoints of each subsegment for better hit-testing on long straight segments
            for idx in range(len(coords) - 1):
                mlat = (float(coords[idx][1]) + float(coords[idx + 1][1])) / 2.0
                mlon = (float(coords[idx][0]) + float(coords[idx + 1][0])) / 2.0
                d_pts.append(haversine_distance_m(latitude, longitude, mlat, mlon))
            d_min = min(d_pts)
            if d_min < best_dist:
                best_dist = d_min
                best_edge = edge
        if best_edge is None:
            return None
        if max_distance_m is not None and best_dist > max_distance_m:
            return None
        return best_edge, best_dist

    def searchable_locations(self) -> list[tuple[str, int]]:
        """Return sorted display labels mapped to node IDs for searchable origin/dest pickers."""
        items: list[tuple[str, int]] = []
        for nid in sorted(self.nodes_by_id.keys()):
            n = self.nodes_by_id[nid]
            display = n.label or f"Node {nid} ({n.latitude:.5f}, {n.longitude:.5f})"
            items.append((display, nid))
        return items

    def reindex_with_db_ids(
        self,
        node_id_map: dict[int, int],
        edge_id_map: dict[str, int],
    ) -> None:
        """Remap node/edge IDs in-place so NetworkX keys match SQLite primary keys."""
        if not node_id_map and not edge_id_map:
            return

        new_nodes: dict[int, RoadNode] = {}
        for old_nid, node in self.nodes_by_id.items():
            real_nid = node_id_map.get(old_nid, old_nid)
            node.node_id = real_nid
            new_nodes[real_nid] = node

        new_edges: dict[int, RoadEdge] = {}
        new_graph = nx.MultiGraph()
        for real_nid, node in new_nodes.items():
            new_graph.add_node(
                real_nid,
                latitude=node.latitude,
                longitude=node.longitude,
                osm_id=node.osm_id,
                source=node.source,
            )

        for edge in self.edges_by_id.values():
            edge.start_node_id = node_id_map.get(edge.start_node_id, edge.start_node_id)
            edge.end_node_id = node_id_map.get(edge.end_node_id, edge.end_node_id)
            edge.edge_id = edge_id_map.get(edge.edge_key, edge.edge_id)
            new_edges[edge.edge_id] = edge
            new_graph.add_edge(
                edge.start_node_id,
                edge.end_node_id,
                key=edge.edge_id,
                edge_id=edge.edge_id,
                distance_m=edge.distance_m,
                road_type=edge.road_type,
                road_name=edge.road_name,
                geometry=edge.geometry,
                grid_cell_ids=edge.grid_cell_ids,
                exposure_category=edge.exposure_category,
                source=edge.source,
            )

        self.nodes_by_id = new_nodes
        self.edges_by_id = new_edges
        self.graph = new_graph


def build_road_network_from_osm(
    neighbourhood_id: int,
    osm_features: Iterable[OSMFeature],
    grid_cells: Iterable[GridCell] | None = None,
) -> RoadNetworkGraph:
    """Build an authentic NetworkX MultiGraph from imported OSM roads without inventing links."""
    road_feats = [f for f in osm_features if f.category == "road"]
    cells = list(grid_cells or [])

    parsed_lines: list[tuple[OSMFeature, int, list[list[float]]]] = []
    skipped = 0
    vertex_counts: Counter[tuple[float, float]] = Counter()
    endpoint_keys: set[tuple[float, float]] = set()
    first_osm_for_vertex: dict[tuple[float, float], int | None] = {}

    for feat in road_feats:
        lines = _extract_linestrings(feat)
        if not lines:
            skipped += 1
            continue
        for p_idx, line in enumerate(lines):
            parsed_lines.append((feat, p_idx, line))
            endpoint_keys.add(_coord_key(line[0][0], line[0][1]))
            endpoint_keys.add(_coord_key(line[-1][0], line[-1][1]))
            seen_in_line: set[tuple[float, float]] = set()
            for pt in line:
                k = _coord_key(pt[0], pt[1])
                if k not in first_osm_for_vertex:
                    first_osm_for_vertex[k] = feat.osm_id
                # Count vertex incidence (also handles self-intersecting loops)
                vertex_counts[k] += 1
                seen_in_line.add(k)

    intersection_keys: set[tuple[float, float]] = {
        k for k, cnt in vertex_counts.items() if cnt >= 2
    } | endpoint_keys

    # Pre-build Shapely grid boxes for accurate segment-to-cell attribution
    cell_boxes: list[tuple[int, GridCell, Any]] = []
    for idx, cell in enumerate(cells):
        cid = cell.id if cell.id is not None else (idx + 1)
        cell_boxes.append(
            (cid, cell, box(cell.min_longitude, cell.min_latitude, cell.max_longitude, cell.max_latitude))
        )

    nodes_by_key: dict[tuple[float, float], RoadNode] = {}
    nodes_by_id: dict[int, RoadNode] = {}
    node_road_names: dict[int, list[str]] = {}
    next_node_id = 1

    def _get_or_create_node(lon: float, lat: float, osm_id_hint: int | None) -> int:
        nonlocal next_node_id
        k = _coord_key(lon, lat)
        existing = nodes_by_key.get(k)
        if existing is not None:
            return existing.node_id
        nid = next_node_id
        next_node_id += 1
        node = RoadNode(
            node_id=nid,
            neighbourhood_id=neighbourhood_id,
            osm_id=first_osm_for_vertex.get(k, osm_id_hint),
            latitude=float(lat),
            longitude=float(lon),
            label="",
            source="OpenStreetMap",
        )
        nodes_by_key[k] = node
        nodes_by_id[nid] = node
        node_road_names[nid] = []
        return nid

    edges_by_id: dict[int, RoadEdge] = {}
    next_edge_id = 1
    graph = nx.MultiGraph()

    for feat, p_idx, line in parsed_lines:
        road_type = feat.road_category or classify_road_category(feat.subcategory, feat.tags)
        road_name = (feat.name or "").strip() or f"Unnamed {road_type} (#{feat.osm_id})"
        source_val = feat.source or "OpenStreetMap"

        # Split polyline at intermediate intersection keys
        split_indices = [0]
        for i in range(1, len(line) - 1):
            if _coord_key(line[i][0], line[i][1]) in intersection_keys:
                split_indices.append(i)
        split_indices.append(len(line) - 1)

        for s_idx in range(len(split_indices) - 1):
            i0 = split_indices[s_idx]
            i1 = split_indices[s_idx + 1]
            sub_pts = line[i0 : i1 + 1]
            if len(sub_pts) < 2:
                continue

            u = _get_or_create_node(sub_pts[0][0], sub_pts[0][1], feat.osm_id)
            v = _get_or_create_node(sub_pts[-1][0], sub_pts[-1][1], feat.osm_id)
            dist_m = calculate_linestring_length_m(sub_pts)
            if dist_m <= 0.01 and u == v:
                continue
            dist_m = max(0.5, float(dist_m))

            geom = {"type": "LineString", "coordinates": sub_pts}
            intersecting_cells = _intersecting_cells_for_linestring(sub_pts, cell_boxes)

            eid = next_edge_id
            next_edge_id += 1
            ekey = f"{feat.osm_id or feat.id or 0}:{p_idx}:{s_idx}"
            edge = RoadEdge(
                edge_id=eid,
                neighbourhood_id=neighbourhood_id,
                osm_feature_id=feat.id,
                osm_id=feat.osm_id,
                edge_key=ekey,
                start_node_id=u,
                end_node_id=v,
                road_name=road_name,
                road_type=road_type,
                distance_m=dist_m,
                geometry=geom,
                grid_cell_ids=intersecting_cells,
                source=source_val,
                exposure_category="Unknown",
                manual_status="Normal",
                status_source="imported",
            )
            edges_by_id[eid] = edge

            short_rname = (feat.name or "").strip() or road_type
            if short_rname not in node_road_names[u]:
                node_road_names[u].append(short_rname)
            if short_rname not in node_road_names[v]:
                node_road_names[v].append(short_rname)

    # Finalize node attributes and populate NetworkX MultiGraph
    for nid, node in nodes_by_id.items():
        rnames = node_road_names.get(nid, [])
        node.connected_roads = rnames
        road_summary = " × ".join(rnames[:2]) if rnames else "Road Junction"
        node.label = f"N{nid:03d}: {road_summary} ({node.latitude:.5f}, {node.longitude:.5f})"
        graph.add_node(
            nid,
            latitude=node.latitude,
            longitude=node.longitude,
            osm_id=node.osm_id,
            source=node.source,
        )

    for eid, edge in edges_by_id.items():
        graph.add_edge(
            edge.start_node_id,
            edge.end_node_id,
            key=eid,
            edge_id=eid,
            distance_m=edge.distance_m,
            road_type=edge.road_type,
            road_name=edge.road_name,
            geometry=edge.geometry,
            grid_cell_ids=edge.grid_cell_ids,
            exposure_category=edge.exposure_category,
            source=edge.source,
        )

    warnings: list[str] = []
    if skipped > 0:
        warnings.append(f"Skipped {skipped} road feature(s) due to missing or invalid geometry.")
    comps = sorted(nx.connected_components(graph), key=len, reverse=True) if graph.number_of_nodes() else []
    if len(comps) > 1:
        warnings.append(
            f"Road network has {len(comps)} disconnected components "
            f"(main component covers {len(comps[0])}/{graph.number_of_nodes()} nodes)."
        )

    return RoadNetworkGraph(
        neighbourhood_id=neighbourhood_id,
        graph=graph,
        nodes_by_id=nodes_by_id,
        edges_by_id=edges_by_id,
        skipped_feature_count=skipped,
        warnings=warnings,
    )


def _intersecting_cells_for_linestring(
    coords: list[list[float]],
    cell_boxes: list[tuple[int, GridCell, Any]],
) -> list[int]:
    if not cell_boxes or len(coords) < 2:
        return []
    try:
        line = LineString([(float(pt[0]), float(pt[1])) for pt in coords])
    except (ValueError, TypeError, GEOSException):
        return []
    l_minx, l_miny, l_maxx, l_maxy = line.bounds
    hits: list[int] = []
    for cid, cell, cbox in cell_boxes:
        if (
            l_maxx < cell.min_longitude
            or l_minx > cell.max_longitude
            or l_maxy < cell.min_latitude
            or l_miny > cell.max_latitude
        ):
            continue
        try:
            if cbox.intersects(line):
                hits.append(cid)
        except GEOSException:
            continue
    return hits


def extract_evacuation_destinations(
    network: RoadNetworkGraph,
    osm_features: Iterable[OSMFeature],
    shelters: Iterable[Any] | None = None,
) -> list[EvacuationDestination]:
    """Extract evacuation destinations from registered shelters and imported OSM features."""
    destinations: list[EvacuationDestination] = []
    seen_names: set[str] = set()

    if shelters:
        for s in shelters:
            lat = float(getattr(s, "latitude", 0.0))
            lon = float(getattr(s, "longitude", 0.0))
            name = str(getattr(s, "name", "") or "").strip()
            if not name:
                continue
            snapped = network.find_nearest_node(lat, lon)
            node_id = snapped[0].node_id if snapped else None
            snap_dist = snapped[1] if snapped else 0.0
            is_ver = bool(getattr(s, "is_verified", False))
            status = str(getattr(s, "status", "Active"))
            avail = int(getattr(s, "available_capacity", 0))
            tot = int(getattr(s, "total_capacity", 0))
            facs = getattr(s, "facilities", ())
            if isinstance(facs, (list, tuple)):
                fac_str = ", ".join(str(x) for x in facs) if facs else "None listed"
            else:
                fac_str = str(facs or "None listed")
            cat = "Verified Shelter" if is_ver else "Registered Shelter (Unverified)"
            destinations.append(
                EvacuationDestination(
                    label=f"{name} [{cat} • {status} • Avail {avail}/{tot}]",
                    category=cat,
                    latitude=lat,
                    longitude=lon,
                    nearest_node_id=node_id,
                    snap_distance_m=snap_dist,
                    source=f"Shelter Registry ({getattr(s, 'source', 'user-entered')})",
                    is_verified_shelter=is_ver,
                    shelter_id=getattr(s, "id", None),
                    address=str(getattr(s, "address", "")),
                    available_capacity=avail,
                    total_capacity=tot,
                    shelter_status=status,
                    facilities=fac_str,
                )
            )
            seen_names.add(f"shelter_reg:{name.lower()}")

    for feat in osm_features:
        if feat.category == "road":
            continue
        tags = {str(k).lower(): str(v).lower() for k, v in (feat.tags or {}).items()}
        amenity = tags.get("amenity", "")
        emerg = tags.get("emergency", "")
        name = (feat.name or "").strip()

        is_shelter = amenity in ("shelter", "emergency_shelter", "refugee_site") or "shelter" in emerg
        is_emerg_svc = amenity in ("hospital", "clinic", "fire_station", "police") or bool(emerg and not is_shelter)
        is_landmark = (
            feat.category == "building"
            and (
                feat.building_category == "Public / Institutional"
                or bool(name)
            )
        )

        if not (is_shelter or is_emerg_svc or is_landmark):
            continue

        pt = _feature_center_point(feat)
        if pt is None:
            continue
        snapped = network.find_nearest_node(pt[0], pt[1])
        node_id = snapped[0].node_id if snapped else None
        snap_dist = snapped[1] if snapped else 0.0

        if is_shelter:
            cat = "Registered Shelter (OSM)"
            verified_flag = True
        elif is_emerg_svc:
            cat = f"Emergency Service ({amenity or emerg})"
            verified_flag = False
        else:
            cat = "Imported OSM Landmark (Unverified — Not an official shelter)"
            verified_flag = False

        base_name = name or f"{feat.building_category or feat.subcategory or 'Landmark'} (#{feat.osm_id})"
        dedup_key = f"{cat}:{base_name.lower()}"
        if dedup_key in seen_names:
            continue
        seen_names.add(dedup_key)

        destinations.append(
            EvacuationDestination(
                label=f"{base_name} [{cat}]",
                category=cat,
                latitude=pt[0],
                longitude=pt[1],
                nearest_node_id=node_id,
                snap_distance_m=snap_dist,
                source=feat.source or "OpenStreetMap",
                is_verified_shelter=verified_flag,
                osm_feature_id=feat.id,
            )
        )

    # Sort Verified Shelters -> Registered Unverified Shelters -> OSM Shelters -> Emergency Services -> Landmarks
    rank = {
        "Verified Shelter": 0,
        "Registered Shelter (Unverified)": 1,
        "Registered Shelter (OSM)": 2,
    }
    destinations.sort(
        key=lambda d: (
            rank.get(d.category, 3 if d.category.startswith("Emergency") else 4),
            d.label.lower(),
        )
    )
    return destinations


__all__ = [
    "EvacuationDestination",
    "RoadEdge",
    "RoadNetworkGraph",
    "RoadNode",
    "build_road_network_from_osm",
    "extract_evacuation_destinations",
]
