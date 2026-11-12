"""Domain data models and Phase 2+ simulation/routing interfaces."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


EARTH_RADIUS_M = 6_371_008.8
METRES_PER_DEG_LAT = 111_320.0


def approximate_cell_metrics_m(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> tuple[float, float, float]:
    """Return (width_m, height_m, area_m2) using spherical Earth surface geometry."""
    phi1 = math.radians(min_lat)
    phi2 = math.radians(max_lat)
    mid_phi = (phi1 + phi2) / 2.0
    dlam = abs(math.radians(max_lon - min_lon))

    height_m = EARTH_RADIUS_M * abs(phi2 - phi1)
    width_m = EARTH_RADIUS_M * max(0.0, math.cos(mid_phi)) * dlam
    area_m2 = (EARTH_RADIUS_M ** 2) * dlam * abs(math.sin(phi2) - math.sin(phi1))
    return width_m, height_m, area_m2


def approximate_cell_dimensions_m(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> tuple[float, float]:
    """Return approximate (width_m, height_m) using spherical Earth scaling."""
    w, h, _ = approximate_cell_metrics_m(min_lat, max_lat, min_lon, max_lon)
    return w, h


@dataclass(slots=True)
class Neighbourhood:
    """Represents a saved neighbourhood workspace and its geographical bounding box."""

    id: int | None
    name: str
    district: str
    state: str
    country: str
    center_latitude: float
    center_longitude: float
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float
    grid_rows: int = 10
    grid_cols: int = 10
    created_at: str = ""
    updated_at: str = ""

    def approx_dimensions_m(self) -> tuple[float, float]:
        """Return approximate (width_m, height_m) of the bounding box."""
        return approximate_cell_dimensions_m(
            self.min_latitude,
            self.max_latitude,
            self.min_longitude,
            self.max_longitude,
        )


@dataclass(slots=True)
class GridCell:
    """Represents one cell in the neighbourhood simulation grid."""

    id: int | None
    neighbourhood_id: int
    row_number: int
    column_number: int
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float
    elevation_m: float | None = None
    elevation_source: str | None = None
    min_elevation_m: float | None = None
    max_elevation_m: float | None = None
    mean_elevation_m: float | None = None
    land_use: str = "Unknown"
    land_use_source: str = "missing"
    infiltration_rate: float = 0.0
    infiltration_source: str = "missing"
    drainage_capacity: float = 0.0
    drainage_source: str = "missing"
    approx_width_m: float | None = None
    approx_height_m: float | None = None
    approx_area_m2: float | None = None
    notes: str = ""
    updated_at: str = ""

    @property
    def cell_code(self) -> str:
        """Human-friendly 1-based grid coordinate code (e.g., R1C1)."""
        return f"R{self.row_number + 1}C{self.column_number + 1}"

    @property
    def center_latitude(self) -> float:
        return (self.min_latitude + self.max_latitude) / 2.0

    @property
    def center_longitude(self) -> float:
        return (self.min_longitude + self.max_longitude) / 2.0

    @property
    def is_configured(self) -> bool:
        """True if any user-editable or imported physical attribute has been populated."""
        return (
            self.land_use != "Unknown"
            or self.elevation_m is not None
            or self.mean_elevation_m is not None
            or self.infiltration_rate > 0.0
            or self.drainage_capacity > 0.0
            or bool(self.notes.strip())
        )

    def approx_dimensions_m(self) -> tuple[float, float]:
        """Approximate ground (width_m, height_m) calculated at this cell's latitude."""
        if self.approx_width_m is not None and self.approx_height_m is not None:
            return self.approx_width_m, self.approx_height_m
        return approximate_cell_dimensions_m(
            self.min_latitude,
            self.max_latitude,
            self.min_longitude,
            self.max_longitude,
        )

    def approx_area_sq_m(self) -> float:
        """Approximate ground area in square metres."""
        if self.approx_area_m2 is not None:
            return self.approx_area_m2
        _, _, area = approximate_cell_metrics_m(
            self.min_latitude,
            self.max_latitude,
            self.min_longitude,
            self.max_longitude,
        )
        return area


@dataclass(slots=True)
class OSMFeature:
    """Represents a single imported OpenStreetMap or GeoJSON geographical feature."""

    id: int | None
    neighbourhood_id: int
    osm_id: int
    element_type: str
    category: str
    subcategory: str
    name: str
    geometry: dict[str, Any]
    tags: dict[str, Any] = field(default_factory=dict)
    source: str = "OpenStreetMap"
    imported_at: str = ""
    length_m: float = 0.0
    road_category: str = ""
    building_category: str = ""
    user_notes: str = ""
    is_user_edited: bool = False


