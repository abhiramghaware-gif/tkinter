"""Rule-driven emergency alert evaluation from real SQLite operational state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from config import ALERT_SEVERITIES, NEAR_EXPIRY_WARNING_DAYS
from core.validation import ValidationError
from database.db import DatabaseManager


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


_SEVERITY_RANK = {
    "Critical": 0,
    "High": 1,
    "Warning": 2,
    "Info": 3,
}


@dataclass(slots=True)
class EmergencyAlertRecord:
    """SQLite-persisted alert generated strictly from database resource conditions."""

    id: int | None
    neighbourhood_id: int
    alert_key: str
    alert_type: str
    severity: str
    title: str
    description: str
    related_resource: str = ""
    acknowledged: bool = False
    acknowledged_at: str = ""
    created_at: str = ""


class AlertManager:
    """Evaluates database state to trigger, deduplicate, and acknowledge emergency alerts."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    def reconcile_alerts(
        self,
        neighbourhood_id: int,
        near_expiry_days: int = NEAR_EXPIRY_WARNING_DAYS,
        reference_date: date | None = None,
    ) -> list[EmergencyAlertRecord]:
        """Recompute condition-driven alerts from live SQLite tables (never fake incidents)."""
        ref_date = reference_date or datetime.now(timezone.utc).date()
        now = _now_iso()
        candidates: list[tuple[str, str, str, str, str, str]] = []

        with self.db.connect() as conn:
            inv_rows = conn.execute(
                "SELECT * FROM inventory_items WHERE neighbourhood_id = ? ORDER BY id ASC",
                (neighbourhood_id,),
            ).fetchall()
            for r in inv_rows:
                iid = int(r["id"])
                name = str(r["item_name"])
                qty = float(r["quantity"])
                min_stk = float(r["minimum_stock"])
                unit = str(r["unit"])
                loc = str(r["storage_location"])
                exp_str = str(r["expiry_date"] or "").strip()

                if qty <= 0.0:
                    candidates.append(
                        (
                            f"inv_zero_{iid}",
                            "Inventory depleted",
                            "Critical",
                            f"Out of stock: {name}",
                            f"{name} at '{loc}' has 0 {unit} remaining (minimum target {min_stk:g} {unit}).",
                            f"inventory_item:{iid}",
                        )
                    )
                elif qty <= min_stk:
                    sev = "High" if (min_stk > 0 and qty <= min_stk * 0.5) else "Warning"
                    candidates.append(
                        (
                            f"inv_low_{iid}",
                            "Low inventory",
                            sev,
                            f"Low stock: {name}",
                            f"{name} at '{loc}' has {qty:g} {unit} <= minimum {min_stk:g} {unit}.",
                            f"inventory_item:{iid}",
                        )
                    )

                if exp_str:
                    try:
                        exp_d = date.fromisoformat(exp_str)
                        delta = (exp_d - ref_date).days
                        if delta < 0:
                            candidates.append(
                                (
                                    f"inv_expired_{iid}",
                                    "Expired supply",
                                    "Critical",
                                    f"Expired item: {name}",
                                    f"{name} ({qty:g} {unit} at '{loc}') expired on {exp_str}. Do not issue without inspection.",
                                    f"inventory_item:{iid}",
                                )
                            )
                        elif delta <= near_expiry_days:
                            candidates.append(
                                (
                                    f"inv_nearexp_{iid}",
                                    "Near-expiry supply",
                                    "Warning",
                                    f"Near expiry ({delta}d): {name}",
                                    f"{name} ({qty:g} {unit} at '{loc}') expires on {exp_str} ({delta} day(s) remaining).",
                                    f"inventory_item:{iid}",
                                )
                            )
                    except ValueError:
                        pass

            shelter_rows = conn.execute(
                "SELECT * FROM shelters WHERE neighbourhood_id = ? ORDER BY id ASC",
                (neighbourhood_id,),
            ).fetchall()
            for r in shelter_rows:
                sid = int(r["id"])
                sname = str(r["name"])
                tot = int(r["total_capacity"])
                occ = int(r["occupied_capacity"])
                avail = max(0, tot - occ)
                status = str(r["status"])
                if status in ("Inactive", "Closed"):
                    continue
                if status == "Full" or (tot > 0 and occ >= tot):
                    candidates.append(
                        (
                            f"shelter_full_{sid}",
                            "Shelter full",
                            "High",
                            f"Shelter full: {sname}",
                            f"Shelter '{sname}' has 0 available spaces ({occ}/{tot} occupied).",
                            f"shelter:{sid}",
                        )
                    )
                elif tot > 0 and (avail <= max(5, int(0.1 * tot)) or (occ / tot) >= 0.9):
                    candidates.append(
                        (
                            f"shelter_lowcap_{sid}",
                            "Shelter low capacity",
                            "Warning",
                            f"Low shelter capacity: {sname}",
                            f"Shelter '{sname}' has only {avail} spaces left ({occ}/{tot} occupied).",
                            f"shelter:{sid}",
                        )
                    )

            veh_rows = conn.execute(
                "SELECT * FROM vehicles WHERE neighbourhood_id = ? ORDER BY id ASC",
                (neighbourhood_id,),
            ).fetchall()
            for r in veh_rows:
                vid = int(r["id"])
                reg = str(r["registration_number"])
                vtype = str(r["vehicle_type"])
                st = str(r["operational_status"])
                if st in ("Under maintenance", "Unavailable"):
                    candidates.append(
                        (
                            f"veh_unavail_{vid}",
                            "Vehicle unavailable",
                            "Warning",
                            f"Vehicle {st.lower()}: {reg}",
                            f"{vtype} '{reg}' is marked '{st}' and cannot be allocated.",
                            f"vehicle:{vid}",
                        )
                    )

            team_rows = conn.execute(
                "SELECT * FROM rescue_teams WHERE neighbourhood_id = ? ORDER BY id ASC",
                (neighbourhood_id,),
            ).fetchall()
            for r in team_rows:
                tid = int(r["id"])
                tname = str(r["team_name"])
                avail_st = str(r["availability"])
                if avail_st in ("Unavailable", "Off duty"):
                    candidates.append(
                        (
                            f"team_unavail_{tid}",
                            "Team unavailable",
                            "Info",
                            f"Rescue team {avail_st.lower()}: {tname}",
                            f"Rescue team '{tname}' is currently '{avail_st}'.",
                            f"rescue_team:{tid}",
                        )
                    )

            alloc_rows = conn.execute(
                "SELECT * FROM resource_allocations WHERE neighbourhood_id = ? ORDER BY id ASC",
                (neighbourhood_id,),
            ).fetchall()
            for r in alloc_rows:
                aid = int(r["id"])
                st = str(r["status"])
                dest = str(r["destination_label"])
                op_id = r["operation_id"]
                if st == "Allocated" and op_id is None:
                    candidates.append(
                        (
                            f"alloc_incomplete_{aid}",
                            "Incomplete allocation",
                            "Warning",
                            f"Unlinked allocation #{aid} ({dest})",
                            (
                                f"Allocation #{aid} ({r['resource_type']} #{r['resource_id']} -> {dest}) "
                                f"is still 'Allocated' without a linked emergency operation or delivery confirmation."
                            ),
                            f"allocation:{aid}",
                        )
                    )

        active_keys = {c[0] for c in candidates}
        with self.db.transaction() as conn:
            existing_rows = conn.execute(
                "SELECT id, alert_key FROM emergency_alerts WHERE neighbourhood_id = ?",
                (neighbourhood_id,),
            ).fetchall()
            existing_map = {str(r["alert_key"]): int(r["id"]) for r in existing_rows}

            for stale_key, stale_id in existing_map.items():
                if stale_key not in active_keys:
                    conn.execute("DELETE FROM emergency_alerts WHERE id = ?", (stale_id,))

            for akey, atype, sev, title, desc, rel in candidates:
                if akey in existing_map:
                    conn.execute(
                        """
                        UPDATE emergency_alerts
                        SET alert_type = ?, severity = ?, title = ?, description = ?, related_resource = ?
                        WHERE id = ?
                        """,
                        (atype, sev, title, desc, rel, existing_map[akey]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO emergency_alerts (
                            neighbourhood_id, alert_key, alert_type, severity,
                            title, description, related_resource,
                            acknowledged, acknowledged_at, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, '', ?)
                        """,
                        (neighbourhood_id, akey, atype, sev, title, desc, rel, now),
                    )

        return self.list_alerts(neighbourhood_id, include_acknowledged=True)

    def list_alerts(
        self,
        neighbourhood_id: int,
        include_acknowledged: bool = True,
        severity_filter: str = "All",
    ) -> list[EmergencyAlertRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM emergency_alerts WHERE neighbourhood_id = ? ORDER BY acknowledged ASC, id DESC",
                (neighbourhood_id,),
            ).fetchall()
        records = [
            EmergencyAlertRecord(
                id=int(r["id"]),
                neighbourhood_id=int(r["neighbourhood_id"]),
                alert_key=str(r["alert_key"]),
                alert_type=str(r["alert_type"]),
                severity=str(r["severity"]),
                title=str(r["title"]),
                description=str(r["description"]),
                related_resource=str(r["related_resource"]),
                acknowledged=bool(int(r["acknowledged"])),
                acknowledged_at=str(r["acknowledged_at"]),
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]
        if not include_acknowledged:
            records = [a for a in records if not a.acknowledged]
        if severity_filter and severity_filter != "All":
            records = [a for a in records if a.severity == severity_filter]
        records.sort(key=lambda a: (a.acknowledged, _SEVERITY_RANK.get(a.severity, 9), -(a.id or 0)))
        return records

    def acknowledge_alert(self, alert_id: int, acknowledged: bool = True) -> EmergencyAlertRecord:
        now = _now_iso() if acknowledged else ""
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM emergency_alerts WHERE id = ?", (alert_id,)).fetchone()
            if row is None:
                raise ValidationError(f"Alert #{alert_id} not found.")
            conn.execute(
                "UPDATE emergency_alerts SET acknowledged = ?, acknowledged_at = ? WHERE id = ?",
                (1 if acknowledged else 0, now, alert_id),
            )
            updated = conn.execute("SELECT * FROM emergency_alerts WHERE id = ?", (alert_id,)).fetchone()
        assert updated is not None
        return EmergencyAlertRecord(
            id=int(updated["id"]),
            neighbourhood_id=int(updated["neighbourhood_id"]),
            alert_key=str(updated["alert_key"]),
            alert_type=str(updated["alert_type"]),
            severity=str(updated["severity"]),
            title=str(updated["title"]),
            description=str(updated["description"]),
            related_resource=str(updated["related_resource"]),
            acknowledged=bool(int(updated["acknowledged"])),
            acknowledged_at=str(updated["acknowledged_at"]),
            created_at=str(updated["created_at"]),
        )

    def acknowledge_all(self, neighbourhood_id: int) -> int:
        now = _now_iso()
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                UPDATE emergency_alerts
                SET acknowledged = 1, acknowledged_at = ?
                WHERE neighbourhood_id = ? AND acknowledged = 0
                """,
                (now, neighbourhood_id),
            )
            return int(cur.rowcount)


__all__ = ["AlertManager", "EmergencyAlertRecord"]
