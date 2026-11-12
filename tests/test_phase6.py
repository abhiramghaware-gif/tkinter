"""Automated Phase 6 verification suite for Emergency Resource & Relief Management."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from core.models import GridCell, Neighbourhood, OSMFeature
from core.validation import ValidationError
from database.db import DatabaseManager
from database.repository import FloodGuardRepository
from emergency import (
    AlertManager,
    InventoryManager,
    InventoryTransactionService,
    OperationManager,
    REPORT_REGISTRY,
    RescueTeamManager,
    ResourceAllocator,
    ShelterManager,
    VehicleManager,
    VolunteerManager,
    export_volunteers_report,
)
from routing.road_network import build_road_network_from_osm, extract_evacuation_destinations
from routing.route_planner import RouteCostWeights, calculate_evacuation_routes
from routing.travel_time import TravelSpeedConfig


def _init_workspace(tmp_path: Path) -> tuple[DatabaseManager, FloodGuardRepository, Neighbourhood]:
    db = DatabaseManager(tmp_path / "phase6_test.db")
    db.initialize()
    repo = FloodGuardRepository(db)
    nb = Neighbourhood(
        id=None,
        name="POTHERI_SYNTHETIC_TEST",
        district="Chengalpattu",
        state="Tamil Nadu",
        country="India",
        center_latitude=12.8230,
        center_longitude=80.0440,
        min_latitude=12.8180,
        max_latitude=12.8280,
        min_longitude=80.0390,
        max_longitude=80.0490,
        grid_rows=1,
        grid_cols=1,
    )
    cells = [
        GridCell(
            id=None,
            neighbourhood_id=0,
            row_number=0,
            column_number=0,
            min_latitude=12.8180,
            max_latitude=12.8280,
            min_longitude=80.0390,
            max_longitude=80.0490,
        )
    ]
    ws = repo.create_neighbourhood_with_cells(nb, cells)
    assert ws.id is not None
    return db, repo, ws


def test_shelter_registration_capacity_validation_and_editing(tmp_path: Path) -> None:
    db, _, ws = _init_workspace(tmp_path)
    assert ws.id is not None
    mgr = ShelterManager(db)

    shelter = mgr.register_shelter(
        neighbourhood_id=ws.id,
        name="Synthetic Community Hall Shelter",
        address="GST Road Potheri Test",
        latitude=12.8235,
        longitude=80.0442,
        total_capacity=120,
        occupied_capacity=35,
        status="Active",
        facilities=["Drinking water", "Medical support", "Toilets"],
        accessibility="Ground floor ramp",
        source="field-verified",
        is_verified=True,
    )
    assert shelter.id is not None
    assert shelter.available_capacity == 85
    assert shelter.is_verified is True
    assert shelter.verification_label == "Verified Shelter"

    with pytest.raises(ValidationError):
        mgr.register_shelter(
            neighbourhood_id=ws.id,
            name="Invalid Overloaded Shelter",
            address="Test",
            latitude=12.8235,
            longitude=80.0442,
            total_capacity=50,
            occupied_capacity=55,
        )

    with pytest.raises(ValidationError):
        mgr.update_occupancy(shelter.id, occupied_capacity=130)

    full = mgr.update_occupancy(shelter.id, occupied_capacity=120)
    assert full.available_capacity == 0
    assert full.status == "Full"

    inactive = mgr.set_shelter_status(shelter.id, "Inactive")
    assert inactive.status == "Inactive"


def test_rescue_team_registration_members_and_operations(tmp_path: Path) -> None:
    db, _, ws = _init_workspace(tmp_path)
    assert ws.id is not None
    mgr = RescueTeamManager(db)

    team = mgr.register_team(
        neighbourhood_id=ws.id,
        team_name="Potheri Alpha Team (Test)",
        leader="Arun Test",
        members=["Member A", "Member B", "Member A"],
        skills="Swift water, first aid",
        current_location="Potheri Main Gate",
    )
    assert team.id is not None
    assert team.member_count == 2  # deduplicated
    assert team.availability == "Available"

    assigned = mgr.assign_operation(team.id, "Synthetic Shelter Support Run", set_status="On operation")
    assert assigned.availability == "On operation"
    assert "Synthetic Shelter" in assigned.current_assignment

    released = mgr.complete_operation(team.id, completion_notes="Test completion")
    assert released.availability == "Available"
    assert released.current_assignment == ""


def test_vehicle_registration_and_team_assignment(tmp_path: Path) -> None:
    db, _, ws = _init_workspace(tmp_path)
    assert ws.id is not None
    tmgr = RescueTeamManager(db)
    vmgr = VehicleManager(db)

    team = tmgr.register_team(ws.id, "Boat Crew Test")
    assert team.id is not None

    veh = vmgr.register_vehicle(
        neighbourhood_id=ws.id,
        registration_number="TN-TEST-001",
        vehicle_type="Rescue boat",
        capacity=8,
        fuel_status="Full",
    )
    assert veh.id is not None

    with pytest.raises(ValidationError):
        vmgr.register_vehicle(ws.id, "TN-TEST-001", "Ambulance", 2)

    assigned = vmgr.assign_vehicle_to_team(veh.id, team.id)
    assert assigned.operational_status == "Assigned"
    assert assigned.assigned_team_id == team.id

    with pytest.raises(ValidationError):
        vmgr.assign_vehicle_to_team(veh.id, team.id)  # already assigned

    released = vmgr.release_vehicle(veh.id)
    assert released.operational_status == "Available"
    assert released.assigned_team_id is None


def test_volunteer_registration_and_contact_privacy(tmp_path: Path) -> None:
    db, _, ws = _init_workspace(tmp_path)
    assert ws.id is not None
    vmgr = VolunteerManager(db)
    op_mgr = OperationManager(db)

    vol = vmgr.add_volunteer(
        neighbourhood_id=ws.id,
        name="Karthik Volunteer Test",
        contact="9876543210",
        emergency_contact="9123456789",
        skills="First aid",
        preferred_area="Potheri Railway Road",
    )
    assert vol.id is not None
    assert vol.masked_contact == "******3210"
    assert "9876543210" not in vol.masked_contact

    redacted_row = vol.to_export_row(include_private_contacts=False)
    assert redacted_row["contact"] == "[REDACTED - PROTECTED]"
    assert redacted_row["emergency_contact"] == "[REDACTED - PROTECTED]"

    csv_path = tmp_path / "volunteers_redacted.csv"
    export_volunteers_report(db, ws, csv_path, fmt="csv", authorize_private_contacts=False)
    text = csv_path.read_text(encoding="utf-8")
    assert "9876543210" not in text
    assert "9123456789" not in text
    assert "[REDACTED - PROTECTED]" in text

    op = op_mgr.create_operation(ws.id, "Water Distribution Test", "Food distribution")
    assert op.id is not None
    assigned = vmgr.assign_to_operation(vol.id, op.id)
    assert assigned.availability == "Assigned"
    assert assigned.assigned_operation_id == op.id


def test_inventory_stock_movements_zero_negative_and_transactions(tmp_path: Path) -> None:
    db, _, ws = _init_workspace(tmp_path)
    assert ws.id is not None
    tx_svc = InventoryTransactionService(db)
    inv_mgr = InventoryManager(db, tx_svc)

    with pytest.raises(ValidationError):
        inv_mgr.register_item(ws.id, "Water Bottles", "Food and water", -5, "litres")

    item = inv_mgr.register_item(
        neighbourhood_id=ws.id,
        item_name="Drinking Water Cans (Synthetic)",
        category="Food and water",
        quantity=100,
        unit="litres",
        minimum_stock=30,
        storage_location="Depot A",
    )
    assert item.id is not None
    assert item.verification_status == "Registered (Unverified)"

    item = inv_mgr.add_stock(item.id, 50, operator="Tester", reason="Replenished")
    assert item.quantity == pytest.approx(150.0)

    item = inv_mgr.deduct_stock(item.id, 130, operator="Tester", reason="Dispatch")
    assert item.quantity == pytest.approx(20.0)
    assert item.is_low_stock is True

    with pytest.raises(ValidationError):
        inv_mgr.deduct_stock(item.id, 25, operator="Tester", reason="Overdraw")

    assert inv_mgr.get_item(item.id).quantity == pytest.approx(20.0)  # type: ignore[union-attr]

    src_after, dst_after = inv_mgr.transfer_stock(
        item.id, amount=10, destination_storage="Depot B", operator="Tester"
    )
    assert src_after.quantity == pytest.approx(10.0)
    assert dst_after.quantity == pytest.approx(10.0)
    assert dst_after.storage_location == "Depot B"

    txs = tx_svc.list_transactions(ws.id, item_id=item.id)
    types = [t.transaction_type for t in txs]
    assert "Stock received" in types
    assert "Stock issued" in types
    assert "Stock transferred" in types


def test_alerts_low_stock_expiry_and_reconciliation(tmp_path: Path) -> None:
    db, _, ws = _init_workspace(tmp_path)
    assert ws.id is not None
    inv_mgr = InventoryManager(db)
    sh_mgr = ShelterManager(db)
    vmgr = VehicleManager(db)
    alert_mgr = AlertManager(db)

    today = date(2026, 11, 12)
    expired_str = (today - timedelta(days=2)).isoformat()
    near_str = (today + timedelta(days=5)).isoformat()

    low_item = inv_mgr.register_item(
        ws.id, "First Aid Kits", "Medical", 2, "kits", minimum_stock=10, expiry_date=expired_str
    )
    near_item = inv_mgr.register_item(
        ws.id, "Packaged Meals", "Food and water", 50, "packets", minimum_stock=10, expiry_date=near_str
    )
    sh_mgr.register_shelter(ws.id, "Full Shelter Test", "Addr", 12.823, 80.044, total_capacity=40, occupied_capacity=40)
    vmgr.register_vehicle(ws.id, "TN-MAINT-1", "Ambulance", 2, operational_status="Under maintenance")

    alerts = alert_mgr.reconcile_alerts(ws.id, reference_date=today)
    alert_types = {a.alert_type for a in alerts}
    assert "Low inventory" in alert_types
    assert "Expired supply" in alert_types
    assert "Near-expiry supply" in alert_types
    assert "Shelter full" in alert_types
    assert "Vehicle unavailable" in alert_types

    # Acknowledge one alert and ensure reconciliation preserves ack while removing resolved ones
    target_alert = next(a for a in alerts if a.alert_type == "Low inventory")
    assert target_alert.id is not None
    alert_mgr.acknowledge_alert(target_alert.id, acknowledged=True)

    inv_mgr.add_stock(low_item.id, 30, reason="Replenished above min")  # type: ignore[arg-type]
    # Note near_item stays; low_item expired remains; inv_low resolved
    alerts_after = alert_mgr.reconcile_alerts(ws.id, reference_date=today)
    assert all(a.alert_key != f"inv_low_{low_item.id}" for a in alerts_after)
    assert any(a.alert_key == f"inv_nearexp_{near_item.id}" for a in alerts_after)


def test_atomic_resource_allocation_and_rollback_safety(tmp_path: Path) -> None:
    db, _, ws = _init_workspace(tmp_path)
    assert ws.id is not None
    inv_mgr = InventoryManager(db)
    sh_mgr = ShelterManager(db)
    tmgr = RescueTeamManager(db)
    vmgr = VehicleManager(db)
    op_mgr = OperationManager(db)
    alloc_mgr = ResourceAllocator(db)

    active_sh = sh_mgr.register_shelter(ws.id, "Active Shelter", "Loc 1", 12.823, 80.044, 100, 10)
    inactive_sh = sh_mgr.register_shelter(ws.id, "Inactive Shelter", "Loc 2", 12.824, 80.045, 50, 0, status="Inactive")
    item = inv_mgr.register_item(ws.id, "Blankets", "Other supplies", 25, "pcs", minimum_stock=5)
    team = tmgr.register_team(ws.id, "Relief Team 1")
    veh = vmgr.register_vehicle(ws.id, "TN-VAN-99", "Van", 6)
    op = op_mgr.create_operation(ws.id, "Blanket Drop", "Shelter supply delivery")
    assert all(x.id is not None for x in (active_sh, inactive_sh, item, team, veh, op))

    # Blocked allocation to inactive shelter
    with pytest.raises(ValidationError):
        alloc_mgr.allocate_resource(
            ws.id, "inventory_item", item.id, "shelter", inactive_sh.id, inactive_sh.name, quantity=10  # type: ignore[arg-type]
        )
    assert inv_mgr.get_item(item.id).quantity == pytest.approx(25.0)  # type: ignore[union-attr]

    # Blocked over-allocation
    with pytest.raises(ValidationError):
        alloc_mgr.allocate_resource(
            ws.id, "inventory_item", item.id, "shelter", active_sh.id, active_sh.name, quantity=30  # type: ignore[arg-type]
        )
    assert inv_mgr.get_item(item.id).quantity == pytest.approx(25.0)  # type: ignore[union-attr]

    # Valid inventory allocation
    a_inv = alloc_mgr.allocate_resource(
        ws.id,
        "inventory_item",
        item.id,  # type: ignore[arg-type]
        "shelter",
        active_sh.id,
        active_sh.name,
        quantity=10,
        operation_id=op.id,
        operator="Tester",
    )
    assert a_inv.id is not None
    assert inv_mgr.get_item(item.id).quantity == pytest.approx(15.0)  # type: ignore[union-attr]

    # Valid vehicle & team allocation
    a_veh = alloc_mgr.allocate_resource(
        ws.id, "vehicle", veh.id, "rescue_team", team.id, team.team_name, operation_id=op.id  # type: ignore[arg-type]
    )
    a_team = alloc_mgr.allocate_resource(
        ws.id, "rescue_team", team.id, "shelter", active_sh.id, active_sh.name, operation_id=op.id  # type: ignore[arg-type]
    )
    assert vmgr.get_vehicle(veh.id).operational_status == "Assigned"  # type: ignore[union-attr]
    assert tmgr.get_team(team.id).availability == "Assigned"  # type: ignore[union-attr]

    # Cancelling allocation restores inventory stock and releases vehicle & team
    alloc_mgr.update_allocation_status(a_inv.id, "Cancelled", operator="Tester")
    assert inv_mgr.get_item(item.id).quantity == pytest.approx(25.0)  # type: ignore[union-attr]

    alloc_mgr.update_allocation_status(a_veh.id, "Returned", operator="Tester")  # type: ignore[arg-type]
    alloc_mgr.update_allocation_status(a_team.id, "Returned", operator="Tester")  # type: ignore[arg-type]
    assert vmgr.get_vehicle(veh.id).operational_status == "Available"  # type: ignore[union-attr]
    assert tmgr.get_team(team.id).availability == "Available"  # type: ignore[union-attr]


def test_saferoute_integration_and_all_10_csv_pdf_reports(tmp_path: Path) -> None:
    db, repo, ws = _init_workspace(tmp_path)
    assert ws.id is not None

    # Synthetic 2-segment OSM road network
    roads = [
        OSMFeature(
            id=1,
            neighbourhood_id=ws.id,
            osm_id=1001,
            element_type="way",
            category="road",
            subcategory="primary",
            name="Potheri Main Test Rd",
            geometry={"type": "LineString", "coordinates": [[80.0410, 12.8230], [80.0460, 12.8230]]},
            tags={"highway": "primary", "name": "Potheri Main Test Rd"},
            road_category="Primary Road",
        )
    ]
    repo.replace_osm_features(ws.id, roads)
    cells = repo.get_grid_cells(ws.id)
    net = build_road_network_from_osm(ws.id, repo.get_osm_features(ws.id), cells)

    sh_mgr = ShelterManager(db)
    sh = sh_mgr.register_shelter(
        ws.id,
        "SRM Test Hall Shelter",
        "Potheri Campus Rd",
        12.8231,
        80.0459,
        total_capacity=200,
        occupied_capacity=40,
        facilities=["Drinking water", "Medical support"],
        is_verified=True,
    )
    dests = extract_evacuation_destinations(net, repo.get_osm_features(ws.id), shelters=[sh])
    assert any(d.shelter_id == sh.id and d.available_capacity == 160 for d in dests)

    sh_dest = next(d for d in dests if d.shelter_id == sh.id)
    node_ids = sorted(net.nodes_by_id.keys())
    res = calculate_evacuation_routes(
        network=net,
        start_node_id=node_ids[0],
        dest_node_id=sh_dest.nearest_node_id,  # type: ignore[arg-type]
        origin_label="Origin",
        destination_label=sh_dest.label,
        exposures={},
        manual_statuses={},
        speed_config=TravelSpeedConfig(mode="Walking"),
        weights=RouteCostWeights(),
    )
    assert res.shortest is not None

    # Seed sample operational rows and verify all 10 CSV + 10 PDF exports
    tmgr = RescueTeamManager(db)
    vmgr = VehicleManager(db)
    vol_mgr = VolunteerManager(db)
    inv_mgr = InventoryManager(db)
    op_mgr = OperationManager(db)
    alloc_mgr = ResourceAllocator(db)

    t1 = tmgr.register_team(ws.id, "Alpha Rescue")
    v1 = vmgr.register_vehicle(ws.id, "TN-01-TEST", "Van", 6)
    vol_mgr.add_volunteer(ws.id, "Volunteer One", contact="9000011111", emergency_contact="9000022222")
    it1 = inv_mgr.register_item(ws.id, "Water Bottles", "Food and water", 40, "litres", minimum_stock=50)
    op1 = op_mgr.create_operation(ws.id, "Supply Run", "Shelter supply delivery", destination_shelter_id=sh.id)
    alloc_mgr.allocate_resource(ws.id, "inventory_item", it1.id, "shelter", sh.id, sh.name, 10, operation_id=op1.id)  # type: ignore[arg-type]

    for slug, _title, fn in REPORT_REGISTRY:
        csv_p = tmp_path / f"{slug}.csv"
        pdf_p = tmp_path / f"{slug}.pdf"
        fn(db, ws, csv_p, fmt="csv")
        fn(db, ws, pdf_p, fmt="pdf")
        assert csv_p.exists() and csv_p.stat().st_size > 100
        assert pdf_p.exists() and pdf_p.read_bytes().startswith(b"%PDF")
        csv_txt = csv_p.read_text(encoding="utf-8")
        assert "CHENNAI FLOODGUARD" in csv_txt
        assert "Physically Verified" in csv_txt

    # Overview stats reflect real SQLite rows cleanly
    stats = op_mgr.get_dashboard_overview(ws.id)
    assert stats.total_shelters == 1
    assert stats.occupied_shelter_capacity == 40
    assert stats.available_shelter_capacity == 160
    assert stats.total_teams == 1 and stats.available_teams == 1
    assert stats.total_vehicles == 1 and stats.available_vehicles == 1
    assert stats.total_volunteers == 1
    assert stats.low_stock_items == 1  # 30 <= 50

    # Verify v4 -> v5 migration cleanly adds all Phase 6 tables to a legacy DB
    v4_db_path = tmp_path / "legacy_v4.db"
    conn = sqlite3.connect(v4_db_path)
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);")
    conn.execute("CREATE TABLE neighbourhoods (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE);")
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (4, '2026-11-01T00:00:00Z');")
    conn.commit()
    conn.close()

    migrated = DatabaseManager(v4_db_path)
    migrated.initialize()
    ok, msg = migrated.verify_integrity()
    assert ok and "v5" in msg


def test_emergency_dashboard_gui_smoke(tmp_path: Path) -> None:
    import tkinter as tk
    from gui.emergency_dashboard import EmergencyDashboardView

    db, _, ws = _init_workspace(tmp_path)
    assert ws.id is not None
    ShelterManager(db).register_shelter(ws.id, "Smoke Test Shelter", "Potheri", 12.823, 80.044, 80, 15)
    VolunteerManager(db).add_volunteer(ws.id, "Smoke Volunteer", contact="9876543210")

    root = tk.Tk()
    root.withdraw()
    try:
        view = EmergencyDashboardView(root, db_manager=db)
        view.pack(fill="both", expand=True)
        view.set_neighbourhood(ws)
        root.update_idletasks()
        assert len(view.notebook.tabs()) == 10
        assert view._overview.total_shelters == 1
        assert view._overview.available_shelter_capacity == 65
        # Volunteer contact masked in Treeview display
        vol_item_ids = view.volunteers_tab.tree.get_children()
        assert len(vol_item_ids) == 1
        vals = view.volunteers_tab.tree.item(vol_item_ids[0], "values")
        assert "9876543210" not in str(vals)
        assert "******3210" in str(vals)
    finally:
        root.destroy()
