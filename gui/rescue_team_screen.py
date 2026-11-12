"""Phase 6 Personnel & Fleet tabs: Rescue Teams, Vehicles, and Volunteers (with privacy masking)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Callable

from config import (
    RESCUE_TEAM_STATUS_OPTIONS,
    THEME,
    VEHICLE_STATUS_OPTIONS,
    VEHICLE_TYPE_OPTIONS,
    VOLUNTEER_AVAILABILITY_OPTIONS,
)
from core.models import Neighbourhood
from core.validation import ValidationError
from emergency.operation_manager import EmergencyOperationRecord, OperationManager
from emergency.rescue_team_manager import RescueTeamManager, RescueTeamRecord
from emergency.vehicle_manager import VehicleManager, VehicleRecord
from emergency.volunteer_manager import VolunteerManager, VolunteerRecord


class RescueTeamsTab(tk.Frame):
    """Manual Rescue Team CRUD, member assignment, and manual status lifecycle."""

    def __init__(
        self,
        parent: tk.Misc,
        team_mgr: RescueTeamManager,
        on_data_changed: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=10, pady=8)
        self.team_mgr = team_mgr
        self.on_data_changed = on_data_changed

        self._neighbourhood: Neighbourhood | None = None
        self._teams: list[RescueTeamRecord] = []
        self._selected_id: int | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        outer = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=345,
        )
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        outer.grid_propagate(False)
        outer.pack_propagate(False)

        canvas = tk.Canvas(outer, bg=THEME["bg_card"], highlightthickness=0, width=323)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        form = tk.Frame(canvas, bg=THEME["bg_card"], padx=10, pady=8)
        form.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=form, anchor="nw", width=323)
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        tk.Label(
            form,
            text="RESCUE TEAM EDITOR (Manual Only)",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(0, 6))

        self.var_name = tk.StringVar()
        self.var_leader = tk.StringVar()
        self.var_members = tk.StringVar()
        self.var_contact = tk.StringVar()
        self.var_skills = tk.StringVar()
        self.var_equipment = tk.StringVar()
        self.var_location = tk.StringVar()
        self.var_avail = tk.StringVar(value=RESCUE_TEAM_STATUS_OPTIONS[0])
        self.var_assign = tk.StringVar()
        self.var_notes = tk.StringVar()

        def field(lbl: str, var: tk.StringVar) -> None:
            tk.Label(form, text=lbl, bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
                anchor="w", fill="x", pady=(2, 1)
            )
            ttk.Entry(form, textvariable=var).pack(fill="x", pady=(0, 3))

        field("Team Name *:", self.var_name)
        field("Team Leader:", self.var_leader)
        field("Members (comma separated):", self.var_members)
        field("Contact / Radio Channel:", self.var_contact)
        field("Skills / Specialization:", self.var_skills)
        field("Assigned Equipment:", self.var_equipment)
        field("Current Location:", self.var_location)

        tk.Label(form, text="Availability Status:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x", pady=(2, 1)
        )
        ttk.Combobox(form, textvariable=self.var_avail, values=RESCUE_TEAM_STATUS_OPTIONS, state="readonly").pack(
            fill="x", pady=(0, 3)
        )
        field("Current Assignment Description:", self.var_assign)
        field("Notes:", self.var_notes)

        btns = tk.Frame(form, bg=THEME["bg_card"])
        btns.pack(fill="x", pady=(6, 4))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        ttk.Button(btns, text="Register Team", style="Accent.TButton", command=self._register).grid(
            row=0, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Update Team", command=self._update).grid(
            row=0, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btns, text="Assign Operation...", command=self._assign_op).grid(
            row=1, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Complete / Release", command=self._complete_op).grid(
            row=1, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btns, text="Clear Form", command=self._clear_form).grid(
            row=2, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Delete Team", command=self._delete).grid(
            row=2, column=1, sticky="ew", padx=(3, 0), pady=2
        )

        # Right side table
        right = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        filt = tk.Frame(right, bg=THEME["bg_card"])
        filt.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(filt, text="Search:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_search = tk.StringVar()
        e_s = ttk.Entry(filt, textvariable=self.var_search, width=22)
        e_s.pack(side="left", padx=(4, 10))
        e_s.bind("<KeyRelease>", lambda _e: self.refresh())

        tk.Label(filt, text="Availability:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_filter = tk.StringVar(value="All")
        cb = ttk.Combobox(filt, textvariable=self.var_filter, values=("All",) + RESCUE_TEAM_STATUS_OPTIONS, state="readonly", width=13)
        cb.pack(side="left", padx=(4, 10))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        self.summary_lbl = tk.Label(filt, text="0 team(s)", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 8, "bold"))
        self.summary_lbl.pack(side="right")

        cols = ("id", "name", "leader", "members", "avail", "assignment", "location", "skills")
        wrap = tk.Frame(right, bg=THEME["bg_card"])
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for k, h, w in [
            ("id", "ID", 40),
            ("name", "Team Name", 150),
            ("leader", "Leader", 110),
            ("members", "Members", 170),
            ("avail", "Availability", 95),
            ("assignment", "Current Assignment", 160),
            ("location", "Location", 120),
            ("skills", "Skills", 130),
        ]:
            self.tree.heading(k, text=h)
            self.tree.column(k, width=w, anchor="e" if k == "id" else "w")
        vsb_t = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb_t.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb_t.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def set_neighbourhood(self, neighbourhood: Neighbourhood | None) -> None:
        if (neighbourhood.id if neighbourhood else None) != (self._neighbourhood.id if self._neighbourhood else None):
            self._selected_id = None
            self._clear_form()
        self._neighbourhood = neighbourhood
        self.refresh()

    def refresh(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        if self._neighbourhood is None or self._neighbourhood.id is None:
            self._teams = []
            self.summary_lbl.configure(text="No active workspace")
            return
        self._teams = self.team_mgr.list_teams(
            self._neighbourhood.id,
            status_filter=self.var_filter.get(),
            search=self.var_search.get(),
        )
        avail_cnt = sum(1 for t in self._teams if t.availability == "Available")
        self.summary_lbl.configure(text=f"{len(self._teams)} team(s) • {avail_cnt} available")
        for t in self._teams:
            self.tree.insert(
                "",
                "end",
                iid=str(t.id),
                values=(
                    t.id,
                    t.team_name,
                    t.leader,
                    f"{t.member_count}: {t.members_summary}",
                    t.availability,
                    t.current_assignment or "None",
                    t.current_location,
                    t.skills,
                ),
            )

    def _clear_form(self) -> None:
        self._selected_id = None
        for v in (
            self.var_name, self.var_leader, self.var_members, self.var_contact,
            self.var_skills, self.var_equipment, self.var_location, self.var_assign, self.var_notes
        ):
            v.set("")
        self.var_avail.set("Available")

    def _on_select(self, _evt=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        tid = int(sel[0])
        t = next((x for x in self._teams if x.id == tid), None)
        if t is None:
            return
        self._selected_id = t.id
        self.var_name.set(t.team_name)
        self.var_leader.set(t.leader)
        self.var_members.set(", ".join(t.members))
        self.var_contact.set(t.contact)
        self.var_skills.set(t.skills)
        self.var_equipment.set(t.equipment)
        self.var_location.set(t.current_location)
        self.var_avail.set(t.availability)
        self.var_assign.set(t.current_assignment)
        self.var_notes.set(t.notes)

    def _register(self) -> None:
        if self._neighbourhood is None or self._neighbourhood.id is None:
            messagebox.showinfo("No Workspace", "Load a neighbourhood workspace first.")
            return
        try:
            rec = self.team_mgr.register_team(
                neighbourhood_id=self._neighbourhood.id,
                team_name=self.var_name.get(),
                leader=self.var_leader.get(),
                members=self.var_members.get(),
                contact=self.var_contact.get(),
                skills=self.var_skills.get(),
                equipment=self.var_equipment.get(),
                current_location=self.var_location.get(),
                availability=self.var_avail.get(),
                current_assignment=self.var_assign.get(),
                notes=self.var_notes.get(),
            )
            self._selected_id = rec.id
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _update(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Team", "Select a rescue team row first.")
            return
        try:
            self.team_mgr.update_team(
                team_id=self._selected_id,
                team_name=self.var_name.get(),
                leader=self.var_leader.get(),
                members=self.var_members.get(),
                contact=self.var_contact.get(),
                skills=self.var_skills.get(),
                equipment=self.var_equipment.get(),
                current_location=self.var_location.get(),
                availability=self.var_avail.get(),
                current_assignment=self.var_assign.get(),
                notes=self.var_notes.get(),
            )
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _assign_op(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Team", "Select a rescue team first.")
            return
        desc = simpledialog.askstring(
            "Manual Operation Assignment",
            "Enter assignment description for this team (manual operator log only):",
            initialvalue=self.var_assign.get(),
            parent=self,
        )
        if not desc:
            return
        try:
            self.team_mgr.assign_operation(self._selected_id, desc, set_status="On operation")
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Assignment Error", str(exc))

    def _complete_op(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Team", "Select a rescue team first.")
            return
        try:
            self.team_mgr.complete_operation(self._selected_id, completion_notes="Manually marked completed.")
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Error", str(exc))

    def _delete(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Team", "Select a rescue team first.")
            return
        cur = self.team_mgr.get_team(self._selected_id)
        if cur is None:
            return
        if not messagebox.askyesno("Confirm Delete", f"Delete rescue team '{cur.team_name}'?"):
            return
        self.team_mgr.delete_team(self._selected_id)
        self._clear_form()
        self.on_data_changed()


class VehiclesTab(tk.Frame):
    """Rescue Vehicle Management tab supporting boats, ambulances, vans, trucks & team assignment."""

    def __init__(
        self,
        parent: tk.Misc,
        vehicle_mgr: VehicleManager,
        team_mgr: RescueTeamManager,
        on_data_changed: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=10, pady=8)
        self.vehicle_mgr = vehicle_mgr
        self.team_mgr = team_mgr
        self.on_data_changed = on_data_changed

        self._neighbourhood: Neighbourhood | None = None
        self._vehicles: list[VehicleRecord] = []
        self._teams: list[RescueTeamRecord] = []
        self._selected_id: int | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        outer = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=340,
        )
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        outer.grid_propagate(False)
        outer.pack_propagate(False)

        form = tk.Frame(outer, bg=THEME["bg_card"], padx=10, pady=8)
        form.pack(fill="both", expand=True)

        tk.Label(
            form,
            text="RESCUE VEHICLE FORM",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(0, 6))

        self.var_reg = tk.StringVar()
        self.var_type = tk.StringVar(value=VEHICLE_TYPE_OPTIONS[0])
        self.var_cap = tk.StringVar(value="4")
        self.var_fuel = tk.StringVar(value="Full")
        self.var_status = tk.StringVar(value=VEHICLE_STATUS_OPTIONS[0])
        self.var_team = tk.StringVar(value="Unassigned")
        self.var_loc = tk.StringVar()
        self.var_notes = tk.StringVar()

        def field(lbl: str, var: tk.StringVar) -> None:
            tk.Label(form, text=lbl, bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
                anchor="w", fill="x", pady=(2, 1)
            )
            ttk.Entry(form, textvariable=var).pack(fill="x", pady=(0, 3))

        field("Registration / ID Number *:", self.var_reg)

        tk.Label(form, text="Vehicle Type *:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x", pady=(2, 1)
        )
        ttk.Combobox(form, textvariable=self.var_type, values=VEHICLE_TYPE_OPTIONS, state="readonly").pack(fill="x", pady=(0, 3))

        row2 = tk.Frame(form, bg=THEME["bg_card"])
        row2.pack(fill="x", pady=(2, 3))
        row2.columnconfigure(0, weight=1)
        row2.columnconfigure(1, weight=1)
        tk.Label(row2, text="Passenger Capacity:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(row2, text="Fuel Status:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        ttk.Entry(row2, textvariable=self.var_cap).grid(row=1, column=0, sticky="ew", padx=(0, 3))
        ttk.Entry(row2, textvariable=self.var_fuel).grid(row=1, column=1, sticky="ew", padx=(3, 0))

        tk.Label(form, text="Operational Status:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x", pady=(2, 1)
        )
        ttk.Combobox(form, textvariable=self.var_status, values=VEHICLE_STATUS_OPTIONS, state="readonly").pack(fill="x", pady=(0, 3))

        tk.Label(form, text="Assigned Rescue Team:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x", pady=(2, 1)
        )
        self.team_cb = ttk.Combobox(form, textvariable=self.var_team, state="readonly")
        self.team_cb.pack(fill="x", pady=(0, 3))

        field("Current Location:", self.var_loc)
        field("Notes:", self.var_notes)

        btns = tk.Frame(form, bg=THEME["bg_card"])
        btns.pack(fill="x", pady=(6, 4))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        ttk.Button(btns, text="Register Vehicle", style="Accent.TButton", command=self._register).grid(
            row=0, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Update Vehicle", command=self._update).grid(
            row=0, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btns, text="Assign to Team", command=self._assign_team).grid(
            row=1, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Release Vehicle", command=self._release).grid(
            row=1, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btns, text="Clear Form", command=self._clear_form).grid(
            row=2, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Delete Vehicle", command=self._delete).grid(
            row=2, column=1, sticky="ew", padx=(3, 0), pady=2
        )

        # Right side
        right = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        filt = tk.Frame(right, bg=THEME["bg_card"])
        filt.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(filt, text="Search:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_search = tk.StringVar()
        e_s = ttk.Entry(filt, textvariable=self.var_search, width=18)
        e_s.pack(side="left", padx=(4, 8))
        e_s.bind("<KeyRelease>", lambda _e: self.refresh())

        tk.Label(filt, text="Status:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_filter_st = tk.StringVar(value="All")
        cb1 = ttk.Combobox(filt, textvariable=self.var_filter_st, values=("All",) + VEHICLE_STATUS_OPTIONS, state="readonly", width=13)
        cb1.pack(side="left", padx=(4, 8))
        cb1.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        self.summary_lbl = tk.Label(filt, text="0 vehicle(s)", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 8, "bold"))
        self.summary_lbl.pack(side="right")

        cols = ("id", "reg", "type", "cap", "fuel", "status", "team", "loc")
        wrap = tk.Frame(right, bg=THEME["bg_card"])
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for k, h, w in [
            ("id", "ID", 40),
            ("reg", "Registration", 115),
            ("type", "Vehicle Type", 130),
            ("cap", "Cap", 48),
            ("fuel", "Fuel", 85),
            ("status", "Status", 125),
            ("team", "Assigned Team", 130),
            ("loc", "Location", 140),
        ]:
            self.tree.heading(k, text=h)
            self.tree.column(k, width=w, anchor="e" if k in ("id", "cap") else "w")
        vsb_t = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb_t.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb_t.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def set_neighbourhood(self, neighbourhood: Neighbourhood | None) -> None:
        if (neighbourhood.id if neighbourhood else None) != (self._neighbourhood.id if self._neighbourhood else None):
            self._selected_id = None
            self._clear_form()
        self._neighbourhood = neighbourhood
        self.refresh()

    def refresh(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        if self._neighbourhood is None or self._neighbourhood.id is None:
            self._vehicles = []
            self._teams = []
            self.team_cb.configure(values=("Unassigned",))
            self.summary_lbl.configure(text="No active workspace")
            return
        self._teams = self.team_mgr.list_teams(self._neighbourhood.id)
        team_choices = ["Unassigned"] + [f"#{t.id}: {t.team_name}" for t in self._teams]
        self.team_cb.configure(values=team_choices)

        self._vehicles = self.vehicle_mgr.list_vehicles(
            self._neighbourhood.id,
            search=self.var_search.get(),
            status_filter=self.var_filter_st.get(),
        )
        avail = sum(1 for v in self._vehicles if v.operational_status == "Available")
        self.summary_lbl.configure(text=f"{len(self._vehicles)} vehicle(s) • {avail} available")
        for v in self._vehicles:
            self.tree.insert(
                "",
                "end",
                iid=str(v.id),
                values=(
                    v.id,
                    v.registration_number,
                    v.vehicle_type,
                    v.capacity,
                    v.fuel_status,
                    v.operational_status,
                    v.assigned_team_name or "Unassigned",
                    v.location,
                ),
            )

    def _selected_team_id(self) -> int | None:
        txt = self.var_team.get()
        if not txt.startswith("#"):
            return None
        try:
            return int(txt.split(":", 1)[0][1:])
        except ValueError:
            return None

    def _clear_form(self) -> None:
        self._selected_id = None
        self.var_reg.set("")
        self.var_type.set(VEHICLE_TYPE_OPTIONS[0])
        self.var_cap.set("4")
        self.var_fuel.set("Full")
        self.var_status.set("Available")
        self.var_team.set("Unassigned")
        self.var_loc.set("")
        self.var_notes.set("")

    def _on_select(self, _evt=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        vid = int(sel[0])
        v = next((x for x in self._vehicles if x.id == vid), None)
        if v is None:
            return
        self._selected_id = v.id
        self.var_reg.set(v.registration_number)
        self.var_type.set(v.vehicle_type)
        self.var_cap.set(str(v.capacity))
        self.var_fuel.set(v.fuel_status)
        self.var_status.set(v.operational_status)
        self.var_team.set(f"#{v.assigned_team_id}: {v.assigned_team_name}" if v.assigned_team_id else "Unassigned")
        self.var_loc.set(v.location)
        self.var_notes.set(v.notes)

    def _register(self) -> None:
        if self._neighbourhood is None or self._neighbourhood.id is None:
            return
        try:
            rec = self.vehicle_mgr.register_vehicle(
                neighbourhood_id=self._neighbourhood.id,
                registration_number=self.var_reg.get(),
                vehicle_type=self.var_type.get(),
                capacity=self.var_cap.get(),
                fuel_status=self.var_fuel.get(),
                operational_status=self.var_status.get(),
                assigned_team_id=self._selected_team_id(),
                location=self.var_loc.get(),
                notes=self.var_notes.get(),
            )
            self._selected_id = rec.id
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _update(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Vehicle", "Select a vehicle row first.")
            return
        try:
            self.vehicle_mgr.update_vehicle(
                vehicle_id=self._selected_id,
                registration_number=self.var_reg.get(),
                vehicle_type=self.var_type.get(),
                capacity=self.var_cap.get(),
                fuel_status=self.var_fuel.get(),
                operational_status=self.var_status.get(),
                assigned_team_id=self._selected_team_id(),
                location=self.var_loc.get(),
                notes=self.var_notes.get(),
            )
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _assign_team(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Vehicle", "Select an available vehicle first.")
            return
        tid = self._selected_team_id()
        if tid is None:
            messagebox.showinfo("Select Team", "Choose a target Rescue Team in 'Assigned Rescue Team'.")
            return
        try:
            self.vehicle_mgr.assign_vehicle_to_team(self._selected_id, tid)
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Assignment Error", str(exc))

    def _release(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Vehicle", "Select a vehicle first.")
            return
        try:
            self.vehicle_mgr.release_vehicle(self._selected_id)
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Release Error", str(exc))

    def _delete(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Vehicle", "Select a vehicle first.")
            return
        cur = self.vehicle_mgr.get_vehicle(self._selected_id)
        if cur is None:
            return
        if not messagebox.askyesno("Confirm Delete", f"Delete vehicle '{cur.registration_number}'?"):
            return
        self.vehicle_mgr.delete_vehicle(self._selected_id)
        self._clear_form()
        self.on_data_changed()


class VolunteersTab(tk.Frame):
    """Volunteer registry with strict contact privacy masking in public lists & maps."""

    def __init__(
        self,
        parent: tk.Misc,
        volunteer_mgr: VolunteerManager,
        op_mgr: OperationManager,
        on_data_changed: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=10, pady=8)
        self.volunteer_mgr = volunteer_mgr
        self.op_mgr = op_mgr
        self.on_data_changed = on_data_changed

        self._neighbourhood: Neighbourhood | None = None
        self._volunteers: list[VolunteerRecord] = []
        self._operations: list[EmergencyOperationRecord] = []
        self._selected_id: int | None = None
        self._show_private = tk.BooleanVar(value=False)
        self._build_ui()

    def _build_ui(self) -> None:
        priv = tk.Frame(
            self,
            bg=THEME["info_bg"],
            highlightbackground=THEME["info"],
            highlightthickness=1,
            padx=10,
            pady=5,
        )
        priv.pack(fill="x", pady=(0, 8))
        tk.Label(
            priv,
            text=(
                "PRIVACY PROTECTION: Volunteer personal phone numbers and emergency contacts are REDACTED/MASKED (`******XXXX`) "
                "in lists, never plotted on maps, and redacted from default exports unless explicitly authorized."
            ),
            bg=THEME["info_bg"],
            fg="#BAE6FD",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            justify="left",
            wraplength=980,
        ).pack(anchor="w", fill="x")

        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        outer = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=345,
        )
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        outer.grid_propagate(False)
        outer.pack_propagate(False)

        form = tk.Frame(outer, bg=THEME["bg_card"], padx=10, pady=8)
        form.pack(fill="both", expand=True)

        tk.Label(
            form,
            text="VOLUNTEER REGISTRATION FORM",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(0, 6))

        self.var_name = tk.StringVar()
        self.var_contact = tk.StringVar()
        self.var_emerg = tk.StringVar()
        self.var_skills = tk.StringVar()
        self.var_avail = tk.StringVar(value=VOLUNTEER_AVAILABILITY_OPTIONS[0])
        self.var_area = tk.StringVar()
        self.var_op = tk.StringVar(value="Unassigned")
        self.var_notes = tk.StringVar()

        tk.Label(form, text="Full Name *:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x", pady=(2, 1)
        )
        ttk.Entry(form, textvariable=self.var_name).pack(fill="x", pady=(0, 3))

        tk.Label(form, text="Contact (Masked by Default):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x", pady=(2, 1)
        )
        self.ent_contact = ttk.Entry(form, textvariable=self.var_contact, show="*")
        self.ent_contact.pack(fill="x", pady=(0, 3))

        tk.Label(form, text="Emergency Contact (Protected):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x", pady=(2, 1)
        )
        self.ent_emerg = ttk.Entry(form, textvariable=self.var_emerg, show="*")
        self.ent_emerg.pack(fill="x", pady=(0, 3))

        ttk.Checkbutton(
            form,
            text="Operator Reveal Contacts in Form Only",
            variable=self._show_private,
            command=self._toggle_mask_fields,
        ).pack(anchor="w", fill="x", pady=(1, 4))

        for lbl, var in [
            ("Skills (e.g., First Aid, Logistics):", self.var_skills),
            ("Preferred Potheri Area:", self.var_area),
        ]:
            tk.Label(form, text=lbl, bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
                anchor="w", fill="x", pady=(2, 1)
            )
            ttk.Entry(form, textvariable=var).pack(fill="x", pady=(0, 3))

        tk.Label(form, text="Availability:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x", pady=(2, 1)
        )
        ttk.Combobox(form, textvariable=self.var_avail, values=VOLUNTEER_AVAILABILITY_OPTIONS, state="readonly").pack(
            fill="x", pady=(0, 3)
        )

        tk.Label(form, text="Assign to Operation:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x", pady=(2, 1)
        )
        self.op_cb = ttk.Combobox(form, textvariable=self.var_op, state="readonly")
        self.op_cb.pack(fill="x", pady=(0, 3))

        tk.Label(form, text="Notes:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x", pady=(2, 1)
        )
        ttk.Entry(form, textvariable=self.var_notes).pack(fill="x", pady=(0, 5))

        btns = tk.Frame(form, bg=THEME["bg_card"])
        btns.pack(fill="x", pady=(4, 2))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        ttk.Button(btns, text="Add Volunteer", style="Accent.TButton", command=self._add).grid(
            row=0, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Update Volunteer", command=self._update).grid(
            row=0, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btns, text="Assign to Operation", command=self._assign_op).grid(
            row=1, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Clear Assignment", command=self._clear_op).grid(
            row=1, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btns, text="Clear Form", command=self._clear_form).grid(
            row=2, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Remove Volunteer", command=self._delete).grid(
            row=2, column=1, sticky="ew", padx=(3, 0), pady=2
        )

        # Right side table (strictly masked contacts)
        right = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        filt = tk.Frame(right, bg=THEME["bg_card"])
        filt.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tk.Label(filt, text="Search:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_search = tk.StringVar()
        e_s = ttk.Entry(filt, textvariable=self.var_search, width=20)
        e_s.pack(side="left", padx=(4, 10))
        e_s.bind("<KeyRelease>", lambda _e: self.refresh())

        tk.Label(filt, text="Availability:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_filter = tk.StringVar(value="All")
        cb = ttk.Combobox(filt, textvariable=self.var_filter, values=("All",) + VOLUNTEER_AVAILABILITY_OPTIONS, state="readonly", width=12)
        cb.pack(side="left", padx=(4, 10))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        self.summary_lbl = tk.Label(filt, text="0 volunteer(s)", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 8, "bold"))
        self.summary_lbl.pack(side="right")

        cols = ("id", "name", "contact", "skills", "avail", "area", "op")
        wrap = tk.Frame(right, bg=THEME["bg_card"])
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for k, h, w in [
            ("id", "ID", 40),
            ("name", "Name", 145),
            ("contact", "Contact (Masked)", 115),
            ("skills", "Skills", 155),
            ("avail", "Availability", 95),
            ("area", "Preferred Area", 130),
            ("op", "Assigned Operation", 160),
        ]:
            self.tree.heading(k, text=h)
            self.tree.column(k, width=w, anchor="e" if k == "id" else "w")
        vsb_t = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb_t.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb_t.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def _toggle_mask_fields(self) -> None:
        ch = "" if self._show_private.get() else "*"
        self.ent_contact.configure(show=ch)
        self.ent_emerg.configure(show=ch)

    def set_neighbourhood(self, neighbourhood: Neighbourhood | None) -> None:
        if (neighbourhood.id if neighbourhood else None) != (self._neighbourhood.id if self._neighbourhood else None):
            self._selected_id = None
            self._clear_form()
        self._neighbourhood = neighbourhood
        self.refresh()

    def refresh(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        if self._neighbourhood is None or self._neighbourhood.id is None:
            self._volunteers = []
            self._operations = []
            self.op_cb.configure(values=("Unassigned",))
            self.summary_lbl.configure(text="No active workspace")
            return
        self._operations = self.op_mgr.list_operations(self._neighbourhood.id)
        op_vals = ["Unassigned"] + [
            f"#{o.id}: {o.operation_name}" for o in self._operations if o.status not in ("Completed", "Cancelled")
        ]
        self.op_cb.configure(values=op_vals)

        self._volunteers = self.volunteer_mgr.list_volunteers(
            self._neighbourhood.id,
            search=self.var_search.get(),
            status_filter=self.var_filter.get(),
        )
        avail = sum(1 for v in self._volunteers if v.availability == "Available")
        self.summary_lbl.configure(text=f"{len(self._volunteers)} volunteer(s) • {avail} available")
        for v in self._volunteers:
            self.tree.insert(
                "",
                "end",
                iid=str(v.id),
                values=(
                    v.id,
                    v.name,
                    v.masked_contact,
                    v.skills,
                    v.availability,
                    v.preferred_area,
                    v.assigned_operation_name or "Unassigned",
                ),
            )

    def _selected_op_id(self) -> int | None:
        txt = self.var_op.get()
        if not txt.startswith("#"):
            return None
        try:
            return int(txt.split(":", 1)[0][1:])
        except ValueError:
            return None

    def _clear_form(self) -> None:
        self._selected_id = None
        for v in (self.var_name, self.var_contact, self.var_emerg, self.var_skills, self.var_area, self.var_notes):
            v.set("")
        self.var_avail.set("Available")
        self.var_op.set("Unassigned")

    def _on_select(self, _evt=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        vid = int(sel[0])
        v = next((x for x in self._volunteers if x.id == vid), None)
        if v is None:
            return
        self._selected_id = v.id
        self.var_name.set(v.name)
        self.var_contact.set(v.contact)
        self.var_emerg.set(v.emergency_contact)
        self.var_skills.set(v.skills)
        self.var_avail.set(v.availability)
        self.var_area.set(v.preferred_area)
        self.var_op.set(
            f"#{v.assigned_operation_id}: {v.assigned_operation_name}" if v.assigned_operation_id else "Unassigned"
        )
        self.var_notes.set(v.notes)

    def _add(self) -> None:
        if self._neighbourhood is None or self._neighbourhood.id is None:
            return
        try:
            rec = self.volunteer_mgr.add_volunteer(
                neighbourhood_id=self._neighbourhood.id,
                name=self.var_name.get(),
                contact=self.var_contact.get(),
                emergency_contact=self.var_emerg.get(),
                skills=self.var_skills.get(),
                availability=self.var_avail.get(),
                preferred_area=self.var_area.get(),
                notes=self.var_notes.get(),
            )
            self._selected_id = rec.id
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _update(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Volunteer", "Select a volunteer row first.")
            return
        try:
            self.volunteer_mgr.update_volunteer(
                volunteer_id=self._selected_id,
                name=self.var_name.get(),
                contact=self.var_contact.get(),
                emergency_contact=self.var_emerg.get(),
                skills=self.var_skills.get(),
                availability=self.var_avail.get(),
                preferred_area=self.var_area.get(),
                notes=self.var_notes.get(),
            )
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _assign_op(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Volunteer", "Select a volunteer first.")
            return
        oid = self._selected_op_id()
        if oid is None:
            messagebox.showinfo("Select Operation", "Choose an active operation in 'Assign to Operation'.")
            return
        try:
            self.volunteer_mgr.assign_to_operation(self._selected_id, oid)
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Assignment Error", str(exc))

    def _clear_op(self) -> None:
        if self._selected_id is None:
            return
        try:
            self.volunteer_mgr.assign_to_operation(self._selected_id, None)
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Error", str(exc))

    def _delete(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Volunteer", "Select a volunteer first.")
            return
        cur = self.volunteer_mgr.get_volunteer(self._selected_id)
        if cur is None:
            return
        if not messagebox.askyesno("Confirm Delete", f"Remove volunteer '{cur.name}'?"):
            return
        self.volunteer_mgr.remove_volunteer(self._selected_id)
        self._clear_form()
        self.on_data_changed()
