"""Inventory transaction audit log participating inside atomic SQLite transactions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from config import INVENTORY_TRANSACTION_TYPES
from core.validation import ValidationError
from database.db import DatabaseManager


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class InventoryTransactionRecord:
    """Immutable audit entry for an inventory stock movement."""

    id: int | None
    neighbourhood_id: int
    item_id: int
    item_name: str
    category: str
    unit: str
    transaction_type: str
    quantity: float
    source_location: str = ""
    destination_location: str = ""
    operator: str = ""
    reason: str = ""
    related_operation_id: int | None = None
    created_at: str = ""


class InventoryTransactionService:
    """Records and queries synchronized inventory movements."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    @staticmethod
    def insert_transaction_conn(
        conn: sqlite3.Connection,
        neighbourhood_id: int,
        item_id: int,
        transaction_type: str,
        quantity: float,
        source_location: str = "",
        destination_location: str = "",
        operator: str = "",
        reason: str = "",
        related_operation_id: int | None = None,
        created_at: str | None = None,
    ) -> int:
        ttype = str(transaction_type or "").strip()
        if ttype not in INVENTORY_TRANSACTION_TYPES:
            raise ValidationError(f"Unsupported inventory transaction type '{ttype}'.")
        qty = float(quantity)
        if qty < 0.0:
            raise ValidationError("Transaction quantity cannot be negative.")
        ts = created_at or _now_iso()
        cur = conn.execute(
            """
            INSERT INTO inventory_transactions (
                neighbourhood_id, item_id, transaction_type, quantity,
                source_location, destination_location, operator, reason,
                related_operation_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                neighbourhood_id,
                item_id,
                ttype,
                qty,
                str(source_location or "").strip(),
                str(destination_location or "").strip(),
                str(operator or "").strip() or "Operator",
                str(reason or "").strip(),
                related_operation_id,
                ts,
            ),
        )
        return int(cur.lastrowid)

    def list_transactions(
        self,
        neighbourhood_id: int,
        item_id: int | None = None,
        transaction_type: str = "All",
        limit: int = 250,
    ) -> list[InventoryTransactionRecord]:
        sql = """
            SELECT t.*, COALESCE(i.item_name, '(Deleted item)') AS item_name,
                   COALESCE(i.category, '') AS category,
                   COALESCE(i.unit, '') AS unit
            FROM inventory_transactions t
            LEFT JOIN inventory_items i ON i.id = t.item_id
            WHERE t.neighbourhood_id = ?
        """
        params: list[object] = [neighbourhood_id]
        if item_id is not None:
            sql += " AND t.item_id = ?"
            params.append(item_id)
        if transaction_type and transaction_type != "All":
            sql += " AND t.transaction_type = ?"
            params.append(transaction_type)
        sql += " ORDER BY t.id DESC LIMIT ?"
        params.append(int(limit))

        with self.db.connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            InventoryTransactionRecord(
                id=int(r["id"]),
                neighbourhood_id=int(r["neighbourhood_id"]),
                item_id=int(r["item_id"]),
                item_name=str(r["item_name"]),
                category=str(r["category"]),
                unit=str(r["unit"]),
                transaction_type=str(r["transaction_type"]),
                quantity=float(r["quantity"]),
                source_location=str(r["source_location"]),
                destination_location=str(r["destination_location"]),
                operator=str(r["operator"]),
                reason=str(r["reason"]),
                related_operation_id=(
                    int(r["related_operation_id"]) if r["related_operation_id"] is not None else None
                ),
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]
