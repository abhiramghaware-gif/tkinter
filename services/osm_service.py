"""OpenStreetMap Overpass API integration for importing neighbourhood features."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests

from config import (
    OSM_CACHE_TTL_SECONDS,
    OVERPASS_MIN_INTERVAL_SEC,
    OVERPASS_TIMEOUT_SECONDS,
    OVERPASS_URLS,
    USER_AGENT,
)
from core.geo_utils import calculate_geometry_length_m
from core.models import OSMFeature
from core.validation import ValidationError, validate_bounding_box, validate_geojson_geometry
from services.cache_service import CacheService

logger = logging.getLogger(__name__)


class OSMImportError(RuntimeError):
    """Raised when Overpass feature retrieval or parsing fails."""


_ALLOWED_HIGHWAY_VALUES = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "residential",
        "living_street",
        "unclassified",
        "service",
        "footway",
        "path",
        "pedestrian",
        "cycleway",
        "steps",
        "track",
        "road",
    }
)


def build_overpass_query(min_lat: float, min_lon: float, max_lat: float, max_lon: float) -> str:
    """Build an Overpass QL query for roads, buildings, waterways, wetlands, and green areas."""
    south, north, west, east = validate_bounding_box(min_lat, max_lat, min_lon, max_lon)
    bbox = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    return f"""[out:json][timeout:40];
