"""Emergency shelter registry, occupancy validation, and SafeRoute metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from config import SHELTER_FACILITY_OPTIONS, SHELTER_SOURCE_OPTIONS, SHELTER_STATUS_OPTIONS
from core.validation import ValidationError, validate_latitude, validate_longitude
from database.db import DatabaseManager


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_int(value: object, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{field_name} must be a whole integer.")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be a valid integer.") from exc
    if parsed < minimum:
        raise ValidationError(f"{field_name} must be >= {minimum} (got {parsed}).")
    return parsed


@dataclass(slots=True)
class ShelterRecord:
    """Registered emergency shelter record (strictly distinct from unverified OSM landmarks)."""

    id: int | None
    neighbourhood_id: int
    name: str
    address: str
    latitude: float
    longitude: float
    total_capacity: int
    occupied_capacity: int
    contact_info: str = ""
    status: str = "Active"
    facilities: list[str] = field(default_factory=list)
    accessibility: str = ""
    source: str = "user-entered"
    is_verified: bool = False
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def available_capacity(self) -> int:
        return max(0, int(self.total_capacity) - int(self.occupied_capacity))

    @property
    def occupancy_pct(self) -> float:
        if self.total_capacity <= 0:
            return 0.0
        return (self.occupied_capacity / float(self.total_capacity)) * 100.0

    @property
    def verification_label(self) -> str:
        return "Verified Shelter" if self.is_verified else "Registered (Unverified)"

    @property
    def facilities_summary(self) -> str:
        return ", ".join(self.facilities) if self.facilities else "None listed"


class ShelterManager:
    """Service layer managing shelter CRUD, occupancy bounds, and filtering."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    @staticmethod
    def _normalize_facilities(facilities: Iterable[str] | str) -> list[str]:
        if isinstance(facilities, str):
            raw_list = [f.strip() for f in facilities.split(",") if f.strip()]
        else:
            raw_list = [str(f).strip() for f in facilities if str(f).strip()]
        allowed = set(SHELTER_FACILITY_OPTIONS)
        cleaned: list[str] = []
        for item in raw_list:
            if item in allowed and item not in cleaned:
                cleaned.append(item)
            elif item not in allowed and item not in cleaned:
                cleaned.append(item)
        return cleaned

    @staticmethod
    def _validate_fields(
        name: str,
        address: str,
        latitude: object,
        longitude: object,
        total_capacity: object,
        occupied_capacity: object,
        status: str,
        source: str,
    ) -> tuple[str, str, float, float, int, int, str, str]:
        cname = str(name or "").strip()
        if not cname:
            raise ValidationError("Shelter name cannot be empty.")
        caddr = str(address or "").strip()
        lat = validate_latitude(latitude, "Shelter latitude")
        lon = validate_longitude(longitude, "Shelter longitude")
        tot = _parse_int(total_capacity, "Total capacity", minimum=0)
        occ = _parse_int(occupied_capacity, "Occupied capacity", minimum=0)
        if occ > tot:
            raise ValidationError(
                f"Occupied capacity ({occ}) cannot exceed total capacity ({tot})."
            )
        cstatus = str(status or "Active").strip()
        if cstatus not in SHELTER_STATUS_OPTIONS:
            raise ValidationError(f"Unsupported shelter status '{cstatus}'.")
        if cstatus == "Active" and tot > 0 and occ >= tot:
            cstatus = "Full"
        elif cstatus == "Full" and occ < tot:
            cstatus = "Active"
        csource = str(source or "user-entered").strip()
        if csource not in SHELTER_SOURCE_OPTIONS:
            raise ValidationError(f"Unsupported shelter source '{csource}'.")
        return cname, caddr, lat, lon, tot, occ, cstatus, csource

    def register_shelter(
        self,
        neighbourhood_id: int,
        name: str,
        address: str,
        latitude: object,
        longitude: object,
        total_capacity: object,
        occupied_capacity: object = 0,
        contact_info: str = "",
        status: str = "Active",
        facilities: Iterable[str] | str = (),
        accessibility: str = "",
        source: str = "user-entered",
        is_verified: bool = False,
        notes: str = "",
    ) -> ShelterRecord:
        cname, caddr, lat, lon, tot, occ, cstatus, csource = self._validate_fields(
            name, address, latitude, longitude, total_capacity, occupied_capacity, status, source
        )
        facs = self._normalize_facilities(facilities)
        verified_flag = 1 if (is_verified or csource == "field-verified") else 0
        now = _now_iso()
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO shelters (
                    neighbourhood_id, name, address, latitude, longitude,
                    total_capacity, occupied_capacity, contact_info, status,
                    facilities, accessibility, source, is_verified, notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    neighbourhood_id,
                    cname,
                    caddr,
                    lat,
                    lon,
                    tot,
                    occ,
                    str(contact_info or "").strip(),
                    cstatus,
                    json.dumps(facs, separators=(",", ":")),
                    str(accessibility or "").strip(),
                    csource,
                    verified_flag,
                    str(notes or "").strip(),
                    now,
                    now,
                ),
            )
            sid = int(cur.lastrowid)
        rec = self.get_shelter(sid)
        assert rec is not None
        return rec

    def update_shelter(
        self,
        shelter_id: int,
        name: str,
        address: str,
        latitude: object,
        longitude: object,
        total_capacity: object,
        occupied_capacity: object,
        contact_info: str = "",
        status: str = "Active",
        facilities: Iterable[str] | str = (),
        accessibility: str = "",
        source: str = "user-entered",
        is_verified: bool = False,
        notes: str = "",
    ) -> ShelterRecord:
        existing = self.get_shelter(shelter_id)
        if existing is None:
            raise ValidationError(f"Shelter #{shelter_id} not found.")
        cname, caddr, lat, lon, tot, occ, cstatus, csource = self._validate_fields(
            name, address, latitude, longitude, total_capacity, occupied_capacity, status, source
        )
        facs = self._normalize_facilities(facilities)
        verified_flag = 1 if (is_verified or csource == "field-verified") else 0
        now = _now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE shelters
                SET name = ?, address = ?, latitude = ?, longitude = ?,
                    total_capacity = ?, occupied_capacity = ?, contact_info = ?, status = ?,
                    facilities = ?, accessibility = ?, source = ?, is_verified = ?,
                    notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    cname,
                    caddr,
                    lat,
                    lon,
                    tot,
                    occ,
                    str(contact_info or "").strip(),
                    cstatus,
                    json.dumps(facs, separators=(",", ":")),
                    str(accessibility or "").strip(),
                    csource,
                    verified_flag,
                    str(notes or "").strip(),
                    now,
                    shelter_id,
                ),
            )
        rec = self.get_shelter(shelter_id)
        assert rec is not None
        return rec

    def update_occupancy(
        self,
        shelter_id: int,
        occupied_capacity: object | None = None,
        total_capacity: object | None = None,
    ) -> ShelterRecord:
        existing = self.get_shelter(shelter_id)
        if existing is None:
            raise ValidationError(f"Shelter #{shelter_id} not found.")
        new_tot = existing.total_capacity if total_capacity is None else _parse_int(total_capacity, "Total capacity", 0)
        new_occ = existing.occupied_capacity if occupied_capacity is None else _parse_int(occupied_capacity, "Occupied capacity", 0)
        if new_occ > new_tot:
            raise ValidationError(
                f"Occupied capacity ({new_occ}) cannot exceed total capacity ({new_tot})."
            )
        new_status = existing.status
        if new_status in ("Active", "Full"):
            new_status = "Full" if (new_tot > 0 and new_occ >= new_tot) else "Active"
        now = _now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE shelters
                SET total_capacity = ?, occupied_capacity = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_tot, new_occ, new_status, now, shelter_id),
            )
        rec = self.get_shelter(shelter_id)
        assert rec is not None
        return rec

    def set_shelter_status(self, shelter_id: int, status: str) -> ShelterRecord:
        existing = self.get_shelter(shelter_id)
        if existing is None:
            raise ValidationError(f"Shelter #{shelter_id} not found.")
        cstatus = str(status or "").strip()
        if cstatus not in SHELTER_STATUS_OPTIONS:
            raise ValidationError(f"Unsupported shelter status '{cstatus}'.")
        if cstatus == "Active" and existing.total_capacity > 0 and existing.occupied_capacity >= existing.total_capacity:
            cstatus = "Full"
        now = _now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE shelters SET status = ?, updated_at = ? WHERE id = ?",
                (cstatus, now, shelter_id),
            )
        rec = self.get_shelter(shelter_id)
        assert rec is not None
        return rec

    def delete_shelter(self, shelter_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM shelters WHERE id = ?", (shelter_id,))

    def get_shelter(self, shelter_id: int) -> ShelterRecord | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
            return self._row_to_record(row) if row else None

    def list_shelters(
        self,
        neighbourhood_id: int,
        search: str = "",
        status_filter: str = "All",
    ) -> list[ShelterRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM shelters WHERE neighbourhood_id = ? ORDER BY name ASC, id ASC",
                (neighbourhood_id,),
            ).fetchall()
        records = [self._row_to_record(r) for r in rows]
        q = search.strip().lower()
        out: list[ShelterRecord] = []
        for r in records:
            if status_filter and status_filter != "All" and r.status != status_filter:
                continue
            if q and (
                q not in r.name.lower()
                and q not in r.address.lower()
                and q not in r.facilities_summary.lower()
                and q not in r.notes.lower()
            ):
                continue
            out.append(r)
        return out

    @staticmethod
    def _row_to_record(row) -> ShelterRecord:
        try:
            facs = json.loads(row["facilities"] or "[]")
            if not isinstance(facs, list):
                facs = []
        except json.JSONDecodeError:
            facs = []
        return ShelterRecord(
            id=int(row["id"]),
            neighbourhood_id=int(row["neighbourhood_id"]),
            name=str(row["name"]),
            address=str(row["address"]),
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            total_capacity=int(row["total_capacity"]),
            occupied_capacity=int(row["occupied_capacity"]),
            contact_info=str(row["contact_info"]),
            status=str(row["status"]),
            facilities=[str(f) for f in facs],
            accessibility=str(row["accessibility"]),
            source=str(row["source"]),
            is_verified=bool(row["is_verified"]),
            notes=str(row["notes"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
