"""Automated Phase 4 tests for Flood Visualization, Risk Mapping, Animation, Comparison & Export."""

from __future__ import annotations

import csv
import json
import time
import tkinter as tk
from pathlib import Path

import pytest
from matplotlib.figure import Figure

from core.flood_statistics import (
    compare_simulations,
    compute_timestep_statistics,
    extract_step_cell_data,
)
from core.models import GridCell, GridFeatureLink, Neighbourhood, OSMFeature
from core.risk_classifier import (
    PROTOTYPE_RISK_DISCLAIMER,
    HeatmapColorScale,
    RiskThresholds,
    calculate_neighbourhood_risk,
    calculate_risk_statistics,
    classify_flood_depth,
    classify_grid_cell,
    color_for_flood_depth,
)
from core.simulation_config import SimulationConfig
from core.simulation_engine import SimulationOutput, SimulationRunRecord, run_simulation
from core.validation import ValidationError
from core.workspace import WorkspaceManager
from database.db import DatabaseManager
from database.repository import FloodGuardRepository
from services.simulation_export import (
    export_charts_png,
    export_flood_depth_grid_csv,
    export_risk_classification_csv,
    export_simulation_geojson,
    export_simulation_summary_pdf,
)
from visualization.flood_animation import FloodAnimationController
from visualization.map_layers import compute_infrastructure_exposure


def _make_neighbourhood_and_grid(rows: int = 3, cols: int = 3, with_elev: bool = False):
    nb = Neighbourhood(
        id=1,
        name="TEST_AREA",
        district="Chengalpattu",
        state="Tamil Nadu",
        country="India",
        center_latitude=12.823,
        center_longitude=80.044,
        min_latitude=12.818,
        max_latitude=12.828,
        min_longitude=80.039,
        max_longitude=80.049,
        grid_rows=rows,
        grid_cols=cols,
    )
    lat_step = (nb.max_latitude - nb.min_latitude) / rows
    lon_step = (nb.max_longitude - nb.min_longitude) / cols
    cells: list[GridCell] = []
    cid = 1
    for r in range(rows):
        max_lat = nb.max_latitude - r * lat_step
        min_lat = max_lat - lat_step
        for c in range(cols):
            min_lon = nb.min_longitude + c * lon_step
            max_lon = min_lon + lon_step
            elev = (12.0 + r * 0.5 - c * 0.2) if with_elev else None
            cells.append(
                GridCell(
                    id=cid,
                    neighbourhood_id=1,
                    row_number=r,
                    column_number=c,
                    min_latitude=min_lat,
                    max_latitude=max_lat,
                    min_longitude=min_lon,
                    max_longitude=max_lon,
                    elevation_m=elev,
                    mean_elevation_m=elev,
                    elevation_source="synthetic-test" if with_elev else "missing",
                    land_use="Residential" if (r + c) % 2 == 0 else "Road",
                    land_use_source="user-entered",
                    infiltration_rate=8.0 if (r + c) % 2 == 0 else 2.0,
                    infiltration_source="user-entered",
                    drainage_capacity=4.0,
                    drainage_source="user-entered",
                )
            )
            cid += 1
    return nb, cells


def test_depth_to_colour_and_configurable_scale() -> None:
    th = RiskThresholds()
    cs_grey = HeatmapColorScale()
    cs_green = HeatmapColorScale(no_water="#22C55E")

    c0, lbl0 = color_for_flood_depth(0.0, th, cs_grey)
    assert c0 == cs_grey.no_water and "No water" in lbl0

    c0_g, _ = color_for_flood_depth(0.0, th, cs_green)
    assert c0_g == "#22C55E"

    assert color_for_flood_depth(0.05, th, cs_grey)[0] == cs_grey.low
    assert color_for_flood_depth(0.20, th, cs_grey)[0] == cs_grey.moderate
    assert color_for_flood_depth(0.45, th, cs_grey)[0] == cs_grey.high
    assert color_for_flood_depth(0.75, th, cs_grey)[0] == cs_grey.very_high
    assert color_for_flood_depth(1.10, th, cs_grey)[0] == cs_grey.critical

    custom_th = RiskThresholds(low_max_cm=5.0, moderate_max_cm=15.0, high_max_cm=30.0, critical_min_cm=60.0)
    assert classify_flood_depth(0.08, custom_th) == "Moderate"

    bad_th = RiskThresholds(low_max_cm=40.0, moderate_max_cm=20.0)
    with pytest.raises(ValidationError):
        bad_th.validate()


