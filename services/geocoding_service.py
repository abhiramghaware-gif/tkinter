"""OpenStreetMap Nominatim geocoding service for resolving neighbourhood bounds."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

from config import (
    DEFAULT_POINT_EXPAND_HALF_SPAN_DEG,
    MAX_BBOX_SPAN_DEG,
    MIN_BBOX_SPAN_DEG,
    NOMINATIM_MIN_INTERVAL_SEC,
    NOMINATIM_URL,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
)
from core.models import GeocodingResult
from core.validation import ValidationError, validate_latitude, validate_longitude
from services.cache_service import CacheService

logger = logging.getLogger(__name__)


class GeocodingError(RuntimeError):
    """Raised when location resolution fails."""


def parse_nominatim_response(raw_data: Any) -> list[GeocodingResult]:
    """Parse and validate a Nominatim JSON list into GeocodingResult objects."""
    if not isinstance(raw_data, list):
        raise GeocodingError("Unexpected geocoding response format (expected JSON list).")

    results: list[GeocodingResult] = []
    for item in raw_data:
        if not isinstance(item, dict):
            continue
        try:
            lat = validate_latitude(item.get("lat"), "Nominatim latitude")
            lon = validate_longitude(item.get("lon"), "Nominatim longitude")
        except ValidationError as exc:
            logger.warning("Skipping invalid Nominatim item: %s", exc)
            continue

        display_name = str(item.get("display_name") or "").strip()
        if not display_name:
            display_name = f"{lat:.5f}, {lon:.5f}"

        address = item.get("address") if isinstance(item.get("address"), dict) else {}
        name = str(
            item.get("name")
            or address.get("suburb")
            or address.get("village")
            or address.get("town")
            or address.get("neighbourhood")
            or display_name.split(",")[0]
        ).strip()
        district = str(
            address.get("state_district")
            or address.get("county")
            or address.get("city_district")
            or ""
        ).strip()
        state = str(address.get("state") or "").strip()
        country = str(address.get("country") or "").strip()

        bbox_note = ""
        raw_bbox = item.get("boundingbox")
        south = north = west = east = 0.0
        bbox_parsed = False

        if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
            try:
                # Nominatim returns [south, north, west, east]
                south = validate_latitude(raw_bbox[0], "South latitude")
                north = validate_latitude(raw_bbox[1], "North latitude")
                west = validate_longitude(raw_bbox[2], "West longitude")
                east = validate_longitude(raw_bbox[3], "East longitude")
                if south < north and west < east:
                    bbox_parsed = True
            except ValidationError:
                bbox_parsed = False

        if not bbox_parsed:
            half = DEFAULT_POINT_EXPAND_HALF_SPAN_DEG
            south, north = max(-89.9, lat - half), min(89.9, lat + half)
            west, east = max(-179.9, lon - half), min(179.9, lon + half)
            bbox_note = "Expanded from point coordinates (~1.7 km box)."
        else:
            lat_span = north - south
            lon_span = east - west
            if lat_span < MIN_BBOX_SPAN_DEG or lon_span < MIN_BBOX_SPAN_DEG:
                half = DEFAULT_POINT_EXPAND_HALF_SPAN_DEG
                south = min(south, max(-89.9, lat - half))
                north = max(north, min(89.9, lat + half))
                west = min(west, max(-179.9, lon - half))
                east = max(east, min(179.9, lon + half))
                bbox_note = "Expanded narrow boundary to ~1.7 km neighbourhood extent."
            elif lat_span > MAX_BBOX_SPAN_DEG or lon_span > MAX_BBOX_SPAN_DEG:
                half = MAX_BBOX_SPAN_DEG / 2.0
                south = max(south, lat - half)
                north = min(north, lat + half)
                west = max(west, lon - half)
                east = min(east, lon + half)
                bbox_note = f"Clamped large regional box to <= {MAX_BBOX_SPAN_DEG}° neighbourhood span."

        osm_id_val = item.get("osm_id")
        try:
            osm_id = int(osm_id_val) if osm_id_val is not None else None
        except (TypeError, ValueError):
            osm_id = None

        results.append(
            GeocodingResult(
                display_name=display_name,
                name=name,
                district=district,
                state=state,
                country=country,
                latitude=lat,
                longitude=lon,
                min_latitude=south,
                max_latitude=north,
                min_longitude=west,
                max_longitude=east,
                osm_type=str(item.get("osm_type") or ""),
                osm_id=osm_id,
                bbox_adjusted_note=bbox_note,
            )
        )

    return results


class GeocodingService:
    """Rate-limited Nominatim client with local caching."""

    def __init__(
        self,
        cache_service: CacheService | None = None,
        session: requests.Session | None = None,
        base_url: str = NOMINATIM_URL,
    ) -> None:
        self.cache = cache_service or CacheService()
        self.session = session or requests.Session()
        self.base_url = base_url
        self._lock = threading.Lock()
        self._last_request_ts = 0.0

    def search_location(
        self,
        query: str,
        limit: int = 5,
        force_refresh: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> tuple[list[GeocodingResult], bool]:
        """Resolve a place query via Nominatim. Returns (results, from_cache)."""
        clean_query = (query or "").strip()
        if not clean_query:
            raise GeocodingError("Please enter a location name to search.")

        cache_key = f"nominatim:{clean_query.lower()}:limit={limit}"
        if not force_refresh:
            cached = self.cache.get("geocoding", cache_key)
            if cached is not None:
                payload, _, _ = cached
                parsed = parse_nominatim_response(payload)
                if parsed:
                    return parsed, True

        if cancel_event and cancel_event.is_set():
            raise GeocodingError("Location search cancelled.")

        self._respect_rate_limit(cancel_event)

        params = {
            "q": clean_query,
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": limit,
        }
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en",
        }

        try:
            resp = self.session.get(
                self.base_url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise GeocodingError(
                "Nominatim geocoding request timed out. Check your connection and retry."
            ) from exc
        except requests.RequestException as exc:
            raise GeocodingError(f"Network error contacting Nominatim: {exc}") from exc

        if resp.status_code == 429:
            raise GeocodingError("Nominatim rate limit reached (HTTP 429). Please wait and retry.")
        if resp.status_code >= 400:
            raise GeocodingError(f"Nominatim returned HTTP {resp.status_code}.")

        try:
            data = resp.json()
        except ValueError as exc:
            raise GeocodingError("Nominatim returned invalid JSON.") from exc

        results = parse_nominatim_response(data)
        if not results:
            raise GeocodingError(f"No geographical results found for '{clean_query}'.")

        self.cache.set("geocoding", cache_key, data, source="OpenStreetMap Nominatim")
        return results, False

    def _respect_rate_limit(self, cancel_event: threading.Event | None) -> None:
        with self._lock:
            now = time.monotonic()
            wait = NOMINATIM_MIN_INTERVAL_SEC - (now - self._last_request_ts)
            if wait > 0:
                if cancel_event and cancel_event.wait(wait):
                    raise GeocodingError("Location search cancelled.")
                if not cancel_event:
                    time.sleep(wait)
            self._last_request_ts = time.monotonic()

