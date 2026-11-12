"""Input, coordinate, grid, and geometry validation helpers."""

import math
from typing import Any, Iterable

from config import (
    DRAINAGE_CAPACITY_UNITS,
    DRAINAGE_STATUS_OPTIONS,
    DRAINAGE_TYPES,
    ELEVATION_SOURCE_OPTIONS,
    LAND_USE_OPTIONS,
    MAX_BBOX_SPAN_DEG,
    MAX_GRID_DIM,
    MIN_GRID_DIM,
)


class ValidationError(ValueError):
    """Raised when domain or user input fails validation."""


def _require_finite_number(value: Any, field_name: str) -> float:
    """Parse a finite float or raise ValidationError (rejects NaN and Infinity)."""
    if value is None or isinstance(value, bool):
        raise ValidationError(f"{field_name} must be a valid number.")
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be a numeric value.") from exc
    if not math.isfinite(num):
        raise ValidationError(f"{field_name} must be finite (NaN or Infinity is not allowed).")
    return num


def validate_workspace_name(name: Any) -> str:
    """Validate and normalize a neighbourhood workspace name."""
    if not isinstance(name, str):
        raise ValidationError("Workspace name must be text.")
    cleaned = name.strip()
    if not cleaned:
        raise ValidationError("Workspace name cannot be empty.")
    if len(cleaned) > 100:
        raise ValidationError("Workspace name must be 100 characters or fewer.")
    return cleaned


def validate_latitude(value: Any, field_name: str = "Latitude") -> float:
    """Validate latitude in [-90, 90]."""
    lat = _require_finite_number(value, field_name)
    if lat < -90.0 or lat > 90.0:
        raise ValidationError(f"{field_name} must be between -90 and 90 degrees (got {lat}).")
    return lat


def validate_longitude(value: Any, field_name: str = "Longitude") -> float:
    """Validate longitude in [-180, 180]."""
    lon = _require_finite_number(value, field_name)
    if lon < -180.0 or lon > 180.0:
        raise ValidationError(f"{field_name} must be between -180 and 180 degrees (got {lon}).")
    return lon


def validate_bounding_box(
    min_lat: Any,
    max_lat: Any,
    min_lon: Any,
    max_lon: Any,
    enforce_max_span: bool = True,
) -> tuple[float, float, float, float]:
    """Validate a geographic bounding box (south, north, west, east)."""
    south = validate_latitude(min_lat, "Minimum latitude")
    north = validate_latitude(max_lat, "Maximum latitude")
    west = validate_longitude(min_lon, "Minimum longitude")
    east = validate_longitude(max_lon, "Maximum longitude")

    if south >= north:
        raise ValidationError(
            f"Minimum latitude ({south}) must be strictly less than maximum latitude ({north})."
        )
    if west >= east:
        raise ValidationError(
            f"Minimum longitude ({west}) must be strictly less than maximum longitude ({east})."
        )

    if enforce_max_span:
        if (north - south) > MAX_BBOX_SPAN_DEG or (east - west) > MAX_BBOX_SPAN_DEG:
            raise ValidationError(
                f"Bounding box span exceeds safe neighbourhood limit ({MAX_BBOX_SPAN_DEG}°). "
                "Please select a smaller neighbourhood area."
            )

    return south, north, west, east


def validate_grid_dimensions(rows: Any, cols: Any) -> tuple[int, int]:
    """Validate simulation grid row and column counts."""
    if isinstance(rows, bool) or isinstance(cols, bool):
        raise ValidationError("Grid dimensions must be integers.")
    try:
        r = int(rows)
        c = int(cols)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Grid rows and columns must be whole integers.") from exc

    # Reject non-integer floats passed as strings or numbers
    if isinstance(rows, float) and not rows.is_integer():
        raise ValidationError("Grid rows must be a whole integer.")
    if isinstance(cols, float) and not cols.is_integer():
        raise ValidationError("Grid columns must be a whole integer.")

    if r < MIN_GRID_DIM or r > MAX_GRID_DIM:
        raise ValidationError(
            f"Grid rows must be between {MIN_GRID_DIM} and {MAX_GRID_DIM} (got {r})."
        )
    if c < MIN_GRID_DIM or c > MAX_GRID_DIM:
        raise ValidationError(
            f"Grid columns must be between {MIN_GRID_DIM} and {MAX_GRID_DIM} (got {c})."
        )
    return r, c