def test_risk_classification_never_claims_safety() -> None:
    _, cells = _make_neighbourhood_and_grid(2, 2, with_elev=True)
    assert classify_flood_depth(0.0) == "No surface flooding"
    assert "safe" not in classify_flood_depth(0.0).lower()
    assert "never" in PROTOTYPE_RISK_DISCLAIMER.lower()

    depths = {1: 0.0, 2: 0.08, 3: 0.25, 4: 0.72}
    cell_cls = classify_grid_cell(cells[0], 0.0)
    assert cell_cls.is_model_assumption is True
    assert cell_cls.risk_category == "No surface flooding"

    nb_risk = calculate_neighbourhood_risk(cells, depths)
    assert nb_risk[1].risk_category == "No surface flooding"
    assert nb_risk[2].risk_category == "Low"
    assert nb_risk[3].risk_category == "Moderate"
    assert nb_risk[4].risk_category == "Very High"

    rstats = calculate_risk_statistics(cells, depths)
    assert rstats.total_cells == 4
    assert rstats.category_counts["No surface flooding"] == 1
    assert rstats.category_counts["Low"] == 1
    assert rstats.category_counts["Moderate"] == 1
    assert rstats.very_high_risk_cells == 1


def test_timestep_statistics_from_real_phase3_output_and_empty_case() -> None:
    _, cells = _make_neighbourhood_and_grid(3, 3, with_elev=True)
    empty_stats = compute_timestep_statistics(None, 0, cells)
    assert empty_stats.is_empty is True
    assert empty_stats.affected_cells == 0
    assert empty_stats.max_depth_cm == 0.0

    cfg = SimulationConfig(
        scenario_name="Storm Test",
        rainfall_intensity_mm_hr=60.0,
        rainfall_duration_min=30.0,
        time_step_min=10.0,
        simulation_mode="elevation_based",
    )
    out = run_simulation(cells, cfg, neighbourhood_id=1)
    s1 = compute_timestep_statistics(out, 1, cells)
    s3 = compute_timestep_statistics(out, 3, cells)
    assert s1.is_empty is False
    assert s3.cumulative_rainfall_m3 > s1.cumulative_rainfall_m3
    assert s3.max_depth_cm > 0.0
    depths, vols, tmin = extract_step_cell_data(out, 2)
    assert len(depths) == 9
    assert len(vols) == 9
    assert tmin == pytest.approx(20.0)


def test_infrastructure_exposure_and_shelters() -> None:
    _, cells = _make_neighbourhood_and_grid(2, 2, with_elev=False)
    c1 = cells[0]
    lat_c = c1.center_latitude
    lon_c = c1.center_longitude

    road = OSMFeature(
        id=101,
        neighbourhood_id=1,
        osm_id=9001,
        element_type="way",
        category="road",
        subcategory="residential",
        name="Potheri Main St",
        geometry={"type": "LineString", "coordinates": [[lon_c - 0.0005, lat_c], [lon_c + 0.0005, lat_c]]},
    )
    bldg = OSMFeature(
        id=102,
        neighbourhood_id=1,
        osm_id=9002,
        element_type="way",
        category="building",
        subcategory="residential",
        name="Block A",
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [lon_c - 0.0002, lat_c - 0.0002],
                [lon_c + 0.0002, lat_c - 0.0002],
                [lon_c + 0.0002, lat_c + 0.0002],
                [lon_c - 0.0002, lat_c + 0.0002],
                [lon_c - 0.0002, lat_c - 0.0002],
            ]],
        },
    )
    shelter = OSMFeature(
        id=103,
        neighbourhood_id=1,
        osm_id=9003,
        element_type="node",
        category="other",
        subcategory="amenity",
        name="Community Shelter",
        geometry={"type": "Point", "coordinates": [lon_c, lat_c]},
        tags={"amenity": "emergency_shelter"},
    )
    links = [
        GridFeatureLink(id=None, grid_cell_id=1, osm_feature_id=101, drainage_feature_id=None, relationship_type="intersects"),
        GridFeatureLink(id=None, grid_cell_id=1, osm_feature_id=102, drainage_feature_id=None, relationship_type="intersects"),
    ]

    # At 8 cm: building (>= 5 cm) is exposed, road (>= 15 cm) is not yet exposed
    exp_low = compute_infrastructure_exposure(
        cells, [road, bldg, shelter], links, {1: 0.08, 2: 0.0, 3: 0.0, 4: 0.0}
    )
    assert 102 in exp_low.exposed_building_ids
    assert 101 not in exp_low.exposed_road_ids
    assert len(exp_low.shelter_features) == 1
    assert "estimate" in exp_low.disclaimer.lower()

    # At 20 cm: both road and building are exposed
    exp_high = compute_infrastructure_exposure(
        cells, [road, bldg, shelter], links, {1: 0.20, 2: 0.0, 3: 0.0, 4: 0.0}
    )
    assert 101 in exp_high.exposed_road_ids
    assert 102 in exp_high.exposed_building_ids


