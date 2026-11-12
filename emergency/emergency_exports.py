"""CSV and PDF operational reporting for all 10 Phase 6 emergency domains."""

from __future__ import annotations

import csv
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

from config import APP_NAME, SCHEMA_VERSION
from core.models import Neighbourhood
from core.validation import ValidationError
from database.db import DatabaseManager
from emergency.inventory_manager import InventoryManager
from emergency.inventory_transactions import InventoryTransactionService
from emergency.operation_manager import OperationManager
from emergency.rescue_team_manager import RescueTeamManager
from emergency.resource_allocator import ResourceAllocator
from emergency.shelter_manager import ShelterManager
from emergency.vehicle_manager import VehicleManager
from emergency.volunteer_manager import VolunteerManager

EMERGENCY_REPORT_ASSUMPTIONS = (
    "Educational emergency decision-support prototype (CHENNAI FLOODGUARD). "
    "Data reflects entries recorded in local SQLite storage and explicitly separates "
    "'Registered (Unverified)' records from 'Physically Verified' field checks. "
    "NOT an official government dispatch record or live emergency agency feed."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _report_metadata(neighbourhood: Neighbourhood, report_title: str, extra: str = "") -> dict[str, str]:
    return {
        "project_name": APP_NAME,
        "report_title": report_title,
        "neighbourhood": neighbourhood.name,
        "generated_utc": _now_iso(),
        "data_source": f"SQLite Local Database (Schema v{SCHEMA_VERSION}, Neighbourhood ID={neighbourhood.id})",
        "verification_note": "Registered (Unverified) entries must not be assumed physically inspected unless marked Physically Verified / Verified Shelter.",
        "assumptions_and_limitations": f"{EMERGENCY_REPORT_ASSUMPTIONS} {extra}".strip(),
    }


def _write_csv_report(
    output_path: Path | str,
    meta: dict[str, str],
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        for k, v in meta.items():
            fh.write(f"# {k}: {v}\n")
        writer = csv.writer(fh)
        writer.writerow(list(headers))
        for row in rows:
            writer.writerow(list(row))
    return path


def _write_pdf_report(
    output_path: Path | str,
    meta: dict[str, str],
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows_per_page = 16
    row_chunks = [list(rows[i : i + rows_per_page]) for i in range(0, len(rows), rows_per_page)]
    if not row_chunks:
        row_chunks = [[]]

    with PdfPages(str(path)) as pdf:
        for page_idx, chunk in enumerate(row_chunks, start=1):
            fig = Figure(figsize=(11.0, 8.5), dpi=120)
            fig.patch.set_facecolor("#FFFFFF")
            ax = fig.add_axes([0.04, 0.06, 0.92, 0.88])
            ax.axis("off")

            ax.text(
                0.0,
                0.98,
                f"{meta['project_name']} — {meta['report_title']}",
                fontsize=14,
                fontweight="bold",
                color="#0F172A",
                va="top",
            )
            meta_lines = (
                f"Neighbourhood: {meta['neighbourhood']}   |   Generated (UTC): {meta['generated_utc']}   |   "
                f"Page {page_idx}/{len(row_chunks)}\n"
                f"Source: {meta['data_source']}\n"
                f"Verification Distinction: {meta['verification_note']}\n"
                + "\n".join(textwrap.wrap(f"Disclaimer & Assumptions: {meta['assumptions_and_limitations']}", width=128))
            )
            ax.text(0.0, 0.925, meta_lines, fontsize=8, color="#334155", va="top", linespacing=1.35)

            if not chunk:
                ax.text(
                    0.5,
                    0.5,
                    "No records stored in SQLite for this report at time of export.",
                    ha="center",
                    va="center",
                    fontsize=11,
                    color="#64748B",
                )
            else:
                formatted_rows = []
                for r in chunk:
                    formatted_rows.append(
                        [textwrap.fill(str(val if val is not None else ""), width=24) for val in r]
                    )
                table = ax.table(
                    cellText=formatted_rows,
                    colLabels=[str(h) for h in headers],
                    loc="upper center",
                    bbox=[0.0, 0.02, 1.0, 0.72],
                    cellLoc="left",
                )
                table.auto_set_font_size(False)
                table.set_fontsize(7.5)
                for (r_i, c_i), cell in table.get_celld().items():
                    cell.set_edgecolor("#CBD5E1")
                    if r_i == 0:
                        cell.set_facecolor("#0F172A")
                        cell.set_text_props(color="#F8FAFC", fontweight="bold")
                    elif r_i % 2 == 1:
                        cell.set_facecolor("#F8FAFC")
                    else:
                        cell.set_facecolor("#FFFFFF")

            pdf.savefig(fig, dpi=120)
    return path


def _export_by_format(
    output_path: Path | str,
    fmt: str,
    meta: dict[str, str],
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> Path:
    fmt_clean = str(fmt or "csv").strip().lower()
    if fmt_clean == "csv":
        return _write_csv_report(output_path, meta, headers, rows)
    if fmt_clean == "pdf":
        return _write_pdf_report(output_path, meta, headers, rows)
    raise ValidationError(f"Unsupported report format '{fmt}'. Expected 'csv' or 'pdf'.")


def _require_nid(neighbourhood: Neighbourhood) -> int:
    if neighbourhood.id is None:
        raise ValidationError("Active neighbourhood must be saved in SQLite before exporting reports.")
    return neighbourhood.id


# =============================================================================
# 10 Required Emergency Reports (§15)
# =============================================================================

def export_shelter_directory_report(
    db: DatabaseManager,
    neighbourhood: Neighbourhood,
    output_path: Path | str,
    fmt: str = "csv",
) -> Path:
    nid = _require_nid(neighbourhood)
    shelters = ShelterManager(db).list_shelters(nid)
    meta = _report_metadata(neighbourhood, "Shelter Directory Report")
    headers = (
        "ID", "Shelter Name", "Address", "Latitude", "Longitude",
        "Status", "Verification Status", "Source", "Facilities", "Accessibility", "Contact Info",
    )
    rows = [
        (
            s.id, s.name, s.address, f"{s.latitude:.6f}", f"{s.longitude:.6f}",
            s.status, s.verification_label, s.source, s.facilities_summary,
            s.accessibility, s.contact_info,
        )
        for s in shelters
    ]
    return _export_by_format(output_path, fmt, meta, headers, rows)


def export_shelter_occupancy_report(
    db: DatabaseManager,
    neighbourhood: Neighbourhood,
    output_path: Path | str,
    fmt: str = "csv",
) -> Path:
    nid = _require_nid(neighbourhood)
    shelters = ShelterManager(db).list_shelters(nid)
    meta = _report_metadata(neighbourhood, "Shelter Occupancy & Capacity Summary")
    headers = (
        "ID", "Shelter Name", "Status", "Verification",
        "Total Capacity", "Occupied Capacity", "Available Capacity", "Occupancy %", "Updated UTC",
    )
    rows = [
        (
            s.id, s.name, s.status, s.verification_label,
            s.total_capacity, s.occupied_capacity, s.available_capacity,
            f"{s.occupancy_pct:.1f}%", s.updated_at,
        )
        for s in shelters
    ]
    return _export_by_format(output_path, fmt, meta, headers, rows)


def export_rescue_teams_report(
    db: DatabaseManager,
    neighbourhood: Neighbourhood,
    output_path: Path | str,
    fmt: str = "csv",
) -> Path:
    nid = _require_nid(neighbourhood)
    teams = RescueTeamManager(db).list_teams(nid)
    meta = _report_metadata(neighbourhood, "Rescue Team Assignments Report")
    headers = (
        "ID", "Team Name", "Leader", "Member Count", "Members",
        "Skills", "Equipment", "Current Location", "Availability", "Current Assignment",
    )
    rows = [
        (
            t.id, t.team_name, t.leader, t.member_count, t.members_summary,
            t.skills, t.equipment, t.current_location, t.availability,
            t.current_assignment or "None",
        )
        for t in teams
    ]
    return _export_by_format(output_path, fmt, meta, headers, rows)


def export_vehicles_report(
    db: DatabaseManager,
    neighbourhood: Neighbourhood,
    output_path: Path | str,
    fmt: str = "csv",
) -> Path:
    nid = _require_nid(neighbourhood)
    vehicles = VehicleManager(db).list_vehicles(nid)
    meta = _report_metadata(neighbourhood, "Rescue Vehicle Status Report")
    headers = (
        "ID", "Registration", "Type", "Capacity", "Fuel Status",
        "Operational Status", "Assigned Team", "Location", "Updated UTC",
    )
    rows = [
        (
            v.id, v.registration_number, v.vehicle_type, v.capacity, v.fuel_status,
            v.operational_status, v.assigned_team_name or "Unassigned", v.location, v.updated_at,
        )
        for v in vehicles
    ]
    return _export_by_format(output_path, fmt, meta, headers, rows)


def export_volunteers_report(
    db: DatabaseManager,
    neighbourhood: Neighbourhood,
    output_path: Path | str,
    fmt: str = "csv",
    authorize_private_contacts: bool = False,
) -> Path:
    """Export registered volunteers; raw personal phone numbers are REDACTED unless explicitly authorized."""
    nid = _require_nid(neighbourhood)
    volunteers = VolunteerManager(db).list_volunteers(nid)
    privacy_note = (
        "Operator explicitly authorized inclusion of private volunteer phone contacts."
        if authorize_private_contacts
        else "Volunteer phone & emergency contacts REDACTED by default privacy policy."
    )
    meta = _report_metadata(neighbourhood, "Volunteer Availability Report", extra=privacy_note)
    headers = (
        "ID", "Name", "Contact", "Emergency Contact",
        "Skills", "Availability", "Preferred Area", "Assigned Operation",
    )
    rows = []
    for v in volunteers:
        row_d = v.to_export_row(include_private_contacts=authorize_private_contacts)
        rows.append(
            (
                row_d["volunteer_id"],
                row_d["name"],
                row_d["contact"],
                row_d["emergency_contact"],
                row_d["skills"],
                row_d["availability"],
                row_d["preferred_area"],
                row_d["assigned_operation"],
            )
        )
    return _export_by_format(output_path, fmt, meta, headers, rows)


def export_inventory_report(
    db: DatabaseManager,
    neighbourhood: Neighbourhood,
    output_path: Path | str,
    fmt: str = "csv",
) -> Path:
    nid = _require_nid(neighbourhood)
    items = InventoryManager(db).list_items(nid)
    meta = _report_metadata(neighbourhood, "Emergency Inventory Stock Summary")
    headers = (
        "ID", "Item Name", "Category", "Quantity", "Unit", "Minimum Stock",
        "Storage Location", "Expiry Date", "Expiry Status", "Verification Status", "Updated UTC",
    )
    rows = [
        (
            i.id, i.item_name, i.category, f"{i.quantity:g}", i.unit, f"{i.minimum_stock:g}",
            i.storage_location, i.expiry_date or "N/A", i.expiry_status(),
            i.verification_status, i.updated_at,
        )
        for i in items
    ]
    return _export_by_format(output_path, fmt, meta, headers, rows)


def export_low_stock_report(
    db: DatabaseManager,
    neighbourhood: Neighbourhood,
    output_path: Path | str,
    fmt: str = "csv",
) -> Path:
    nid = _require_nid(neighbourhood)
    items = [
        i for i in InventoryManager(db).list_items(nid)
        if i.is_low_stock or i.expiry_status() != "Valid" and i.expiry_status() != "N/A"
    ]
    meta = _report_metadata(neighbourhood, "Low-Stock & Expiry Alert Report")
    headers = (
        "ID", "Item Name", "Category", "Quantity", "Min Stock", "Unit",
        "Low Stock?", "Expiry Status", "Verification Status", "Storage Location",
    )
    rows = [
        (
            i.id, i.item_name, i.category, f"{i.quantity:g}", f"{i.minimum_stock:g}", i.unit,
            "YES" if i.is_low_stock else "NO", i.expiry_status(),
            i.verification_status, i.storage_location,
        )
        for i in items
    ]
    return _export_by_format(output_path, fmt, meta, headers, rows)


def export_inventory_transactions_report(
    db: DatabaseManager,
    neighbourhood: Neighbourhood,
    output_path: Path | str,
    fmt: str = "csv",
) -> Path:
    nid = _require_nid(neighbourhood)
    txs = InventoryTransactionService(db).list_transactions(nid, limit=500)
    meta = _report_metadata(neighbourhood, "Inventory Transaction History Report")
    headers = (
        "Tx ID", "Timestamp UTC", "Item Name", "Category", "Type",
        "Quantity", "Unit", "From", "To", "Operator", "Reason",
    )
    rows = [
        (
            t.id, t.created_at, t.item_name, t.category, t.transaction_type,
            f"{t.quantity:g}", t.unit, t.source_location, t.destination_location,
            t.operator, t.reason,
        )
        for t in txs
    ]
    return _export_by_format(output_path, fmt, meta, headers, rows)


def export_resource_allocations_report(
    db: DatabaseManager,
    neighbourhood: Neighbourhood,
    output_path: Path | str,
    fmt: str = "csv",
) -> Path:
    nid = _require_nid(neighbourhood)
    allocs = ResourceAllocator(db).list_allocations(nid)
    meta = _report_metadata(neighbourhood, "Resource Allocation Report")
    headers = (
        "ID", "Resource Type", "Resource", "Quantity", "Destination Type",
        "Destination", "Operation", "Status", "Operator", "Reason", "Created UTC",
    )
    rows = [
        (
            a.id, a.resource_type, a.resource_label, f"{a.quantity:g}",
            a.destination_type, a.destination_label, a.operation_name or "None",
            a.status, a.operator, a.reason, a.created_at,
        )
        for a in allocs
    ]
    return _export_by_format(output_path, fmt, meta, headers, rows)


def export_operations_report(
    db: DatabaseManager,
    neighbourhood: Neighbourhood,
    output_path: Path | str,
    fmt: str = "csv",
) -> Path:
    nid = _require_nid(neighbourhood)
    ops = OperationManager(db).list_operations(nid)
    meta = _report_metadata(neighbourhood, "Emergency Operations Summary Report")
    headers = (
        "ID", "Operation Name", "Type", "Priority", "Start Location",
        "Destination", "Assigned Team", "Assigned Vehicle", "Status", "Started UTC", "Completed UTC",
    )
    rows = [
        (
            o.id, o.operation_name, o.operation_type, o.priority, o.start_location,
            o.destination, o.assigned_team_name or "Unassigned",
            o.assigned_vehicle_label or "Unassigned", o.status,
            o.start_time or "—", o.completion_time or "—",
        )
        for o in ops
    ]
    return _export_by_format(output_path, fmt, meta, headers, rows)


REPORT_REGISTRY = (
    ("shelter_directory", "Shelter Directory Report", export_shelter_directory_report),
    ("shelter_occupancy", "Shelter Occupancy & Capacity Summary", export_shelter_occupancy_report),
    ("rescue_teams", "Rescue Team Assignments Report", export_rescue_teams_report),
    ("vehicles", "Rescue Vehicle Status Report", export_vehicles_report),
    ("volunteers", "Volunteer Availability Report (Privacy Redacted)", export_volunteers_report),
    ("inventory", "Emergency Inventory Summary", export_inventory_report),
    ("low_stock", "Low-Stock & Expiry Alert Report", export_low_stock_report),
    ("transactions", "Inventory Transaction History Report", export_inventory_transactions_report),
    ("allocations", "Resource Allocation Report", export_resource_allocations_report),
    ("operations", "Emergency Operations Summary", export_operations_report),
)

__all__ = [
    "EMERGENCY_REPORT_ASSUMPTIONS",
    "REPORT_REGISTRY",
    "export_shelter_directory_report",
    "export_shelter_occupancy_report",
    "export_rescue_teams_report",
    "export_vehicles_report",
    "export_volunteers_report",
    "export_inventory_report",
    "export_low_stock_report",
    "export_inventory_transactions_report",
    "export_resource_allocations_report",
    "export_operations_report",
]
