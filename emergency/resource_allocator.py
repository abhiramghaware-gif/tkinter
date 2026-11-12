"""Atomic emergency resource allocation across inventory, shelters, teams, vehicles & volunteers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from config import ALLOCATION_RESOURCE_TYPES, ALLOCATION_STATUS_OPTIONS
from core.validation import ValidationError
from database.db import DatabaseManager
from emergency.inventory_transactions import InventoryTransactionService


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class ResourceAllocationRecord:
    """Manual allocation record linking resources to shelters, rescue teams, or operations."""

    id: int | None
    neighbourhood_id: int
    resource_type: str
    resource_id: int
    resource_label: str
    destination_type: str
    destination_id: int | None
    destination_label: str
    quantity: float
    operation_id: int | None = None
    operation_name: str = ""
    status: str = "Allocated"
    reason: str = ""
    operator: str = ""
    created_at: str = ""
    updated_at: str = ""


class ResourceAllocator:
    """Performs validated, atomic manual resource allocations via SQLite transactions."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        tx_service: InventoryTransactionService | None = None,
    ) -> None:
        self.db = db_manager
        self.tx_service = tx_service or InventoryTransactionService(db_manager)

    def allocate_resource(
        self,
        neighbourhood_id: int,
        resource_type: str,
        resource_id: int,
        destination_type: str,
        destination_id: int | None,
        destination_label: str,
        quantity: object = 1.0,
        operation_id: int | None = None,
        reason: str = "",
        operator: str = "Operator",
    ) -> ResourceAllocationRecord:
        rtype = str(resource_type or "").strip()
        if rtype not in ALLOCATION_RESOURCE_TYPES:
            raise ValidationError(f"Unsupported allocation resource type '{rtype}'.")

        dest_lbl = str(destination_label or "").strip()
        if not dest_lbl:
            raise ValidationError("Allocation destination description cannot be empty.")

        if isinstance(quantity, bool):
            raise ValidationError("Allocation quantity must be numeric.")
        try:
            qty = float(quantity)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValidationError("Allocation quantity must be a valid number.") from exc
        if not math.isfinite(qty) or qty <= 0.0:
            raise ValidationError("Allocation quantity must be > 0.")

        now = _now_iso()
        with self.db.transaction() as conn:
            # Optional operation validation
            if operation_id is not None:
                op_row = conn.execute(
                    "SELECT id, operation_name, status FROM emergency_operations WHERE id = ?",
                    (operation_id,),
                ).fetchone()
                if op_row is None:
                    raise ValidationError(f"Emergency operation #{operation_id} not found.")
                if op_row["status"] in ("Completed", "Cancelled"):
                    raise ValidationError(
                        f"Cannot allocate resources to '{op_row['status']}' operation '{op_row['operation_name']}'."
                    )

            # Optional shelter destination check (when destination_type == 'shelter')
            if destination_type == "shelter" and destination_id is not None:
                sh_row = conn.execute(
                    "SELECT id, name, status, total_capacity, occupied_capacity FROM shelters WHERE id = ?",
                    (destination_id,),
                ).fetchone()
                if sh_row is None:
                    raise ValidationError(f"Destination shelter #{destination_id} not found.")
                if sh_row["status"] in ("Inactive", "Closed"):
                    raise ValidationError(
                        f"Shelter '{sh_row['name']}' is '{sh_row['status']}' and cannot receive allocations."
                    )

            # Resource-specific validation & atomic state update
            if rtype == "inventory_item":
                item_row = conn.execute(
                    "SELECT * FROM inventory_items WHERE id = ?", (resource_id,)
                ).fetchone()
                if item_row is None:
                    raise ValidationError(f"Inventory item #{resource_id} not found.")
                cur_qty = float(item_row["quantity"])
                if cur_qty < qty:
                    raise ValidationError(
                        f"Insufficient inventory for '{item_row['item_name']}': "
                        f"available {cur_qty} {item_row['unit']}, requested {qty} {item_row['unit']}."
                    )
                conn.execute(
                    "UPDATE inventory_items SET quantity = ?, updated_at = ? WHERE id = ?",
                    (cur_qty - qty, now, resource_id),
                )
                self.tx_service.insert_transaction_conn(
                    conn=conn,
                    neighbourhood_id=neighbourhood_id,
                    item_id=resource_id,
                    transaction_type="Stock issued",
                    quantity=qty,
                    source_location=str(item_row["storage_location"]),
                    destination_location=dest_lbl,
                    operator=operator,
                    reason=reason or f"Allocated to {dest_lbl}",
                    related_operation_id=operation_id,
                    created_at=now,
                )

            elif rtype == "vehicle":
                qty = 1.0
                veh_row = conn.execute(
                    "SELECT * FROM vehicles WHERE id = ?", (resource_id,)
                ).fetchone()
                if veh_row is None:
                    raise ValidationError(f"Vehicle #{resource_id} not found.")
                if veh_row["operational_status"] != "Available":
                    raise ValidationError(
                        f"Vehicle '{veh_row['registration_number']}' is currently '{veh_row['operational_status']}'."
                    )
                team_id_val = destination_id if destination_type == "rescue_team" else veh_row["assigned_team_id"]
                if destination_type == "rescue_team" and destination_id is not None:
                    trow = conn.execute("SELECT id FROM rescue_teams WHERE id = ?", (destination_id,)).fetchone()
                    if trow is None:
                        raise ValidationError(f"Target rescue team #{destination_id} not found.")
                conn.execute(
                    """
                    UPDATE vehicles
                    SET operational_status = 'Assigned', assigned_team_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (team_id_val, now, resource_id),
                )

            elif rtype == "rescue_team":
                qty = 1.0
                trow = conn.execute(
                    "SELECT * FROM rescue_teams WHERE id = ?", (resource_id,)
                ).fetchone()
                if trow is None:
                    raise ValidationError(f"Rescue team #{resource_id} not found.")
                if trow["availability"] != "Available":
                    raise ValidationError(
                        f"Rescue team '{trow['team_name']}' is currently '{trow['availability']}'."
                    )
                conn.execute(
                    """
                    UPDATE rescue_teams
                    SET availability = 'Assigned', current_assignment = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (dest_lbl, now, resource_id),
                )

            elif rtype == "volunteer":
                qty = 1.0
                vrow = conn.execute(
                    "SELECT * FROM volunteers WHERE id = ?", (resource_id,)
                ).fetchone()
                if vrow is None:
                    raise ValidationError(f"Volunteer #{resource_id} not found.")
                if vrow["availability"] != "Available":
                    raise ValidationError(
                        f"Volunteer '{vrow['name']}' is currently '{vrow['availability']}'."
                    )
                conn.execute(
                    """
                    UPDATE volunteers
                    SET availability = 'Assigned', assigned_operation_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (operation_id, now, resource_id),
                )

            cur = conn.execute(
                """
                INSERT INTO resource_allocations (
                    neighbourhood_id, resource_type, resource_id, destination_type,
                    destination_id, destination_label, quantity, operation_id,
                    status, reason, operator, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Allocated', ?, ?, ?, ?)
                """,
                (
                    neighbourhood_id,
                    rtype,
                    resource_id,
                    str(destination_type or "").strip(),
                    destination_id,
                    dest_lbl,
                    qty,
                    operation_id,
                    str(reason or "").strip(),
                    str(operator or "").strip() or "Operator",
                    now,
                    now,
                ),
            )
            alloc_id = int(cur.lastrowid)

        rec = self.get_allocation(alloc_id)
        assert rec is not None
        return rec

    def update_allocation_status(
        self,
        allocation_id: int,
        new_status: str,
        operator: str = "Operator",
        notes: str = "",
    ) -> ResourceAllocationRecord:
        st = str(new_status or "").strip()
        if st not in ALLOCATION_STATUS_OPTIONS:
            raise ValidationError(f"Invalid allocation status '{st}'.")
        now = _now_iso()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM resource_allocations WHERE id = ?", (allocation_id,)
            ).fetchone()
            if row is None:
                raise ValidationError(f"Allocation #{allocation_id} not found.")
            prev_st = str(row["status"])
            if prev_st == st:
                rec = self.get_allocation(allocation_id)
                assert rec is not None
                return rec

            rtype = str(row["resource_type"])
            rid = int(row["resource_id"])
            qty = float(row["quantity"])

            if rtype == "vehicle":
                if st == "Dispatched":
                    conn.execute(
                        "UPDATE vehicles SET operational_status = 'In use', updated_at = ? WHERE id = ?",
                        (now, rid),
                    )
                elif st in ("Returned", "Cancelled"):
                    conn.execute(
                        """
                        UPDATE vehicles
                        SET operational_status = 'Available', assigned_team_id = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (now, rid),
                    )
            elif rtype == "rescue_team":
                if st == "Dispatched":
                    conn.execute(
                        "UPDATE rescue_teams SET availability = 'On operation', updated_at = ? WHERE id = ?",
                        (now, rid),
                    )
                elif st in ("Returned", "Cancelled", "Delivered"):
                    conn.execute(
                        """
                        UPDATE rescue_teams
                        SET availability = 'Available', current_assignment = '', updated_at = ?
                        WHERE id = ?
                        """,
                        (now, rid),
                    )
            elif rtype == "volunteer" and st in ("Returned", "Cancelled"):
                conn.execute(
                    """
                    UPDATE volunteers
                    SET availability = 'Available', assigned_operation_id = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, rid),
                )
            elif rtype == "inventory_item" and st in ("Returned", "Cancelled") and prev_st in ("Allocated", "Dispatched"):
                item_row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (rid,)).fetchone()
                if item_row is not None:
                    conn.execute(
                        "UPDATE inventory_items SET quantity = ?, updated_at = ? WHERE id = ?",
                        (float(item_row["quantity"]) + qty, now, rid),
                    )
                    self.tx_service.insert_transaction_conn(
                        conn=conn,
                        neighbourhood_id=int(row["neighbourhood_id"]),
                        item_id=rid,
                        transaction_type="Stock returned",
                        quantity=qty,
                        source_location=str(row["destination_label"]),
                        destination_location=str(item_row["storage_location"]),
                        operator=operator,
                        reason=notes or f"Allocation #{allocation_id} marked {st}",
                        related_operation_id=row["operation_id"],
                        created_at=now,
                    )

            conn.execute(
                "UPDATE resource_allocations SET status = ?, updated_at = ? WHERE id = ?",
                (st, now, allocation_id),
            )
        rec = self.get_allocation(allocation_id)
        assert rec is not None
        return rec

    def get_allocation(self, allocation_id: int) -> ResourceAllocationRecord | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM resource_allocations WHERE id = ?", (allocation_id,)
            ).fetchone()
            if row is None:
                return None
            return self._hydrate_row(conn, row)

    def list_allocations(
        self,
        neighbourhood_id: int,
        status_filter: str = "All",
    ) -> list[ResourceAllocationRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM resource_allocations
                WHERE neighbourhood_id = ?
                ORDER BY id DESC
                """,
                (neighbourhood_id,),
            ).fetchall()
            out: list[ResourceAllocationRecord] = []
            for r in rows:
                if status_filter and status_filter != "All" and r["status"] != status_filter:
                    continue
                out.append(self._hydrate_row(conn, r))
            return out

    @staticmethod
    def _hydrate_row(conn, row) -> ResourceAllocationRecord:
        rtype = str(row["resource_type"])
        rid = int(row["resource_id"])
        res_label = f"{rtype} #{rid}"
        if rtype == "inventory_item":
            ir = conn.execute("SELECT item_name, unit FROM inventory_items WHERE id = ?", (rid,)).fetchone()
            if ir:
                res_label = f"{ir['item_name']} ({ir['unit']})"
        elif rtype == "vehicle":
            vr = conn.execute(
                "SELECT registration_number, vehicle_type FROM vehicles WHERE id = ?", (rid,)
            ).fetchone()
            if vr:
                res_label = f"{vr['registration_number']} ({vr['vehicle_type']})"
        elif rtype == "rescue_team":
            tr = conn.execute("SELECT team_name FROM rescue_teams WHERE id = ?", (rid,)).fetchone()
            if tr:
                res_label = str(tr["team_name"])
        elif rtype == "volunteer":
            volr = conn.execute("SELECT name FROM volunteers WHERE id = ?", (rid,)).fetchone()
            if volr:
                res_label = f"Volunteer: {volr['name']}"

        op_id = int(row["operation_id"]) if row["operation_id"] is not None else None
        op_name = ""
        if op_id is not None:
            opr = conn.execute(
                "SELECT operation_name FROM emergency_operations WHERE id = ?", (op_id,)
            ).fetchone()
            if opr:
                op_name = str(opr["operation_name"])

        return ResourceAllocationRecord(
            id=int(row["id"]),
            neighbourhood_id=int(row["neighbourhood_id"]),
            resource_type=rtype,
            resource_id=rid,
            resource_label=res_label,
            destination_type=str(row["destination_type"]),
            destination_id=int(row["destination_id"]) if row["destination_id"] is not None else None,
            destination_label=str(row["destination_label"]),
            quantity=float(row["quantity"]),
            operation_id=op_id,
            operation_name=op_name,
            status=str(row["status"]),
            reason=str(row["reason"]),
            operator=str(row["operator"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
