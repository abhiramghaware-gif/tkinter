"""Tests for simulation grid generation, uniqueness, dimensions, and cell persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.validation import ValidationError
from core.workspace import WorkspaceManager, build_grid_cells
from database.db import DatabaseManager
from database.repository import FloodGuardRepository


@pytest.fixture
def workspace_env(tmp_path: Path) -> tuple[FloodGuardRepository, WorkspaceManager]:
    db_mgr = DatabaseManager(db_path=tmp_path / "grid_test.db")
    db_mgr.initialize()
    repo = FloodGuardRepository(db_mgr)
    return repo, WorkspaceManager(repo)


def test_default_grid_has_100_unique_cells(workspace_env) -> None:
    repo, ws_mgr = workspace_env
    ws, created = ws_mgr.create_or_get_workspace(
        name="GRID_10X10",
        center_latitude=12.823,
        center_longitude=80.044,
        min_latitude=12.815,
        max_latitude=12.831,
        min_longitude=80.036,
        max_longitude=80.052,
    )
    assert created is True
    assert ws.id is not None

    cells = repo.get_grid_cells(ws.id)
    assert len(cells) == 100

    coords = {(c.row_number, c.column_number) for c in cells}
    assert len(coords) == 100
    assert coords == {(r, c) for r in range(10) for c in range(10)}

    # Verify each cell has valid non-zero dimensions derived from latitude
    for cell in cells:
        w_m, h_m = cell.approx_dimensions_m()
        assert w_m > 0
        assert h_m > 0
        assert cell.min_latitude < cell.max_latitude
        assert cell.min_longitude < cell.max_longitude
        assert cell.elevation_m is None


def test_invalid_grid_dimensions_rejected() -> None:
    for bad_rows, bad_cols in [(0, 10), (-3, 10), (1, 10), (10, 51), (3.5, 10), (True, 10), ("abc", 10)]:
        with pytest.raises(ValidationError):
            build_grid_cells(1, 12.815, 12.831, 80.036, 80.052, rows=bad_rows, cols=bad_cols)


def test_save_and_export_cell_properties(workspace_env, tmp_path: Path) -> None:
    repo, ws_mgr = workspace_env
    ws, _ = ws_mgr.create_or_get_workspace(
        name="EXPORT_TEST",
        center_latitude=12.823,
        center_longitude=80.044,
        min_latitude=12.815,
        max_latitude=12.831,
        min_longitude=80.036,
        max_longitude=80.052,
    )
    assert ws.id is not None
    cells = repo.get_grid_cells(ws.id)

    updated = ws_mgr.validate_and_save_cell(
        cell=cells[42],
        elevation_input="",
        elevation_source_input="Unset (NULL)",
        land_use_input="Water Body",
        infiltration_input="2.5",
        drainage_input="40.0",
        notes_input="Retention pond edge",
    )
    assert updated.elevation_m is None
    assert updated.elevation_source is None
    assert updated.land_use == "Water Body"
    assert updated.infiltration_rate == 2.5
    assert updated.drainage_capacity == 40.0

    geojson_path = ws_mgr.export_grid_geojson(ws, repo.get_grid_cells(ws.id), export_dir=tmp_path)
    csv_path = ws_mgr.export_grid_csv(ws, repo.get_grid_cells(ws.id), export_dir=tmp_path)
    assert geojson_path.exists()
    assert csv_path.exists()

