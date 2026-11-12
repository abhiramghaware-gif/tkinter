"""Infrastructure exposure calculation and Phase 4 map overlay renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import tkinter as tk

from core.models import GridCell, GridFeatureLink, OSMFeature
from visualization.map_renderer import GeoViewport, MapRenderer


@dataclass(slots=True)
class ExposureSummary:
    """Simulated road/building/shelter exposure counts for a timestep (estimate only)."""

    exposed_road_ids: set[int] = field(default_factory=set)
    exposed_building_ids: set[int] = field(default_factory=set)
    shelter_features: list[OSMFeature] = field(default_factory=list)
    exposed_roads_by_cell: dict[int, int] = field(default_factory=dict)
    exposed_buildings_by_cell: dict[int, int] = field(default_factory=dict)
    road_threshold_cm: float = 15.0
    building_threshold_cm: float = 5.0
    disclaimer: str = (
        "Simulated infrastructure overlap estimate only — NOT confirmed real-world road closure or structural damage."
    )


def _is_shelter_feature(feat: OSMFeature) -> bool:
    tags = {str(k).lower(): str(v).lower() for k, v in feat.tags.items()}
    if tags.get("amenity") in ("shelter", "emergency_shelter", "refugee_site"):
        return True
    if "emergency" in tags and "shelter" in tags.get("emergency", ""):
        return True
    if "shelter" in (feat.name or "").lower():
        return True
    return False


def _feature_center(feat: OSMFeature) -> tuple[float, float] | None:
    geom = feat.geometry or {}
    gtype = geom.get("type")
    coords = geom.get("coordinates")
    if not coords:
        return None
    if gtype == "Point":
        return float(coords[1]), float(coords[0])
    if gtype == "LineString" and coords:
        mid = coords[len(coords) // 2]
        return float(mid[1]), float(mid[0])
    if gtype == "Polygon" and coords and coords[0]:
        pts = coords[0]
        return (
            sum(float(p[1]) for p in pts) / len(pts),
            sum(float(p[0]) for p in pts) / len(pts),
        )
    if gtype == "MultiPolygon" and coords and coords[0] and coords[0][0]:
        pts = coords[0][0]
        return (
            sum(float(p[1]) for p in pts) / len(pts),
            sum(float(p[0]) for p in pts) / len(pts),
        )
    return None


def compute_infrastructure_exposure(
    cells: list[GridCell],
    osm_features: Iterable[OSMFeature],
    links: Iterable[GridFeatureLink],
    depths_by_cell_id: dict[int, float],
    road_threshold_cm: float = 15.0,
    building_threshold_cm: float = 5.0,
) -> ExposureSummary:
    """Identify OSM roads and buildings overlapping inundated cells above configured thresholds."""
    feats = list(osm_features)
    feat_by_id = {f.id: f for f in feats if f.id is not None}
    shelters = [f for f in feats if _is_shelter_feature(f)]

    road_cutoff_m = max(0.0, float(road_threshold_cm)) / 100.0
    bldg_cutoff_m = max(0.0, float(building_threshold_cm)) / 100.0

    # Build mapping feature_id -> intersecting cell_ids
    feat_to_cells: dict[int, set[int]] = {}
    for lk in links:
        if lk.osm_feature_id is not None:
            feat_to_cells.setdefault(lk.osm_feature_id, set()).add(lk.grid_cell_id)

    # Fallback if grid_feature_links have not been populated for synthetic grids
    if not feat_to_cells and feats and cells:
        for f in feats:
            if f.id is None:
                continue
            pt = _feature_center(f)
            if pt is None:
                continue
            lat, lon = pt
            for idx, c in enumerate(cells):
                cid = c.id if c.id is not None else (idx + 1)
                if c.min_latitude <= lat <= c.max_latitude and c.min_longitude <= lon <= c.max_longitude:
                    feat_to_cells.setdefault(f.id, set()).add(cid)

    exposed_roads: set[int] = set()
    exposed_bldgs: set[int] = set()
    roads_by_cell: dict[int, int] = {}
    bldgs_by_cell: dict[int, int] = {}

    for fid, cell_ids in feat_to_cells.items():
        feat = feat_by_id.get(fid)
        if feat is None:
            continue
        if feat.category == "road":
            hit_cells = [cid for cid in cell_ids if float(depths_by_cell_id.get(cid, 0.0)) >= road_cutoff_m and float(depths_by_cell_id.get(cid, 0.0)) > 0.0]
            if hit_cells:
                exposed_roads.add(fid)
                for cid in hit_cells:
                    roads_by_cell[cid] = roads_by_cell.get(cid, 0) + 1
        elif feat.category == "building":
            hit_cells = [cid for cid in cell_ids if float(depths_by_cell_id.get(cid, 0.0)) >= bldg_cutoff_m and float(depths_by_cell_id.get(cid, 0.0)) > 0.0]
            if hit_cells:
                exposed_bldgs.add(fid)
                for cid in hit_cells:
                    bldgs_by_cell[cid] = bldgs_by_cell.get(cid, 0) + 1

    return ExposureSummary(
        exposed_road_ids=exposed_roads,
        exposed_building_ids=exposed_bldgs,
        shelter_features=shelters,
        exposed_roads_by_cell=roads_by_cell,
        exposed_buildings_by_cell=bldgs_by_cell,
        road_threshold_cm=road_threshold_cm,
        building_threshold_cm=building_threshold_cm,
    )


class MapLayersOverlayRenderer:
    """Highlights simulated exposed roads, buildings, and mapped shelters over OSM."""

    def render_exposure(
        self,
        canvas: tk.Canvas,
        viewport: GeoViewport,
        osm_features: Iterable[OSMFeature],
        exposure: ExposureSummary,
        highlight_exposed_roads: bool = True,
        highlight_exposed_buildings: bool = True,
        show_shelters: bool = True,
        registered_shelters: Iterable[Any] | None = None,
    ) -> None:
        canvas.delete("layer_exposure")
        canvas.delete("layer_shelters")

        for feat in osm_features:
            if feat.id is None:
                continue
            if highlight_exposed_roads and feat.id in exposure.exposed_road_ids:
                self._draw_highlighted_line(canvas, viewport, feat, "#F43F5E", 3.2)
            elif highlight_exposed_buildings and feat.id in exposure.exposed_building_ids:
                self._draw_highlighted_poly(canvas, viewport, feat, "#FB923C", 2.0)

        if show_shelters:
            for sh in exposure.shelter_features:
                pt = _feature_center(sh)
                if pt is None:
                    continue
                x, y = viewport.geo_to_screen(pt[0], pt[1])
                r = 7
                canvas.create_polygon(
                    x, y - r, x + r, y, x, y + r, x - r, y,
                    fill="#14B8A6",
                    outline="#F8FAFC",
                    width=1.5,
                    tags=("layer_shelters",),
                )
                canvas.create_text(
                    x,
                    y,
                    text="S",
                    fill="#042F2E",
                    font=("Segoe UI", 7, "bold"),
                    tags=("layer_shelters",),
                )
            for reg in (registered_shelters or ()):
                lat = float(getattr(reg, "latitude", 0.0))
                lon = float(getattr(reg, "longitude", 0.0))
                is_ver = bool(getattr(reg, "is_verified", False))
                status = str(getattr(reg, "status", "Active"))
                fill = (
                    "#64748B" if status in ("Inactive", "Closed")
                    else ("#EF4444" if status == "Full" else ("#14B8A6" if is_ver else "#F59E0B"))
                )
                x, y = viewport.geo_to_screen(lat, lon)
                r = 8
                canvas.create_polygon(
                    x, y - r, x + r, y, x, y + r, x - r, y,
                    fill=fill,
                    outline="#F8FAFC",
                    width=1.6,
                    tags=("layer_shelters",),
                )
                canvas.create_text(
                    x,
                    y,
                    text="S" if is_ver else "S?",
                    fill="#042F2E",
                    font=("Segoe UI", 7, "bold"),
                    tags=("layer_shelters",),
                )

    @staticmethod
    def _draw_highlighted_line(
        canvas: tk.Canvas,
        viewport: GeoViewport,
        feat: OSMFeature,
        color: str,
        width: float,
    ) -> None:
        geom = feat.geometry or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "LineString":
            pts = MapRenderer._project_ring(viewport, coords)
            if len(pts) >= 4:
                canvas.create_line(*pts, fill=color, width=width, capstyle=tk.ROUND, tags=("layer_exposure",))
        elif gtype == "MultiLineString":
            for line in coords:
                pts = MapRenderer._project_ring(viewport, line)
                if len(pts) >= 4:
                    canvas.create_line(*pts, fill=color, width=width, capstyle=tk.ROUND, tags=("layer_exposure",))

    @staticmethod
    def _draw_highlighted_poly(
        canvas: tk.Canvas,
        viewport: GeoViewport,
        feat: OSMFeature,
        outline: str,
        width: float,
    ) -> None:
        geom = feat.geometry or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "Polygon" and coords:
            pts = MapRenderer._project_ring(viewport, coords[0])
            if len(pts) >= 6:
                canvas.create_polygon(*pts, fill="", outline=outline, width=width, tags=("layer_exposure",))
        elif gtype == "MultiPolygon":
            for poly in coords:
                if poly:
                    pts = MapRenderer._project_ring(viewport, poly[0])
                    if len(pts) >= 6:
                        canvas.create_polygon(*pts, fill="", outline=outline, width=width, tags=("layer_exposure",))
