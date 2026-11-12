"""Emergency relief inventory stock management with zero-negative-stock enforcement."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timezone

from config import (
    INVENTORY_CATEGORIES,
    INVENTORY_VERIFICATION_STATUSES,
    NEAR_EXPIRY_WARNING_DAYS,
)
from core.validation import ValidationError
from database.db import DatabaseManager
from emergency.inventory_transactions import InventoryTransactionService


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_non_negative_float(value: object, field_name: str, allow_zero: bool = True) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{field_name} must be numeric.")
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be a valid number.") from exc
    if not math.isfinite(num):
        raise ValidationError(f"{field_name} must be finite.")
    if allow_zero and num < 0.0:
        raise ValidationError(f"{field_name} cannot be negative (got {num}).")
    if (not allow_zero) and num <= 0.0:
        raise ValidationError(f"{field_name} must be strictly greater than zero (got {num}).")
    return num


def _validate_expiry_date(date_text: str) -> str:
    cleaned = str(date_text or "").strip()
    if not cleaned:
        return ""
    try:
        date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValidationError(
            f"Expiry date '{cleaned}' must be in ISO YYYY-MM-DD format (or blank if not applicable)."
        ) from exc
    return cleaned


@dataclass(slots=True)
class InventoryItemRecord:
    """Registered relief inventory item distinguishing registered vs physically verified counts."""

    id: int | None
    neighbourhood_id: int
    item_name: str
    category: str
    quantity: float
    unit: str
    minimum_stock: float
    storage_location: str = ""
    expiry_date: str = ""
    supplier: str = ""
    verification_status: str = "Registered (Unverified)"
    last_verified_at: str = ""
    notes: str = ""
    updated_at: str = ""

    @property
    def is_low_stock(self) -> bool:
        return float(self.quantity) <= float(self.minimum_stock)

    def expiry_status(self, reference_date: date | None = None, near_days: int = NEAR_EXPIRY_WARNING_DAYS) -> str:
        if not self.expiry_date:
            return "N/A"
        try:
            exp = date.fromisoformat(self.expiry_date)
        except ValueError:
            return "Invalid date"
        ref = reference_date or datetime.now(timezone.utc).date()
        delta = (exp - ref).days
        if delta < 0:
            return "Expired"
        if delta <= near_days:
            return f"Near expiry ({delta}d)"
        return "Valid"


class InventoryManager:
    """Service layer enforcing non-negative stock and synchronized SQLite audit transactions."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        tx_service: InventoryTransactionService | None = None,
    ) -> None:
        self.db = db_manager
        self.tx_service = tx_service or InventoryTransactionService(db_manager)

    def register_item(
        self,
        neighbourhood_id: int,
        item_name: str,
        category: str,
        quantity: object,
        unit: str,
        minimum_stock: object = 0.0,
        storage_location: str = "",
        expiry_date: str = "",
        supplier: str = "",
        verification_status: str = "Registered (Unverified)",
        operator: str = "Operator",
        notes: str = "",
    ) -> InventoryItemRecord:
        cname = str(item_name or "").strip()
        if not cname:
            raise ValidationError("Inventory item name cannot be empty.")
        ccat = str(category or "").strip()
        if ccat not in INVENTORY_CATEGORIES:
            raise ValidationError(f"Unsupported inventory category '{ccat}'.")
        cunit = str(unit or "").strip()
        if not cunit:
            raise ValidationError("Inventory unit cannot be empty (e.g. 'litres', 'packets', 'kits').")
        qty = _parse_non_negative_float(quantity, "Quantity", allow_zero=True)
        min_stk = _parse_non_negative_float(minimum_stock, "Minimum stock level", allow_zero=True)
        exp_clean = _validate_expiry_date(expiry_date)
        ver = str(verification_status or "Registered (Unverified)").strip()
        if ver not in INVENTORY_VERIFICATION_STATUSES:
            raise ValidationError(f"Invalid verification status '{ver}'.")
        loc = str(storage_location or "").strip() or "Primary Store"
        now = _now_iso()
        verified_ts = now if ver == "Physically Verified" else ""

        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO inventory_items (
                    neighbourhood_id, item_name, category, quantity, unit,
                    minimum_stock, storage_location, expiry_date, supplier,
                    verification_status, last_verified_at, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    neighbourhood_id,
                    cname,
                    ccat,
                    qty,
                    cunit,
                    min_stk,
                    loc,
                    exp_clean,
                    str(supplier or "").strip(),
                    ver,
                    verified_ts,
                    str(notes or "").strip(),
                    now,
                ),
            )
            iid = int(cur.lastrowid)
            if qty > 0.0:
                self.tx_service.insert_transaction_conn(
                    conn=conn,
                    neighbourhood_id=neighbourhood_id,
                    item_id=iid,
                    transaction_type="Stock received",
                    quantity=qty,
                    source_location=str(supplier or "").strip() or "Initial registration",
                    destination_location=loc,
                    operator=operator,
                    reason="Initial item stock entry",
                    created_at=now,
                )
        rec = self.get_item(iid)
        assert rec is not None
        return rec

    def update_item_metadata(
        self,
        item_id: int,
        item_name: str,
        category: str,
        unit: str,
        minimum_stock: object,
        storage_location: str = "",
        expiry_date: str = "",
        supplier: str = "",
        verification_status: str = "Registered (Unverified)",
        notes: str = "",
    ) -> InventoryItemRecord:
        existing = self.get_item(item_id)
        if existing is None:
            raise ValidationError(f"Inventory item #{item_id} not found.")
        cname = str(item_name or "").strip()
        if not cname:
            raise ValidationError("Inventory item name cannot be empty.")
        ccat = str(category or "").strip()
        if ccat not in INVENTORY_CATEGORIES:
            raise ValidationError(f"Unsupported inventory category '{ccat}'.")
        cunit = str(unit or "").strip()
        if not cunit:
            raise ValidationError("Inventory unit cannot be empty.")
        min_stk = _parse_non_negative_float(minimum_stock, "Minimum stock level", allow_zero=True)
        exp_clean = _validate_expiry_date(expiry_date)
        ver = str(verification_status or "Registered (Unverified)").strip()
        if ver not in INVENTORY_VERIFICATION_STATUSES:
            raise ValidationError(f"Invalid verification status '{ver}'.")
        now = _now_iso()
        verified_ts = now if ver == "Physically Verified" else existing.last_verified_at

        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE inventory_items
                SET item_name = ?, category = ?, unit = ?, minimum_stock = ?,
                    storage_location = ?, expiry_date = ?, supplier = ?,
                    verification_status = ?, last_verified_at = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    cname,
                    ccat,
                    cunit,
                    min_stk,
                    str(storage_location or "").strip() or existing.storage_location,
                    exp_clean,
                    str(supplier or "").strip(),
                    ver,
                    verified_ts,
                    str(notes or "").strip(),
                    now,
                    item_id,
                ),
            )
        rec = self.get_item(item_id)
        assert rec is not None
        return rec

    def add_stock(
        self,
        item_id: int,
        amount: object,
        operator: str = "Operator",
        reason: str = "Replenishment",
        source_location: str = "",
        transaction_type: str = "Stock received",
        related_operation_id: int | None = None,
    ) -> InventoryItemRecord:
        delta = _parse_non_negative_float(amount, "Addition quantity", allow_zero=False)
        if transaction_type not in ("Stock received", "Stock returned"):
            raise ValidationError(f"Invalid addition transaction type '{transaction_type}'.")
        now = _now_iso()
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise ValidationError(f"Inventory item #{item_id} not found.")
            new_qty = float(row["quantity"]) + delta
            conn.execute(
                "UPDATE inventory_items SET quantity = ?, updated_at = ? WHERE id = ?",
                (new_qty, now, item_id),
            )
            self.tx_service.insert_transaction_conn(
                conn=conn,
                neighbourhood_id=int(row["neighbourhood_id"]),
                item_id=item_id,
                transaction_type=transaction_type,
                quantity=delta,
                source_location=source_location or str(row["supplier"] or "External supply"),
                destination_location=str(row["storage_location"]),
                operator=operator,
                reason=reason,
                related_operation_id=related_operation_id,
                created_at=now,
            )
        rec = self.get_item(item_id)
        assert rec is not None
        return rec

    def deduct_stock(
        self,
        item_id: int,
        amount: object,
        operator: str = "Operator",
        reason: str = "Manual stock issue",
        destination_location: str = "",
        related_operation_id: int | None = None,
    ) -> InventoryItemRecord:
        delta = _parse_non_negative_float(amount, "Issue quantity", allow_zero=False)
        now = _now_iso()
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise ValidationError(f"Inventory item #{item_id} not found.")
            cur_qty = float(row["quantity"])
            if cur_qty < delta:
                raise ValidationError(
                    f"Insufficient stock for '{row['item_name']}': available {cur_qty} {row['unit']}, "
                    f"requested {delta} {row['unit']}. Negative stock is prohibited."
                )
            new_qty = cur_qty - delta
            conn.execute(
                "UPDATE inventory_items SET quantity = ?, updated_at = ? WHERE id = ?",
                (new_qty, now, item_id),
            )
            self.tx_service.insert_transaction_conn(
                conn=conn,
                neighbourhood_id=int(row["neighbourhood_id"]),
                item_id=item_id,
                transaction_type="Stock issued",
                quantity=delta,
                source_location=str(row["storage_location"]),
                destination_location=destination_location or "Field distribution",
                operator=operator,
                reason=reason,
                related_operation_id=related_operation_id,
                created_at=now,
            )
        rec = self.get_item(item_id)
        assert rec is not None
        return rec

    def adjust_stock(
        self,
        item_id: int,
        new_quantity: object,
        operator: str = "Operator",
        reason: str = "Inventory reconciliation",
        verification_status: str | None = None,
    ) -> InventoryItemRecord:
        target = _parse_non_negative_float(new_quantity, "Adjusted stock quantity", allow_zero=True)
        now = _now_iso()
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise ValidationError(f"Inventory item #{item_id} not found.")
            cur_qty = float(row["quantity"])
            diff = abs(target - cur_qty)
            ver = verification_status or str(row["verification_status"])
            if ver not in INVENTORY_VERIFICATION_STATUSES:
                raise ValidationError(f"Invalid verification status '{ver}'.")
            ver_ts = now if ver == "Physically Verified" else str(row["last_verified_at"])
            conn.execute(
                """
                UPDATE inventory_items
                SET quantity = ?, verification_status = ?, last_verified_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (target, ver, ver_ts, now, item_id),
            )
            self.tx_service.insert_transaction_conn(
                conn=conn,
                neighbourhood_id=int(row["neighbourhood_id"]),
                item_id=item_id,
                transaction_type="Stock adjustment",
                quantity=diff,
                source_location=str(row["storage_location"]),
                destination_location=str(row["storage_location"]),
                operator=operator,
                reason=f"{reason} ({cur_qty:g} -> {target:g} {row['unit']})",
                created_at=now,
            )
        rec = self.get_item(item_id)
        assert rec is not None
        return rec

    def transfer_stock(
        self,
        item_id: int,
        amount: object,
        destination_storage: str,
        operator: str = "Operator",
        reason: str = "Inter-store transfer",
        related_operation_id: int | None = None,
    ) -> tuple[InventoryItemRecord, InventoryItemRecord]:
        qty = _parse_non_negative_float(amount, "Transfer quantity", allow_zero=False)
        dest_loc = str(destination_storage or "").strip()
        if not dest_loc:
            raise ValidationError("Destination storage location cannot be empty.")
        now = _now_iso()

        with self.db.transaction() as conn:
            src_row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
            if src_row is None:
                raise ValidationError(f"Inventory item #{item_id} not found.")
            src_loc = str(src_row["storage_location"])
            if src_loc.lower() == dest_loc.lower():
                raise ValidationError("Destination storage location must differ from current storage location.")
            cur_qty = float(src_row["quantity"])
            if cur_qty < qty:
                raise ValidationError(
                    f"Cannot transfer {qty} {src_row['unit']}: only {cur_qty} available at '{src_loc}'."
                )

            # Deduct source row
            conn.execute(
                "UPDATE inventory_items SET quantity = ?, updated_at = ? WHERE id = ?",
                (cur_qty - qty, now, item_id),
            )

            nid = int(src_row["neighbourhood_id"])
            dest_row = conn.execute(
                """
                SELECT * FROM inventory_items
                WHERE neighbourhood_id = ?
                  AND LOWER(item_name) = LOWER(?)
                  AND category = ?
                  AND unit = ?
                  AND LOWER(storage_location) = LOWER(?)
                  AND expiry_date = ?
                """,
                (
                    nid,
                    src_row["item_name"],
                    src_row["category"],
                    src_row["unit"],
                    dest_loc,
                    src_row["expiry_date"],
                ),
            ).fetchone()

            if dest_row is not None:
                dest_id = int(dest_row["id"])
                conn.execute(
                    "UPDATE inventory_items SET quantity = ?, updated_at = ? WHERE id = ?",
                    (float(dest_row["quantity"]) + qty, now, dest_id),
                )
            else:
                cur_dest = conn.execute(
                    """
                    INSERT INTO inventory_items (
                        neighbourhood_id, item_name, category, quantity, unit,
                        minimum_stock, storage_location, expiry_date, supplier,
                        verification_status, last_verified_at, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        nid,
                        src_row["item_name"],
                        src_row["category"],
                        qty,
                        src_row["unit"],
                        float(src_row["minimum_stock"]),
                        dest_loc,
                        src_row["expiry_date"],
                        src_row["supplier"],
                        "Registered (Unverified)",
                        "",
                        f"Transferred from {src_loc}",
                        now,
                    ),
                )
                dest_id = int(cur_dest.lastrowid)

            self.tx_service.insert_transaction_conn(
                conn=conn,
                neighbourhood_id=nid,
                item_id=item_id,
                transaction_type="Stock transferred",
                quantity=qty,
                source_location=src_loc,
                destination_location=dest_loc,
                operator=operator,
                reason=reason,
                related_operation_id=related_operation_id,
                created_at=now,
            )

        src_rec = self.get_item(item_id)
        dest_rec = self.get_item(dest_id)
        assert src_rec is not None and dest_rec is not None
        return src_rec, dest_rec

    def delete_item(self, item_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))

    def get_item(self, item_id: int) -> InventoryItemRecord | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
            return self._row_to_record(row) if row else None

    def list_items(
        self,
        neighbourhood_id: int,
        search: str = "",
        category_filter: str = "All",
        low_stock_only: bool = False,
        expiry_only: bool = False,
        reference_date: date | None = None,
    ) -> list[InventoryItemRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM inventory_items
                WHERE neighbourhood_id = ?
                ORDER BY category ASC, item_name ASC, id ASC
                """,
                (neighbourhood_id,),
            ).fetchall()
        records = [self._row_to_record(r) for r in rows]
        q = search.strip().lower()
        out: list[InventoryItemRecord] = []
        for r in records:
            if category_filter and category_filter != "All" and r.category != category_filter:
                continue
            if low_stock_only and not r.is_low_stock:
                continue
            if expiry_only:
                st = r.expiry_status(reference_date=reference_date)
                if st not in ("Expired",) and not st.startswith("Near expiry"):
                    continue
            if q and (
                q not in r.item_name.lower()
                and q not in r.category.lower()
                and q not in r.storage_location.lower()
                and q not in r.supplier.lower()
            ):
                continue
            out.append(r)
        return out

    @staticmethod
    def _row_to_record(row) -> InventoryItemRecord:
        return InventoryItemRecord(
            id=int(row["id"]),
            neighbourhood_id=int(row["neighbourhood_id"]),
            item_name=str(row["item_name"]),
            category=str(row["category"]),
            quantity=float(row["quantity"]),
            unit=str(row["unit"]),
            minimum_stock=float(row["minimum_stock"]),
            storage_location=str(row["storage_location"]),
            expiry_date=str(row["expiry_date"]),
            supplier=str(row["supplier"]),
            verification_status=str(row["verification_status"]),
            last_verified_at=str(row["last_verified_at"]),
            notes=str(row["notes"]),
            updated_at=str(row["updated_at"]),
        )
