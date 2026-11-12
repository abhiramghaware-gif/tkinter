"""Open-Meteo weather integration with offline fallback and explicit data provenance."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any

import requests

from config import (
    OPEN_METEO_ATTRIBUTION,
    OPEN_METEO_URL,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    WEATHER_CACHE_TTL_SECONDS,
)
from core.models import HourlyForecastPoint, WeatherSnapshot
from core.validation import validate_latitude, validate_longitude
from services.cache_service import CacheService, format_age_seconds

logger = logging.getLogger(__name__)


WMO_WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherServiceError(RuntimeError):
    """Raised when live weather retrieval fails."""


def decode_wmo_weather_code(code: int | None) -> str:
    if code is None:
        return "Unavailable"
    return WMO_WEATHER_CODES.get(int(code), f"WMO Code {code}")


def _safe_float(val: Any) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        num = float(val)
        return num if math.isfinite(num) else None
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    if val is None or isinstance(val, bool):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def extract_hourly_from_raw(raw_data: dict[str, Any]) -> list[HourlyForecastPoint]:
    """Extract hourly forecast rows from an Open-Meteo JSON payload."""
    hourly = raw_data.get("hourly")
    if not isinstance(hourly, dict):
        return []

    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    hums = hourly.get("relative_humidity_2m") or []
    precips = hourly.get("precipitation") or []
    rains = hourly.get("rain") or []
    codes = hourly.get("weather_code") or []

    points: list[HourlyForecastPoint] = []
    for idx, t_str in enumerate(times[:48]):
        points.append(
            HourlyForecastPoint(
                time_iso=str(t_str),
                temperature_c=_safe_float(temps[idx]) if idx < len(temps) else None,
                humidity_pct=_safe_float(hums[idx]) if idx < len(hums) else None,
                precipitation_mm=_safe_float(precips[idx]) if idx < len(precips) else None,
                rain_mm=_safe_float(rains[idx]) if idx < len(rains) else None,
                weather_code=_safe_int(codes[idx]) if idx < len(codes) else None,
            )
        )
    return points


def parse_open_meteo_response(
    raw_data: Any,
    neighbourhood_id: int = 0,
    retrieved_at: str = "",
) -> WeatherSnapshot:
    """Parse and validate an Open-Meteo Forecast API JSON response."""
    if not isinstance(raw_data, dict):
        raise WeatherServiceError("Invalid Open-Meteo response (expected JSON object).")

    current = raw_data.get("current")
    if not isinstance(current, dict):
        raise WeatherServiceError("Open-Meteo response missing 'current' weather block.")

    stamp = retrieved_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    wcode = _safe_int(current.get("weather_code"))
    hourly = extract_hourly_from_raw(raw_data)

    return WeatherSnapshot(
        id=None,
        neighbourhood_id=neighbourhood_id,
        temperature_c=_safe_float(current.get("temperature_2m")),
        humidity_pct=_safe_float(current.get("relative_humidity_2m")),
        precipitation_mm=_safe_float(current.get("precipitation")),
        rainfall_mm=_safe_float(current.get("rain")),
        weather_code=wcode,
        weather_description=decode_wmo_weather_code(wcode),
        data_type="Open-Meteo Current Model Field & Hourly Forecast (Not Physical Gauge)",
        source=OPEN_METEO_ATTRIBUTION,
        observed_at=str(current.get("time") or ""),
        retrieved_at=stamp,
        hourly_forecast=hourly,
        raw_json=json.dumps(raw_data, separators=(",", ":")),
        is_stale=False,
        age_label="Just retrieved",
    )


def compute_snapshot_age(snapshot: WeatherSnapshot) -> WeatherSnapshot:
    """Populate age_label and is_stale flag relative to current UTC time."""
    if not snapshot.retrieved_at:
        snapshot.age_label = "Unknown age"
        snapshot.is_stale = True
        return snapshot
    try:
        dt = datetime.fromisoformat(snapshot.retrieved_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
        snapshot.age_label = format_age_seconds(age)
        snapshot.is_stale = age > WEATHER_CACHE_TTL_SECONDS
    except ValueError:
        snapshot.age_label = snapshot.retrieved_at
        snapshot.is_stale = True
    return snapshot


def check_internet_connectivity(timeout: float = 3.5) -> bool:
    """Perform a single lightweight connectivity probe (never called in tight loops)."""
    try:
        resp = requests.head(
            "https://api.open-meteo.com/v1/forecast",
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        return resp.status_code < 500
    except requests.RequestException:
        return False


class WeatherService:
    """Optional Open-Meteo client with cache & offline fallback."""

    def __init__(
        self,
        cache_service: CacheService | None = None,
        session: requests.Session | None = None,
        base_url: str = OPEN_METEO_URL,
    ) -> None:
        self.cache = cache_service or CacheService()
        self.session = session or requests.Session()
        self.base_url = base_url

    def fetch_live_weather(
        self,
        neighbourhood_id: int,
        latitude: float,
        longitude: float,
    ) -> WeatherSnapshot:
        """Fetch live current-model + hourly forecast from Open-Meteo."""
        lat = validate_latitude(latitude, "Weather latitude")
        lon = validate_longitude(longitude, "Weather longitude")

        params = {
            "latitude": f"{lat:.5f}",
            "longitude": f"{lon:.5f}",
            "current": "temperature_2m,relative_humidity_2m,precipitation,rain,weather_code",
            "hourly": "temperature_2m,relative_humidity_2m,precipitation,rain,weather_code",
            "forecast_days": 2,
            "timezone": "auto",
        }
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }

        try:
            resp = self.session.get(
                self.base_url,
                params=params,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.Timeout as exc:
            raise WeatherServiceError("Open-Meteo request timed out.") from exc
        except requests.RequestException as exc:
            raise WeatherServiceError(f"Network error contacting Open-Meteo: {exc}") from exc

        if resp.status_code == 429:
            raise WeatherServiceError("Open-Meteo rate limit reached (HTTP 429).")
        if resp.status_code >= 400:
            raise WeatherServiceError(f"Open-Meteo returned HTTP {resp.status_code}.")

        try:
            data = resp.json()
        except ValueError as exc:
            raise WeatherServiceError("Open-Meteo returned invalid JSON.") from exc

        snapshot = parse_open_meteo_response(data, neighbourhood_id=neighbourhood_id)
        cache_key = f"open_meteo:{lat:.4f},{lon:.4f}"
        self.cache.set("weather", cache_key, data, source=OPEN_METEO_ATTRIBUTION)
        return snapshot

    def get_cached_file_weather(
        self,
        neighbourhood_id: int,
        latitude: float,
        longitude: float,
    ) -> WeatherSnapshot | None:
        """Return locally cached Open-Meteo payload (marked stale if past TTL)."""
        cache_key = f"open_meteo:{latitude:.4f},{longitude:.4f}"
        cached = self.cache.get("weather", cache_key, max_age_seconds=None)
        if cached is None:
            return None
        payload, cached_at, _ = cached
        try:
            snap = parse_open_meteo_response(
                payload,
                neighbourhood_id=neighbourhood_id,
                retrieved_at=cached_at,
            )
            return compute_snapshot_age(snap)
        except WeatherServiceError:
            return None

