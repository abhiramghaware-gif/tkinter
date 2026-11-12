"""Application configuration and constants for CHENNAI FLOODGUARD."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Application Metadata
APP_NAME = "CHENNAI FLOODGUARD"
APP_SUBTITLE = "Urban Flood Simulation & Emergency Decision Support"
APP_VERSION = "1.0.0-phase7"
SCHEMA_VERSION = 5
MODEL_VERSION = "floodguard-wb-v1.0"


def _resolve_runtime_paths() -> tuple[Path, Path]:
    """Resolve read-only resource root and writable app-data directory (source vs PyInstaller)."""
    if getattr(sys, "frozen", False):
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        env_dir = os.environ.get("FLOODGUARD_DATA_DIR")
        if env_dir:
            data_root = Path(env_dir)
        elif os.name == "nt":
            local_app = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            data_root = Path(local_app) / "ChennaiFloodGuard"
        else:
            data_root = Path.home() / ".local" / "share" / "ChennaiFloodGuard"
        return bundle_root, data_root
    src_root = Path(__file__).resolve().parent
    return src_root, Path(os.environ.get("FLOODGUARD_DATA_DIR") or (src_root / "data"))


# Directory & File Paths
BASE_DIR, DATA_DIR = _resolve_runtime_paths()
BUNDLE_DIR = BASE_DIR
CACHE_DIR = DATA_DIR / "cache"
EXPORTS_DIR = DATA_DIR / "exports"
BACKUPS_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / "floodguard.db"
DATABASE_DIR = BASE_DIR / "database"
SCHEMA_PATH = DATABASE_DIR / "schema.sql"
ASSETS_DIR = BASE_DIR / "assets"
LOG_PATH = DATA_DIR / "floodguard.log"

# Default Geographical Search (resolved dynamically via Nominatim; never hardcoded coords)
DEFAULT_LOCATION_QUERY = "Potheri, Chengalpattu district, Tamil Nadu, India"
DEFAULT_WORKSPACE_NAME = "POTHERI"

# Grid Configuration Defaults & Bounds
DEFAULT_GRID_ROWS = 10
DEFAULT_GRID_COLS = 10
MIN_GRID_DIM = 2
MAX_GRID_DIM = 50

# Bounding Box Safety Limits (degrees)
# Prevents downloading excessively large areas from public Overpass servers
MIN_BBOX_SPAN_DEG = 0.002
MAX_BBOX_SPAN_DEG = 0.08
DEFAULT_POINT_EXPAND_HALF_SPAN_DEG = 0.008  # ~1.7 km x 1.7 km neighbourhood box

# Land-Use Options & Elevation Provenance Options
LAND_USE_OPTIONS = (
    "Residential",
    "Commercial",
    "Industrial",
    "Road",
    "Open Ground",
    "Green Area",
    "Water Body",
    "Mixed Use",
    "Unknown",
)

ELEVATION_SOURCE_OPTIONS = (
    "Unset (NULL)",
    "User-provided",
    "Illustrative (Non-verified)",
    "Imported Raster",
)

DATA_PROVENANCE_VALUES = (
    "imported",
    "user-entered",
    "inferred",
    "missing",
)

# Road & Building Classification Constants
ROAD_CATEGORIES = (
    "Motorway / Major",
    "Primary",
    "Secondary",
    "Tertiary",
    "Residential",
    "Service",
    "Footpath",
)

BUILDING_CATEGORIES = (
    "Residential",
    "Commercial",
    "Industrial",
    "Public / Institutional",
    "General Building",
)

# Drainage Infrastructure Constants
DRAINAGE_TYPES = (
    "Stormwater drain",
    "Drain inlet",
    "Drain outlet",
    "Drainage channel",
    "Culvert",
    "Pumping station",
)

DRAINAGE_STATUS_OPTIONS = (
    "Operational",
    "Partially blocked",
    "Blocked",
    "Unknown",
)

DRAINAGE_CAPACITY_UNITS = (
    "mm/hr",
    "L/s",
    "m3/s",
)

# External API Configuration (No API keys required)
USER_AGENT = "ChennaiFloodGuard/0.3.0-Phase3 (Academic Urban Flood Prototype; Python-Requests)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

REQUEST_TIMEOUT_SECONDS = 20
OVERPASS_TIMEOUT_SECONDS = 45
NOMINATIM_MIN_INTERVAL_SEC = 1.2
OVERPASS_MIN_INTERVAL_SEC = 2.0
WEATHER_CACHE_TTL_SECONDS = 1800  # 30 minutes
OSM_CACHE_TTL_SECONDS = 86400 * 7  # 7 days

OSM_ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"
OPEN_METEO_ATTRIBUTION = "Weather data by Open-Meteo.com (Model / Forecast)"

# UI Theme Palette (Dark Navy & Slate + Cyan/Teal Accent)
THEME = {
    "bg_root": "#0B1120",
    "bg_sidebar": "#0F172A",
    "bg_header": "#111827",
    "bg_surface": "#111827",
    "bg_card": "#1E293B",
    "bg_card_alt": "#263348",
    "bg_input": "#0F172A",
    "bg_hover": "#334155",
    "border": "#334155",
    "border_strong": "#475569",
    "accent": "#06B6D4",
    "accent_teal": "#14B8A6",
    "accent_hover": "#22D3EE",
    "accent_muted": "#164E63",
    "text_primary": "#F8FAFC",
    "text_secondary": "#CBD5E1",
    "text_muted": "#94A3B8",
    "success": "#10B981",
    "success_bg": "#064E3B",
    "warning": "#F59E0B",
    "warning_bg": "#451A03",
    "error": "#EF4444",
    "error_bg": "#450A0A",
    "info": "#38BDF8",
    "info_bg": "#0C4A6E",
}

# Map & Grid Visualization Colors
MAP_COLORS = {
    "canvas_bg": "#0A101D",
    "road_motorway": "#FDE047",
    "road_primary": "#F8FAFC",
    "road_secondary": "#CBD5E1",
    "road_tertiary": "#94A3B8",
    "road_residential": "#64748B",
    "road_service": "#475569",
    "road_footpath": "#A8A29E",
    "waterway_line": "#38BDF8",
    "water_fill": "#0C4A6E",
    "water_outline": "#0284C7",
    "wetland_fill": "#0F4C5C",
    "wetland_outline": "#14B8A6",
    "building_fill": "#475569",
    "building_outline": "#64748B",
    "green_fill": "#143D30",
    "green_outline": "#1E5E48",
    "other_fill": "#2D3748",
    "other_outline": "#4A5568",
    "grid_line": "#334155",
    "grid_line_subtle": "#1E293B",
    "grid_selected": "#22D3EE",
    "grid_configured": "#14B8A6",
    "feature_selected": "#F472B6",
    "drainage_operational": "#2DD4BF",
    "drainage_partial": "#F59E0B",
    "drainage_blocked": "#EF4444",
    "drainage_unknown": "#94A3B8",
    "scale_bar": "#E2E8F0",
}

LAND_USE_TINT_COLORS = {
    "Residential": "#7C3AED",
    "Commercial": "#F59E0B",
    "Industrial": "#EA580C",
    "Road": "#94A3B8",
    "Open Ground": "#A3E635",
    "Green Area": "#10B981",
    "Water Body": "#0284C7",
    "Mixed Use": "#EC4899",
    "Unknown": "",
}

# =============================================================================
# Phase 3: Flood Simulation Configuration Defaults (Illustrative Model Params)
# =============================================================================
SIMULATION_MODE_ELEVATION = "elevation_based"
SIMULATION_MODE_ILLUSTRATIVE = "illustrative_assumed"

SIMULATION_MODE_LABELS = {
    SIMULATION_MODE_ELEVATION: "Elevation-based (Verified / User Grid Elevation)",
    SIMULATION_MODE_ILLUSTRATIVE: "Illustrative Assumed Terrain (Non-verified)",
}

RAINFALL_DISTRIBUTIONS = ("constant", "increasing", "decreasing", "custom")

# Hypothetical rainfall intensity presets (mm/hr) — NEVER presented as real observations
RAINFALL_PRESETS = {
    "Light rainfall (10 mm/hr)": 10.0,
    "Moderate rainfall (30 mm/hr)": 30.0,
    "Heavy rainfall (60 mm/hr)": 60.0,
    "Extreme rainfall (100 mm/hr)": 100.0,
    "Custom": None,
}

# Editable illustrative infiltration assumptions (mm/hr) per hydrological category.
# Explicitly marked as illustrative assumptions unless replaced by measured local data.
DEFAULT_INFILTRATION_RATES_MM_HR = {
    "Concrete": 1.0,
    "Road": 2.0,
    "Residential": 8.0,
    "Commercial": 4.0,
    "Vegetation": 22.0,
    "Open soil": 15.0,
    "Water body": 0.0,
}

LAND_USE_TO_INFILTRATION_CATEGORY = {
    "Concrete": "Concrete",
    "Road": "Road",
    "Residential": "Residential",
    "Commercial": "Commercial",
    "Industrial": "Commercial",
    "Mixed Use": "Residential",
    "Green Area": "Vegetation",
    "Vegetation": "Vegetation",
    "Open Ground": "Open soil",
    "Open soil": "Open soil",
    "Water Body": "Water body",
    "Water body": "Water body",
    "Unknown": "Residential",
}

DRAINAGE_STATUS_FACTORS = {
    "Operational": 1.0,
    "Partially blocked": 0.5,
    "Blocked": 0.0,
    "Unknown": 0.0,
}

DEFAULT_MASS_BALANCE_TOLERANCE_M3 = 1e-6
WET_CELL_DEPTH_THRESHOLD_M = 1e-4  # 0.1 mm threshold to count cell as holding surface water

# =============================================================================
# Phase 4: Flood Risk Classification & Heatmap Color Scale (Prototype Defaults)
# =============================================================================
RISK_CATEGORIES = (
    "No surface flooding",
    "Low",
    "Moderate",
    "High",
    "Very High",
)

# Illustrative threshold upper bounds in centimetres (prototype assumptions only)
DEFAULT_RISK_THRESHOLDS_CM = {
    "low_max_cm": 10.0,
    "moderate_max_cm": 30.0,
    "high_max_cm": 60.0,
    "critical_min_cm": 100.0,  # Extra heatmap tier for Critical depth visual emphasis
}

DEFAULT_HEATMAP_COLORS = {
    "no_water": "#64748B",      # Light slate / grey (user-switchable to green #22C55E)
    "low": "#38BDF8",           # Light blue
    "moderate": "#FACC15",      # Yellow
    "high": "#F97316",          # Orange
    "very_high": "#EF4444",     # Red
    "critical": "#991B1B",      # Dark red
}

RISK_BADGE_COLORS = {
    "No surface flooding": "#64748B",
    "Low": "#38BDF8",
    "Moderate": "#FACC15",
    "High": "#F97316",
    "Very High": "#EF4444",
}

DEFAULT_ROAD_EXPOSURE_THRESHOLD_CM = 15.0
DEFAULT_BUILDING_EXPOSURE_THRESHOLD_CM = 5.0

# =============================================================================
# Phase 5: SafeRoute Evacuation Planning & Road Exposure Defaults
# =============================================================================
ROAD_STATUS_OPTIONS = (
    "Normal",
    "Closed",
    "Blocked",
    "Under inspection",
)

ROAD_EXPOSURE_CATEGORIES = (
    "No surface flooding",
    "Low",
    "Moderate",
    "High",
    "Very high",
    "Unknown",
)

# Illustrative road exposure depth thresholds in centimetres (prototype defaults)
DEFAULT_ROAD_EXPOSURE_THRESHOLDS_CM = {
    "low_max_cm": 10.0,
    "moderate_max_cm": 30.0,
    "high_max_cm": 60.0,
}

TRAVEL_MODES = (
    "Walking",
    "Two-wheeler/Car",
)

# Editable assumed speeds (km/hr) — NOT real-time traffic measurements
DEFAULT_SPEED_ASSUMPTIONS_KMH = {
    "Walking": {
        "Motorway / Major": 4.5,
        "Primary": 4.5,
        "Secondary": 4.5,
        "Tertiary": 4.5,
        "Residential": 4.5,
        "Service": 4.5,
        "Footpath": 4.5,
    },
    "Two-wheeler/Car": {
        "Motorway / Major": 50.0,
        "Primary": 40.0,
        "Secondary": 32.0,
        "Tertiary": 26.0,
        "Residential": 20.0,
        "Service": 15.0,
        "Footpath": 0.0,  # Excluded by default for motorized vehicles
    },
}

ROUTE_COLORS = {
    "shortest": "#3B82F6",      # Distinct Blue
    "flood_aware": "#22C55E",   # Distinct Green
    "alternative": "#F59E0B",   # Distinct Orange
    "closed": "#EF4444",        # Red
    "unknown": "#9CA3AF",       # Grey
}

# =============================================================================
# Phase 6: Emergency Resource & Relief Management Defaults
# =============================================================================
SHELTER_STATUS_OPTIONS = (
    "Active",
    "Inactive",
    "Full",
    "Closed",
)

SHELTER_FACILITY_OPTIONS = (
    "Drinking water",
    "Food",
    "Toilets",
    "Electricity",
    "First aid",
    "Accessible facilities",
    "Sleeping arrangements",
)

SHELTER_SOURCE_OPTIONS = (
    "user-entered",
    "field-verified",
    "osm-unverified",
)

RESCUE_TEAM_STATUS_OPTIONS = (
    "Available",
    "Assigned",
    "On operation",
    "Unavailable",
    "Off duty",
)

VEHICLE_TYPE_OPTIONS = (
    "Rescue boat",
    "Ambulance",
    "Car",
    "Van",
    "Truck",
    "Other rescue vehicle",
)

VEHICLE_STATUS_OPTIONS = (
    "Available",
    "Assigned",
    "In use",
    "Under maintenance",
    "Unavailable",
)

VOLUNTEER_AVAILABILITY_OPTIONS = (
    "Available",
    "Assigned",
    "Unavailable",
    "Off duty",
)

INVENTORY_CATEGORIES = (
    "Food and water",
    "Medical",
    "Rescue equipment",
    "Other supplies",
)

INVENTORY_SUBTYPE_EXAMPLES = {
    "Food and water": ("Drinking water", "Packaged food", "Ready-to-eat meals", "Milk and infant food"),
    "Medical": ("First-aid kits", "Bandages", "Antiseptic supplies", "Basic medical equipment"),
    "Rescue equipment": ("Life jackets", "Ropes", "Flashlights", "Batteries", "Emergency lamps", "Rescue tools"),
    "Other supplies": ("Blankets", "Clothing", "Hygiene kits", "Sanitation supplies"),
}

INVENTORY_VERIFICATION_STATUSES = (
    "Registered (Unverified)",
    "Physically Verified",
)

INVENTORY_TRANSACTION_TYPES = (
    "Stock received",
    "Stock issued",
    "Stock returned",
    "Stock transferred",
    "Stock adjustment",
)

ALLOCATION_RESOURCE_TYPES = (
    "inventory_item",
    "vehicle",
    "rescue_team",
    "volunteer",
)

ALLOCATION_STATUS_OPTIONS = (
    "Allocated",
    "Dispatched",
    "Delivered",
    "Returned",
    "Cancelled",
)

OPERATION_TYPES = (
    "Shelter supply delivery",
    "Food distribution",
    "Medical assistance",
    "Rescue support",
    "Volunteer coordination",
    "Equipment delivery",
)

OPERATION_PRIORITIES = (
    "Low",
    "Medium",
    "High",
    "Critical",
)

OPERATION_STATUS_OPTIONS = (
    "Planned",
    "Ready",
    "In progress",
    "Completed",
    "Cancelled",
)

ALERT_SEVERITIES = (
    "Info",
    "Warning",
    "High",
    "Critical",
)

NEAR_EXPIRY_WARNING_DAYS = 14
INVENTORY_EXPIRY_WARNING_DAYS = NEAR_EXPIRY_WARNING_DAYS
SHELTER_NEAR_FULL_RATIO = 0.90

REPORT_TYPES = (
    ("neighbourhood_profile", "1. Neighbourhood Profile Report"),
    ("geographical_data", "2. Geographical Data Report"),
    ("weather_data", "3. Weather Data Report"),
    ("flood_simulation", "4. Flood Simulation Report"),
    ("flood_risk_analysis", "5. Flood-Risk Analysis Report"),
    ("scenario_comparison", "6. Scenario Comparison Report"),
    ("saferoute_analysis", "7. SafeRoute Analysis Report"),
    ("shelter_capacity", "8. Shelter Capacity Report"),
    ("emergency_resource", "9. Emergency Resource Report"),
    ("inventory", "10. Inventory Report"),
    ("emergency_operations", "11. Emergency Operations Report"),
    ("complete_project", "12. Complete Project Report"),
)