def test_animation_controller_after_lifecycle() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        steps_seen: list[int] = []
        states_seen: list[str] = []
        ctrl = FloodAnimationController(
            root,
            on_step_changed=lambda i: steps_seen.append(i),
            on_state_changed=lambda s: states_seen.append(s),
        )
        ctrl.configure_steps(total_steps=4, start_index=0)
        ctrl.set_speed(8.0)  # minimum 90 ms interval
        assert ctrl.current_index == 0

        ctrl.next_step()
        assert ctrl.current_index == 1
        ctrl.prev_step()
        assert ctrl.current_index == 0
        ctrl.seek(2)
        assert ctrl.current_index == 2

        ctrl.start()
        assert ctrl.is_playing is True
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and ctrl.is_playing:
            root.update()
            time.sleep(0.02)
        assert "Completed" in states_seen
        assert ctrl.current_index == 3

        # Restart from end wraps cleanly to 0, then pause & resume & stop
        ctrl.start()
        assert ctrl.current_index == 0
        ctrl.pause()
        assert ctrl.is_paused is True and ctrl.is_playing is False
        ctrl.resume()
        assert ctrl.is_playing is True
        ctrl.stop()
        assert ctrl.current_index == 0
        assert ctrl.is_playing is False
    finally:
        root.destroy()


def test_compare_simulations_compatible_and_incompatible() -> None:
    _, cells_3x3 = _make_neighbourhood_and_grid(3, 3, with_elev=True)
    _, cells_2x2 = _make_neighbourhood_and_grid(2, 2, with_elev=True)

    cfg_mod = SimulationConfig(
        scenario_name="Moderate",
        rainfall_intensity_mm_hr=30.0,
        rainfall_duration_min=30.0,
        time_step_min=10.0,
        simulation_mode="elevation_based",
    )
    cfg_heavy = SimulationConfig(
        scenario_name="Heavy",
        rainfall_intensity_mm_hr=60.0,
        rainfall_duration_min=30.0,
        time_step_min=10.0,
        simulation_mode="elevation_based",
    )
    out_a = run_simulation(cells_3x3, cfg_mod, neighbourhood_id=1)
    out_b = run_simulation(cells_3x3, cfg_heavy, neighbourhood_id=1)

    cmp_ok = compare_simulations(out_a, out_b, cells_3x3, cells_3x3)
    assert cmp_ok.are_compatible is True
    assert cmp_ok.compatibility_warnings == []
    assert cmp_ok.max_depth_delta_cm > 0.0

    # Incompatible check (different neighbourhood, grid size, duration, mode)
    cfg_other = SimulationConfig(
        scenario_name="Other",
        rainfall_intensity_mm_hr=60.0,
        rainfall_duration_min=45.0,
        time_step_min=5.0,
        simulation_mode="illustrative_assumed",
    )
    out_other = run_simulation(cells_2x2, cfg_other, neighbourhood_id=2)
    cmp_bad = compare_simulations(out_a, out_other, cells_3x3, cells_2x2)
    assert cmp_bad.are_compatible is False
    assert len(cmp_bad.compatibility_warnings) >= 4


