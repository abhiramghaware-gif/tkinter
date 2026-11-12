"""Emergency operations workflow and SQLite-backed dashboard statistics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from config import NEAR_EXPIRY_WARNING_DAYS, OPERATION_PRIORITIES, OPERATION_STATUS_OPTIONS, OPERATION_TYPES
from core.validation import ValidationError
from database.db import DatabaseManager


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class EmergencyOperationRecord:
    """Manual relief/rescue operation record tracking teams, vehicles, and status transitions."""

    id: int | None
    neighbourhood_id: int
    operation_name: str
    operation_type: str
    priority: str = "Medium"
    start_location: str = ""
    destination: str = ""
    destination_shelter_id: int | None = None
    assigned_team_id: int | None = None
    assigned_team_name: str = ""
    assigned_vehicle_id: int | None = None
    assigned_vehicle_label: str = ""
    status: str = "Planned"
    start_time: str = ""
    completion_time: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(slots=True)
class DashboardOverviewStats:
    """Strictly database-derived summary counts for Emergency Management Overview."""

    total_shelters: int = 0
    active_shelters: int = 0
    full_shelters: int = 0
    total_shelter_capacity: int = 0
    occupied_shelter_capacity: int = 0
    available_shelter_capacity: int = 0
    available_teams: int = 0
    active_teams: int = 0
    total_teams: int = 0
    available_vehicles: int = 0
    total_vehicles: int = 0
    total_volunteers: int = 0
    available_volunteers: int = 0
    total_inventory_items: int = 0
    low_stock_items: int = 0
    expiring_or_expired_items: int = 0
    active_operations: int = 0
    unacknowledged_alerts: int = 0
    inventory_by_category: dict[str, int] = field(default_factory=dict)
    recent_activity: list[str] = field(default_factory=list)


class OperationManager:
    """Service layer managing emergency operations and database-backed dashboard summaries."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    def create_operation(
        self,
        neighbourhood_id: int,
        operation_name: str,
        operation_type: str,
        priority: str = "Medium",
        start_location: str = "",
        destination: str = "",
        destination_shelter_id: int | None = None,
        assigned_team_id: int | None = None,
        assigned_vehicle_id: int | None = None,
        status: str = "Planned",
        notes: str = "",
    ) -> EmergencyOperationRecord:
        cname = str(operation_name or "").strip()
        if not cname:
            raise ValidationError("Operation name cannot be empty.")
        otype = str(operation_type or "").strip()
        if otype not in OPERATION_TYPES:
            raise ValidationError(f"Invalid operation type '{otype}'.")
        prio = str(priority or "Medium").strip()
        if prio not in OPERATION_PRIORITIES:
            raise ValidationError(f"Invalid operation priority '{prio}'.")
        st = str(status or "Planned").strip()
        if st not in OPERATION_STATUS_OPTIONS:
            raise ValidationError(f"Invalid operation status '{st}'.")
        now = _now_iso()
        s_time = now if st == "In progress" else ""
        c_time = now if st == "Completed" else ""

        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO emergency_operations (
                    neighbourhood_id, operation_name, operation_type, priority,
                    start_location, destination, destination_shelter_id,
                    assigned_team_id, assigned_vehicle_id, status,
                    start_time, completion_time, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    neighbourhood_id,
                    cname,
                    otype,
                    prio,
                    str(start_location or "").strip(),
                    str(destination or "").strip(),
                    destination_shelter_id,
                    assigned_team_id,
                    assigned_vehicle_id,
                    st,
                    s_time,
                    c_time,
                    str(notes or "").strip(),
                    now,
                    now,
                ),
            )
            oid = int(cur.lastrowid)
        rec = self.get_operation(oid)
        assert rec is not None
        return rec

    def update_operation_status(
        self,
        operation_id: int,
        new_status: str,
        notes: str = "",
    ) -> EmergencyOperationRecord:
        existing = self.get_operation(operation_id)
        if existing is None:
            raise ValidationError(f"Operation #{operation_id} not found.")
        st = str(new_status or "").strip()
        if st not in OPERATION_STATUS_OPTIONS:
            raise ValidationError(f"Invalid operation status '{st}'.")
        now = _now_iso()
        s_time = existing.start_time or (now if st in ("In progress", "Completed") else "")
        c_time = now if st == "Completed" else existing.completion_time
        merged_notes = existing.notes
        if notes.strip():
            merged_notes = f"{existing.notes}\n[{st} @ {now}] {notes.strip()}".strip()

        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE emergency_operations
                SET status = ?, start_time = ?, completion_time = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (st, s_time, c_time, merged_notes, now, operation_id),
            )
        rec = self.get_operation(operation_id)
        assert rec is not None
        return rec

    def delete_operation(self, operation_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM emergency_operations WHERE id = ?", (operation_id,))

    def get_operation(self, operation_id: int) -> EmergencyOperationRecord | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT eo.*,
                       COALESCE(rt.team_name, '') AS team_name,
                       COALESCE(v.registration_number || ' (' || v.vehicle_type || ')', '') AS veh_label
                FROM emergency_operations eo
                LEFT JOIN rescue_teams rt ON rt.id = eo.assigned_team_id
                LEFT JOIN vehicles v ON v.id = eo.assigned_vehicle_id
                WHERE eo.id = ?
                """,
                (operation_id,),
            ).fetchone()
            return self._row_to_record(row) if row else None

    def list_operations(
        self,
        neighbourhood_id: int,
        status_filter: str = "All",
    ) -> list[EmergencyOperationRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT eo.*,
                       COALESCE(rt.team_name, '') AS team_name,
                       COALESCE(v.registration_number || ' (' || v.vehicle_type || ')', '') AS veh_label
                FROM emergency_operations eo
                LEFT JOIN rescue_teams rt ON rt.id = eo.assigned_team_id
                LEFT JOIN vehicles v ON v.id = eo.assigned_vehicle_id
                WHERE eo.neighbourhood_id = ?
                ORDER BY eo.id DESC
                """,
                (neighbourhood_id,),
            ).fetchall()
        records = [self._row_to_record(r) for r in rows]
        if status_filter and status_filter != "All":
            return [r for r in records if r.status == status_filter]
        return records

    def get_dashboard_overview(self, neighbourhood_id: int) -> DashboardOverviewStats:
        stats = DashboardOverviewStats()
        today = datetime.now(timezone.utc).date()

        with self.db.connect() as conn:
            # Shelters
            sh_rows = conn.execute(
                "SELECT total_capacity, occupied_capacity, status FROM shelters WHERE neighbourhood_id = ?",
                (neighbourhood_id,),
            ).fetchall()
            stats.total_shelters = len(sh_rows)
            for r in sh_rows:
                tot = int(r["total_capacity"])
                occ = int(r["occupied_capacity"])
                stats.total_shelter_capacity += tot
                stats.occupied_shelter_capacity += occ
                if r["status"] in ("Active", "Full"):
                    stats.active_shelters += 1
                if tot > 0 and occ >= tot:
                    stats.full_shelters += 1
            stats.available_shelter_capacity = max(
                0, stats.total_shelter_capacity - stats.occupied_shelter_capacity
            )

            # Rescue teams
            t_rows = conn.execute(
                "SELECT availability FROM rescue_teams WHERE neighbourhood_id = ?",
                (neighbourhood_id,),
            ).fetchall()
            stats.total_teams = len(t_rows)
            for r in t_rows:
                av = str(r["availability"])
                if av == "Available":
                    stats.available_teams += 1
                elif av in ("Assigned", "On operation"):
                    stats.active_teams += 1

            # Vehicles
            v_rows = conn.execute(
                "SELECT operational_status FROM vehicles WHERE neighbourhood_id = ?",
                (neighbourhood_id,),
            ).fetchall()
            stats.total_vehicles = len(v_rows)
            stats.available_vehicles = sum(
                1 for r in v_rows if r["operational_status"] == "Available"
            )

            # Volunteers
            vol_rows = conn.execute(
                "SELECT availability FROM volunteers WHERE neighbourhood_id = ?",
                (neighbourhood_id,),
            ).fetchall()
            stats.total_volunteers = len(vol_rows)
            stats.available_volunteers = sum(
                1 for r in vol_rows if r["availability"] == "Available"
            )

            # Inventory
            inv_rows = conn.execute(
                "SELECT category, quantity, minimum_stock, expiry_date FROM inventory_items WHERE neighbourhood_id = ?",
                (neighbourhood_id,),
            ).fetchall()
            stats.total_inventory_items = len(inv_rows)
            for r in inv_rows:
                cat = str(r["category"])
                stats.inventory_by_category[cat] = stats.inventory_by_category.get(cat, 0) + 1
                if float(r["quantity"]) <= float(r["minimum_stock"]):
                    stats.low_stock_items += 1
                ed = str(r["expiry_date"] or "").strip()
                if ed:
                    try:
                        days_left = (date.fromisoformat(ed) - today).days
                        if days_left <= NEAR_EXPIRY_WARNING_DAYS:
                            stats.expiring_or_expired_items += 1
                    except ValueError:
                        pass

            # Operations
            op_rows = conn.execute(
                "SELECT id, operation_name, status, updated_at FROM emergency_operations WHERE neighbourhood_id = ? ORDER BY id DESC",
                (neighbourhood_id,),
            ).fetchall()
            stats.active_operations = sum(
                1 for r in op_rows if r["status"] in ("Planned", "Ready", "In progress")
            )

            # Unacknowledged alerts
            al_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM emergency_alerts WHERE neighbourhood_id = ? AND acknowledged = 0",
                (neighbourhood_id,),
            ).fetchone()
            stats.unacknowledged_alerts = int(al_row["cnt"]) if al_row else 0

            # Recent chronological activity feed (SQLite only)
            activity: list[tuple[str, str]] = []
            for r in op_rows[:6]:
                activity.append(
                    (
                        str(r["updated_at"]),
                        f"[Operation] {r['operation_name']} — {r['status']}",
                    )
                )
            tx_rows = conn.execute(
                """
                SELECT t.transaction_type, t.quantity, t.destination_location, t.created_at,
                       COALESCE(i.item_name, 'Item') AS item_name, COALESCE(i.unit, '') AS unit
                FROM inventory_transactions t
                LEFT JOIN inventory_items i ON i.id = t.item_id
                WHERE t.neighbourhood_id = ?
                ORDER BY t.id DESC LIMIT 6
                """,
                (neighbourhood_id,),
            ).fetchall()
            for r in tx_rows:
                activity.append(
                    (
                        str(r["created_at"]),
                        f"[{r['transaction_type']}] {r['item_name']}: {float(r['quantity']):g} {r['unit']} -> {r['destination_location']}",
                    )
                )
            alloc_rows = conn.execute(
                "SELECT resource_type, destination_label, status, updated_at FROM resource_allocations WHERE neighbourhood_id = ? ORDER BY id DESC LIMIT 6",
                (neighbourhood_id,),
            ).fetchall()
            for r in alloc_rows:
                activity.append(
                    (
                        str(r["updated_at"]),
                        f"[Allocation] {r['resource_type']} -> {r['destination_label']} ({r['status']})",
                    )
                )

            activity.sort(key=lambda pair: pair[0], reverse=True)
            stats.recent_activity = [f"{ts}  |  {msg}" for ts, msg in activity[:12]]

        return stats

    @staticmethod
    def _row_to_record(row) -> EmergencyOperationRecord:
        return EmergencyOperationRecord(
            id=int(row["id"]),
            neighbourhood_id=int(row["neighbourhood_id"]),
            operation_name=str(row["operation_name"]),
            operation_type=str(row["operation_type"]),
            priority=str(row["priority"]),
            start_location=str(row["start_location"]),
            destination=str(row["destination"]),
            destination_shelter_id=(
                int(row["destination_shelter_id"]) if row["destination_shelter_id"] is not None else None
            ),
            assigned_team_id=(
                int(row["assigned_team_id"]) if row["assigned_team_id"] is not None else None
            ),
            assigned_team_name=str(row["team_name"]),
            assigned_vehicle_id=(
                int(row["assigned_vehicle_id"]) if row["assigned_vehicle_id"] is not None else None
            ),
            assigned_vehicle_label=str(row["veh_label"]),
            status=str(row["status"]),
            start_time=str(row["start_time"]),
            completion_time=str(row["completion_time"]),
            notes=str(row["notes"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
