"""Volunteer registration and privacy-preserving availability tracking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from config import VOLUNTEER_AVAILABILITY_OPTIONS
from core.validation import ValidationError
from database.db import DatabaseManager


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def mask_contact_value(contact: str) -> str:
    """Return a masked placeholder for UI/public views so personal phone numbers stay protected."""
    cleaned = str(contact or "").strip()
    if not cleaned:
        return "Not supplied"
    if len(cleaned) <= 4:
        return "****"
    return f"******{cleaned[-4:]}"


@dataclass(slots=True)
class VolunteerRecord:
    """Registered volunteer entry with explicit contact redaction helper."""

    id: int | None
    neighbourhood_id: int
    name: str
    contact: str = ""
    emergency_contact: str = ""
    skills: str = ""
    availability: str = "Available"
    preferred_area: str = ""
    assigned_operation_id: int | None = None
    assigned_operation_name: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def masked_contact(self) -> str:
        return mask_contact_value(self.contact)

    @property
    def masked_emergency_contact(self) -> str:
        return mask_contact_value(self.emergency_contact)

    def to_export_row(self, include_private_contacts: bool = False) -> dict[str, object]:
        """Never include raw contact info unless explicitly authorized."""
        return {
            "volunteer_id": self.id,
            "name": self.name,
            "contact": self.contact if include_private_contacts else "[REDACTED - PROTECTED]",
            "emergency_contact": (
                self.emergency_contact if include_private_contacts else "[REDACTED - PROTECTED]"
            ),
            "skills": self.skills,
            "availability": self.availability,
            "preferred_area": self.preferred_area,
            "assigned_operation": self.assigned_operation_name or "Unassigned",
            "notes": self.notes,
        }


class VolunteerManager:
    """Service layer managing volunteer CRUD, search, availability, and operation assignment."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    def add_volunteer(
        self,
        neighbourhood_id: int,
        name: str,
        contact: str = "",
        emergency_contact: str = "",
        skills: str = "",
        availability: str = "Available",
        preferred_area: str = "",
        notes: str = "",
    ) -> VolunteerRecord:
        cname = str(name or "").strip()
        if not cname:
            raise ValidationError("Volunteer name cannot be empty.")
        cavail = str(availability or "Available").strip()
        if cavail not in VOLUNTEER_AVAILABILITY_OPTIONS:
            raise ValidationError(f"Invalid volunteer availability '{cavail}'.")
        now = _now_iso()
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO volunteers (
                    neighbourhood_id, name, contact, emergency_contact, skills,
                    availability, preferred_area, assigned_operation_id, notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    neighbourhood_id,
                    cname,
                    str(contact or "").strip(),
                    str(emergency_contact or "").strip(),
                    str(skills or "").strip(),
                    cavail,
                    str(preferred_area or "").strip(),
                    str(notes or "").strip(),
                    now,
                    now,
                ),
            )
            vid = int(cur.lastrowid)
        rec = self.get_volunteer(vid)
        assert rec is not None
        return rec

    def update_volunteer(
        self,
        volunteer_id: int,
        name: str,
        contact: str = "",
        emergency_contact: str = "",
        skills: str = "",
        availability: str = "Available",
        preferred_area: str = "",
        notes: str = "",
    ) -> VolunteerRecord:
        existing = self.get_volunteer(volunteer_id)
        if existing is None:
            raise ValidationError(f"Volunteer #{volunteer_id} not found.")
        cname = str(name or "").strip()
        if not cname:
            raise ValidationError("Volunteer name cannot be empty.")
        cavail = str(availability or "Available").strip()
        if cavail not in VOLUNTEER_AVAILABILITY_OPTIONS:
            raise ValidationError(f"Invalid volunteer availability '{cavail}'.")
        now = _now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE volunteers
                SET name = ?, contact = ?, emergency_contact = ?, skills = ?,
                    availability = ?, preferred_area = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    cname,
                    str(contact or "").strip(),
                    str(emergency_contact or "").strip(),
                    str(skills or "").strip(),
                    cavail,
                    str(preferred_area or "").strip(),
                    str(notes or "").strip(),
                    now,
                    volunteer_id,
                ),
            )
        rec = self.get_volunteer(volunteer_id)
        assert rec is not None
        return rec

    def update_availability(self, volunteer_id: int, availability: str) -> VolunteerRecord:
        existing = self.get_volunteer(volunteer_id)
        if existing is None:
            raise ValidationError(f"Volunteer #{volunteer_id} not found.")
        cavail = str(availability or "").strip()
        if cavail not in VOLUNTEER_AVAILABILITY_OPTIONS:
            raise ValidationError(f"Invalid volunteer availability '{cavail}'.")
        now = _now_iso()
        op_id = None if cavail == "Available" else existing.assigned_operation_id
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE volunteers
                SET availability = ?, assigned_operation_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (cavail, op_id, now, volunteer_id),
            )
        rec = self.get_volunteer(volunteer_id)
        assert rec is not None
        return rec

    def assign_to_operation(self, volunteer_id: int, operation_id: int | None) -> VolunteerRecord:
        existing = self.get_volunteer(volunteer_id)
        if existing is None:
            raise ValidationError(f"Volunteer #{volunteer_id} not found.")
        now = _now_iso()
        with self.db.transaction() as conn:
            if operation_id is not None:
                op_row = conn.execute(
                    "SELECT id FROM emergency_operations WHERE id = ?", (operation_id,)
                ).fetchone()
                if op_row is None:
                    raise ValidationError(f"Operation #{operation_id} not found.")
                if existing.availability != "Available":
                    raise ValidationError(
                        f"Volunteer '{existing.name}' is '{existing.availability}' and cannot be assigned."
                    )
                next_avail = "Assigned"
            else:
                next_avail = "Available" if existing.availability == "Assigned" else existing.availability
            conn.execute(
                """
                UPDATE volunteers
                SET assigned_operation_id = ?, availability = ?, updated_at = ?
                WHERE id = ?
                """,
                (operation_id, next_avail, now, volunteer_id),
            )
        rec = self.get_volunteer(volunteer_id)
        assert rec is not None
        return rec

    def remove_volunteer(self, volunteer_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM volunteers WHERE id = ?", (volunteer_id,))

    def get_volunteer(self, volunteer_id: int) -> VolunteerRecord | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT v.*, COALESCE(eo.operation_name, '') AS op_name
                FROM volunteers v
                LEFT JOIN emergency_operations eo ON eo.id = v.assigned_operation_id
                WHERE v.id = ?
                """,
                (volunteer_id,),
            ).fetchone()
            return self._row_to_record(row) if row else None

    def list_volunteers(
        self,
        neighbourhood_id: int,
        search: str = "",
        status_filter: str = "All",
    ) -> list[VolunteerRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT v.*, COALESCE(eo.operation_name, '') AS op_name
                FROM volunteers v
                LEFT JOIN emergency_operations eo ON eo.id = v.assigned_operation_id
                WHERE v.neighbourhood_id = ?
                ORDER BY v.name ASC, v.id ASC
                """,
                (neighbourhood_id,),
            ).fetchall()
        records = [self._row_to_record(r) for r in rows]
        q = search.strip().lower()
        out: list[VolunteerRecord] = []
        for r in records:
            if status_filter and status_filter != "All" and r.availability != status_filter:
                continue
            if q and (
                q not in r.name.lower()
                and q not in r.skills.lower()
                and q not in r.preferred_area.lower()
            ):
                continue
            out.append(r)
        return out

    @staticmethod
    def _row_to_record(row) -> VolunteerRecord:
        return VolunteerRecord(
            id=int(row["id"]),
            neighbourhood_id=int(row["neighbourhood_id"]),
            name=str(row["name"]),
            contact=str(row["contact"]),
            emergency_contact=str(row["emergency_contact"]),
            skills=str(row["skills"]),
            availability=str(row["availability"]),
            preferred_area=str(row["preferred_area"]),
            assigned_operation_id=(
                int(row["assigned_operation_id"]) if row["assigned_operation_id"] is not None else None
            ),
            assigned_operation_name=str(row["op_name"]),
            notes=str(row["notes"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
