"""Geodesic measurements and Shapely geometric feature-to-grid intersection utilities."""

from __future__ import annotations

import logging
import math
from typing import Any

from shapely.geometry import Point, box, shape
from shapely.errors import GEOSException

from core.models import DrainageFeature, GridCell, GridFeatureLink, OSMFeature

logger = logging.getLogger(__name__)

EARTH_RADIUS_M = 6_371_008.8


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance in metres between two WGS84 points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return EARTH_RADIUS_M * c


def calculate_linestring_length_m(coords: list[list[float]]) -> float:
    """Compute cumulative Haversine length in metres for a GeoJSON [lon, lat] sequence."""
    if not coords or len(coords) < 2:
        return 0.0
    total = 0.0
    for i in range(len(coords) - 1):
        lon1, lat1 = float(coords[i][0]), float(coords[i][1])
        lon2, lat2 = float(coords[i + 1][0]), float(coords[i + 1][1])
        total += haversine_distance_m(lat1, lon1, lat2, lon2)
    return total


def calculate_geometry_length_m(geometry: dict[str, Any]) -> float:
    """Compute length in metres for LineString/MultiLineString geometries (0.0 for points/polygons)."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return 0.0
    if gtype == "LineString":
        return calculate_linestring_length_m(coords)
    if gtype == "MultiLineString":
        return sum(calculate_linestring_length_m(line) for line in coords)
    return 0.0


def calculate_cell_metrics_m(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> tuple[float, float, float]:
    """Compute (approx_width_m, approx_height_m, approx_area_m2) using spherical Earth geometry.

    Uses meridian arc for height, center-latitude parallel arc for width, and exact
    spherical-quadrilateral surface area R^2 * dlon * (sin(lat2) - sin(lat1)).
    """
    phi1 = math.radians(min_lat)
    phi2 = math.radians(max_lat)
    mid_phi = (phi1 + phi2) / 2.0
    dlam = abs(math.radians(max_lon - min_lon))

    height_m = EARTH_RADIUS_M * abs(phi2 - phi1)
    width_m = EARTH_RADIUS_M * max(0.0, math.cos(mid_phi)) * dlam
    area_m2 = (EARTH_RADIUS_M ** 2) * dlam * abs(math.sin(phi2) - math.sin(phi1))
    return width_m, height_m, area_m2


def compute_feature_grid_links(
    cells: list[GridCell],
    osm_features: list[OSMFeature],
    drainage_features: list[DrainageFeature],
) -> list[GridFeatureLink]:
    """Compute normalized spatial associations between grid cells and OSM/drainage features."""
    if not cells:
        return []

    cell_boxes: list[tuple[GridCell, Any]] = []
    for cell in cells:
        if cell.id is None:
            continue
        cell_boxes.append(
            (cell, box(cell.min_longitude, cell.min_latitude, cell.max_longitude, cell.max_latitude))
        )

    links: list[GridFeatureLink] = []

    for feat in osm_features:
        if feat.id is None:
            continue
        try:
            geom = shape(feat.geometry)
            if not geom.is_valid:
                geom = geom.buffer(0)
        except (ValueError, TypeError, GEOSException) as exc:
            logger.debug("Skipping non-shapely geometry for OSM id=%s: %s", feat.id, exc)
            continue

        f_minx, f_miny, f_maxx, f_maxy = geom.bounds
        for cell, cbox in cell_boxes:
            if (
                f_maxx < cell.min_longitude
                or f_minx > cell.max_longitude
                or f_maxy < cell.min_latitude
                or f_miny > cell.max_latitude
            ):
                continue
            try:
                if cbox.contains(geom):
                    rel = "within"
                elif cbox.intersects(geom):
                    rel = "intersects"
                else:
                    continue
                links.append(
                    GridFeatureLink(
                        id=None,
                        grid_cell_id=cell.id,
                        osm_feature_id=feat.id,
                        drainage_feature_id=None,
                        relationship_type=rel,
                    )
                )
            except GEOSException:
                continue

    for drain in drainage_features:
        if drain.id is None:
            continue
        pt = Point(drain.longitude, drain.latitude)
        for cell, cbox in cell_boxes:
            if (
                cell.min_latitude <= drain.latitude <= cell.max_latitude
                and cell.min_longitude <= drain.longitude <= cell.max_longitude
            ) or cbox.intersects(pt):
                links.append(
                    GridFeatureLink(
                        id=None,
                        grid_cell_id=cell.id,
                        osm_feature_id=None,
                        drainage_feature_id=drain.id,
                        relationship_type="contains",
                    )
                )
                break

    return links