@dataclass(slots=True)
class DrainageFeature:
    """User-entered drainage infrastructure point element."""

    id: int | None
    neighbourhood_id: int
    grid_cell_id: int | None
    name: str
    feature_type: str
    latitude: float
    longitude: float
    capacity: float | None = None
    capacity_unit: str = "L/s"
    status: str = "Unknown"
    source: str = "user-entered"
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class GridFeatureLink:
    """Normalized spatial link between a GridCell and an OSMFeature or DrainageFeature."""

    id: int | None
    grid_cell_id: int
    osm_feature_id: int | None
    drainage_feature_id: int | None
    relationship_type: str
    created_at: str = ""


@dataclass(slots=True)
class ElevationSourceRecord:
    """Tracks imported elevation raster files and their CRS metadata."""

    id: int | None
    neighbourhood_id: int
    source_name: str
    file_name: str
    coordinate_reference_system: str
    imported_at: str
    source_description: str = ""


@dataclass(slots=True)
class LandUseHistoryEntry:
    """Audit trail entry for grid-cell land-use classification changes."""

    id: int | None
    grid_cell_id: int
    previous_category: str
    new_category: str
    source: str
    updated_at: str


@dataclass(slots=True)
class DataQualitySummary:
    """Phase 2 neighbourhood data completeness and provenance counts."""

    road_count: int = 0
    building_count: int = 0
    water_feature_count: int = 0
    green_area_count: int = 0
    drainage_count: int = 0
    total_grid_cells: int = 0
    missing_elevation_cells: int = 0
    missing_land_use_cells: int = 0
    missing_infiltration_cells: int = 0
    missing_drainage_cells: int = 0
    imported_elevation_cells: int = 0
    user_elevation_cells: int = 0
    imported_osm_count: int = 0
    user_edited_osm_count: int = 0
    inferred_land_use_cells: int = 0
    user_land_use_cells: int = 0
    user_drainage_count: int = 0
    grid_links_count: int = 0


@dataclass(slots=True)
class GeocodingResult:
    """Resolved location candidate returned by geocoding service."""

    display_name: str
    name: str
    district: str
    state: str
    country: str
    latitude: float
    longitude: float
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float
    osm_type: str = ""
    osm_id: int | None = None
    bbox_adjusted_note: str = ""


@dataclass(slots=True)
class HourlyForecastPoint:
    """Single hourly forecast entry from Open-Meteo."""

    time_iso: str
    temperature_c: float | None
    humidity_pct: float | None
    precipitation_mm: float | None
    rain_mm: float | None
    weather_code: int | None


@dataclass(slots=True)
class WeatherSnapshot:
    """Current model estimate + hourly forecast retrieved from Open-Meteo or local cache."""

    id: int | None
    neighbourhood_id: int
    temperature_c: float | None
    humidity_pct: float | None
    precipitation_mm: float | None
    rainfall_mm: float | None
    weather_code: int | None
    weather_description: str
    data_type: str
    source: str
    observed_at: str
    retrieved_at: str
    hourly_forecast: list[HourlyForecastPoint] = field(default_factory=list)
    raw_json: str = ""
    is_stale: bool = False
    age_label: str = ""


@dataclass(slots=True)
class DashboardSummary:
    """Aggregated workspace statistics displayed on the Dashboard."""

    neighbourhood: Neighbourhood | None
    road_count: int = 0
    building_count: int = 0
    waterway_count: int = 0
    green_area_count: int = 0
    other_feature_count: int = 0
    total_grid_cells: int = 0
    configured_grid_cells: int = 0
    last_map_update: str | None = None
    weather: WeatherSnapshot | None = None


# =============================================================================
# Phase 2+ Future-Compatible Interfaces (No fake implementations in Phase 1)
# =============================================================================


@dataclass(slots=True)
class RainfallScenarioConfig:
    """Configuration contract for future Phase 2 rainfall scenario generator."""

    scenario_name: str
    total_rainfall_mm: float
    duration_hours: float
    time_step_minutes: int = 15
    distribution_pattern: str = "uniform"


class FloodSimulationEngine(ABC):
    """Abstract contract for Phase 2 runoff, infiltration, drainage, and accumulation."""

    @abstractmethod
    def run_simulation(
        self,
        cells: list[GridCell],
        scenario: RainfallScenarioConfig,
    ) -> dict[str, Any]:
        """Compute cell-level water depth and risk metrics (implemented in Phase 2)."""


class EvacuationRouter(ABC):
    """Abstract contract for Phase 2 NetworkX-based SafeRoute evacuation analysis."""

    @abstractmethod
    def compute_safe_routes(
        self,
        features: list[OSMFeature],
        inundated_cell_ids: set[int],
        origin: tuple[float, float],
        destination: tuple[float, float],
    ) -> list[dict[str, Any]]:
        """Compute passable alternative routes avoiding flooded segments (Phase 2)."""


class EmergencyResourceAllocator(ABC):
    """Abstract contract for Phase 2 shelter capacity and resource allocation."""

    @abstractmethod
    def allocate_resources(
        self,
        neighbourhood: Neighbourhood,
        affected_cells: list[GridCell],
    ) -> dict[str, Any]:
        """Plan shelter capacities and emergency supply distribution (Phase 2)."""