def validate_elevation(value: Any) -> float | None:
    """Validate optional elevation in metres (None or empty string -> None)."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    elev = _require_finite_number(value, "Elevation (m)")
    if elev < -500.0 or elev > 9000.0:
        raise ValidationError("Elevation must be between -500 m and 9000 m.")
    return elev


def validate_elevation_source(source: Any, elevation: float | None) -> str | None:
    """Validate elevation provenance metadata."""
    if elevation is None:
        return None
    if not isinstance(source, str) or not source.strip():
        return "User-provided"
    cleaned = source.strip()
    if cleaned == "Unset (NULL)":
        return "User-provided"
    if cleaned not in ELEVATION_SOURCE_OPTIONS:
        return cleaned
    return cleaned


def validate_non_negative_rate(value: Any, field_name: str) -> float:
    """Validate non-negative physical rate (e.g., infiltration/drainage mm/hour)."""
    rate = _require_finite_number(value, field_name)
    if rate < 0.0:
        raise ValidationError(f"{field_name} cannot be negative (got {rate}).")
    if rate > 10000.0:
        raise ValidationError(f"{field_name} exceeds realistic upper limit of 10000 mm/hr.")
    return rate


def validate_land_use(land_use: Any) -> str:
    """Validate land-use classification against allowed options."""
    if not isinstance(land_use, str) or land_use not in LAND_USE_OPTIONS:
        allowed = ", ".join(LAND_USE_OPTIONS)
        raise ValidationError(f"Invalid land-use '{land_use}'. Allowed values: {allowed}.")
    return land_use


def _validate_coord_pair(pair: Any) -> tuple[float, float]:
    """Validate a single GeoJSON [lon, lat] coordinate pair."""
    if not isinstance(pair, (list, tuple)) or len(pair) < 2:
        raise ValidationError("GeoJSON coordinate must be a [longitude, latitude] pair.")
    lon = validate_longitude(pair[0], "Geometry longitude")
    lat = validate_latitude(pair[1], "Geometry latitude")
    return lon, lat


def _validate_coord_list(coords: Any, min_points: int) -> None:
    if not isinstance(coords, (list, tuple)) or len(coords) < min_points:
        raise ValidationError(f"Geometry coordinate sequence must have at least {min_points} points.")
    for pair in coords:
        _validate_coord_pair(pair)


def validate_geojson_geometry(geometry: Any) -> dict[str, Any]:
    """Validate a GeoJSON geometry dict and ensure all coordinates are valid and finite."""
    if not isinstance(geometry, dict):
        raise ValidationError("Geometry must be a JSON object.")
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")

    if geom_type == "Point":
        _validate_coord_pair(coords)
    elif geom_type == "LineString":
        _validate_coord_list(coords, 2)
    elif geom_type == "MultiLineString":
        if not isinstance(coords, list) or not coords:
            raise ValidationError("MultiLineString must contain at least one LineString.")
        for line in coords:
            _validate_coord_list(line, 2)
    elif geom_type == "Polygon":
        if not isinstance(coords, list) or not coords:
            raise ValidationError("Polygon must contain at least one linear ring.")
        for ring in coords:
            _validate_coord_list(ring, 4)
    elif geom_type == "MultiPolygon":
        if not isinstance(coords, list) or not coords:
            raise ValidationError("MultiPolygon must contain at least one Polygon.")
        for polygon in coords:
            if not isinstance(polygon, list) or not polygon:
                raise ValidationError("Each polygon in MultiPolygon must contain at least one ring.")
            for ring in polygon:
                _validate_coord_list(ring, 4)
    else:
        raise ValidationError(f"Unsupported or invalid GeoJSON geometry type: {geom_type!r}")

    return geometry


def validate_drainage_inputs(
    name: Any,
    feature_type: Any,
    latitude: Any,
    longitude: Any,
    capacity: Any,
    capacity_unit: Any,
    status: Any,
) -> tuple[str, str, float, float, float | None, str, str]:
    """Validate manual drainage infrastructure attributes."""
    clean_name = validate_workspace_name(name) if isinstance(name, str) and name.strip() else ""
    if not clean_name:
        raise ValidationError("Drainage element name cannot be empty.")
    if feature_type not in DRAINAGE_TYPES:
        raise ValidationError(f"Invalid drainage type '{feature_type}'.")
    lat = validate_latitude(latitude, "Drainage latitude")
    lon = validate_longitude(longitude, "Drainage longitude")

    cap_val: float | None
    if capacity is None or (isinstance(capacity, str) and not capacity.strip()):
        cap_val = None
    else:
        cap_val = validate_non_negative_rate(capacity, "Drainage capacity")

    unit = str(capacity_unit or "L/s").strip()
    if unit not in DRAINAGE_CAPACITY_UNITS:
        raise ValidationError(f"Invalid capacity unit '{unit}'. Allowed: {', '.join(DRAINAGE_CAPACITY_UNITS)}.")

    if status not in DRAINAGE_STATUS_OPTIONS:
        raise ValidationError(f"Invalid operational status '{status}'.")

    return clean_name, str(feature_type), lat, lon, cap_val, unit, str(status)

