"""Phase 3 automated tests using synthetic test grids (clearly labelled synthetic, no network)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from config import SIMULATION_MODE_ELEVATION, SIMULATION_MODE_ILLUSTRATIVE
from core.drainage_model import calculate_drainage
from core.infiltration_model import calculate_infiltration
from core.models import DrainageFeature, GridCell
from core.rainfall_model import calculate_rainfall
from core.simulation_config import SimulationConfig, create_preset_config
from core.simulation_engine import run_simulation, validate_scenario
from core.validation import ValidationError
from core.water_flow_model import build_neighbour_index, calculate_surface_flow
from core.workspace import WorkspaceManager
from database.db import DatabaseManager
from database.repository import FloodGuardRepository


def _make_synthetic_grid(
    rows: int = 3,
    cols: int = 3,
    elevations: list[float | None] | None = None,
    land_use: str = "Residential",
    area_m2: float = 10_000.0,
) -> list[GridCell]:
    """Build a small deterministic synthetic GridCell list for unit testing."""
    cells: list[GridCell] = []
    cid = 1
    for r in range(rows):
        for c in range(cols):
            idx = r * cols + c
            elev = elevations[idx] if elevations is not None else 15.0
            cells.append(
                GridCell(
                    id=cid,
                    neighbourhood_id=1,
                    row_number=r,
                    column_number=c,
                    min_latitude=12.820 + (rows - 1 - r) * 0.001,
                    max_latitude=12.820 + (rows - r) * 0.001,
                    min_longitude=80.040 + c * 0.001,
                    max_longitude=80.040 + (c + 1) * 0.001,
                    elevation_m=elev,
                    elevation_source="Synthetic Test Elevation" if elev is not None else None,
                    mean_elevation_m=elev,
                    land_use=land_use,
                    land_use_source="user-entered",
                    infiltration_rate=0.0,
                    infiltration_source="missing",
                    drainage_capacity=0.0,
                    drainage_source="missing",
                    approx_width_m=100.0,
                    approx_height_m=100.0,
                    approx_area_m2=area_m2,
                )
            )
            cid += 1
    return cells


def test_zero_rainfall_produces_no_water() -> None:
    cells = _make_synthetic_grid(rows=2, cols=2, elevations=[12.0, 12.0, 12.0, 12.0])
    cfg = SimulationConfig(
        scenario_name="Synthetic Zero Rain",
        rainfall_intensity_mm_hr=0.0,
        rainfall_duration_min=30.0,
        time_step_min=10.0,
        initial_water_depth_m=0.0,
        simulation_mode=SIMULATION_MODE_ELEVATION,
    )
    out = run_simulation(cells, cfg)
    assert out.summary.total_rainfall_volume_m3 == 0.0
    assert out.summary.max_water_depth_m == 0.0
    assert out.summary.final_surface_volume_m3 == 0.0
    assert out.summary.max_affected_cells == 0
    assert out.summary.mass_balance_passed is True


def test_rainfall_volume_si_calculation() -> None:
    # 60 mm/hr for 30 min (0.5 hr) -> 0.03 m depth; 10,000 m2 cell -> 300 m3
    areas = np.array([10_000.0, 20_000.0], dtype=np.float64)
    depth_m, vols_m3 = calculate_rainfall(areas, intensity_mm_hr=60.0, time_step_seconds=1800.0)
    assert abs(depth_m - 0.03) < 1e-12
    assert abs(vols_m3[0] - 300.0) < 1e-9
    assert abs(vols_m3[1] - 600.0) < 1e-9


def test_infiltration_cannot_exceed_available_water_or_capacity() -> None:
    areas = np.array([1000.0, 1000.0], dtype=np.float64)
    # Rate = 36 mm/hr over 1 hr = 0.036 m potential depth -> 36 m3 potential volume
    rates = np.array([36.0, 36.0], dtype=np.float64)
    # Cell 0 has only 10 m3 available; Cell 1 has 100 m3 available
    avail = np.array([10.0, 100.0], dtype=np.float64)

    loss, rem = calculate_infiltration(avail, areas, rates, time_step_seconds=3600.0)
    assert abs(loss[0] - 10.0) < 1e-9
    assert abs(rem[0] - 0.0) < 1e-9
    assert abs(loss[1] - 36.0) < 1e-9
    assert abs(rem[1] - 64.0) < 1e-9
    assert np.all(rem >= 0.0)


def test_drainage_respects_capacity_status_unknown_and_disabled() -> None:
    cells = _make_synthetic_grid(rows=1, cols=3, elevations=[10.0, 10.0, 10.0], area_m2=1000.0)
    # Cell 1: Operational pump 10 L/s (= 0.01 m3/s -> 0.6 m3 over 60s)
    # Cell 2: Drain with unknown capacity (None -> must not invent capacity -> 0 m3/s)
    # Cell 3: Disabled What-If drain
    drains = [
        DrainageFeature(
            id=101, neighbourhood_id=1, grid_cell_id=1, name="Pump 1",
            feature_type="Pumping station", latitude=cells[0].center_latitude,
            longitude=cells[0].center_longitude, capacity=10.0, capacity_unit="L/s",
            status="Operational", source="user-entered",
        ),
        DrainageFeature(
            id=102, neighbourhood_id=1, grid_cell_id=2, name="Unmeasured Drain",
            feature_type="Stormwater drain", latitude=cells[1].center_latitude,
            longitude=cells[1].center_longitude, capacity=None, capacity_unit="L/s",
            status="Operational", source="user-entered",
        ),
        DrainageFeature(
            id=103, neighbourhood_id=1, grid_cell_id=3, name="Disabled Drain",
            feature_type="Culvert", latitude=cells[2].center_latitude,
            longitude=cells[2].center_longitude, capacity=50.0, capacity_unit="L/s",
            status="Operational", source="user-entered",
        ),
    ]
    cfg = SimulationConfig(
        scenario_name="Synthetic Drainage Bounds",
        rainfall_intensity_mm_hr=0.0,
        rainfall_duration_min=1.0,
        time_step_min=1.0,
        initial_water_depth_m=0.005,  # 5 m3 per 1000 m2 cell
        simulation_mode=SIMULATION_MODE_ELEVATION,
        category_infiltration_rates_mm_hr={k: 0.0 for k in ("Concrete", "Road", "Residential", "Commercial", "Vegetation", "Open soil", "Water body")},
        disabled_drainage_ids={103},
    )
    out = run_simulation(cells, cfg, drainage_features=drains)
    c1, c2, c3 = out.final_cells
    # Cell 1: 10 L/s * 60 s = 0.6 m3 max removed (< 5.0 m3 available)
    assert abs(c1.total_drainage_m3 - 0.6) < 1e-9
    # Cell 2: unknown capacity -> 0 removed
    assert c2.total_drainage_m3 == 0.0
    # Cell 3: disabled -> 0 removed
    assert c3.total_drainage_m3 == 0.0
    assert out.summary.mass_balance_passed is True

    # Also test capacity exceeding available water cannot create negative volume
    loss, rem = calculate_drainage(
        np.array([0.2, 5.0]), np.array([1.0, 1.0]), time_step_seconds=10.0
    )
    assert abs(loss[0] - 0.2) < 1e-9 and rem[0] == 0.0
    assert abs(loss[1] - 5.0) < 1e-9 and rem[1] == 0.0


def test_water_flows_downhill_and_conserves_mass_at_boundaries() -> None:
    # 3x3 synthetic terrain sloping down toward East and South; high point at R1C1 (20 m)
    elevs = [
        20.0, 15.0, 10.0,
        16.0, 12.0, 8.0,
        12.0, 8.0, 4.0,
    ]
    cells = _make_synthetic_grid(rows=3, cols=3, elevations=elevs, area_m2=1000.0)
    nbrs = build_neighbour_index(cells)
    areas = np.array([c.approx_area_sq_m() for c in cells], dtype=np.float64)
    elev_arr = np.array(elevs, dtype=np.float64)

    # Put 500 m3 (0.5 m depth) only in top-left corner boundary cell (index 0)
    init_vols = np.zeros(9, dtype=np.float64)
    init_vols[0] = 500.0

    # After 30s, water moves into immediate downhill neighbours (1 and 3)
    vols_30s, transferred_30s, _ = calculate_surface_flow(
        init_vols, areas, elev_arr, nbrs, time_step_seconds=30.0, mobility=0.35
    )
    assert transferred_30s > 0.0
    assert abs(float(np.sum(vols_30s)) - 500.0) < 1e-10
    assert vols_30s[0] < 500.0
    assert vols_30s[1] > 0.0
    assert vols_30s[3] > 0.0

    # After 300s on steep slope, water cascades all the way to lowest basin cell (8) with zero loss
    vols_after, transferred, _ = calculate_surface_flow(
        init_vols, areas, elev_arr, nbrs, time_step_seconds=300.0, mobility=0.35
    )

    assert transferred > 0.0
    assert np.all(vols_after >= 0.0)
    # Exact internal mass conservation (nothing leaks out of grid boundaries)
    assert abs(float(np.sum(vols_after)) - 500.0) < 1e-10
    assert vols_after[0] < 500.0
    assert vols_after[8] > 0.0


def test_validation_rejects_bad_inputs_and_missing_elevation() -> None:
    cells_missing = _make_synthetic_grid(rows=2, cols=2, elevations=[10.0, None, 10.0, 10.0])

    # Missing elevation must raise ValidationError in elevation_based mode
    with pytest.raises(ValidationError, match="NULL/missing elevation"):
        validate_scenario(
            cells_missing,
            SimulationConfig(simulation_mode=SIMULATION_MODE_ELEVATION),
        )

    # Illustrative mode succeeds with explicit warning
    resolved = validate_scenario(
        cells_missing,
        SimulationConfig(simulation_mode=SIMULATION_MODE_ILLUSTRATIVE),
    )
    assert resolved["used_illustrative_terrain"] is True
    assert any("ILLUSTRATIVE TERRAIN MODE" in w for w in resolved["warnings"])

    valid_cells = _make_synthetic_grid(rows=2, cols=2, elevations=[10.0, 10.0, 10.0, 10.0])
    with pytest.raises(ValidationError):
        validate_scenario(valid_cells, SimulationConfig(rainfall_intensity_mm_hr=-5.0, simulation_mode=SIMULATION_MODE_ELEVATION))
    with pytest.raises(ValidationError):
        validate_scenario(valid_cells, SimulationConfig(time_step_min=0.0, simulation_mode=SIMULATION_MODE_ELEVATION))
    with pytest.raises(ValidationError):
        validate_scenario([], SimulationConfig(simulation_mode=SIMULATION_MODE_ILLUSTRATIVE))


def test_mass_conservation_reproducibility_and_whatif_non_destructive() -> None:
    elevs = [18.0, 16.0, 15.0, 12.0]
    cells = _make_synthetic_grid(rows=2, cols=2, elevations=elevs, area_m2=10_000.0)

    for pattern in ("constant", "increasing", "decreasing", "custom"):
        cfg = SimulationConfig(
            scenario_name=f"Synthetic {pattern}",
            rainfall_intensity_mm_hr=60.0,
            rainfall_duration_min=30.0,
            time_step_min=5.0,
            distribution_pattern=pattern,
            custom_intensities_mm_hr=[10.0, 30.0, 90.0, 60.0, 20.0, 10.0],
            initial_water_depth_m=0.02,
            simulation_mode=SIMULATION_MODE_ELEVATION,
        )
        out1 = run_simulation(cells, cfg)
        out2 = run_simulation(cells, cfg)

        assert out1.summary.mass_balance_passed is True
        assert out1.summary.mass_balance_error_m3 < 1e-8
        assert out1.summary.final_surface_volume_m3 >= 0.0
        # Identical inputs -> exact reproducible results
        assert out1.summary.max_water_depth_m == pytest.approx(out2.summary.max_water_depth_m)
        assert out1.summary.final_surface_volume_m3 == pytest.approx(out2.summary.final_surface_volume_m3)

    # What-If scenarios: doubled rainfall, cell infiltration override, extra drain (cells untouched!)
    base_cfg = create_preset_config("Moderate rainfall (30 mm/hr)", duration_min=30.0, time_step_min=5.0, simulation_mode=SIMULATION_MODE_ELEVATION)
    base_out = run_simulation(cells, base_cfg)

    whatif_cfg = base_cfg.clone()
    whatif_cfg.rainfall_scale_factor = 2.0
    whatif_cfg.cell_infiltration_overrides_mm_hr = {1: 40.0}
    whatif_cfg.extra_drainage_features = [
        DrainageFeature(
            id=999, neighbourhood_id=1, grid_cell_id=4, name="What-If Channel",
            feature_type="Drainage channel", latitude=cells[3].center_latitude,
            longitude=cells[3].center_longitude, capacity=200.0, capacity_unit="L/s",
            status="Operational", source="what-if-hypothetical",
        )
    ]
    whatif_out = run_simulation(cells, whatif_cfg)
    assert whatif_out.summary.total_rainfall_volume_m3 == pytest.approx(
        2.0 * base_out.summary.total_rainfall_volume_m3
    )
    assert whatif_out.summary.total_drainage_volume_m3 > 0.0
    assert whatif_out.summary.mass_balance_passed is True
    # Original grid cells must remain unmodified
    assert all(c.infiltration_source == "missing" for c in cells)


def test_simulation_sqlite_persistence_and_v2_to_v3_migration(tmp_path: Path) -> None:
    db_file = tmp_path / "sim_v2.db"
    # Create an authentic v2 database with existing POTHERI data and upgrade to v3
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
            center_latitude REAL, center_longitude REAL,
            approx_width_m REAL, approx_height_m REAL, approx_area_m2 REAL,
            elevation_m REAL, elevation_source TEXT,
            min_elevation_m REAL, max_elevation_m REAL, mean_elevation_m REAL,
            land_use TEXT NOT NULL DEFAULT 'Unknown',
            land_use_source TEXT NOT NULL DEFAULT 'missing',
            infiltration_rate REAL NOT NULL DEFAULT 0.0,
            infiltration_source TEXT NOT NULL DEFAULT 'missing',
            drainage_capacity REAL NOT NULL DEFAULT 0.0,
            drainage_source TEXT NOT NULL DEFAULT 'missing',
            notes TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
            FOREIGN KEY (neighbourhood_id) REFERENCES neighbourhoods(id) ON DELETE CASCADE,
            UNIQUE (neighbourhood_id, row_number, column_number)
        );
        INSERT INTO schema_migrations VALUES (1, '2026-11-12T00:00:00Z');
        INSERT INTO schema_migrations VALUES (2, '2026-11-12T00:00:00Z');
        INSERT INTO neighbourhoods VALUES (1, 'POTHERI', 'Chengalpattu', 'Tamil Nadu', 'India', 12.823, 80.044, 12.820, 12.825, 80.040, 80.045, 2, 2, '2026-11-12T00:00:00Z', '2026-11-12T00:00:00Z');
        INSERT INTO grid_cells VALUES (1, 1, 0, 0, 12.8225, 12.825, 80.040, 80.0425, 12.82375, 80.04125, 270.0, 278.0, 75000.0, 16.0, 'User-provided', 16.0, 16.0, 16.0, 'Residential', 'user-entered', 8.0, 'user-entered', 0.0, 'missing', 'Preserved', '2026-11-12T00:00:00Z');
        INSERT INTO grid_cells VALUES (2, 1, 0, 1, 12.8225, 12.825, 80.0425, 80.045, 12.82375, 80.04375, 270.0, 278.0, 75000.0, 15.0, 'User-provided', 15.0, 15.0, 15.0, 'Road', 'user-entered', 2.0, 'user-entered', 0.0, 'missing', 'Preserved', '2026-11-12T00:00:00Z');
        INSERT INTO grid_cells VALUES (3, 1, 1, 0, 12.820, 12.8225, 80.040, 80.0425, 12.82125, 80.04125, 270.0, 278.0, 75000.0, 14.0, 'User-provided', 14.0, 14.0, 14.0, 'Open Ground', 'user-entered', 15.0, 'user-entered', 0.0, 'missing', 'Preserved', '2026-11-12T00:00:00Z');
        INSERT INTO grid_cells VALUES (4, 1, 1, 1, 12.820, 12.8225, 80.0425, 80.045, 12.82125, 80.04375, 270.0, 278.0, 75000.0, 13.0, 'User-provided', 13.0, 13.0, 13.0, 'Green Area', 'user-entered', 22.0, 'user-entered', 0.0, 'missing', 'Preserved', '2026-11-12T00:00:00Z');
        PRAGMA user_version = 2;
        """
    )
    conn.commit()
    conn.close()

    db_mgr = DatabaseManager(db_path=db_file)
    db_mgr.initialize()
    ok, msg = db_mgr.verify_integrity()
    assert ok and "SQLite OK (v" in msg and "FK=ON" in msg

    repo = FloodGuardRepository(db_mgr)
    potheri = repo.get_neighbourhood_by_name("POTHERI")
    assert potheri is not None and potheri.id is not None
    cells = repo.get_grid_cells(potheri.id)
    assert len(cells) == 4 and cells[0].notes == "Preserved"

    cfg = create_preset_config(
        "Heavy rainfall (60 mm/hr)",
        duration_min=20.0,
        time_step_min=5.0,
        simulation_mode=SIMULATION_MODE_ELEVATION,
    )
    out = run_simulation(cells, cfg, neighbourhood_id=potheri.id)
    sim_id = repo.save_simulation_output(out)
    assert sim_id > 0

    runs = repo.list_simulation_runs(potheri.id)
    assert len(runs) == 1
    assert runs[0].scenario_name == "[Hypothetical] Heavy rainfall (60 mm/hr)"

    loaded = repo.load_simulation_output(sim_id)
    assert loaded is not None
    assert loaded.summary.mass_balance_passed is True
    assert loaded.summary.total_rainfall_volume_m3 == pytest.approx(out.summary.total_rainfall_volume_m3)
    assert loaded.summary.max_water_depth_m == pytest.approx(out.summary.max_water_depth_m)
    assert len(loaded.steps) == 4
    assert len(loaded.final_cells) == 4
