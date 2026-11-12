"""Route metrics computation and side-by-side route comparison helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from routing.flood_exposure import RoadFloodExposure
from routing.road_network import RoadEdge
from routing.travel_time import TravelSpeedConfig, estimate_route_travel_time_minutes, format_travel_time


@dataclass(slots=True)
class RouteMetrics:
    """Computed distance, travel-time estimate, flood exposure, and geometry for one route."""

    route_name: str
    route_type: str  # Shortest | Flood-aware | Alternative
    travel_mode: str
    origin_label: str
    destination_label: str
    origin_node_id: int
    dest_node_id: int
    total_distance_m: float
    total_distance_km: float
    estimated_time_minutes: float
    estimated_time_display: str
    segment_count: int
    exposed_segment_count: int
    high_risk_segment_count: int
    closed_segment_count: int
    unknown_segment_count: int
    max_water_depth_m: float
    max_water_depth_cm: float
    avg_water_depth_cm: float
    node_ids: list[int] = field(default_factory=list)
    edge_ids: list[int] = field(default_factory=list)
    road_names: list[str] = field(default_factory=list)
    coordinates: list[list[float]] = field(default_factory=list)  # [[lon, lat], ...]
    warnings: list[str] = field(default_factory=list)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "route_name": self.route_name,
            "route_type": self.route_type,
            "travel_mode": self.travel_mode,
            "total_distance_km": round(self.total_distance_km, 4),
            "estimated_time_minutes": round(self.estimated_time_minutes, 2),
            "segment_count": self.segment_count,
            "exposed_segment_count": self.exposed_segment_count,
            "high_risk_segment_count": self.high_risk_segment_count,
            "closed_segment_count": self.closed_segment_count,
            "unknown_segment_count": self.unknown_segment_count,
            "max_water_depth_cm": round(self.max_water_depth_cm, 2),
            "road_names": self.road_names,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class RouteComparisonSummary:
    """Analytical comparison table & caveats across calculated routes."""

    routes: list[RouteMetrics]
    comparison_notes: list[str] = field(default_factory=list)
    disclaimer: str = (
        "Decision-support estimates only: assumed road speeds (not live traffic) and simulated depths "
        "(not observed conditions). Unknown exposure must NEVER be treated as safe."
    )


def build_route_metrics(
    route_name: str,
    route_type: str,
    origin_label: str,
    destination_label: str,
    node_ids: list[int],
    edges: list[RoadEdge],
    exposures: dict[int, RoadFloodExposure],
    manual_statuses: dict[int, str],
    speed_config: TravelSpeedConfig,
) -> RouteMetrics:
    """Aggregate segment distances, assumed times, flood depths, and geometry along a route."""
    total_dist_m = sum(e.distance_m for e in edges)
    est_min = estimate_route_travel_time_minutes(
        [(e.distance_m, e.road_type) for e in edges],
        speed_config,
    )

    exposed_cnt = 0
    high_risk_cnt = 0
    closed_cnt = 0
    unknown_cnt = 0
    max_d_m = 0.0
    weighted_d_sum = 0.0
    known_dist = 0.0

    road_names: list[str] = []
    coords_path: list[list[float]] = []

    for idx, edge in enumerate(edges):
        st = manual_statuses.get(edge.edge_id, edge.manual_status or "Normal")
        if st in ("Closed", "Blocked"):
            closed_cnt += 1

        exp = exposures.get(edge.edge_id)
        cat = exp.exposure_category if exp is not None else edge.exposure_category
        seg_max = exp.max_depth_m if exp is not None else edge.max_depth_m

        if cat in ("Low", "Moderate", "High", "Very high"):
            exposed_cnt += 1
        if cat in ("High", "Very high"):
            high_risk_cnt += 1
        if cat == "Unknown" or seg_max is None:
            unknown_cnt += 1
        else:
            max_d_m = max(max_d_m, float(seg_max))
            weighted_d_sum += float(seg_max) * edge.distance_m
            known_dist += edge.distance_m

        rname = edge.road_name.strip()
        if rname and (not road_names or road_names[-1] != rname):
            road_names.append(rname)

        # Orient subsegment polyline cleanly along node traversal order
        seg_coords = list((edge.geometry or {}).get("coordinates") or [])
        if seg_coords and idx < len(node_ids) - 1:
            curr_u = node_ids[idx]
            if curr_u == edge.end_node_id and edge.start_node_id != edge.end_node_id:
                seg_coords.reverse()
            if not coords_path:
                coords_path.extend(seg_coords)
            else:
                if coords_path[-1] == seg_coords[0]:
                    coords_path.extend(seg_coords[1:])
                else:
                    coords_path.extend(seg_coords)

    warnings: list[str] = []
    if high_risk_cnt > 0:
        warnings.append(f"Crosses {high_risk_cnt} high/very-high simulated flood exposure segment(s).")
    if unknown_cnt > 0:
        warnings.append(f"Includes {unknown_cnt} segment(s) with Unknown flood exposure (not verified safe).")
    if closed_cnt > 0:
        warnings.append(f"Touches {closed_cnt} manually marked Closed/Blocked segment(s).")
    if speed_config.mode == "Walking":
        warnings.append("Walking estimates assume clear footpaths and passable surfaces (non-traffic).")
    else:
        warnings.append("Travel time uses assumed category speeds, not real-time traffic conditions.")

    avg_cm = (weighted_d_sum / known_dist) * 100.0 if known_dist > 0.0 else 0.0

    return RouteMetrics(
        route_name=route_name,
        route_type=route_type,
        travel_mode=speed_config.mode,
        origin_label=origin_label,
        destination_label=destination_label,
        origin_node_id=node_ids[0] if node_ids else 0,
        dest_node_id=node_ids[-1] if node_ids else 0,
        total_distance_m=total_dist_m,
        total_distance_km=total_dist_m / 1000.0,
        estimated_time_minutes=est_min,
        estimated_time_display=format_travel_time(est_min),
        segment_count=len(edges),
        exposed_segment_count=exposed_cnt,
        high_risk_segment_count=high_risk_cnt,
        closed_segment_count=closed_cnt,
        unknown_segment_count=unknown_cnt,
        max_water_depth_m=max_d_m,
        max_water_depth_cm=max_d_m * 100.0,
        avg_water_depth_cm=avg_cm,
        node_ids=list(node_ids),
        edge_ids=[e.edge_id for e in edges],
        road_names=road_names,
        coordinates=coords_path,
        warnings=warnings,
    )


def compare_routes(routes: list[RouteMetrics]) -> RouteComparisonSummary:
    """Produce comparative insights between Shortest, Flood-aware, and Alternative routes."""
    notes: list[str] = []
    if not routes:
        return RouteComparisonSummary(routes=[], comparison_notes=["No routes calculated."])

    shortest = next((r for r in routes if r.route_type == "Shortest"), None)
    flood_aware = next((r for r in routes if r.route_type == "Flood-aware"), None)
    alternative = next((r for r in routes if r.route_type == "Alternative"), None)

    if shortest and flood_aware:
        if shortest.edge_ids == flood_aware.edge_ids:
            notes.append("Flood-aware route matches the Shortest route under current conditions/penalties.")
        else:
            d_diff_m = flood_aware.total_distance_m - shortest.total_distance_m
            t_diff_min = flood_aware.estimated_time_minutes - shortest.estimated_time_minutes
            risk_diff = shortest.high_risk_segment_count - flood_aware.high_risk_segment_count
            exp_diff = shortest.exposed_segment_count - flood_aware.exposed_segment_count
            notes.append(
                f"Flood-aware detour adds {d_diff_m:+.0f} m ({t_diff_min:+.1f} min est.) vs Shortest path, "
                f"reducing exposed segments by {exp_diff:+d} and high-risk segments by {risk_diff:+d}."
            )
    if alternative and flood_aware and alternative.edge_ids != flood_aware.edge_ids:
        notes.append(
            f"Alternative corridor spans {alternative.total_distance_km:.2f} km "
            f"({alternative.exposed_segment_count} exposed, {alternative.unknown_segment_count} unknown segments)."
        )
    if any(r.unknown_segment_count > 0 for r in routes):
        notes.append(
            "One or more routes traverse segments with Unknown exposure — inspect elevation/simulation coverage before relying on them."
        )

    return RouteComparisonSummary(routes=routes, comparison_notes=notes)


__all__ = [
    "RouteComparisonSummary",
    "RouteMetrics",
    "build_route_metrics",
    "compare_routes",
]
