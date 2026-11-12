"""Rescue vehicle inventory, maintenance status, and manual team assignment."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from config import VEHICLE_STATUS_OPTIONS, VEHICLE_TYPE_OPTIONS
from core.validation import ValidationError
from database.db import DatabaseManager


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class VehicleRecord:
    """Registered rescue vehicle record."""

    id: int | None
    neighbourhood_id: int
    registration_number: str
    vehicle_type: str
    capacity: int = 0
    fuel_status: str = "Unknown"
    operational_status: str = "Available"
    assigned_team_id: int | None = None
    assigned_team_name: str = ""
    location: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


class VehicleManager:
    """Service layer for managing rescue vehicles and manual team assignments."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    @staticmethod
    def _validate(
        reg_number: str,
        vehicle_type: str,
        capacity: object,
        operational_status: str,
    ) -> tuple[str, str, int, str]:
        creg = str(reg_number or "").strip()
        if not creg:
            raise ValidationError("Vehicle registration/identifier number cannot be empty.")
        vtype = str(vehicle_type or "").strip()
        if vtype not in VEHICLE_TYPE_OPTIONS:
            raise ValidationError(f"Invalid vehicle type '{vtype}'.")
        if isinstance(capacity, bool):
            raise ValidationError("Vehicle capacity must be an integer.")
        try:
            cap = int(capacity)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValidationError("Vehicle capacity must be a valid integer.") from exc
        if cap < 0:
            raise ValidationError("Vehicle capacity cannot be negative.")
        st = str(operational_status or "Available").strip()
        if st not in VEHICLE_STATUS_OPTIONS:
            raise ValidationError(f"Invalid vehicle operational status '{st}'.")
        return creg, vtype, cap, st

    def register_vehicle(
        self,
        neighbourhood_id: int,
        registration_number: str,
        vehicle_type: str,
        capacity: object = 0,
        fuel_status: str = "Unknown",
        operational_status: str = "Available",
        assigned_team_id: int | None = None,
        location: str = "",
        notes: str = "",
    ) -> VehicleRecord:
        creg, vtype, cap, st = self._validate(registration_number, vehicle_type, capacity, operational_status)
        if assigned_team_id is not None and st == "Available":
            st = "Assigned"
        now = _now_iso()
        try:
            with self.db.transaction() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO vehicles (
                        neighbourhood_id, registration_number, vehicle_type, capacity,
                        fuel_status, operational_status, assigned_team_id, location, notes,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        neighbourhood_id,
                        creg,
                        vtype,
                        cap,
                        str(fuel_status or "Unknown").strip(),
                        st,
                        assigned_team_id,
                        str(location or "").strip(),
                        str(notes or "").strip(),
                        now,
                        now,
                    ),
                )
                vid = int(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValidationError(
                f"Vehicle with registration '{creg}' already exists in this neighbourhood."
            ) from exc
        rec = self.get_vehicle(vid)
        assert rec is not None
        return rec

    def update_vehicle(
        self,
        vehicle_id: int,
        registration_number: str,
        vehicle_type: str,
        capacity: object,
        fuel_status: str = "Unknown",
        operational_status: str = "Available",
        assigned_team_id: int | None = None,
        location: str = "",
        notes: str = "",
    ) -> VehicleRecord:
        existing = self.get_vehicle(vehicle_id)
        if existing is None:
            raise ValidationError(f"Vehicle #{vehicle_id} not found.")
        creg, vtype, cap, st = self._validate(registration_number, vehicle_type, capacity, operational_status)
        now = _now_iso()
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    UPDATE vehicles
                    SET registration_number = ?, vehicle_type = ?, capacity = ?,
                        fuel_status = ?, operational_status = ?, assigned_team_id = ?,
                        location = ?, notes = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        creg,
                        vtype,
                        cap,
                        str(fuel_status or "Unknown").strip(),
                        st,
                        assigned_team_id,
                        str(location or "").strip(),
                        str(notes or "").strip(),
                        now,
                        vehicle_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Duplicate registration number '{creg}'.") from exc
        rec = self.get_vehicle(vehicle_id)
        assert rec is not None
        return rec

    def assign_vehicle_to_team(self, vehicle_id: int, team_id: int, status: str = "Assigned") -> VehicleRecord:
        existing = self.get_vehicle(vehicle_id)
        if existing is None:
            raise ValidationError(f"Vehicle #{vehicle_id} not found.")
        if existing.operational_status != "Available":
            raise ValidationError(
                f"Vehicle '{existing.registration_number}' is '{existing.operational_status}' and cannot be assigned."
            )
        if status not in ("Assigned", "In use"):
            raise ValidationError(f"Invalid assignment status '{status}'.")
        now = _now_iso()
        with self.db.transaction() as conn:
            team_row = conn.execute("SELECT id FROM rescue_teams WHERE id = ?", (team_id,)).fetchone()
            if team_row is None:
                raise ValidationError(f"Rescue team #{team_id} not found.")
            conn.execute(
                """
                UPDATE vehicles
                SET assigned_team_id = ?, operational_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (team_id, status, now, vehicle_id),
            )
        rec = self.get_vehicle(vehicle_id)
        assert rec is not None
        return rec

    def release_vehicle(self, vehicle_id: int) -> VehicleRecord:
        existing = self.get_vehicle(vehicle_id)
        if existing is None:
            raise ValidationError(f"Vehicle #{vehicle_id} not found.")
        now = _now_iso()
        next_status = "Available" if existing.operational_status in ("Assigned", "In use") else existing.operational_status
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE vehicles
                SET assigned_team_id = NULL, operational_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_status, now, vehicle_id),
            )
        rec = self.get_vehicle(vehicle_id)
        assert rec is not None
        return rec

    def set_status(self, vehicle_id: int, operational_status: str) -> VehicleRecord:
        existing = self.get_vehicle(vehicle_id)
        if existing is None:
            raise ValidationError(f"Vehicle #{vehicle_id} not found.")
        st = str(operational_status or "").strip()
        if st not in VEHICLE_STATUS_OPTIONS:
            raise ValidationError(f"Invalid vehicle operational status '{st}'.")
        now = _now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE vehicles SET operational_status = ?, updated_at = ? WHERE id = ?",
                (st, now, vehicle_id),
            )
        rec = self.get_vehicle(vehicle_id)
        assert rec is not None
        return rec

    def delete_vehicle(self, vehicle_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))

    def get_vehicle(self, vehicle_id: int) -> VehicleRecord | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT v.*, COALESCE(rt.team_name, '') AS team_name
                FROM vehicles v
                LEFT JOIN rescue_teams rt ON rt.id = v.assigned_team_id
                WHERE v.id = ?
                """,
                (vehicle_id,),
            ).fetchone()
            return self._row_to_record(row) if row else None

    def list_vehicles(
        self,
        neighbourhood_id: int,
        search: str = "",
        status_filter: str = "All",
        type_filter: str = "All",
    ) -> list[VehicleRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT v.*, COALESCE(rt.team_name, '') AS team_name
                FROM vehicles v
                LEFT JOIN rescue_teams rt ON rt.id = v.assigned_team_id
                WHERE v.neighbourhood_id = ?
                ORDER BY v.registration_number ASC, v.id ASC
                """,
                (neighbourhood_id,),
            ).fetchall()
        records = [self._row_to_record(r) for r in rows]
        q = search.strip().lower()
        out: list[VehicleRecord] = []
        for r in records:
            if status_filter and status_filter != "All" and r.operational_status != status_filter:
                continue
            if type_filter and type_filter != "All" and r.vehicle_type != type_filter:
                continue
            if q and (
                q not in r.registration_number.lower()
                and q not in r.vehicle_type.lower()
                and q not in r.location.lower()
                and q not in r.assigned_team_name.lower()
            ):
                continue
            out.append(r)
        return out

    @staticmethod
    def _row_to_record(row) -> VehicleRecord:
        return VehicleRecord(
            id=int(row["id"]),
            neighbourhood_id=int(row["neighbourhood_id"]),
            registration_number=str(row["registration_number"]),
            vehicle_type=str(row["vehicle_type"]),
            capacity=int(row["capacity"]),
            fuel_status=str(row["fuel_status"]),
            operational_status=str(row["operational_status"]),
            assigned_team_id=int(row["assigned_team_id"]) if row["assigned_team_id"] is not None else None,
            assigned_team_name=str(row["team_name"]),
            location=str(row["location"]),
            notes=str(row["notes"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