def test_phase4_exports_preserve_missing_elevation_and_valid_outputs(tmp_path: Path) -> None:
    nb, cells = _make_neighbourhood_and_grid(2, 2, with_elev=False)
    cfg = SimulationConfig(
        scenario_name="Illustrative Test",
        rainfall_intensity_mm_hr=60.0,
        rainfall_duration_min=20.0,
        time_step_min=10.0,
        simulation_mode="illustrative_assumed",
    )
    out = run_simulation(cells, cfg, neighbourhood_id=1)
    out.run.id = 77

    # 1. Depth CSV — missing DEM elevation remains blank & marked Unset (NULL)
    depth_csv = export_flood_depth_grid_csv(nb, out, cells, 2, tmp_path / "depths.csv")
    raw_lines = depth_csv.read_text(encoding="utf-8").splitlines()
    assert any("Potheri" in ln or nb.name in ln for ln in raw_lines[:10])
    assert any("Illustrative Assumed Terrain" in ln for ln in raw_lines[:15])
    data_lines = [ln for ln in raw_lines if not ln.startswith("#")]
    rows = list(csv.DictReader(data_lines))
    assert len(rows) == 4
    assert rows[0]["ground_elevation_m"] == ""
    assert rows[0]["elevation_source"] == "Unset (NULL)"
    assert float(rows[0]["water_depth_cm"]) >= 0.0

    # 2. Risk CSV
    risk_csv = export_risk_classification_csv(nb, out, cells, 2, tmp_path / "risk.csv")
    r_text = risk_csv.read_text(encoding="utf-8")
    assert "not official" in r_text.lower()

    # 3. GeoJSON export with valid polygon bounds & null ground_elevation_m
    gj_path = export_simulation_geojson(nb, out, cells, 2, tmp_path / "grid.geojson")
    gj = json.loads(gj_path.read_text(encoding="utf-8"))
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 4
    assert gj["features"][0]["geometry"]["type"] == "Polygon"
    assert gj["features"][0]["properties"]["ground_elevation_m"] is None

    # Invalid coordinates must raise rather than invent geometry
    bad_cell = GridCell(
        id=99,
        neighbourhood_id=1,
        row_number=0,
        column_number=0,
        min_latitude=95.0,
        max_latitude=96.0,
        min_longitude=80.0,
        max_longitude=80.1,
    )
    with pytest.raises(ValidationError):
        export_simulation_geojson(nb, out, [bad_cell], 2, tmp_path / "bad.geojson")

    # 4. PNG Chart export
    fig = Figure(figsize=(4, 3))
    ax = fig.add_subplot(111)
    ax.plot([s.sim_time_minutes for s in out.steps], [s.max_water_depth_m for s in out.steps])
    png_path = export_charts_png(fig, tmp_path / "charts.png")
    assert png_path.exists() and png_path.stat().st_size > 1000

    # 5. PDF Summary report export
    pdf_path = export_simulation_summary_pdf(nb, out, cells, 2, tmp_path / "summary.pdf")
    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")


def test_sqlite_save_and_reload_into_phase4_stats(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "test_p4.db")
    db.initialize()
    repo = FloodGuardRepository(db)
    wm = WorkspaceManager(repo)

    ws, _ = wm.create_or_get_workspace(
        name="POTHERI_P4_TEST",
        center_latitude=12.823,
        center_longitude=80.044,
        min_latitude=12.818,
        max_latitude=12.828,
        min_longitude=80.039,
        max_longitude=80.049,
        district="Chengalpattu",
        state="Tamil Nadu",
        country="India",
        grid_rows=2,
        grid_cols=2,
    )
    assert ws.id is not None
    saved_cells = repo.get_grid_cells(ws.id)

    cfg = SimulationConfig(
        scenario_name="Persisted Storm",
        rainfall_intensity_mm_hr=60.0,
        rainfall_duration_min=20.0,
        time_step_min=10.0,
        simulation_mode="illustrative_assumed",
    )
    out = run_simulation(saved_cells, cfg, neighbourhood_id=ws.id)
    sim_id = repo.save_simulation_output(out)

    loaded = repo.load_simulation_output(sim_id)
    assert loaded is not None
    stats = compute_timestep_statistics(loaded, 2, saved_cells)
    assert stats.is_empty is False
    assert stats.affected_cells >= 1
    assert stats.affected_cells == loaded.steps[-1].affected_cell_count
    assert stats.max_depth_cm > 0.0
