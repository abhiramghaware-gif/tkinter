"""Tests for SQLite database initialization, persistence, duplicate handling, and offline access."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.models import WeatherSnapshot
from core.workspace import WorkspaceManager
from database.db import DatabaseManager
from database.repository import FloodGuardRepository


@pytest.fixture
def db_setup(tmp_path: Path) -> tuple[DatabaseManager, FloodGuardRepository, WorkspaceManager]:
    db_file = tmp_path / "test_floodguard.db"
    db_mgr = DatabaseManager(db_path=db_file)
    db_mgr.initialize()
    repo = FloodGuardRepository(db_mgr)
    ws_mgr = WorkspaceManager(repo)
    return db_mgr, repo, ws_mgr


def test_database_initialization_and_foreign_keys(db_setup) -> None:
    db_mgr, _, _ = db_setup
    assert db_mgr.db_path.exists()
    ok, msg = db_mgr.verify_integrity()
    assert ok is True
    assert "FK=ON" in msg

    with db_mgr.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "schema_migrations",
            "neighbourhoods",
            "grid_cells",
            "osm_features",
            "weather_observations",
            "scenarios",
            "app_settings",
        }
        assert expected.issubset(tables)

        # Foreign key violation must raise IntegrityError
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO grid_cells (
                    neighbourhood_id, row_number, column_number,
                    min_latitude, max_latitude, min_longitude, max_longitude,
                    updated_at
                ) VALUES (99999, 0, 0, 12.8, 12.81, 80.0, 80.01, '2026-01-01T00:00:00Z')
                """
            )


def test_workspace_creation_and_duplicate_handling(db_setup) -> None:
    _, repo, ws_mgr = db_setup

    ws1, created1 = ws_mgr.create_or_get_workspace(
        name="SAMPLE_AREA",
        center_latitude=12.823,
        center_longitude=80.044,
        min_latitude=12.815,
        max_latitude=12.831,
        min_longitude=80.036,
        max_longitude=80.052,
        district="Chengalpattu",
        state="Tamil Nadu",
        country="India",
    )
    assert created1 is True
    assert ws1.id is not None

    # Creating the same workspace twice must NOT duplicate it or its 100 cells
    ws2, created2 = ws_mgr.create_or_get_workspace(
        name="sample_area",
        center_latitude=12.823,
        center_longitude=80.044,
        min_latitude=12.815,
        max_latitude=12.831,
        min_longitude=80.036,
        max_longitude=80.052,
    )
    assert created2 is False
    assert ws2.id == ws1.id
    assert len(repo.list_neighbourhoods()) == 1
    assert len(repo.get_grid_cells(ws1.id)) == 100


def test_offline_persistence_and_weather_storage(tmp_path: Path) -> None:
    db_file = tmp_path / "offline_persist.db"
    db1 = DatabaseManager(db_path=db_file)
    db1.initialize()
    repo1 = FloodGuardRepository(db1)
    ws_mgr1 = WorkspaceManager(repo1)

    ws, _ = ws_mgr1.create_or_get_workspace(
        name="OFFLINE_TEST",
        center_latitude=12.823,
        center_longitude=80.044,
        min_latitude=12.815,
        max_latitude=12.831,
        min_longitude=80.036,
        max_longitude=80.052,
    )
    assert ws.id is not None
    cells = repo1.get_grid_cells(ws.id)
    target = cells[0]
    assert target.elevation_m is None  # Never invent elevation

    ws_mgr1.validate_and_save_cell(
        cell=target,
        elevation_input="14.5",
        elevation_source_input="User-provided",
        land_use_input="Residential",
        infiltration_input="12.0",
        drainage_input="25.0",
        notes_input="Near main drain",
    )

    repo1.save_weather_observation(
        WeatherSnapshot(
            id=None,
            neighbourhood_id=ws.id,
            temperature_c=29.2,
            humidity_pct=78.0,
            precipitation_mm=0.4,
            rainfall_mm=0.4,
            weather_code=3,
            weather_description="Overcast",
            data_type="Open-Meteo Model",
            source="Open-Meteo",
            observed_at="2026-11-12T12:00",
            retrieved_at="2026-11-12T12:05:00+00:00",
            raw_json="{}",
        )
    )

    # Reopen completely fresh DB/Repo instance simulating restart while offline
    db2 = DatabaseManager(db_path=db_file)
    repo2 = FloodGuardRepository(db2)
    loaded_ws = repo2.get_neighbourhood_by_name("OFFLINE_TEST")
    assert loaded_ws is not None
    loaded_cells = repo2.get_grid_cells(loaded_ws.id)
    assert len(loaded_cells) == 100
    assert loaded_cells[0].land_use == "Residential"
    assert loaded_cells[0].elevation_m == 14.5
    assert loaded_cells[0].elevation_source == "User-provided"
    assert loaded_cells[0].infiltration_rate == 12.0
    assert loaded_cells[0].drainage_capacity == 25.0
    assert loaded_cells[0].notes == "Near main drain"

    cached_weather = repo2.get_latest_weather_observation(loaded_ws.id)
    assert cached_weather is not None
    assert cached_weather.temperature_c == 29.2
    assert cached_weather.source == "Open-Meteo"

