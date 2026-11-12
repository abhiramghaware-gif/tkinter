"""Phase 2 automated test suite using synthetic fixtures (no internet required)."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from core.geo_utils import calculate_geometry_length_m, compute_feature_grid_links
from core.models import DrainageFeature, GridCell, approximate_cell_metrics_m
from core.validation import ValidationError, validate_drainage_inputs, validate_land_use
from core.workspace import WorkspaceManager
from database.db import DatabaseManager
from database.repository import FloodGuardRepository
from services.elevation_service import RASTERIO_AVAILABLE, ElevationService
from services.geojson_io_service import GeoDataIOError, GeoJSONIOService
from services.osm_service import classify_road_category, parse_overpass_response
from visualization.map_renderer import GeoViewport

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_geo_viewport_coordinate_roundtrip_and_zoom() -> None:
    vp = GeoViewport(12.815, 12.831, 80.036, 80.052, width=800, height=600)
    lat, lon = 12.823, 80.044
    x, y = vp.geo_to_screen(lat, lon)
    r_lat, r_lon = vp.screen_to_geo(x, y)
    assert abs(r_lat - lat) < 1e-7
    assert abs(r_lon - lon) < 1e-7

    # Zoom around cursor should keep the geographic point under pivot fixed
    vp.zoom_at(2.0, x + 40, y - 30)
    vp.pan_by(15, -20)
    x2, y2 = vp.geo_to_screen(lat, lon)
    r_lat2, r_lon2 = vp.screen_to_geo(x2, y2)
    assert abs(r_lat2 - lat) < 1e-7
    assert abs(r_lon2 - lon) < 1e-7


def test_grid_cell_bounds_and_spherical_area_calculations() -> None:
    w_eq, h_eq, area_eq = approximate_cell_metrics_m(0.0, 0.01, 80.0, 80.01)
    w_ch, h_ch, area_ch = approximate_cell_metrics_m(12.82, 12.83, 80.04, 80.05)

    # At 12.8N latitude, East-West width and area must be smaller than at equator (~cos(12.8 deg))
    assert w_ch < w_eq
    assert area_ch < area_eq
    assert abs(h_ch - h_eq) < 5.0
    assert abs(area_ch - (w_ch * h_ch)) / area_ch < 0.01


def test_road_classification_and_geodesic_length() -> None:
    assert classify_road_category("motorway") == "Motorway / Major"
    assert classify_road_category("primary") == "Primary"
    assert classify_road_category("secondary") == "Secondary"
    assert classify_road_category("tertiary") == "Tertiary"
    assert classify_road_category("residential") == "Residential"
    assert classify_road_category("service") == "Service"
    assert classify_road_category("footway") == "Footpath"

    # Synthetic ~1.11 km meridian line
    geom = {"type": "LineString", "coordinates": [[80.04, 12.82], [80.04, 12.83]]}
    length_m = calculate_geometry_length_m(geom)
    assert 1100.0 < length_m < 1125.0


def test_land_use_validation_mixed_use_and_inference(tmp_path: Path) -> None:
    assert validate_land_use("Mixed Use") == "Mixed Use"
    with pytest.raises(ValidationError):
        validate_land_use("InvalidZone")

    db_mgr = DatabaseManager(db_path=tmp_path / "lu.db")
    db_mgr.initialize()
    repo = FloodGuardRepository(db_mgr)
    ws_mgr = WorkspaceManager(repo)

    ws, _ = ws_mgr.create_or_get_workspace(
        name="LU_TEST",
        center_latitude=12.823,
        center_longitude=80.044,
        min_latitude=12.820,
        max_latitude=12.825,
        min_longitude=80.040,
        max_longitude=80.045,
        grid_rows=2,
        grid_cols=2,
    )
    assert ws.id is not None

    raw = json.loads((FIXTURES_DIR / "sample_geometries.json").read_text(encoding="utf-8"))
    feats = parse_overpass_response(raw, neighbourhood_id=ws.id)
    repo.replace_osm_features(ws.id, feats)
    links_cnt = ws_mgr.rebuild_feature_grid_links(ws.id)
    assert links_cnt > 0

    suggested = ws_mgr.suggest_land_use_from_features(ws.id)
    assert suggested > 0
    cells = repo.get_grid_cells(ws.id)
    assert any(c.land_use_source == "inferred" for c in cells)
    history = repo.get_land_use_history(ws.id)
    assert len(history) == suggested


def test_feature_to_grid_links_and_multi_cell_intersection(tmp_path: Path) -> None:
    db_mgr = DatabaseManager(db_path=tmp_path / "links.db")
    db_mgr.initialize()
    repo = FloodGuardRepository(db_mgr)
    ws_mgr = WorkspaceManager(repo)

    ws, _ = ws_mgr.create_or_get_workspace(
        name="LINKS_TEST",
        center_latitude=12.8225,
        center_longitude=80.0425,
        min_latitude=12.820,
        max_latitude=12.825,
        min_longitude=80.040,
        max_longitude=80.045,
        grid_rows=2,
        grid_cols=2,
    )
    assert ws.id is not None

    raw = json.loads((FIXTURES_DIR / "sample_geometries.json").read_text(encoding="utf-8"))
    feats = parse_overpass_response(raw, neighbourhood_id=ws.id)
    repo.replace_osm_features(ws.id, feats)

    cells = repo.get_grid_cells(ws.id)
    stored_feats = repo.get_osm_features(ws.id)
    links = compute_feature_grid_links(cells, stored_feats, [])
    repo.replace_grid_feature_links(ws.id, links)

    # Diagonal road in fixture crosses multiple cells, stored once in osm_features
    road = next(f for f in stored_feats if f.category == "road")
    assert road.id is not None
    intersected_cells = repo.get_cells_for_osm_feature(road.id)
    assert len(intersected_cells) >= 2
    assert len(repo.get_osm_features(ws.id)) == 4


def test_drainage_creation_editing_and_persistence(tmp_path: Path) -> None:
    cname, ctype, lat, lon, cap, unit, status = validate_drainage_inputs(
        "GST Culvert 1", "Culvert", "12.823", "80.044", "45.5", "L/s", "Partially blocked"
    )
    assert cname == "GST Culvert 1"
    assert cap == 45.5

    with pytest.raises(ValidationError):
        validate_drainage_inputs("", "Culvert", "12.823", "80.044", "10", "L/s", "Operational")

    db_file = tmp_path / "drain.db"
    db1 = DatabaseManager(db_path=db_file)
    db1.initialize()
    repo1 = FloodGuardRepository(db1)
    ws_mgr1 = WorkspaceManager(repo1)

    ws, _ = ws_mgr1.create_or_get_workspace(
        name="DRAIN_TEST",
        center_latitude=12.823,
        center_longitude=80.044,
        min_latitude=12.815,
        max_latitude=12.831,
        min_longitude=80.036,
        max_longitude=80.052,
    )
    assert ws.id is not None
    cells = repo1.get_grid_cells(ws.id)
    target_cell = ws_mgr1.find_cell_for_point(cells, lat, lon)
    assert target_cell is not None

    dr = repo1.create_drainage_feature(
        DrainageFeature(
            id=None,
            neighbourhood_id=ws.id,
            grid_cell_id=target_cell.id,
            name=cname,
            feature_type=ctype,
            latitude=lat,
            longitude=lon,
            capacity=cap,
            capacity_unit=unit,
            status=status,
            source="user-entered",
            notes="Needs desilting",
        )
    )
    assert dr.id is not None

    # Offline edit & persistence check across fresh DB instance
    dr.status = "Operational"
    repo1.update_drainage_feature(dr)

    db2 = DatabaseManager(db_path=db_file)
    repo2 = FloodGuardRepository(db2)
    loaded = repo2.list_drainage_features(ws.id)
    assert len(loaded) == 1
    assert loaded[0].status == "Operational"
    assert loaded[0].source == "user-entered"


def test_elevation_geotiff_import_and_missing_values(tmp_path: Path) -> None:
    if not RASTERIO_AVAILABLE:
        pytest.skip("rasterio not installed")

    import rasterio
    from rasterio.transform import from_bounds

    db_mgr = DatabaseManager(db_path=tmp_path / "elev.db")
    db_mgr.initialize()
    repo = FloodGuardRepository(db_mgr)
    ws_mgr = WorkspaceManager(repo)

    ws, _ = ws_mgr.create_or_get_workspace(
        name="ELEV_TEST",
        center_latitude=12.8225,
        center_longitude=80.0425,
        min_latitude=12.820,
        max_latitude=12.825,
        min_longitude=80.040,
        max_longitude=80.045,
        grid_rows=2,
        grid_cols=2,
    )
    assert ws.id is not None

    # Create synthetic GeoTIFF covering only the northern half, with nodata=-9999 in eastern cell
    tif_path = tmp_path / "synthetic_dem.tif"
    arr = np.array([[18.5, -9999.0], [16.0, 20.0]], dtype=np.float32)
    transform = from_bounds(80.040, 12.8225, 80.045, 12.825, 2, 2)
    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=-9999.0,
    ) as dst:
        dst.write(arr, 1)

    svc = ElevationService()
    cells = repo.get_grid_cells(ws.id)
    summary = svc.load_geotiff_for_grid(tif_path, ws.id, cells, source_name="Synthetic Test DEM")
    repo.update_cells_elevation_batch(summary.cell_updates, ws.id)
    repo.save_elevation_source(summary.source_record)

    updated_cells = repo.get_grid_cells(ws.id)
    # Row 0 Col 0 (NW) is covered -> valid elevation; Southern cells outside raster -> NULL
    nw_cell = next(c for c in updated_cells if c.row_number == 0 and c.column_number == 0)
    sw_cell = next(c for c in updated_cells if c.row_number == 1 and c.column_number == 0)
    assert nw_cell.elevation_m is not None
    assert nw_cell.min_elevation_m is not None and nw_cell.max_elevation_m is not None
    assert "Imported Raster" in (nw_cell.elevation_source or "")
    assert sw_cell.elevation_m is None


def test_geojson_import_export_and_csv_exports(tmp_path: Path) -> None:
    db_mgr = DatabaseManager(db_path=tmp_path / "io.db")
    db_mgr.initialize()
    repo = FloodGuardRepository(db_mgr)
    ws_mgr = WorkspaceManager(repo)

    ws, _ = ws_mgr.create_or_get_workspace(
        name="IO_TEST",
        center_latitude=12.823,
        center_longitude=80.044,
        min_latitude=12.820,
        max_latitude=12.825,
        min_longitude=80.040,
        max_longitude=80.045,
        grid_rows=2,
        grid_cols=2,
    )
    assert ws.id is not None

    sample_geojson = tmp_path / "synthetic_input.geojson"
    sample_geojson.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"category": "road", "highway": "secondary", "name": "Test Avenue"},
                        "geometry": {"type": "LineString", "coordinates": [[80.041, 12.821], [80.044, 12.824]]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    feats = GeoJSONIOService.import_geojson_features(sample_geojson, ws.id)
    assert len(feats) == 1
    assert feats[0].road_category == "Secondary"
    repo.upsert_osm_features(ws.id, feats)

    dr = repo.create_drainage_feature(
        DrainageFeature(
            id=None,
            neighbourhood_id=ws.id,
            grid_cell_id=None,
            name="Inlet 1",
            feature_type="Drain inlet",
            latitude=12.822,
            longitude=80.042,
            capacity=12.0,
            capacity_unit="L/s",
            status="Operational",
        )
    )

    out_geojson = GeoJSONIOService.export_neighbourhood_geojson(
        ws, repo.get_osm_features(ws.id), [dr], tmp_path / "out.geojson"
    )
    out_grid_csv = GeoJSONIOService.export_grid_csv(ws, repo.get_grid_cells(ws.id), tmp_path / "grid.csv")
    out_drain_csv = GeoJSONIOService.export_drainage_csv(ws, [dr], tmp_path / "drain.csv")

    assert out_geojson.exists() and json.loads(out_geojson.read_text(encoding="utf-8"))["type"] == "FeatureCollection"
    with out_grid_csv.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
        assert len(rows) == 4
        assert "approx_area_m2" in rows[0]
    with out_drain_csv.open(encoding="utf-8") as fh:
        drows = list(csv.DictReader(fh))
        assert len(drows) == 1
        assert drows[0]["source"] == "user-entered"

    # Reject invalid GeoJSON
    bad_file = tmp_path / "bad.geojson"
    bad_file.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(GeoDataIOError):
        GeoJSONIOService.import_geojson_features(bad_file, ws.id)


def test_database_migration_v1_to_v2_preserves_phase1_data(tmp_path: Path) -> None:
    db_file = tmp_path / "legacy_v1.db"
    # Build an authentic Phase 1 v1 schema & row manually
    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        CREATE TABLE neighbourhoods (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
            district TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT '', country TEXT NOT NULL DEFAULT '',
            center_latitude REAL NOT NULL, center_longitude REAL NOT NULL,
            min_latitude REAL NOT NULL, max_latitude REAL NOT NULL,
            min_longitude REAL NOT NULL, max_longitude REAL NOT NULL,
            grid_rows INTEGER NOT NULL DEFAULT 10, grid_cols INTEGER NOT NULL DEFAULT 10,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE grid_cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT, neighbourhood_id INTEGER NOT NULL,
            row_number INTEGER NOT NULL, column_number INTEGER NOT NULL,
            min_latitude REAL NOT NULL, max_latitude REAL NOT NULL,
            min_longitude REAL NOT NULL, max_longitude REAL NOT NULL,
            elevation_m REAL, elevation_source TEXT,
            land_use TEXT NOT NULL DEFAULT 'Unknown',
            infiltration_rate REAL NOT NULL DEFAULT 0.0,
            drainage_capacity REAL NOT NULL DEFAULT 0.0,
            notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
            FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
            UNIQUE (neighbourhood_id, row_number, column_number)
        );
        CREATE TABLE osm_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT, neighbourhood_id INTEGER NOT NULL,
            osm_id INTEGER NOT NULL, element_type TEXT NOT NULL, category TEXT NOT NULL,
            subcategory TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '',
            geometry_json TEXT NOT NULL, tags_json TEXT NOT NULL DEFAULT '{}',
            source TEXT NOT NULL DEFAULT 'OpenStreetMap', imported_at TEXT NOT NULL,
            FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
            UNIQUE (neighbourhood_id, element_type, osm_id)
        );
        CREATE TABLE weather_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, neighbourhood_id INTEGER NOT NULL,
            temperature REAL, humidity REAL, precipitation REAL, rainfall REAL,
            weather_code INTEGER, data_type TEXT NOT NULL, source TEXT NOT NULL,
            observed_at TEXT, retrieved_at TEXT NOT NULL, raw_json TEXT NOT NULL,
            FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE
        );
        CREATE TABLE scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT, neighbourhood_id INTEGER NOT NULL,
            scenario_name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE
        );
        CREATE TABLE app_settings (id INTEGER PRIMARY KEY AUTOINCREMENT, setting_key TEXT NOT NULL UNIQUE, setting_value TEXT);
        INSERT INTO schema_migrations VALUES (1, '2026-11-12T00:00:00Z');
        INSERT INTO neighbourhoods VALUES (1, 'POTHERI', 'Chengalpattu', 'Tamil Nadu', 'India', 12.823, 80.044, 12.815, 12.831, 80.036, 80.052, 10, 10, '2026-11-12T00:00:00Z', '2026-11-12T00:00:00Z');
        INSERT INTO grid_cells VALUES (1, 1, 0, 0, 12.8294, 12.831, 80.036, 80.0376, 15.0, 'User-provided', 'Residential', 10.0, 20.0, 'Phase 1 preserved cell', '2026-11-12T00:00:00Z');
        PRAGMA user_version = 1;
        """
    )
    conn.commit()
    conn.close()

    # Initialize DatabaseManager -> must safely migrate v1 -> v2 without losing POTHERI!
    db_mgr = DatabaseManager(db_path=db_file)
    db_mgr.initialize()
    ok, msg = db_mgr.verify_integrity()
    assert ok and "SQLite OK (v" in msg and "FK=ON" in msg

    repo = FloodGuardRepository(db_mgr)
    potheri = repo.get_neighbourhood_by_name("POTHERI")
    assert potheri is not None
    cells = repo.get_grid_cells(potheri.id)
    assert len(cells) == 1
    assert cells[0].notes == "Phase 1 preserved cell"
    assert cells[0].land_use == "Residential"
    assert cells[0].land_use_source == "user-entered"
    assert cells[0].approx_area_sq_m() > 0

    # Offline road editing should also work after migration
    dq = repo.get_data_quality_summary(potheri.id)
    assert dq.total_grid_cells == 1
