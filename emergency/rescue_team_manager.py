"""Rescue team registration, member management, and manual status tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from config import RESCUE_TEAM_STATUS_OPTIONS
from core.validation import ValidationError
from database.db import DatabaseManager


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class RescueTeamRecord:
    """Registered rescue team entry (manual status and operation assignment only)."""

    id: int | None
    neighbourhood_id: int
    team_name: str
    leader: str = ""
    members: list[str] = field(default_factory=list)
    contact: str = ""
    skills: str = ""
    equipment: str = ""
    current_location: str = ""
    availability: str = "Available"
    current_assignment: str = ""
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def members_summary(self) -> str:
        return ", ".join(self.members) if self.members else "None listed"


class RescueTeamManager:
    """Service layer managing rescue teams, members, and manual operation updates."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    @staticmethod
    def _normalize_members(members: Iterable[str] | str) -> list[str]:
        if isinstance(members, str):
            raw = [m.strip() for m in members.replace(";", ",").split(",") if m.strip()]
        else:
            raw = [str(m).strip() for m in members if str(m).strip()]
        deduped: list[str] = []
        for m in raw:
            if m not in deduped:
                deduped.append(m)
        return deduped

    def register_team(
        self,
        neighbourhood_id: int,
        team_name: str,
        leader: str = "",
        members: Iterable[str] | str = (),
        contact: str = "",
        skills: str = "",
        equipment: str = "",
        current_location: str = "",
        availability: str = "Available",
        current_assignment: str = "",
        notes: str = "",
    ) -> RescueTeamRecord:
        cname = str(team_name or "").strip()
        if not cname:
            raise ValidationError("Rescue team name cannot be empty.")
        cavail = str(availability or "Available").strip()
        if cavail not in RESCUE_TEAM_STATUS_OPTIONS:
            raise ValidationError(f"Invalid team availability '{cavail}'.")
        mem_list = self._normalize_members(members)
        now = _now_iso()
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO rescue_teams (
                    neighbourhood_id, team_name, leader, members_json, contact,
                    skills, equipment, current_location, availability,
                    current_assignment, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    neighbourhood_id,
                    cname,
                    str(leader or "").strip(),
                    json.dumps(mem_list, separators=(",", ":")),
                    str(contact or "").strip(),
                    str(skills or "").strip(),
                    str(equipment or "").strip(),
                    str(current_location or "").strip(),
                    cavail,
                    str(current_assignment or "").strip(),
                    str(notes or "").strip(),
                    now,
                    now,
                ),
            )
            tid = int(cur.lastrowid)
        rec = self.get_team(tid)
        assert rec is not None
        return rec

    def update_team(
        self,
        team_id: int,
        team_name: str,
        leader: str = "",
        members: Iterable[str] | str = (),
        contact: str = "",
        skills: str = "",
        equipment: str = "",
        current_location: str = "",
        availability: str = "Available",
        current_assignment: str = "",
        notes: str = "",
    ) -> RescueTeamRecord:
        existing = self.get_team(team_id)
        if existing is None:
            raise ValidationError(f"Rescue team #{team_id} not found.")
        cname = str(team_name or "").strip()
        if not cname:
            raise ValidationError("Rescue team name cannot be empty.")
        cavail = str(availability or "Available").strip()
        if cavail not in RESCUE_TEAM_STATUS_OPTIONS:
            raise ValidationError(f"Invalid team availability '{cavail}'.")
        mem_list = self._normalize_members(members)
        now = _now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE rescue_teams
                SET team_name = ?, leader = ?, members_json = ?, contact = ?,
                    skills = ?, equipment = ?, current_location = ?,
                    availability = ?, current_assignment = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    cname,
                    str(leader or "").strip(),
                    json.dumps(mem_list, separators=(",", ":")),
                    str(contact or "").strip(),
                    str(skills or "").strip(),
                    str(equipment or "").strip(),
                    str(current_location or "").strip(),
                    cavail,
                    str(current_assignment or "").strip(),
                    str(notes or "").strip(),
                    now,
                    team_id,
                ),
            )
        rec = self.get_team(team_id)
        assert rec is not None
        return rec

    def assign_members(self, team_id: int, members: Iterable[str] | str) -> RescueTeamRecord:
        existing = self.get_team(team_id)
        if existing is None:
            raise ValidationError(f"Rescue team #{team_id} not found.")
        mem_list = self._normalize_members(members)
        now = _now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE rescue_teams SET members_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(mem_list, separators=(",", ":")), now, team_id),
            )
        rec = self.get_team(team_id)
        assert rec is not None
        return rec

    def update_availability(self, team_id: int, availability: str) -> RescueTeamRecord:
        existing = self.get_team(team_id)
        if existing is None:
            raise ValidationError(f"Rescue team #{team_id} not found.")
        cavail = str(availability or "").strip()
        if cavail not in RESCUE_TEAM_STATUS_OPTIONS:
            raise ValidationError(f"Invalid team availability '{cavail}'.")
        now = _now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE rescue_teams SET availability = ?, updated_at = ? WHERE id = ?",
                (cavail, now, team_id),
            )
        rec = self.get_team(team_id)
        assert rec is not None
        return rec

    def assign_operation(
        self,
        team_id: int,
        operation_label: str,
        set_status: str = "Assigned",
        notes: str = "",
    ) -> RescueTeamRecord:
        existing = self.get_team(team_id)
        if existing is None:
            raise ValidationError(f"Rescue team #{team_id} not found.")
        if existing.availability in ("Unavailable", "Off duty"):
            raise ValidationError(
                f"Team '{existing.team_name}' is currently '{existing.availability}' and cannot be assigned."
            )
        if set_status not in ("Assigned", "On operation"):
            raise ValidationError(f"Invalid operational assignment status '{set_status}'.")
        op_txt = str(operation_label or "").strip()
        if not op_txt:
            raise ValidationError("Operation description cannot be empty.")
        merged_notes = existing.notes
        if notes.strip():
            merged_notes = f"{existing.notes}\n{notes.strip()}".strip()
        now = _now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE rescue_teams
                SET availability = ?, current_assignment = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (set_status, op_txt, merged_notes, now, team_id),
            )
        rec = self.get_team(team_id)
        assert rec is not None
        return rec

    def complete_operation(self, team_id: int, completion_notes: str = "") -> RescueTeamRecord:
        existing = self.get_team(team_id)
        if existing is None:
            raise ValidationError(f"Rescue team #{team_id} not found.")
        merged_notes = existing.notes
        if completion_notes.strip():
            merged_notes = f"{existing.notes}\n[Completed] {completion_notes.strip()}".strip()
        now = _now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE rescue_teams
                SET availability = 'Available', current_assignment = '', notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (merged_notes, now, team_id),
            )
        rec = self.get_team(team_id)
        assert rec is not None
        return rec

    def delete_team(self, team_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM rescue_teams WHERE id = ?", (team_id,))

    def get_team(self, team_id: int) -> RescueTeamRecord | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM rescue_teams WHERE id = ?", (team_id,)).fetchone()
            return self._row_to_record(row) if row else None

    def list_teams(
        self,
        neighbourhood_id: int,
        search: str = "",
        status_filter: str = "All",
    ) -> list[RescueTeamRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM rescue_teams WHERE neighbourhood_id = ? ORDER BY team_name ASC, id ASC",
                (neighbourhood_id,),
            ).fetchall()
        records = [self._row_to_record(r) for r in rows]
        q = search.strip().lower()
        out: list[RescueTeamRecord] = []
        for r in records:
            if status_filter and status_filter != "All" and r.availability != status_filter:
                continue
            if q and (
                q not in r.team_name.lower()
                and q not in r.leader.lower()
                and q not in r.skills.lower()
                and q not in r.members_summary.lower()
                and q not in r.current_assignment.lower()
            ):
                continue
            out.append(r)
        return out

    @staticmethod
    def _row_to_record(row) -> RescueTeamRecord:
        try:
            members = json.loads(row["members_json"] or "[]")
            if not isinstance(members, list):
                members = []
        except json.JSONDecodeError:
            members = []
        return RescueTeamRecord(
            id=int(row["id"]),
            neighbourhood_id=int(row["neighbourhood_id"]),
            team_name=str(row["team_name"]),
            leader=str(row["leader"]),
            members=[str(m) for m in members],
            contact=str(row["contact"]),
            skills=str(row["skills"]),
            equipment=str(row["equipment"]),
            current_location=str(row["current_location"]),
            availability=str(row["availability"]),
            current_assignment=str(row["current_assignment"]),
            notes=str(row["notes"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