(
  way["highway"]({bbox});
  wr["building"]({bbox});
  wr["waterway"]({bbox});
  wr["natural"~"^(water|wetland|wood|scrub|grassland)$"]({bbox});
  way["landuse"~"^(reservoir|basin|grass|forest|meadow|recreation_ground|park)$"]({bbox});
  way["leisure"~"^(park|garden|playground)$"]({bbox});
);
out geom;
"""


def classify_road_category(subcategory: str, tags: dict[str, Any] | None = None) -> str:
    """Classify an OSM highway value into standardized road categories."""
    hw = (subcategory or (tags or {}).get("highway") or "").lower().strip()
    if hw in ("motorway", "motorway_link", "trunk", "trunk_link"):
        return "Motorway / Major"
    if hw in ("primary", "primary_link"):
        return "Primary"
    if hw in ("secondary", "secondary_link"):
        return "Secondary"
    if hw in ("tertiary", "tertiary_link"):
        return "Tertiary"
    if hw in ("residential", "living_street", "unclassified"):
        return "Residential"
    if hw == "service":
        return "Service"
    if hw in ("footway", "path", "pedestrian", "cycleway", "steps"):
        return "Footpath"
    return "Residential"


def classify_building_category(subcategory: str, tags: dict[str, Any] | None = None) -> str:
    """Classify an OSM building tag without inferring occupancy or population."""
    bval = (subcategory or (tags or {}).get("building") or "").lower().strip()
    amenity = str((tags or {}).get("amenity") or "").lower().strip()
    if bval in ("residential", "apartments", "house", "detached", "dormitory", "terrace"):
        return "Residential"
    if bval in ("commercial", "retail", "office", "supermarket", "hotel", "mall"):
        return "Commercial"
    if bval in ("industrial", "warehouse", "factory", "manufacture"):
        return "Industrial"
    if bval in ("school", "university", "college", "hospital", "public", "civic", "government") or amenity in (
        "school",
        "university",
        "college",
        "hospital",
        "clinic",
        "community_centre",
    ):
        return "Public / Institutional"
    return "General Building"


def _classify_tags(tags: dict[str, Any]) -> tuple[str, str]:
    """Map OSM tags into (category, subcategory)."""
    if "waterway" in tags:
        return "waterway", str(tags.get("waterway") or "waterway")
    if tags.get("natural") == "water" or tags.get("landuse") in ("reservoir", "basin"):
        sub = tags.get("water") or tags.get("landuse") or "water"
        return "waterway", str(sub)
    if tags.get("natural") == "wetland":
        return "green_area", "wetland"
    if "building" in tags:
        btype = str(tags.get("building") or "yes")
        return "building", "building" if btype == "yes" else btype
    if "highway" in tags:
        return "road", str(tags.get("highway") or "road")
    if (
        tags.get("leisure") in ("park", "garden", "playground")
        or tags.get("landuse") in ("grass", "forest", "meadow", "recreation_ground", "park")
        or tags.get("natural") in ("wood", "scrub", "grassland")
    ):
        sub = tags.get("leisure") or tags.get("landuse") or tags.get("natural") or "green"
        return "green_area", str(sub)
    return "other", "feature"


def _points_to_ring(coords: list[list[float]]) -> list[list[float]]:
    if coords[0] != coords[-1]:
        return coords + [coords[0]]
    return coords


def _way_geometry_to_geojson(
    raw_geom: Any,
    prefer_polygon: bool,
) -> dict[str, Any] | None:
    if not isinstance(raw_geom, list) or len(raw_geom) < 2:
        return None
    coords: list[list[float]] = []
    for pt in raw_geom:
        if not isinstance(pt, dict) or "lon" not in pt or "lat" not in pt:
            return None
        coords.append([float(pt["lon"]), float(pt["lat"])])

    is_closed = len(coords) >= 4 and coords[0] == coords[-1]
    if prefer_polygon and len(coords) >= 3:
        ring = _points_to_ring(coords)
        if len(ring) >= 4:
            return {"type": "Polygon", "coordinates": [ring]}
    if is_closed and prefer_polygon:
        return {"type": "Polygon", "coordinates": [coords]}
    return {"type": "LineString", "coordinates": coords}


def _relation_to_geojson(members: Any, prefer_polygon: bool) -> dict[str, Any] | None:
    if not isinstance(members, list):
        return None
    polygons: list[list[list[list[float]]]] = []
    lines: list[list[list[float]]] = []

    for member in members:
        if not isinstance(member, dict):
            continue
        geom = member.get("geometry")
        if not isinstance(geom, list) or len(geom) < 2:
            continue
        coords = []
        valid = True
        for pt in geom:
            if not isinstance(pt, dict) or "lon" not in pt or "lat" not in pt:
                valid = False
                break
            coords.append([float(pt["lon"]), float(pt["lat"])])
        if not valid:
            continue

        role = member.get("role", "outer")
        if prefer_polygon and len(coords) >= 3 and role in ("outer", ""):
            ring = _points_to_ring(coords)
            if len(ring) >= 4:
                polygons.append([ring])
        else:
            lines.append(coords)

    if polygons:
        if len(polygons) == 1:
            return {"type": "Polygon", "coordinates": polygons[0]}
        return {"type": "MultiPolygon", "coordinates": polygons}
    if lines:
        if len(lines) == 1:
            return {"type": "LineString", "coordinates": lines[0]}
        return {"type": "MultiLineString", "coordinates": lines}
    return None


def parse_overpass_response(
    raw_data: Any,
    neighbourhood_id: int = 0,
    imported_at: str = "",
) -> list[OSMFeature]:
    """Parse and validate Overpass JSON into OSMFeature records."""
    if not isinstance(raw_data, dict) or "elements" not in raw_data:
        raise OSMImportError("Invalid Overpass response: missing 'elements' field.")

    elements = raw_data.get("elements")
    if not isinstance(elements, list):
        raise OSMImportError("Invalid Overpass response: 'elements' must be a list.")

    stamp = imported_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    features: list[OSMFeature] = []
    seen: set[tuple[str, int]] = set()

    for elem in elements:
        if not isinstance(elem, dict):
            continue
        el_type = elem.get("type")
        el_id = elem.get("id")
        if el_type not in ("way", "relation", "node") or el_id is None:
            continue

        try:
            osm_id = int(el_id)
        except (TypeError, ValueError):
            continue

        key = (str(el_type), osm_id)
        if key in seen:
            continue

        tags = elem.get("tags") if isinstance(elem.get("tags"), dict) else {}
        if not tags:
            continue

        category, subcategory = _classify_tags(tags)
        if category == "road" and subcategory.lower().strip() not in _ALLOWED_HIGHWAY_VALUES:
            continue
        prefer_polygon = category in ("building", "green_area") or (
            category == "waterway"
            and (tags.get("natural") == "water" or tags.get("landuse") in ("reservoir", "basin"))
        )

        geojson: dict[str, Any] | None = None
        try:
            if el_type == "way":
                geojson = _way_geometry_to_geojson(elem.get("geometry"), prefer_polygon)
            elif el_type == "relation":
                geojson = _relation_to_geojson(elem.get("members"), prefer_polygon)
            elif el_type == "node" and "lat" in elem and "lon" in elem:
                geojson = {"type": "Point", "coordinates": [float(elem["lon"]), float(elem["lat"])]}

            if geojson is None:
                continue
            validate_geojson_geometry(geojson)
        except (ValidationError, TypeError, ValueError) as exc:
            logger.debug("Skipping malformed OSM element %s/%s: %s", el_type, osm_id, exc)
            continue

        seen.add(key)
        name = str(tags.get("name") or tags.get("name:en") or "").strip()
        length_m = calculate_geometry_length_m(geojson) if category in ("road", "waterway") else 0.0
        road_cat = classify_road_category(subcategory, tags) if category == "road" else ""
        bldg_cat = classify_building_category(subcategory, tags) if category == "building" else ""
        features.append(
            OSMFeature(
                id=None,
                neighbourhood_id=neighbourhood_id,
                osm_id=osm_id,
                element_type=str(el_type),
                category=category,
                subcategory=subcategory,
                name=name,
                geometry=geojson,
                tags={str(k): str(v) for k, v in tags.items()},
                source="OpenStreetMap (Overpass API)",
                imported_at=stamp,
                length_m=length_m,
                road_category=road_cat,
                building_category=bldg_cat,
            )
        )

    return features


class OSMService:
    """Rate-limited Overpass client with local JSON caching."""

    def __init__(
        self,
        cache_service: CacheService | None = None,
        session: requests.Session | None = None,
        endpoints: tuple[str, ...] = OVERPASS_URLS,
    ) -> None:
        self.cache = cache_service or CacheService()
        self.session = session or requests.Session()
        self.endpoints = endpoints
        self._lock = threading.Lock()
        self._last_request_ts = 0.0

    def fetch_features(
        self,
        neighbourhood_id: int,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        force_refresh: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> tuple[list[OSMFeature], bool]:
        """Fetch OSM features for the bounding box. Returns (features, from_cache)."""
        south, north, west, east = validate_bounding_box(min_lat, max_lat, min_lon, max_lon)
        cache_key = f"overpass:{south:.5f},{west:.5f},{north:.5f},{east:.5f}"

        if not force_refresh:
            cached = self.cache.get("osm", cache_key, max_age_seconds=OSM_CACHE_TTL_SECONDS)
            if cached is not None:
                payload, cached_at, _ = cached
                features = parse_overpass_response(
                    payload,
                    neighbourhood_id=neighbourhood_id,
                    imported_at=cached_at,
                )
                return features, True

        if cancel_event and cancel_event.is_set():
            raise OSMImportError("OpenStreetMap import cancelled.")

        query = build_overpass_query(south, west, north, east)
        self._respect_rate_limit(cancel_event)

        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        last_error: str = "Unknown error"

        for endpoint in self.endpoints:
            if cancel_event and cancel_event.is_set():
                raise OSMImportError("OpenStreetMap import cancelled.")
            try:
                resp = self.session.post(
                    endpoint,
                    data={"data": query},
                    headers=headers,
                    timeout=OVERPASS_TIMEOUT_SECONDS,
                )
            except requests.Timeout:
                last_error = f"Timed out contacting {endpoint}."
                logger.warning(last_error)
                continue
            except requests.RequestException as exc:
                last_error = f"Network error contacting {endpoint}: {exc}"
                logger.warning(last_error)
                continue

            if resp.status_code == 429:
                last_error = f"Overpass rate limit reached (HTTP 429) on {endpoint}."
                logger.warning(last_error)
                continue
            if resp.status_code >= 500:
                last_error = f"Overpass server busy (HTTP {resp.status_code}) on {endpoint}."
                logger.warning(last_error)
                continue
            if resp.status_code >= 400:
                raise OSMImportError(f"Overpass rejected query (HTTP {resp.status_code}).")

            try:
                raw_data = resp.json()
            except ValueError as exc:
                last_error = f"Invalid JSON returned by {endpoint}."
                logger.warning("%s: %s", last_error, exc)
                continue

            stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            features = parse_overpass_response(
                raw_data,
                neighbourhood_id=neighbourhood_id,
                imported_at=stamp,
            )
            self.cache.set("osm", cache_key, raw_data, source=f"Overpass API ({endpoint})")
            return features, False

        raise OSMImportError(
            f"Unable to retrieve OpenStreetMap features ({last_error}). "
            "Previously saved data has been preserved."
        )

    def _respect_rate_limit(self, cancel_event: threading.Event | None) -> None:
        with self._lock:
            now = time.monotonic()
            wait = OVERPASS_MIN_INTERVAL_SEC - (now - self._last_request_ts)
            if wait > 0:
                if cancel_event and cancel_event.wait(wait):
                    raise OSMImportError("OpenStreetMap import cancelled.")
                if not cancel_event:
                    time.sleep(wait)
            self._last_request_ts = time.monotonic()

