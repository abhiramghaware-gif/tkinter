"""Automated Phase 5 tests for SafeRoute Road Network, Flood Exposure, Routing & SQLite v4."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from core.models import GridCell, Neighbourhood, OSMFeature
from core.simulation_config import SimulationConfig
from core.simulation_engine import (
    SimulationCellStepRecord,
    SimulationOutput,
    SimulationRunRecord,
    SimulationStepRecord,
    SimulationSummary,
)
from core.validation import ValidationError
from database.db import DatabaseManager
from database.repository import FloodGuardRepository
from gui.saferoute_screen import SafeRouteScreen
from routing.flood_exposure import (
    RoadExposureThresholds,
    analyze_road_network_exposure,
    classify_road_exposure_depth,
)
from routing.road_network import (
    build_road_network_from_osm,
    extract_evacuation_destinations,
)
from routing.route_comparison import compare_routes
from routing.route_planner import (
    RouteCostWeights,
    calculate_evacuation_routes,
    calculate_single_route,
)
from routing.travel_time import (
    TravelSpeedConfig,
    estimate_route_travel_time_minutes,
    estimate_segment_time_minutes,
)


def _make_grid_2x2(with_elev: bool = True) -> tuple[Neighbourhood, list[GridCell]]:
    nb = Neighbourhood(
        id=1,
        name="TEST_SAFEROUTE",
        district="Chengalpattu",
        state="Tamil Nadu",
        country="India",
        center_latitude=12.825,
        center_longitude=80.045,
        min_latitude=12.820,
        max_latitude=12.830,
        min_longitude=80.040,
        max_longitude=80.050,
        grid_rows=2,
        grid_cols=2,
    )
    cells = [
        GridCell(
            id=1,
            neighbourhood_id=1,
            row_number=0,
            column_number=0,
            min_latitude=12.825,
            max_latitude=12.830,
            min_longitude=80.040,
            max_longitude=80.045,
            elevation_m=14.0 if with_elev else None,
            mean_elevation_m=14.0 if with_elev else None,
            elevation_source="synthetic-test" if with_elev else "missing",
        ),
        GridCell(
            id=2,
            neighbourhood_id=1,
            row_number=0,
            column_number=1,
            min_latitude=12.825,
            max_latitude=12.830,
            min_longitude=80.045,
            max_longitude=80.050,
            elevation_m=14.5 if with_elev else None,
            mean_elevation_m=14.5 if with_elev else None,
            elevation_source="synthetic-test" if with_elev else "missing",
        ),
        GridCell(
            id=3,
            neighbourhood_id=1,
            row_number=1,
            column_number=0,
            min_latitude=12.820,
            max_latitude=12.825,
            min_longitude=80.040,
            max_longitude=80.045,
            elevation_m=11.0 if with_elev else None,
            mean_elevation_m=11.0 if with_elev else None,
            elevation_source="synthetic-test" if with_elev else "missing",
        ),
        GridCell(
            id=4,
            neighbourhood_id=1,
            row_number=1,
            column_number=1,
            min_latitude=12.820,
            max_latitude=12.825,
            min_longitude=80.045,
            max_longitude=80.050,
            elevation_m=11.2 if with_elev else None,
            mean_elevation_m=11.2 if with_elev else None,
            elevation_source="synthetic-test" if with_elev else "missing",
        ),
    ]
    return nb, cells


def _make_diamond_osm_roads() -> list[OSMFeature]:
    """Build a synthetic diamond network with a shorter floodplain highway and a dry ridge detour.

    West/East endpoints sit just north of cell boundary (lat 12.8255, cells 1 & 2, 0 cm).
    South valley shortcut dips to lat 12.8220 through flooded south cells (3 & 4).
    North ridge detour stays strictly >= 12.8255 inside dry north cells (1 & 2).
    """
    return [
        OSMFeature(
            id=101,
            neighbourhood_id=1,
            osm_id=9001,
            element_type="way",
            category="road",
            subcategory="primary",
            name="Flooded Highway",
            geometry={
                "type": "LineString",
                "coordinates": [[80.041, 12.8255], [80.045, 12.822], [80.049, 12.8255]],
            },
            tags={"highway": "primary", "name": "Flooded Highway"},
            road_category="Primary road",
        ),
        OSMFeature(
            id=102,
            neighbourhood_id=1,
            osm_id=9002,
            element_type="way",
            category="road",
            subcategory="residential",
            name="Highland Detour",
            geometry={
                "type": "LineString",
                "coordinates": [
                    [80.041, 12.8255],
                    [80.041, 12.8290],
                    [80.045, 12.8290],
                    [80.049, 12.8290],
                    [80.049, 12.8255],
                ],
            },
            tags={"highway": "residential", "name": "Highland Detour"},
            road_category="Residential road",
        ),
        OSMFeature(
            id=103,
            neighbourhood_id=1,
            osm_id=9003,
            element_type="way",
            category="road",
            subcategory="secondary",
            name="Midtown Link",
            geometry={
                "type": "LineString",
                "coordinates": [[80.045, 12.822], [80.045, 12.8290]],
            },
            tags={"highway": "secondary", "name": "Midtown Link"},
            road_category="Secondary road",
        ),
        # Malformed geometry should be safely skipped without throwing
        OSMFeature(
            id=104,
            neighbourhood_id=1,
            osm_id=9004,
            element_type="way",
            category="road",
            subcategory="service",
            name="Broken Road",
            geometry={"type": "LineString", "coordinates": [[80.042, 12.822]]},
            tags={"highway": "service"},
            road_category="Service road",
        ),
    ]


def _make_synthetic_sim_output(
    depths_by_cell_id: dict[int, float],
    sim_id: int | None = None,
    mode: str = "elevation_based",
) -> SimulationOutput:
    cfg = SimulationConfig(
        scenario_name="Test Storm",
        rainfall_intensity_mm_hr=60.0,
        rainfall_duration_min=60.0,
        time_step_min=15.0,
        simulation_mode=mode,
    )
    run = SimulationRunRecord(
        id=sim_id,
        neighbourhood_id=1,
        scenario_name="Test Storm",
        rainfall_intensity=60.0,
        rainfall_duration=60.0,
        time_step=15.0,
        simulation_mode=mode,
        distribution_pattern="constant",
        initial_water_depth=0.0,
        config_json=cfg.to_json(),
        start_time="2026-01-01T00:00:00+00:00",
        completion_time="2026-01-01T00:01:00+00:00",
        status="completed",
        model_version="phase3-v1",
    )
    max_d = max(depths_by_cell_id.values()) if depths_by_cell_id else 0.0
    avg_d = (
        sum(depths_by_cell_id.values()) / len(depths_by_cell_id)
        if depths_by_cell_id
        else 0.0
    )
    aff_cnt = sum(1 for d in depths_by_cell_id.values() if d > 0.001)
    step = SimulationStepRecord(
        timestep=1,
        sim_time_minutes=15.0,
        rainfall_intensity_mm_hr=60.0,
        rainfall_input_m3=100.0,
        infiltration_loss_m3=20.0,
        drainage_loss_m3=10.0,
        water_transferred_m3=0.0,
        total_volume_remaining_m3=70.0,
        max_water_depth_m=max_d,
        avg_water_depth_m=avg_d,
        affected_cell_count=aff_cnt,
        total_area_affected_m2=aff_cnt * 1000.0,
        mass_balance_error_m3=0.0,
    )
    cell_steps = [
        SimulationCellStepRecord(
            timestep=1,
            sim_time_minutes=15.0,
            cell_id=cid,
            cell_code=f"C{cid}",
            water_depth_m=d,
            water_volume_m3=d * 1000.0,
            rainfall_input_m3=10.0,
            infiltration_loss_m3=2.0,
            drainage_loss_m3=1.0,
            flow_transferred_m3=0.0,
        )
        for cid, d in depths_by_cell_id.items()
    ]
    summary = SimulationSummary(
        max_water_depth_m=max_d,
        avg_water_depth_m=avg_d,
        initial_water_volume_m3=0.0,
        total_rainfall_volume_m3=100.0,
        total_infiltration_volume_m3=20.0,
        total_drainage_volume_m3=10.0,
        total_transferred_volume_m3=0.0,
        final_surface_volume_m3=70.0,
        max_affected_cells=aff_cnt,
        total_affected_area_m2=aff_cnt * 1000.0,
        time_of_max_depth_minutes=15.0,
        mass_balance_error_m3=0.0,
        mass_balance_tolerance_m3=1e-6,
        mass_balance_passed=True,
        used_illustrative_terrain=(mode != "elevation_based"),
        total_steps=1,
    )
    return SimulationOutput(
        run=run,
        config=cfg,
        summary=summary,
        steps=[step],
        cell_steps=cell_steps,
        final_cells=[],
        drainage_profiles={},
    )


def test_road_network_creation_splits_intersections_and_skips_malformed() -> None:
    _, cells = _make_grid_2x2()
    roads = _make_diamond_osm_roads()
    net = build_road_network_from_osm(1, roads, cells)

    assert net.skipped_feature_count == 1
    assert net.node_count == 4  # West corner, South-Mid, North-Mid, East corner
    assert net.edge_count == 5  # 2 south edges + 2 north edges + 1 midtown link
    assert len(net.get_connected_components()) == 1
    assert all(e.distance_m > 0.0 for e in net.edges_by_id.values())
    assert all(len(e.grid_cell_ids) >= 1 for e in net.edges_by_id.values())


def test_evacuation_destinations_only_from_real_osm_no_invention() -> None:
    _, cells = _make_grid_2x2()
    roads = _make_diamond_osm_roads()
    school = OSMFeature(
        id=201,
        neighbourhood_id=1,
        osm_id=8801,
        element_type="way",
        category="building",
        subcategory="school",
        name="Potheri Govt School",
        geometry={
            "type": "Polygon",
            "coordinates": [
                [
                    [80.0485, 12.8275],
                    [80.0492, 12.8275],
                    [80.0492, 12.8282],
                    [80.0485, 12.8282],
                    [80.0485, 12.8275],
                ]
            ],
        },
        tags={"building": "school", "name": "Potheri Govt School"},
        building_category="School",
    )
    net = build_road_network_from_osm(1, roads, cells)
    dests = extract_evacuation_destinations(net, [school])
    assert len(dests) == 1
    assert "Unverified" in dests[0].label
    assert dests[0].is_verified_shelter is False
    assert dests[0].nearest_node_id is not None

    # No shelters/schools -> returns empty list (never invents fake shelters)
    assert extract_evacuation_destinations(net, roads) == []


def test_flood_exposure_classification_and_unknown_never_safe() -> None:
    th = RoadExposureThresholds()
    assert classify_road_exposure_depth(None, th) == "Unknown"
    assert classify_road_exposure_depth(0.0, th) == "No surface flooding"
    assert classify_road_exposure_depth(0.05, th) == "Low"
    assert classify_road_exposure_depth(0.20, th) == "Moderate"
    assert classify_road_exposure_depth(0.45, th) == "High"
    assert classify_road_exposure_depth(0.75, th) == "Very high"

    # Without simulation output, all edges MUST be Unknown
    _, cells = _make_grid_2x2(with_elev=False)
    net = build_road_network_from_osm(1, _make_diamond_osm_roads(), cells)
    exp_none = analyze_road_network_exposure(net, cells, output=None)
    assert all(e.exposure_category == "Unknown" for e in exp_none.values())

    # With 0.0 m simulated depth on missing-elevation cells, dry roads remain Unknown (never safe)
    sim_dry = _make_synthetic_sim_output({1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}, mode="illustrative_assumed")
    exp_no_dem = analyze_road_network_exposure(net, cells, output=sim_dry)
    assert all(e.exposure_category == "Unknown" for e in exp_no_dem.values())


def test_shortest_vs_flood_aware_dijkstra_routing() -> None:
    _, cells = _make_grid_2x2(with_elev=True)
    net = build_road_network_from_osm(1, _make_diamond_osm_roads(), cells)
    west = net.find_nearest_node(12.8255, 80.041)[0]
    east = net.find_nearest_node(12.8255, 80.049)[0]

    # Flood south highway cells (3 & 4) heavily (45 cm -> High); keep north cells (1 & 2) dry (0 cm)
    sim = _make_synthetic_sim_output({1: 0.0, 2: 0.0, 3: 0.45, 4: 0.45})
    exposures = analyze_road_network_exposure(net, cells, sim)

    res = calculate_evacuation_routes(
        network=net,
        start_node_id=west.node_id,
        dest_node_id=east.node_id,
        origin_label="West Gate",
        destination_label="East Junction",
        exposures=exposures,
        manual_statuses={},
        speed_config=TravelSpeedConfig(mode="Two-wheeler/Car"),
        weights=RouteCostWeights(),
        simulation_id=1,
        timestep=1,
    )

    assert res.shortest is not None
    assert res.flood_aware is not None
    assert res.shortest.high_risk_segment_count > 0
    assert "Flooded Highway" in res.shortest.road_names
    # Flood-aware detours via Highland Detour avoiding High flood exposure!
    assert res.flood_aware.high_risk_segment_count == 0
    assert "Highland Detour" in res.flood_aware.road_names
    assert res.flood_aware.total_distance_m > res.shortest.total_distance_m
    assert res.comparison is not None
    assert len(res.comparison.comparison_notes) >= 1


def test_manual_road_closure_avoidance_and_recalculation() -> None:
    _, cells = _make_grid_2x2(with_elev=True)
    net = build_road_network_from_osm(1, _make_diamond_osm_roads(), cells)
    west = net.find_nearest_node(12.8255, 80.041)[0]
    east = net.find_nearest_node(12.8255, 80.049)[0]

    sim = _make_synthetic_sim_output({1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0})
    exposures = analyze_road_network_exposure(net, cells, sim)

    # Close one south highway edge manually -> even Shortest route must avoid Closed road!
    south_edge_ids = [
        eid for eid, e in net.edges_by_id.items() if "Flooded Highway" in e.road_name
    ]
    manual = {south_edge_ids[0]: "Closed"}

    res_closed = calculate_evacuation_routes(
        network=net,
        start_node_id=west.node_id,
        dest_node_id=east.node_id,
        origin_label="A",
        destination_label="B",
        exposures=exposures,
        manual_statuses=manual,
        speed_config=TravelSpeedConfig(mode="Two-wheeler/Car"),
        weights=RouteCostWeights(avoid_closed_roads=True),
    )
    assert res_closed.shortest is not None
    assert res_closed.shortest.closed_segment_count == 0
    assert south_edge_ids[0] not in res_closed.shortest.edge_ids

    # Reopen the road and recalculate -> shortest path uses Flooded Highway again
    res_reopened = calculate_evacuation_routes(
        network=net,
        start_node_id=west.node_id,
        dest_node_id=east.node_id,
        origin_label="A",
        destination_label="B",
        exposures=exposures,
        manual_statuses={},
        speed_config=TravelSpeedConfig(mode="Two-wheeler/Car"),
        weights=RouteCostWeights(avoid_closed_roads=True),
    )
    assert res_reopened.shortest is not None
    assert south_edge_ids[0] in res_reopened.shortest.edge_ids


def test_travel_modes_and_speed_assumptions() -> None:
    _, cells = _make_grid_2x2(with_elev=True)
    # Footpath-only bridge connecting two islands
    footpath_osm = [
        OSMFeature(
            id=301,
            neighbourhood_id=1,
            osm_id=9301,
            element_type="way",
            category="road",
            subcategory="footway",
            name="Pedestrian Footbridge",
            geometry={"type": "LineString", "coordinates": [[80.041, 12.825], [80.046, 12.825]]},
            tags={"highway": "footway", "name": "Pedestrian Footbridge"},
            road_category="Footpath",
        )
    ]
    net = build_road_network_from_osm(1, footpath_osm, cells)
    n1 = net.find_nearest_node(12.825, 80.041)[0]
    n2 = net.find_nearest_node(12.825, 80.046)[0]

    car_cfg = TravelSpeedConfig(mode="Two-wheeler/Car")
    assert estimate_segment_time_minutes(500.0, "Footpath", car_cfg) is None
    car_route, car_fail = calculate_single_route(
        net, n1.node_id, n2.node_id, "Shortest", "Start", "End", {}, {}, car_cfg, RouteCostWeights()
    )
    assert car_route is None
    assert car_fail is not None and "footpath" in car_fail.reason.lower()

    walk_cfg = TravelSpeedConfig(mode="Walking")
    walk_route, walk_fail = calculate_single_route(
        net, n1.node_id, n2.node_id, "Shortest", "Start", "End", {}, {}, walk_cfg, RouteCostWeights()
    )
    assert walk_fail is None
    assert walk_route is not None
    assert walk_route.estimated_time_minutes > 1.0

    # Custom negative speed must fail validation
    bad_cfg = TravelSpeedConfig(mode="Walking")
    bad_cfg.speeds_by_mode["Walking"]["Footpath"] = -5.0
    with pytest.raises(ValidationError):
        bad_cfg.validate()


def test_disconnected_and_blocked_network_diagnostics() -> None:
    _, cells = _make_grid_2x2(with_elev=True)
    islands = [
        OSMFeature(
            id=401,
            neighbourhood_id=1,
            osm_id=9401,
            element_type="way",
            category="road",
            subcategory="residential",
            name="West Island St",
            geometry={"type": "LineString", "coordinates": [[80.041, 12.822], [80.042, 12.822]]},
            tags={"highway": "residential"},
            road_category="Residential road",
        ),
        OSMFeature(
            id=402,
            neighbourhood_id=1,
            osm_id=9402,
            element_type="way",
            category="road",
            subcategory="residential",
            name="East Island St",
            geometry={"type": "LineString", "coordinates": [[80.048, 12.822], [80.049, 12.822]]},
            tags={"highway": "residential"},
            road_category="Residential road",
        ),
    ]
    net = build_road_network_from_osm(1, islands, cells)
    w = net.find_nearest_node(12.822, 80.041)[0]
    e = net.find_nearest_node(12.822, 80.049)[0]

    res = calculate_evacuation_routes(
        network=net,
        start_node_id=w.node_id,
        dest_node_id=e.node_id,
        origin_label="West Island",
        destination_label="East Island",
        exposures={},
        manual_statuses={},
        speed_config=TravelSpeedConfig(mode="Two-wheeler/Car"),
        weights=RouteCostWeights(),
    )
    assert res.shortest is None
    assert res.flood_aware is None
    assert any("disconnected" in f.reason.lower() for f in res.failures)


def test_route_comparison_and_sqlite_v4_persistence(tmp_path: Path) -> None:
    db_file = tmp_path / "phase5_test.db"
    db = DatabaseManager(db_file)
    db.initialize()
    ok, msg = db.verify_integrity()
    assert ok and "SQLite OK (v" in msg and "FK=ON" in msg
    repo = FloodGuardRepository(db)

    nb, cells = _make_grid_2x2(with_elev=True)
    ws = repo.create_neighbourhood_with_cells(nb, cells)
    assert ws.id is not None
    db_cells = repo.get_grid_cells(ws.id)

    roads = [r for r in _make_diamond_osm_roads() if r.id != 104]
    repo.replace_osm_features(ws.id, roads)
    db_roads = repo.get_osm_features(ws.id)

    net = build_road_network_from_osm(ws.id, db_roads, db_cells)
    repo.sync_road_network(net)

    # Re-syncing preserves edge IDs and manual closures!
    target_edge_id = next(iter(net.edges_by_id.keys()))
    repo.upsert_road_condition(
        neighbourhood_id=ws.id,
        road_edge_id=target_edge_id,
        status="Blocked",
        exposure_category="High",
        maximum_water_depth=0.45,
        status_source="user-entered",
        notes="Fallen tree test",
    )

    net_rebuilt = build_road_network_from_osm(ws.id, db_roads, db_cells)
    repo.sync_road_network(net_rebuilt)
    assert set(net_rebuilt.edges_by_id.keys()) == set(net.edges_by_id.keys())

    conds = repo.get_road_conditions(ws.id)
    assert conds[target_edge_id].status == "Blocked"
    assert conds[target_edge_id].status_source == "user-entered"

    # Route planning & route_history persistence with a real saved simulation_runs row
    west = net_rebuilt.find_nearest_node(12.8255, 80.041)[0]
    east = net_rebuilt.find_nearest_node(12.8255, 80.049)[0]
    sim = _make_synthetic_sim_output(
        {c.id: 0.45 if c.row_number == 1 else 0.0 for c in db_cells if c.id},
        sim_id=None,
    )
    saved_sim_id = repo.save_simulation_output(sim)
    sim.run.id = saved_sim_id
    exposures = analyze_road_network_exposure(net_rebuilt, db_cells, sim)
    merged_conds = repo.sync_simulation_road_conditions(ws.id, exposures, conds)
    # Manual Blocked state must stay preserved across simulation exposure sync
    assert merged_conds[target_edge_id].status == "Blocked"
    assert merged_conds[target_edge_id].status_source == "user-entered"

    res = calculate_evacuation_routes(
        network=net_rebuilt,
        start_node_id=west.node_id,
        dest_node_id=east.node_id,
        origin_label="West Gate",
        destination_label="East Gate",
        exposures=exposures,
        manual_statuses={eid: c.status for eid, c in merged_conds.items()},
        speed_config=TravelSpeedConfig(mode="Walking"),
        weights=RouteCostWeights(),
    )
    assert res.shortest is not None
    cmp_summary = compare_routes(res.routes)
    assert "decision-support" in cmp_summary.disclaimer.lower()

    hist_id = repo.save_route_history(ws.id, res.shortest, simulation_id=None, time_step=1)
    assert hist_id > 0
    hist = repo.list_route_history(ws.id)
    assert len(hist) == 1
    assert hist[0]["origin"] == "West Gate"


def test_saferoute_gui_screen_smoke(tmp_path: Path) -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    root.withdraw()

    db = DatabaseManager(tmp_path / "gui_p5.db")
    db.initialize()
    repo = FloodGuardRepository(db)
    nb, cells = _make_grid_2x2(with_elev=True)
    ws = repo.create_neighbourhood_with_cells(nb, cells)
    assert ws.id is not None
    db_cells = repo.get_grid_cells(ws.id)
    repo.replace_osm_features(ws.id, [r for r in _make_diamond_osm_roads() if r.id != 104])
    db_roads = repo.get_osm_features(ws.id)

    screen = SafeRouteScreen(
        root,
        on_fetch_simulation=repo.load_simulation_output,
        on_sync_road_network=repo.sync_road_network,
        on_load_road_conditions=repo.get_road_conditions,
        on_save_road_condition=repo.upsert_road_condition,
        on_sync_sim_conditions=repo.sync_simulation_road_conditions,
        on_save_route_history=repo.save_route_history,
        on_list_route_history=repo.list_route_history,
    )
    screen.pack(fill="both", expand=True)
    screen.refresh_workspace(ws, db_cells, db_roads, [], [])
    root.update_idletasks()
    res = screen.calculate_routes_sync()
    assert res is not None and res.shortest is not None
    root.destroy()
