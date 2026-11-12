"""Phase 6 Emergency Operations, Alerts & Reports GUI tabs."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from config import (
    ALERT_SEVERITIES,
    EXPORTS_DIR,
    OPERATION_PRIORITIES,
    OPERATION_STATUS_OPTIONS,
    OPERATION_TYPES,
    THEME,
)
from core.models import Neighbourhood
from core.validation import ValidationError
from database.db import DatabaseManager
from emergency.alert_manager import AlertManager, EmergencyAlertRecord
from emergency.emergency_exports import REPORT_REGISTRY
from emergency.operation_manager import EmergencyOperationRecord, OperationManager
from emergency.rescue_team_manager import RescueTeamManager, RescueTeamRecord
from emergency.shelter_manager import ShelterManager, ShelterRecord
from emergency.vehicle_manager import VehicleManager, VehicleRecord


class OperationsTab(tk.Frame):
    """Manual relief & rescue operation coordinator with chronological status notes."""

    def __init__(
        self,
        parent: tk.Misc,
        op_mgr: OperationManager,
        shelter_mgr: ShelterManager,
        team_mgr: RescueTeamManager,
        vehicle_mgr: VehicleManager,
        on_data_changed: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=10, pady=8)
        self.op_mgr = op_mgr
        self.shelter_mgr = shelter_mgr
        self.team_mgr = team_mgr
        self.vehicle_mgr = vehicle_mgr
        self.on_data_changed = on_data_changed

        self._neighbourhood: Neighbourhood | None = None
        self._operations: list[EmergencyOperationRecord] = []
        self._shelters: list[ShelterRecord] = []
        self._teams: list[RescueTeamRecord] = []
        self._vehicles: list[VehicleRecord] = []
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
            width=352,
        )
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        outer.grid_propagate(False)
        outer.pack_propagate(False)

        canvas = tk.Canvas(outer, bg=THEME["bg_card"], highlightthickness=0, width=330)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        form = tk.Frame(canvas, bg=THEME["bg_card"], padx=10, pady=8)
        form.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=form, anchor="nw", width=330)
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        tk.Label(
            form,
            text="EMERGENCY OPERATION LOG",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(0, 6))

        self.var_name = tk.StringVar()
        self.var_type = tk.StringVar(value=OPERATION_TYPES[0])
        self.var_prio = tk.StringVar(value=OPERATION_PRIORITIES[1])
        self.var_start = tk.StringVar()
        self.var_dest = tk.StringVar()
        self.var_shelter = tk.StringVar(value="None")
        self.var_team = tk.StringVar(value="Unassigned")
        self.var_veh = tk.StringVar(value="Unassigned")
        self.var_status = tk.StringVar(value=OPERATION_STATUS_OPTIONS[0])
        self.var_notes = tk.StringVar()

        def field(lbl: str, var: tk.StringVar) -> None:
            tk.Label(form, text=lbl, bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
                anchor="w", fill="x", pady=(2, 1)
            )
            ttk.Entry(form, textvariable=var).pack(fill="x", pady=(0, 3))

        field("Operation Name *:", self.var_name)

        tk.Label(form, text="Operation Type:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        ttk.Combobox(form, textvariable=self.var_type, values=OPERATION_TYPES, state="readonly").pack(fill="x", pady=(0, 3))

        row_ps = tk.Frame(form, bg=THEME["bg_card"])
        row_ps.pack(fill="x", pady=(2, 3))
        row_ps.columnconfigure(0, weight=1)
        row_ps.columnconfigure(1, weight=1)
        tk.Label(row_ps, text="Priority:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w")
        tk.Label(row_ps, text="Initial Status:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        ttk.Combobox(row_ps, textvariable=self.var_prio, values=OPERATION_PRIORITIES, state="readonly").grid(
            row=1, column=0, sticky="ew", padx=(0, 3)
        )
        ttk.Combobox(row_ps, textvariable=self.var_status, values=OPERATION_STATUS_OPTIONS, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=(3, 0)
        )

        field("Start Location:", self.var_start)
        field("Destination Description:", self.var_dest)

        tk.Label(form, text="Destination Shelter (Optional):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        self.shelter_cb = ttk.Combobox(form, textvariable=self.var_shelter, state="readonly")
        self.shelter_cb.pack(fill="x", pady=(0, 3))

        tk.Label(form, text="Assigned Rescue Team:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        self.team_cb = ttk.Combobox(form, textvariable=self.var_team, state="readonly")
        self.team_cb.pack(fill="x", pady=(0, 3))

        tk.Label(form, text="Assigned Vehicle:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        self.veh_cb = ttk.Combobox(form, textvariable=self.var_veh, state="readonly")
        self.veh_cb.pack(fill="x", pady=(0, 3))

        field("Operation Notes:", self.var_notes)

        btns = tk.Frame(form, bg=THEME["bg_card"])
        btns.pack(fill="x", pady=(6, 4))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        ttk.Button(btns, text="Create Operation", style="Accent.TButton", command=self._create).grid(
            row=0, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Clear Form", command=self._clear_form).grid(
            row=0, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btns, text="Set In Progress", command=lambda: self._set_status("In progress")).grid(
            row=1, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Mark Completed", command=lambda: self._set_status("Completed")).grid(
            row=1, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btns, text="Cancel Operation", command=lambda: self._set_status("Cancelled")).grid(
            row=2, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btns, text="Delete Selected", command=self._delete).grid(
            row=2, column=1, sticky="ew", padx=(3, 0), pady=2
        )

        # Right side: filter + table + log notes box
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
        tk.Label(filt, text="Status:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_filter = tk.StringVar(value="All")
        cb = ttk.Combobox(filt, textvariable=self.var_filter, values=("All",) + OPERATION_STATUS_OPTIONS, state="readonly", width=13)
        cb.pack(side="left", padx=(4, 10))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        self.summary_lbl = tk.Label(filt, text="0 operation(s)", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 8, "bold"))
        self.summary_lbl.pack(side="right")

        cols = ("id", "name", "type", "prio", "status", "dest", "team", "veh", "start", "done")
        wrap = tk.Frame(right, bg=THEME["bg_card"])
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for k, h, w in [
            ("id", "ID", 36),
            ("name", "Operation Name", 155),
            ("type", "Type", 130),
            ("prio", "Priority", 65),
            ("status", "Status", 88),
            ("dest", "Destination", 125),
            ("team", "Team", 110),
            ("veh", "Vehicle", 110),
            ("start", "Started", 110),
            ("done", "Completed", 110),
        ]:
            self.tree.heading(k, text=h)
            self.tree.column(k, width=w, anchor="e" if k == "id" else "w")
        vsb_t = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb_t.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb_t.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        tk.Label(
            right,
            text="SELECTED OPERATION CHRONOLOGICAL NOTES",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).grid(row=2, column=0, sticky="w", pady=(8, 3))
        self.notes_view = tk.Text(
            right,
            height=5,
            bg=THEME["bg_input"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 8),
            wrap="word",
            bd=0,
            padx=8,
            pady=6,
            state="disabled",
        )
        self.notes_view.grid(row=3, column=0, sticky="ew")

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
            self._operations = []
            self.summary_lbl.configure(text="No active workspace")
            return
        nid = self._neighbourhood.id
        self._shelters = self.shelter_mgr.list_shelters(nid)
        self._teams = self.team_mgr.list_teams(nid)
        self._vehicles = self.vehicle_mgr.list_vehicles(nid)

        self.shelter_cb.configure(values=["None"] + [f"#{s.id}: {s.name}" for s in self._shelters])
        self.team_cb.configure(values=["Unassigned"] + [f"#{t.id}: {t.team_name}" for t in self._teams])
        self.veh_cb.configure(values=["Unassigned"] + [f"#{v.id}: {v.registration_number} ({v.vehicle_type})" for v in self._vehicles])

        self._operations = self.op_mgr.list_operations(nid, status_filter=self.var_filter.get())
        active_cnt = sum(1 for o in self._operations if o.status in ("Planned", "Ready", "In progress"))
        self.summary_lbl.configure(text=f"{len(self._operations)} operation(s) • {active_cnt} open")
        for o in self._operations:
            self.tree.insert(
                "",
                "end",
                iid=str(o.id),
                values=(
                    o.id,
                    o.operation_name,
                    o.operation_type,
                    o.priority,
                    o.status,
                    o.destination,
                    o.assigned_team_name or "Unassigned",
                    o.assigned_vehicle_label or "Unassigned",
                    o.start_time or "—",
                    o.completion_time or "—",
                ),
            )

    @staticmethod
    def _parse_prefixed_id(val: str) -> int | None:
        if not val.startswith("#"):
            return None
        try:
            return int(val.split(":", 1)[0][1:])
        except ValueError:
            return None

    def _clear_form(self) -> None:
        self._selected_id = None
        self.var_name.set("")
        self.var_type.set(OPERATION_TYPES[0])
        self.var_prio.set("Medium")
        self.var_start.set("")
        self.var_dest.set("")
        self.var_shelter.set("None")
        self.var_team.set("Unassigned")
        self.var_veh.set("Unassigned")
        self.var_status.set("Planned")
        self.var_notes.set("")

    def _on_select(self, _evt=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        oid = int(sel[0])
        op = next((x for x in self._operations if x.id == oid), None)
        if op is None:
            return
        self._selected_id = op.id
        self.var_name.set(op.operation_name)
        self.var_type.set(op.operation_type)
        self.var_prio.set(op.priority)
        self.var_start.set(op.start_location)
        self.var_dest.set(op.destination)
        self.var_status.set(op.status)
        self.notes_view.configure(state="normal")
        self.notes_view.delete("1.0", "end")
        self.notes_view.insert("1.0", op.notes or "(No operation notes recorded)")
        self.notes_view.configure(state="disabled")

    def _create(self) -> None:
        if self._neighbourhood is None or self._neighbourhood.id is None:
            return
        dest = self.var_dest.get().strip()
        sh_id = self._parse_prefixed_id(self.var_shelter.get())
        if not dest and sh_id is not None:
            sh = next((s for s in self._shelters if s.id == sh_id), None)
            if sh:
                dest = sh.name
        try:
            rec = self.op_mgr.create_operation(
                neighbourhood_id=self._neighbourhood.id,
                operation_name=self.var_name.get(),
                operation_type=self.var_type.get(),
                priority=self.var_prio.get(),
                start_location=self.var_start.get(),
                destination=dest,
                destination_shelter_id=sh_id,
                assigned_team_id=self._parse_prefixed_id(self.var_team.get()),
                assigned_vehicle_id=self._parse_prefixed_id(self.var_veh.get()),
                status=self.var_status.get(),
                notes=self.var_notes.get(),
            )
            self._selected_id = rec.id
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _set_status(self, new_status: str) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Operation", "Select an operation row first.")
            return
        note = simpledialog.askstring(
            f"Update Operation Status -> {new_status}",
            "Optional progress/completion note (blank if none):",
            parent=self,
        )
        if note is None:
            return
        try:
            self.op_mgr.update_operation_status(self._selected_id, new_status, notes=note)
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Status Error", str(exc))

    def _delete(self) -> None:
        if self._selected_id is None:
            return
        cur = self.op_mgr.get_operation(self._selected_id)
        if cur is None:
            return
        if not messagebox.askyesno("Confirm Delete", f"Delete operation '{cur.operation_name}'?"):
            return
        self.op_mgr.delete_operation(self._selected_id)
        self._clear_form()
        self.on_data_changed()


class AlertsTab(tk.Frame):
    """Rule-driven emergency alert center backed strictly by SQLite state."""

    def __init__(
        self,
        parent: tk.Misc,
        alert_mgr: AlertManager,
        on_data_changed: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=10, pady=8)
        self.alert_mgr = alert_mgr
        self.on_data_changed = on_data_changed

        self._neighbourhood: Neighbourhood | None = None
        self._alerts: list[EmergencyAlertRecord] = []
        self._build_ui()

    def _build_ui(self) -> None:
        banner = tk.Frame(
            self,
            bg=THEME["warning_bg"],
            highlightbackground=THEME["warning"],
            highlightthickness=1,
            padx=10,
            pady=5,
        )
        banner.pack(fill="x", pady=(0, 8))
        tk.Label(
            banner,
            text=(
                "RULE-BASED RESOURCE ALERTS: Triggered solely by real SQLite state (low/zero stock, expired/near-expiry supplies, "
                "full or low-capacity shelters, unavailable vehicles/teams, unlinked allocations). Never shows fake incident alerts."
            ),
            bg=THEME["warning_bg"],
            fg="#FDE68A",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            justify="left",
            wraplength=980,
        ).pack(anchor="w", fill="x")

        bar = tk.Frame(
            self,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=7,
        )
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="Reconcile Alerts Now", style="Accent.TButton", command=self._reconcile_now).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(bar, text="Acknowledge Selected", command=self._ack_selected).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Acknowledge All", command=self._ack_all).pack(side="left", padx=(0, 12))

        tk.Label(bar, text="Severity:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_sev = tk.StringVar(value="All")
        cb = ttk.Combobox(bar, textvariable=self.var_sev, values=("All",) + ALERT_SEVERITIES, state="readonly", width=11)
        cb.pack(side="left", padx=(4, 10))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        self.var_show_ack = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Show Acknowledged", variable=self.var_show_ack, command=self.refresh).pack(side="left")

        self.summary_lbl = tk.Label(bar, text="0 alert(s)", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 8, "bold"))
        self.summary_lbl.pack(side="right")

        card = tk.Frame(
            self,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        card.pack(fill="both", expand=True)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        cols = ("id", "sev", "type", "title", "desc", "ack", "created")
        self.tree = ttk.Treeview(card, columns=cols, show="headings", selectmode="browse")
        for k, h, w in [
            ("id", "ID", 38),
            ("sev", "Severity", 80),
            ("type", "Alert Type", 145),
            ("title", "Title", 210),
            ("desc", "Condition Details", 370),
            ("ack", "Status", 100),
            ("created", "Triggered UTC", 130),
        ]:
            self.tree.heading(k, text=h)
            self.tree.column(k, width=w, anchor="e" if k == "id" else "w")
        self.tree.tag_configure("Critical", foreground="#FCA5A5")
        self.tree.tag_configure("High", foreground="#FDBA74")
        self.tree.tag_configure("Warning", foreground="#FDE047")
        self.tree.tag_configure("Acked", foreground="#94A3B8")

        vsb = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

    def set_neighbourhood(self, neighbourhood: Neighbourhood | None) -> None:
        self._neighbourhood = neighbourhood
        self.refresh()

    def refresh(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        if self._neighbourhood is None or self._neighbourhood.id is None:
            self._alerts = []
            self.summary_lbl.configure(text="No active workspace")
            return
        self._alerts = self.alert_mgr.list_alerts(
            self._neighbourhood.id,
            include_acknowledged=bool(self.var_show_ack.get()),
            severity_filter=self.var_sev.get(),
        )
        unack = sum(1 for a in self._alerts if not a.acknowledged)
        self.summary_lbl.configure(text=f"{len(self._alerts)} alert(s) • {unack} unacknowledged")
        for a in self._alerts:
            tag = ("Acked",) if a.acknowledged else (a.severity,)
            self.tree.insert(
                "",
                "end",
                iid=str(a.id),
                values=(
                    a.id,
                    a.severity,
                    a.alert_type,
                    a.title,
                    a.description,
                    "Acknowledged" if a.acknowledged else "ACTIVE",
                    a.created_at,
                ),
                tags=tag,
            )

    def _reconcile_now(self) -> None:
        self.on_data_changed()

    def _ack_selected(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Select Alert", "Select an alert row first.")
            return
        self.alert_mgr.acknowledge_alert(int(sel[0]), acknowledged=True)
        self.on_data_changed()

    def _ack_all(self) -> None:
        if self._neighbourhood is None or self._neighbourhood.id is None:
            return
        self.alert_mgr.acknowledge_all(self._neighbourhood.id)
        self.on_data_changed()


class ReportsTab(tk.Frame):
    """CSV & PDF report exporter for all 10 Phase 6 emergency domains."""

    def __init__(self, parent: tk.Misc, db: DatabaseManager) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=12, pady=10)
        self.db = db
        self._neighbourhood: Neighbourhood | None = None
        self.var_authorize_contacts = tk.BooleanVar(value=False)
        self._build_ui()

    def _build_ui(self) -> None:
        hdr = tk.Frame(
            self,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        hdr.pack(fill="x", pady=(0, 10))
        tk.Label(
            hdr,
            text="EMERGENCY RESOURCE & RELIEF REPORTS (CSV / PDF)",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            hdr,
            text=(
                "Every exported CSV and PDF embeds: Project Name, UTC Generation Date, SQLite Schema Source, "
                "Registered (Unverified) vs Physically Verified distinction, and prototype decision-support disclaimers."
            ),
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
            wraplength=960,
        ).pack(anchor="w", pady=(3, 6))

        ttk.Checkbutton(
            hdr,
            text="Authorize inclusion of private volunteer phone contacts in Volunteer Report exports (unchecked = REDACTED - PROTECTED)",
            variable=self.var_authorize_contacts,
        ).pack(anchor="w")

        grid_card = tk.Frame(
            self,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        grid_card.pack(fill="both", expand=True)
        grid_card.columnconfigure(0, weight=1)
        grid_card.columnconfigure(1, weight=1)

        for idx, (slug, title, fn) in enumerate(REPORT_REGISTRY):
            r = idx // 2
            c = idx % 2
            box = tk.Frame(
                grid_card,
                bg=THEME["bg_input"],
                highlightbackground=THEME["border"],
                highlightthickness=1,
                padx=10,
                pady=8,
            )
            box.grid(row=r, column=c, sticky="ew", padx=6, pady=6)
            tk.Label(
                box,
                text=f"{idx + 1}. {title}",
                bg=THEME["bg_input"],
                fg=THEME["text_primary"],
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            ).pack(side="left", fill="x", expand=True)

            ttk.Button(
                box,
                text="PDF",
                width=6,
                command=lambda s=slug, t=title, f=fn: self._export(s, t, f, "pdf"),
            ).pack(side="right", padx=(4, 0))
            ttk.Button(
                box,
                text="CSV",
                width=6,
                style="Accent.TButton",
                command=lambda s=slug, t=title, f=fn: self._export(s, t, f, "csv"),
            ).pack(side="right")

    def set_neighbourhood(self, neighbourhood: Neighbourhood | None) -> None:
        self._neighbourhood = neighbourhood

    def _export(self, slug: str, title: str, fn, fmt: str) -> None:
        if self._neighbourhood is None or self._neighbourhood.id is None:
            messagebox.showinfo("No Workspace", "Load a neighbourhood workspace first.")
            return
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ws_clean = self._neighbourhood.name.lower().replace(" ", "_")
        ext = f".{fmt}"
        path = filedialog.asksaveasfilename(
            title=f"Export {title} ({fmt.upper()})",
            initialdir=str(EXPORTS_DIR),
            initialfile=f"{ws_clean}_{slug}{ext}",
            defaultextension=ext,
            filetypes=[(f"{fmt.upper()} files", f"*{ext}")],
        )
        if not path:
            return
        try:
            if slug == "volunteers":
                out = fn(
                    self.db,
                    self._neighbourhood,
                    Path(path),
                    fmt=fmt,
                    authorize_private_contacts=bool(self.var_authorize_contacts.get()),
                )
            else:
                out = fn(self.db, self._neighbourhood, Path(path), fmt=fmt)
            messagebox.showinfo("Export Complete", f"Saved {fmt.upper()} report to:\n{out}")
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc))
