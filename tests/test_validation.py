"""Tests for coordinate, bounding box, numeric rate, land-use, and geometry validation."""

from __future__ import annotations

import math

import pytest

from core.validation import (
    ValidationError,
    validate_bounding_box,
    validate_elevation,
    validate_geojson_geometry,
    validate_land_use,
    validate_latitude,
    validate_longitude,
    validate_non_negative_rate,
    validate_workspace_name,
)


def test_coordinate_validation_bounds_and_non_finite() -> None:
    assert validate_latitude(12.823) == 12.823
    assert validate_longitude(80.044) == 80.044

    for bad_lat in [-90.1, 90.001, float("nan"), float("inf"), float("-inf"), "abc", None]:
        with pytest.raises(ValidationError):
            validate_latitude(bad_lat)

    for bad_lon in [-180.1, 180.1, math.nan, math.inf, "xyz", True]:
        with pytest.raises(ValidationError):
            validate_longitude(bad_lon)


def test_bounding_box_validation() -> None:
    s, n, w, e = validate_bounding_box(12.815, 12.831, 80.036, 80.052)
    assert (s, n, w, e) == (12.815, 12.831, 80.036, 80.052)

    # Inverted bounds
    with pytest.raises(ValidationError):
        validate_bounding_box(12.84, 12.82, 80.03, 80.05)
    with pytest.raises(ValidationError):
        validate_bounding_box(12.81, 12.83, 80.06, 80.04)

    # Excessively large area rejected by default
    with pytest.raises(ValidationError):
        validate_bounding_box(12.0, 13.0, 80.0, 81.0)


def test_cell_attribute_and_workspace_validation() -> None:
    assert validate_workspace_name("  POTHERI  ") == "POTHERI"
    with pytest.raises(ValidationError):
        validate_workspace_name("   ")

    assert validate_elevation("") is None
    assert validate_elevation(None) is None
    assert validate_elevation("18.2") == 18.2
    with pytest.raises(ValidationError):
        validate_elevation(float("nan"))

    assert validate_non_negative_rate("0", "Drainage") == 0.0
    with pytest.raises(ValidationError):
        validate_non_negative_rate("-5", "Infiltration")
    with pytest.raises(ValidationError):
        validate_non_negative_rate(float("inf"), "Infiltration")

    assert validate_land_use("Residential") == "Residential"
    with pytest.raises(ValidationError):
        validate_land_use("MarsColony")


def test_geojson_geometry_validation() -> None:
    valid_line = {"type": "LineString", "coordinates": [[80.04, 12.82], [80.05, 12.83]]}
    assert validate_geojson_geometry(valid_line) == valid_line

    with pytest.raises(ValidationError):
        validate_geojson_geometry({"type": "LineString", "coordinates": [[80.04, 12.82]]})

    with pytest.raises(ValidationError):
        validate_geojson_geometry({"type": "Polygon", "coordinates": [[[200.0, 12.8], [80.0, 12.8], [80.0, 12.9], [200.0, 12.8]]]})

