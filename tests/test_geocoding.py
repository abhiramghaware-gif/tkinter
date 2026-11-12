"""Offline mock-based tests for Nominatim geocoding, Overpass OSM parsing, Open-Meteo weather, and failed requests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from services.cache_service import CacheService
from services.geocoding_service import GeocodingError, GeocodingService, parse_nominatim_response
from services.osm_service import OSMImportError, OSMService, parse_overpass_response
from services.weather_service import WeatherService, WeatherServiceError, parse_open_meteo_response

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_parse_nominatim_fixture() -> None:
    raw = json.loads((FIXTURES_DIR / "sample_nominatim.json").read_text(encoding="utf-8"))
    results = parse_nominatim_response(raw)
    assert len(results) == 1
    r = results[0]
    assert r.name == "Sample Neighbourhood"
    assert r.min_latitude < r.max_latitude
    assert r.min_longitude < r.max_longitude
    assert r.district == "Chengalpattu"


def test_parse_overpass_fixture_and_skip_malformed() -> None:
    raw = json.loads((FIXTURES_DIR / "sample_geometries.json").read_text(encoding="utf-8"))
    features = parse_overpass_response(raw, neighbourhood_id=1)

    # 5 elements in fixture: 4 valid (road, building, waterway, green_area) + 1 invalid lat=999 skipped
    assert len(features) == 4
    categories = {f.category for f in features}
    assert categories == {"road", "building", "waterway", "green_area"}

    building = next(f for f in features if f.category == "building")
    assert building.geometry["type"] == "Polygon"
    road = next(f for f in features if f.category == "road")
    assert road.geometry["type"] == "LineString"


def test_parse_open_meteo_weather_fixture() -> None:
    raw = json.loads((FIXTURES_DIR / "sample_weather.json").read_text(encoding="utf-8"))
    snap = parse_open_meteo_response(raw, neighbourhood_id=1)
    assert snap.temperature_c == 28.4
    assert snap.humidity_pct == 82.0
    assert snap.precipitation_mm == 1.2
    assert snap.rainfall_mm == 1.2
    assert snap.weather_description == "Slight rain"
    assert len(snap.hourly_forecast) == 3
    assert snap.hourly_forecast[1].precipitation_mm == 2.4


def test_failed_external_requests_handled_gracefully(tmp_path: Path) -> None:
    cache = CacheService(cache_dir=tmp_path / "cache")

    # 1. Geocoding timeout
    mock_session = MagicMock(spec=requests.Session)
    mock_session.get.side_effect = requests.Timeout("Simulated timeout")
    geo_svc = GeocodingService(cache_service=cache, session=mock_session)
    with pytest.raises(GeocodingError, match="timed out"):
        geo_svc.search_location("Potheri", force_refresh=True)

    # 2. Geocoding empty response
    empty_resp = MagicMock()
    empty_resp.status_code = 200
    empty_resp.json.return_value = []
    mock_session.get.side_effect = None
    mock_session.get.return_value = empty_resp
    with pytest.raises(GeocodingError, match="No geographical results"):
        geo_svc.search_location("NonexistentPlaceXYZ", force_refresh=True)

    # 3. Overpass HTTP 429 / invalid JSON
    osm_session = MagicMock(spec=requests.Session)
    rate_resp = MagicMock()
    rate_resp.status_code = 429
    osm_session.post.return_value = rate_resp
    osm_svc = OSMService(cache_service=cache, session=osm_session, endpoints=("https://mock.overpass/api",))
    with pytest.raises(OSMImportError, match="HTTP 429"):
        osm_svc.fetch_features(1, 12.815, 12.831, 80.036, 80.052, force_refresh=True)

    # 4. Weather invalid JSON
    weather_session = MagicMock(spec=requests.Session)
    bad_json_resp = MagicMock()
    bad_json_resp.status_code = 200
    bad_json_resp.json.side_effect = ValueError("Bad JSON")
    weather_session.get.return_value = bad_json_resp
    weather_svc = WeatherService(cache_service=cache, session=weather_session)
    with pytest.raises(WeatherServiceError, match="invalid JSON"):
        weather_svc.fetch_live_weather(1, 12.823, 80.044)

