"""Phase 5 SafeRoute road network, flood exposure, routing, and comparison package."""

from routing.flood_exposure import (
    RoadExposureThresholds,
    RoadFloodExposure,
    analyze_road_network_exposure,
    classify_road_exposure_depth,
)
from routing.road_network import (
    EvacuationDestination,
    RoadEdge,
    RoadNetworkGraph,
    RoadNode,
    build_road_network_from_osm,
    extract_evacuation_destinations,
)
from routing.route_comparison import (
    RouteComparisonSummary,
    RouteMetrics,
    build_route_metrics,
    compare_routes,
)
from routing.route_planner import (
    RoadConditionRecord,
    RouteCostWeights,
    RouteFailureInfo,
    RoutePlanningResult,
    calculate_evacuation_routes,
    calculate_single_route,
)
from routing.travel_time import (
    TravelSpeedConfig,
    estimate_route_travel_time_minutes,
    estimate_segment_time_minutes,
    format_travel_time,
)

__all__ = [
    "EvacuationDestination",
    "RoadConditionRecord",
    "RoadEdge",
    "RoadExposureThresholds",
    "RoadFloodExposure",
    "RoadNetworkGraph",
    "RoadNode",
    "RouteComparisonSummary",
    "RouteCostWeights",
    "RouteFailureInfo",
    "RouteMetrics",
    "RoutePlanningResult",
    "TravelSpeedConfig",
    "analyze_road_network_exposure",
    "build_road_network_from_osm",
    "build_route_metrics",
    "calculate_evacuation_routes",
    "calculate_single_route",
    "classify_road_exposure_depth",
    "compare_routes",
    "estimate_route_travel_time_minutes",
    "estimate_segment_time_minutes",
    "extract_evacuation_destinations",
    "format_travel_time",
]
