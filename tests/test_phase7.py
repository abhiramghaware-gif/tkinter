"""Phase 7 automated unit, workflow integration, backup/restore, report & GUI tests."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

import database.db as db_mod
from core.models import DrainageFeature, GridCell, Neighbourhood, OSMFeature
from core.risk_classifier import RiskThresholds
from core.scenario_comparator import compare_multiple_scenarios, compute_meaningful_pct_change
from core.scenario_manager import ScenarioManager, clone_config_from_run
from core.simulation_config import SimulationConfig
from core.simulation_engine import run_simulation
from core.validation import ValidationError
from core.workspace import WorkspaceManager
from database.backup_manager import DatabaseBackupManager
from database.db import DatabaseManager
from database.repository import FloodGuardRepository
from emergency import (
    InventoryManager,
    OperationManager,
    RescueTeamManager,
    ResourceAllocator,
    ShelterManager,
    VehicleManager,
)
from routing.flood_exposure import analyze_road_network_exposure
from routing.road_network import build_road_network_from_osm
from routing.route_planner import calculate_evacuation_routes
from services.report_generator import REPORT_TYPES, ReportGenerator


def _seed_workspace(db_path: Path) -> tuple[DatabaseManager, FloodGuardRepository, int, list[GridCell], list[DrainageFeature]]:
    db = DatabaseManager(db_path)
    db.initialize()
    repo = FloodGuardRepository(db)

    ws, _created = WorkspaceManager(repo).create_or_get_workspace(
        name="POTHERI_P7_TEST",
        center_latitude=12.823,
        center_longitude=80.044,
        min_latitude=12.818,
        max_latitude=12.828,
        min_longitude=80.039,
        max_longitude=80.049,
        district="Chengalpattu",
        state="Tamil Nadu",
        country="India",
        grid_rows=4,
        grid_cols=4,
    )
    assert ws.id is not None
    nid = ws.id
    cells = repo.get_grid_cells(nid)
    for idx, cell in enumerate(cells):
        cell.elevation_m = 18.0 - (cell.row_number * 0.8 + cell.column_number * 0.4)
        cell.mean_elevation_m = cell.elevation_m
        cell.elevation_source = "User-provided"
        cell.land_use = "Residential" if idx % 3 else "Road"
        cell.land_use_source = "user-entered"
        cell.infiltration_rate = 8.0 if cell.land_use == "Residential" else 2.0
        cell.infiltration_source = "user-entered"
        repo.update_grid_cell(cell)
    cells = repo.get_grid_cells(nid)

    d1 = repo.create_drainage_feature(
        DrainageFeature(
            id=None, neighbourhood_id=nid, grid_cell_id=cells[5].id,
            name="Potheri Main Drain A", feature_type="Stormwater drain",
            latitude=cells[5].center_latitude, longitude=cells[5].center_longitude,
            capacity=180.0, capacity_unit="L/s", status="Operational", source="user-entered",
        )
    )
    d2 = repo.create_drainage_feature(
        DrainageFeature(
            id=None, neighbourhood_id=nid, grid_cell_id=cells[10].id,
            name="Potheri Link Culvert B", feature_type="Culvert",
            latitude=cells[10].center_latitude, longitude=cells[10].center_longitude,
            capacity=120.0, capacity_unit="L/s", status="Operational", source="user-entered",
        )
    )
    # Minimal connected road loop across the 4x4 grid
    road_feats = [
        OSMFeature(
            id=None, neighbourhood_id=nid, osm_id=9001, element_type="way",
            category="road", subcategory="primary", name="GST Trunk Road",
            road_category="Primary", length_m=800.0,
            geometry={
                "type": "LineString",
                "coordinates": [
                    [80.0405, 12.8195],
                    [80.0440, 12.8230],
                    [80.0475, 12.8265],
                ],
            },
        ),
        OSMFeature(
            id=None, neighbourhood_id=nid, osm_id=9002, element_type="way",
            category="road", subcategory="residential", name="West Campus Lane",
            road_category="Residential", length_m=1100.0,
            geometry={
                "type": "LineString",
                "coordinates": [
                    [80.0405, 12.8195],
                    [80.0405, 12.8245],
                    [80.0475, 12.8265],
                ],
            },
        ),
    ]
    repo.replace_osm_features(nid, road_feats)
    return db, repo, nid, cells, [d1, d2]


# ---------------------------------------------------------------------------
# Unit Tests: ScenarioManager (6 Experiments) & ScenarioComparator
# ---------------------------------------------------------------------------

def test_what_if_scenario_manager_six_experiments_and_non_destructive(tmp_path: Path) -> None:
    db, repo, nid, cells, drains = _seed_workspace(tmp_path / "p7_exp.db")
    nb = repo.get_neighbourhood_by_id(nid)
    assert nb is not None

    base_cfg = SimulationConfig(
        scenario_name="Baseline 30mm",
        rainfall_intensity_mm_hr=30.0,
        rainfall_duration_min=30.0,
        time_step_min=10.0,
    )
    base_out = run_simulation(cells, base_cfg, drains, neighbourhood_id=nb.id)
    base_id = repo.save_simulation_output(base_out)

    mgr = ScenarioManager()
    # Cloning must never alter saved baseline or grid_cells in SQLite
    snapshot_before = [(c.id, c.infiltration_rate, c.drainage_capacity) for c in repo.get_grid_cells(nid)]

    expected_counts = {
        "exp1_heavy_rainfall": 3,
        "exp2_drainage_failure": 3,
        "exp3_improved_drainage": 3,
        "exp4_land_use": 3,
        "exp5_road_closure": 2,
        "exp6_combined_extreme": 2,
    }
    for exp_key, count in expected_counts.items():
        title, variants = mgr.build_experiment_variants(
            exp_key,
            base_cfg,
            cells,
            drains,
            baseline_run_id=base_id,
        )
        assert title
        assert len(variants) == count
        res = mgr.run_experiment_batch(nb, cells, drains, exp_key, title, variants)
        assert len(res.outputs) == count
        for out in res.outputs:
            assert out.summary.mass_balance_passed

    # Confirm Exp 3 marks extra channel as hypothetical & Exp 6 labels stress test
    _, exp3_vars = mgr.build_experiment_variants("exp3_improved_drainage", base_cfg, cells, drains)
    assert exp3_vars[-1].is_hypothetical
    assert exp3_vars[-1].config.extra_drainage_features[0].source == "what-if-hypothetical"

    _, exp6_vars = mgr.build_experiment_variants("exp6_combined_extreme", base_cfg, cells, drains)
    assert exp6_vars[-1].is_stress_test

    snapshot_after = [(c.id, c.infiltration_rate, c.drainage_capacity) for c in repo.get_grid_cells(nid)]
    assert snapshot_before == snapshot_after

    with pytest.raises(ValidationError):
        mgr.create_modified_variant(base_cfg, name="Bad", rainfall_intensity_mm_hr=-5.0)


def test_scenario_comparator_metrics_pct_edge_cases_and_incompatibility(tmp_path: Path) -> None:
    assert compute_meaningful_pct_change(0.0, 5.0) == (None, "N/A (baseline=0)")
    assert compute_meaningful_pct_change(0.0, 0.0) == (0.0, "0.0%")
    pct, txt = compute_meaningful_pct_change(10.0, 15.0)
    assert pct == pytest.approx(50.0)
    assert txt == "+50.0%"

    db, repo, nid, cells, drains = _seed_workspace(tmp_path / "p7_cmp.db")
    nb = repo.get_neighbourhood_by_id(nid)
    assert nb is not None
    osm = repo.get_osm_features(nid)
    net = build_road_network_from_osm(nid, osm, cells)
    nids = list(net.nodes_by_id.keys())

    out_a = run_simulation(cells, SimulationConfig("Low 20", rainfall_intensity_mm_hr=20.0, rainfall_duration_min=30.0, time_step_min=10.0), drains, neighbourhood_id=nb.id)
    out_b = run_simulation(cells, SimulationConfig("Extreme 100", rainfall_intensity_mm_hr=100.0, rainfall_duration_min=30.0, time_step_min=10.0), drains, neighbourhood_id=nb.id)
    out_c = run_simulation(cells, SimulationConfig("Incompatible 60m", rainfall_intensity_mm_hr=60.0, rainfall_duration_min=60.0, time_step_min=10.0), drains, neighbourhood_id=nb.id)

    comp = compare_multiple_scenarios(
        [out_a, out_b],
        cells,
        network=net,
        origin_node_id=nids[0],
        dest_node_id=nids[-1],
    )
    assert comp.are_compatible
    assert comp.rows[1].max_depth_cm > comp.rows[0].max_depth_cm
    assert comp.rows[0].peak_depth_time_min >= 0.0
    assert any("Rainfall:" in d for d in comp.config_differences)

    comp_warn = compare_multiple_scenarios([out_a, out_c], cells)
    assert not comp_warn.are_compatible
    assert any("Duration difference" in w for w in comp_warn.compatibility_warnings)


# ---------------------------------------------------------------------------
# Unit Tests: Database Audit, Online Backup, Validation & Confirmed Restore
# ---------------------------------------------------------------------------

def test_database_audit_backup_validation_and_restore(tmp_path: Path) -> None:
    db, repo, nid, _cells, _drains = _seed_workspace(tmp_path / "live.db")
    mgr = DatabaseBackupManager(db, backup_dir=tmp_path / "backups")

    audit = mgr.audit_database()
    assert audit.overall_ok
    assert audit.foreign_keys_enabled
    assert not audit.missing_tables
    assert audit.index_count > 0

    bpath, bval = mgr.create_backup(label="clean_snapshot")
    assert bval.is_valid
    assert bpath.exists()

    # Reject corrupt / non-SQLite files
    bad_file = tmp_path / "corrupt.db"
    bad_file.write_bytes(b"NOT A SQLITE FILE" * 100)
    bad_res = mgr.validate_backup(bad_file)
    assert not bad_res.is_valid

    # Mutate live DB after backup
    WorkspaceManager(repo).create_or_get_workspace(
        name="TEMP_EXTRA",
        center_latitude=12.83,
        center_longitude=80.05,
        min_latitude=12.825,
        max_latitude=12.835,
        min_longitude=80.045,
        max_longitude=80.055,
        grid_rows=2,
        grid_cols=2,
    )
    assert repo.get_neighbourhood_by_name("TEMP_EXTRA") is not None

    # Restore without confirmation must fail
    with pytest.raises(PermissionError):
        mgr.restore_backup(bpath, user_confirmed=False)

    # Restore with confirmation succeeds & writes pre-restore safety snapshot
    safety_path, rval = mgr.restore_backup(bpath, user_confirmed=True)
    assert rval.is_valid
    assert safety_path is not None and safety_path.exists()
    assert repo.get_neighbourhood_by_name("TEMP_EXTRA") is None
    assert repo.get_neighbourhood_by_name("POTHERI_P7_TEST") is not None


# ---------------------------------------------------------------------------
# Integration Workflows 1–5 (§17) + All 12 Reports (PDF & CSV)
# ---------------------------------------------------------------------------

def test_workflow_1_flood_simulation_and_all_12_reports(tmp_path: Path) -> None:
    db, repo, nid, cells, drains = _seed_workspace(tmp_path / "wf1.db")
    nb = repo.get_neighbourhood_by_id(nid)
    assert nb is not None
    osm = repo.get_osm_features(nid)
    net = build_road_network_from_osm(nid, osm, cells)

    cfg = SimulationConfig("WF1 Storm 60mm", rainfall_intensity_mm_hr=60.0, rainfall_duration_min=30.0, time_step_min=10.0)
    out = run_simulation(cells, cfg, drains, neighbourhood_id=nb.id)
    sim_id = repo.save_simulation_output(out)

    cfg2 = clone_config_from_run(out.run, scenario_name="WF1 Baseline 30mm")
    cfg2.rainfall_intensity_mm_hr = 30.0
    out2 = run_simulation(cells, cfg2, drains, neighbourhood_id=nb.id)
    sim2_id = repo.save_simulation_output(out2)

    gen = ReportGenerator(db, exports_dir=tmp_path / "reports")
    for rkey, _title in REPORT_TYPES:
        pdf_res = gen.generate_report(
            rkey, nid, file_format="pdf", simulation_id=sim_id,
            comparison_sim_ids=[sim2_id, sim_id], network=net,
        )
        assert pdf_res.output_path.exists()
        assert pdf_res.output_path.read_bytes().startswith(b"%PDF-")

        csv_res = gen.generate_report(
            rkey, nid, file_format="csv", simulation_id=sim_id,
            comparison_sim_ids=[sim2_id, sim_id], network=net,
        )
        assert csv_res.output_path.exists()
        assert csv_res.output_path.stat().st_size > 20


def test_workflow_2_evacuation_route_comparison(tmp_path: Path) -> None:
    db, repo, nid, cells, drains = _seed_workspace(tmp_path / "wf2.db")
    nb = repo.get_neighbourhood_by_id(nid)
    assert nb is not None
    osm = repo.get_osm_features(nid)
    net = build_road_network_from_osm(nid, osm, cells)

    out = run_simulation(
        cells,
        SimulationConfig("WF2 Extreme", rainfall_intensity_mm_hr=100.0, rainfall_duration_min=30.0, time_step_min=10.0),
        drains,
        neighbourhood_id=nb.id,
    )
    sim_id = repo.save_simulation_output(out)
    exps = analyze_road_network_exposure(net, cells, out, timestep=out.steps[-1].timestep)
    nids = list(net.nodes_by_id.keys())
    res = calculate_evacuation_routes(
        net, nids[0], nids[-1], "Origin", "Destination", exps,
        {eid: "Normal" for eid in net.edges_by_id},
        simulation_id=sim_id, timestep=out.steps[-1].timestep,
    )
    assert res.shortest is not None
    assert res.flood_aware is not None
    assert res.comparison is not None


def test_workflow_3_emergency_management_end_to_end(tmp_path: Path) -> None:
    db, repo, nid, _cells, _drains = _seed_workspace(tmp_path / "wf3.db")
    sh_mgr = ShelterManager(db)
    tm_mgr = RescueTeamManager(db)
    vh_mgr = VehicleManager(db)
    in_mgr = InventoryManager(db)
    op_mgr = OperationManager(db)
    al_mgr = ResourceAllocator(db)

    shelter = sh_mgr.register_shelter(nid, "Potheri Hall", "Main Rd", 12.822, 80.043, total_capacity=200, occupied_capacity=40, is_verified=True)
    team = tm_mgr.register_team(nid, "Alpha Squad", leader="Karthik", members=["Divya", "Suresh"], availability="Available")
    veh = vh_mgr.register_vehicle(nid, "TN-19-FG-99", "Rescue boat", capacity=8, fuel_status="Full", operational_status="Available")
    item = in_mgr.register_item(nid, "Drinking water", "Food and water", 100.0, "cans", minimum_stock=20.0)
    op = op_mgr.create_operation(
        nid, "Supply Water to Potheri Hall", "Shelter supply delivery",
        priority="High", destination=shelter.name, destination_shelter_id=shelter.id,
        assigned_team_id=team.id, assigned_vehicle_id=veh.id, status="In progress",
    )
    al_mgr.allocate_resource(nid, "inventory_item", item.id, "shelter", shelter.id, shelter.name, quantity=35.0, operation_id=op.id)  # type: ignore[arg-type]
    updated_item = in_mgr.get_item(item.id)  # type: ignore[arg-type]
    assert updated_item is not None and updated_item.quantity == pytest.approx(65.0)

    gen = ReportGenerator(db, exports_dir=tmp_path / "reports")
    op_pdf = gen.generate_report("emergency_operations", nid, file_format="pdf")
    assert op_pdf.output_path.exists() and op_pdf.output_path.read_bytes().startswith(b"%PDF-")


def test_workflow_4_what_if_experiment_and_comparison_export(tmp_path: Path) -> None:
    db, repo, nid, cells, drains = _seed_workspace(tmp_path / "wf4.db")
    nb = repo.get_neighbourhood_by_id(nid)
    assert nb is not None

    base_cfg = SimulationConfig("Base Moderate", rainfall_intensity_mm_hr=30.0, rainfall_duration_min=30.0, time_step_min=10.0)
    out_base = run_simulation(cells, base_cfg, drains, neighbourhood_id=nb.id)
    id_base = repo.save_simulation_output(out_base)

    mgr = ScenarioManager()
    disabled = {drains[0].id} if drains[0].id is not None else set()
    variant = mgr.create_modified_variant(
        base_cfg,
        name="WF4 Higher Rain + Drain Failed",
        baseline_run_id=id_base,
        rainfall_intensity_mm_hr=80.0,
        disabled_drainage_ids=disabled,
        is_hypothetical=True,
    )
    out_alt = mgr.run_variant(nb, cells, drains, variant)
    id_alt = repo.save_simulation_output(out_alt)

    comp = compare_multiple_scenarios([out_base, out_alt], cells)
    assert comp.rows[1].max_depth_cm > comp.rows[0].max_depth_cm
    assert comp.rows[1].disabled_drainage_count == 1

    gen = ReportGenerator(db, exports_dir=tmp_path / "reports")
    res_pdf = gen.generate_report("scenario_comparison", nid, file_format="pdf", comparison_sim_ids=[id_base, id_alt])
    res_csv = gen.generate_report("scenario_comparison", nid, file_format="csv", comparison_sim_ids=[id_base, id_alt])
    assert res_pdf.output_path.read_bytes().startswith(b"%PDF-")
    assert "WF4 Higher Rain + Drain Failed" in res_csv.output_path.read_text(encoding="utf-8")


def test_workflow_5_and_full_app_gui_offline_smoke(tmp_path: Path) -> None:
    db_path = tmp_path / "wf5_gui.db"
    db, repo, nid, cells, drains = _seed_workspace(db_path)
    repo.set_setting("force_offline", "true")
    repo.set_setting("active_neighbourhood_id", str(nid))

    orig_init = db_mod.DatabaseManager.__init__

    def _patched_init(self, db_path_arg: Path = db_path, schema_path_arg: Path | None = None) -> None:
        if schema_path_arg is None:
            orig_init(self, db_path=db_path)
        else:
            orig_init(self, db_path=db_path, schema_path=schema_path_arg)

    db_mod.DatabaseManager.__init__ = _patched_init  # type: ignore[method-assign]
    from gui.app import FloodGuardApp

    app = None
    try:
        app = FloodGuardApp()
        app.update()
        assert app.is_offline_mode is True

        # Visit all Phase 7 views safely offline
        for page in ("dashboard", "simulation_lab", "flood_map", "saferoute", "resources", "what_if", "reports", "settings"):
            app.navigate_to(page)
            app.update()

        # Run a What-If variant offline, calculate a route, manage inventory, generate a report
        nb = repo.get_neighbourhood_by_id(nid)
        assert nb is not None
        out = run_simulation(
            cells,
            SimulationConfig("Offline Run", rainfall_intensity_mm_hr=50.0, rainfall_duration_min=20.0, time_step_min=10.0),
            drains,
            neighbourhood_id=nb.id,
        )
        sid = repo.save_simulation_output(out)
        in_mgr = InventoryManager(app.db_manager)
        in_mgr.register_item(nid, "Flashlights", "Rescue equipment", 25, "units", minimum_stock=5)
        gen = ReportGenerator(app.db_manager, exports_dir=tmp_path / "offline_rep")
        rep = gen.generate_report("complete_project", nid, file_format="pdf", simulation_id=sid)
        assert rep.output_path.exists()
    finally:
        if app is not None:
            app.destroy()
        db_mod.DatabaseManager.__init__ = orig_init  # type: ignore[method-assign]
