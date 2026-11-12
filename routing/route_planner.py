"""NetworkX Dijkstra shortest, flood-aware, and alternative evacuation route planner."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx

from routing.flood_exposure import RoadFloodExposure
from routing.road_network import RoadEdge, RoadNetworkGraph
from routing.route_comparison import (
    RouteComparisonSummary,
    RouteMetrics,
    build_route_metrics,
    compare_routes,
)
from routing.travel_time import TravelSpeedConfig


@dataclass(slots=True)
class RoadConditionRecord:
    """Manual & simulation-derived status state for one road edge."""

    road_edge_id: int
    status: str = "Normal"  # Normal | Closed | Blocked | Under inspection
    exposure_category: str = "Unknown"
    maximum_water_depth: float | None = None
    simulation_id: int | None = None
    time_step: int | None = None
    status_source: str = "imported"  # user-entered | simulation-derived | imported | unknown
    notes: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class RouteCostWeights:
    """Configurable Dijkstra cost parameters (distance + exposure + inspection penalties)."""

    distance_weight: float = 1.0
    penalty_low: float = 40.0
    penalty_moderate: float = 350.0
    penalty_high: float = 2000.0
    penalty_very_high: float = 8000.0
    penalty_unknown: float = 200.0
    penalty_under_inspection: float = 500.0
    avoid_high_exposure: bool = False
    avoid_closed_roads: bool = True

    def penalty_for_exposure(self, category: str) -> float:
        if category == "No surface flooding":
            return 0.0
        if category == "Low":
            return float(self.penalty_low)
        if category == "Moderate":
            return float(self.penalty_moderate)
        if category == "High":
            return float(self.penalty_high)
        if category == "Very high":
            return float(self.penalty_very_high)
        # Unknown is NEVER zero-cost safe
        return float(self.penalty_unknown)


@dataclass(slots=True)
class RouteFailureInfo:
    """Clear diagnostic explanation when no route can be computed."""

    route_type: str
    reason: str
    suggestion: str


@dataclass(slots=True)
class RoutePlanningResult:
    """Combined SafeRoute bundle containing calculated routes, comparison, and any warnings."""

    shortest: RouteMetrics | None = None
    flood_aware: RouteMetrics | None = None
    alternative: RouteMetrics | None = None
    comparison: RouteComparisonSummary | None = None
    failures: list[RouteFailureInfo] = field(default_factory=list)
    simulation_id: int | None = None
    timestep: int | None = None

    @property
    def routes(self) -> list[RouteMetrics]:
        out: list[RouteMetrics] = []
        for r in (self.shortest, self.flood_aware, self.alternative):
            if r is not None:
                out.append(r)
        return out


def _compute_dijkstra_edge_path(
    network: RoadNetworkGraph,
    start_node_id: int,
    dest_node_id: int,
    edge_weight_fn,
) -> tuple[list[int], list[RoadEdge]] | None:
    """Run Dijkstra on the NetworkX MultiGraph using exact per-edge weight callback."""
    # Construct a filtered simple weighted Graph picking the minimum-weight parallel edge
    # between each (u, v) pair so NetworkX Dijkstra returns both exact nodes and exact edge_id.
    g = nx.Graph()
    for nid in network.nodes_by_id:
        g.add_node(nid)

    best_parallel: dict[tuple[int, int], tuple[float, RoadEdge]] = {}
    for eid, edge in network.edges_by_id.items():
        w = edge_weight_fn(edge)
        if w is None or not math.isfinite(w):
            continue
        u, v = edge.start_node_id, edge.end_node_id
        if u == v:
            continue
        key = (u, v) if u < v else (v, u)
        prev = best_parallel.get(key)
        if prev is None or w < prev[0]:
            best_parallel[key] = (float(w), edge)

    for (u, v), (w, edge) in best_parallel.items():
        g.add_edge(u, v, weight=w, road_edge=edge)

    if start_node_id not in g or dest_node_id not in g:
        return None
    if start_node_id == dest_node_id:
        return [start_node_id], []

    try:
        node_path = nx.dijkstra_path(g, source=start_node_id, target=dest_node_id, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None

    edge_path: list[RoadEdge] = []
    for i in range(len(node_path) - 1):
        u, v = node_path[i], node_path[i + 1]
        data = g.get_edge_data(u, v)
        if not data or "road_edge" not in data:
            return None
        edge_path.append(data["road_edge"])
    return node_path, edge_path


def _diagnose_no_path(
    network: RoadNetworkGraph,
    start_node_id: int,
    dest_node_id: int,
    route_type: str,
    speed_config: TravelSpeedConfig,
    weights: RouteCostWeights,
    exposures: dict[int, RoadFloodExposure],
    manual_statuses: dict[int, str],
) -> RouteFailureInfo:
    if start_node_id not in network.nodes_by_id or dest_node_id not in network.nodes_by_id:
        return RouteFailureInfo(
            route_type=route_type,
            reason="Selected origin or destination node does not exist in the loaded road network.",
            suggestion="Pick an intersection or location directly on the mapped Potheri road network.",
        )
    if not network.are_connected(start_node_id, dest_node_id):
        return RouteFailureInfo(
            route_type=route_type,
            reason="Origin and destination lie in disconnected OpenStreetMap road components.",
            suggestion="Select endpoints within the same connected road component or verify OSM road coverage.",
        )
    blocked_edges = sum(1 for st in manual_statuses.values() if st in ("Closed", "Blocked"))
    high_edges = sum(
        1 for exp in exposures.values() if exp.exposure_category in ("High", "Very high")
    )
    if weights.avoid_closed_roads and blocked_edges > 0 and weights.avoid_high_exposure and high_edges > 0:
        return RouteFailureInfo(
            route_type=route_type,
            reason="All connecting corridors are either manually Closed/Blocked or exceed High flood exposure.",
            suggestion="Reopen a closed segment, disable 'Avoid high-exposure roads', or choose another destination.",
        )
    if weights.avoid_closed_roads and blocked_edges > 0:
        return RouteFailureInfo(
            route_type=route_type,
            reason=f"Manual road closures/blocks ({blocked_edges} edge(s)) severed all open paths to destination.",
            suggestion="Inspect closed segments in Road Closure Manager or test another destination.",
        )
    if speed_config.mode == "Two-wheeler/Car" and speed_config.speed_kmh_for("Footpath") <= 0.0:
        return RouteFailureInfo(
            route_type=route_type,
            reason="Only pedestrian footpaths/steps connect the chosen endpoints (excluded in Two-wheeler/Car mode).",
            suggestion="Switch Travel Mode to 'Walking' or pick endpoints on vehicular roads.",
        )
    return RouteFailureInfo(
        route_type=route_type,
        reason="No feasible path satisfied all active constraints (closures, high-risk avoidance, or travel mode).",
        suggestion="Relax route constraints or select a different origin/destination pair.",
    )


def calculate_single_route(
    network: RoadNetworkGraph,
    start_node_id: int,
    dest_node_id: int,
    route_type: str,
    origin_label: str,
    destination_label: str,
    exposures: dict[int, RoadFloodExposure],
    manual_statuses: dict[int, str],
    speed_config: TravelSpeedConfig,
    weights: RouteCostWeights,
    avoid_edge_ids: set[int] | None = None,
) -> tuple[RouteMetrics | None, RouteFailureInfo | None]:
    """Run NetworkX Dijkstra for a single strategy ('Shortest', 'Flood-aware', or 'Alternative')."""
    speed_config.validate()
    avoid_set = avoid_edge_ids or set()

    def _edge_weight(edge: RoadEdge) -> float | None:
        # Travel mode check (e.g. Footpath speed == 0 km/hr in Two-wheeler/Car)
        if speed_config.speed_kmh_for(edge.road_type) <= 0.0:
            return None

        m_status = manual_statuses.get(edge.edge_id, edge.manual_status or "Normal")
        if weights.avoid_closed_roads and m_status in ("Closed", "Blocked"):
            return None

        exp = exposures.get(edge.edge_id)
        exp_cat = exp.exposure_category if exp is not None else edge.exposure_category

        if route_type == "Shortest":
            # Geometric shortest over passable open roads
            w = max(0.5, float(edge.distance_m))
            if m_status in ("Closed", "Blocked"):
                w += 100_000.0
            return w

        # Flood-aware or Alternative route
        if weights.avoid_high_exposure and exp_cat in ("High", "Very high"):
            return None

        w = (
            max(0.5, float(edge.distance_m)) * float(weights.distance_weight)
            + weights.penalty_for_exposure(exp_cat)
        )
        if m_status == "Under inspection":
            w += float(weights.penalty_under_inspection)
        elif m_status in ("Closed", "Blocked"):
            # Only reached if avoid_closed_roads is False
            w += 100_000.0

        if route_type == "Alternative" and edge.edge_id in avoid_set:
            w = w * 3.0 + 400.0
        return w

    solved = _compute_dijkstra_edge_path(network, start_node_id, dest_node_id, _edge_weight)
    if solved is None:
        fail = _diagnose_no_path(
            network,
            start_node_id,
            dest_node_id,
            route_type,
            speed_config,
            weights,
            exposures,
            manual_statuses,
        )
        return None, fail

    node_path, edge_path = solved
    display_names = {
        "Shortest": "Shortest Route (Distance)",
        "Flood-aware": "Flood-Aware Route",
        "Alternative": "Alternative Corridor",
    }
    metrics = build_route_metrics(
        route_name=display_names.get(route_type, route_type),
        route_type=route_type,
        origin_label=origin_label,
        destination_label=destination_label,
        node_ids=node_path,
        edges=edge_path,
        exposures=exposures,
        manual_statuses=manual_statuses,
        speed_config=speed_config,
    )
    return metrics, None


def calculate_evacuation_routes(
    network: RoadNetworkGraph,
    start_node_id: int,
    dest_node_id: int,
    origin_label: str,
    destination_label: str,
    exposures: dict[int, RoadFloodExposure],
    manual_statuses: dict[int, str],
    speed_config: TravelSpeedConfig | None = None,
    weights: RouteCostWeights | None = None,
    simulation_id: int | None = None,
    timestep: int | None = None,
) -> RoutePlanningResult:
    """Calculate Shortest, Flood-Aware, and Alternative routes plus side-by-side comparison."""
    sp = speed_config or TravelSpeedConfig()
    wt = weights or RouteCostWeights()
    failures: list[RouteFailureInfo] = []

    shortest, f_short = calculate_single_route(
        network, start_node_id, dest_node_id, "Shortest",
        origin_label, destination_label, exposures, manual_statuses, sp, wt,
    )
    if f_short:
        failures.append(f_short)

    flood_aware, f_fa = calculate_single_route(
        network, start_node_id, dest_node_id, "Flood-aware",
        origin_label, destination_label, exposures, manual_statuses, sp, wt,
    )
    if f_fa:
        failures.append(f_fa)

    # Diversify alternative route away from Flood-aware (or Shortest if Flood-aware missing)
    used_edges: set[int] = set()
    if flood_aware is not None:
        used_edges.update(flood_aware.edge_ids)
    elif shortest is not None:
        used_edges.update(shortest.edge_ids)

    alternative, f_alt = calculate_single_route(
        network, start_node_id, dest_node_id, "Alternative",
        origin_label, destination_label, exposures, manual_statuses, sp, wt,
        avoid_edge_ids=used_edges,
    )
    if f_alt:
        failures.append(f_alt)

    # If alternative is identical to both shortest and flood-aware, keep or flag transparently
    all_routes = [r for r in (shortest, flood_aware, alternative) if r is not None]
    comp = compare_routes(all_routes)
    if (
        alternative is not None
        and flood_aware is not None
        and alternative.edge_ids == flood_aware.edge_ids
        and all_routes
    ):
        comp.comparison_notes.append(
            "Only one unique corridor connects the selected endpoints under current constraints; Alternative matches primary path."
        )

    return RoutePlanningResult(
        shortest=shortest,
        flood_aware=flood_aware,
        alternative=alternative,
        comparison=comp,
        failures=failures,
        simulation_id=simulation_id,
        timestep=timestep,
    )


__all__ = [
    "RoadConditionRecord",
    "RouteCostWeights",
    "RouteFailureInfo",
    "RoutePlanningResult",
    "calculate_evacuation_routes",
    "calculate_single_route",
]
