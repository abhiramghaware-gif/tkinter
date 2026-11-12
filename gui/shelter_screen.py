"""Phase 6 Shelter Management tab (CRUD, occupancy limits, verification, SafeRoute handoff)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from config import SHELTER_FACILITY_OPTIONS, SHELTER_SOURCE_OPTIONS, SHELTER_STATUS_OPTIONS, THEME
from core.models import Neighbourhood
from core.validation import ValidationError
from emergency.shelter_manager import ShelterManager, ShelterRecord


class SheltersTab(tk.Frame):
    """Emergency Shelter registration, capacity tracking, and SafeRoute navigation tab."""

    def __init__(
        self,
        parent: tk.Misc,
        shelter_mgr: ShelterManager,
        on_data_changed: Callable[[], None],
        on_plan_route_to_shelter: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=10, pady=8)
        self.shelter_mgr = shelter_mgr
        self.on_data_changed = on_data_changed
        self.on_plan_route_to_shelter = on_plan_route_to_shelter

        self._neighbourhood: Neighbourhood | None = None
        self._shelters: list[ShelterRecord] = []
        self._selected_id: int | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        # Top info banner
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
                "SHELTER REGISTRY NOTICE: Distinguish 'Registered (Unverified)' entries from 'Physically Verified' field sites. "
                "Occupied capacity is strictly validated <= Total capacity."
            ),
            bg=THEME["warning_bg"],
            fg="#FDE68A",
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

        # Left fixed-width scrollable form
        outer = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=355,
        )
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        outer.grid_propagate(False)
        outer.pack_propagate(False)

        canvas = tk.Canvas(outer, bg=THEME["bg_card"], highlightthickness=0, width=333)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        form = tk.Frame(canvas, bg=THEME["bg_card"], padx=10, pady=8)
        form.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=form, anchor="nw", width=333)
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        tk.Label(
            form,
            text="SHELTER DETAILS FORM",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(0, 6))

        self.var_name = tk.StringVar()
        self.var_address = tk.StringVar()
        self.var_lat = tk.StringVar()
        self.var_lon = tk.StringVar()
        self.var_total = tk.StringVar(value="100")
        self.var_occupied = tk.StringVar(value="0")
        self.var_contact = tk.StringVar()
        self.var_status = tk.StringVar(value=SHELTER_STATUS_OPTIONS[0])
        self.var_source = tk.StringVar(value=SHELTER_SOURCE_OPTIONS[0])
        self.var_verified = tk.BooleanVar(value=False)
        self.var_access = tk.StringVar()
        self.var_notes = tk.StringVar()

        def add_field(lbl_txt: str, var: tk.StringVar) -> ttk.Entry:
            tk.Label(
                form, text=lbl_txt, bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w"
            ).pack(anchor="w", fill="x", pady=(2, 1))
            ent = ttk.Entry(form, textvariable=var)
            ent.pack(fill="x", pady=(0, 3))
            return ent

        add_field("Shelter Name *:", self.var_name)
        add_field("Address / Landmark:", self.var_address)

        coords_row = tk.Frame(form, bg=THEME["bg_card"])
        coords_row.pack(fill="x", pady=(2, 3))
        coords_row.columnconfigure(0, weight=1)
        coords_row.columnconfigure(1, weight=1)
        tk.Label(coords_row, text="Latitude *:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(coords_row, text="Longitude *:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        ttk.Entry(coords_row, textvariable=self.var_lat).grid(row=1, column=0, sticky="ew", padx=(0, 3))
        ttk.Entry(coords_row, textvariable=self.var_lon).grid(row=1, column=1, sticky="ew", padx=(3, 0))

        cap_row = tk.Frame(form, bg=THEME["bg_card"])
        cap_row.pack(fill="x", pady=(2, 3))
        cap_row.columnconfigure(0, weight=1)
        cap_row.columnconfigure(1, weight=1)
        tk.Label(cap_row, text="Total Capacity *:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(cap_row, text="Occupied Capacity:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        e_tot = ttk.Entry(cap_row, textvariable=self.var_total)
        e_tot.grid(row=1, column=0, sticky="ew", padx=(0, 3))
        e_occ = ttk.Entry(cap_row, textvariable=self.var_occupied)
        e_occ.grid(row=1, column=1, sticky="ew", padx=(3, 0))
        e_tot.bind("<KeyRelease>", lambda _e: self._update_avail_preview())
        e_occ.bind("<KeyRelease>", lambda _e: self._update_avail_preview())

        self.avail_preview_lbl = tk.Label(
            form,
            text="Available Capacity: 100 spaces",
            bg=THEME["bg_input"],
            fg=THEME["accent_teal"],
            font=("Segoe UI", 8, "bold"),
            padx=6,
            pady=3,
            anchor="w",
        )
        self.avail_preview_lbl.pack(fill="x", pady=(0, 4))

        st_row = tk.Frame(form, bg=THEME["bg_card"])
        st_row.pack(fill="x", pady=(2, 3))
        st_row.columnconfigure(0, weight=1)
        st_row.columnconfigure(1, weight=1)
        tk.Label(st_row, text="Status:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(st_row, text="Data Source:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        ttk.Combobox(st_row, textvariable=self.var_status, values=SHELTER_STATUS_OPTIONS, state="readonly").grid(
            row=1, column=0, sticky="ew", padx=(0, 3)
        )
        ttk.Combobox(st_row, textvariable=self.var_source, values=SHELTER_SOURCE_OPTIONS, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=(3, 0)
        )

        ttk.Checkbutton(
            form,
            text="Physically Verified Field Shelter",
            variable=self.var_verified,
        ).pack(anchor="w", fill="x", pady=(3, 4))

        tk.Label(
            form, text="Facilities Available:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w"
        ).pack(anchor="w", fill="x", pady=(2, 1))
        self.facility_vars: dict[str, tk.BooleanVar] = {}
        fac_box = tk.Frame(form, bg=THEME["bg_input"], padx=6, pady=4)
        fac_box.pack(fill="x", pady=(0, 4))
        for fac in SHELTER_FACILITY_OPTIONS:
            v = tk.BooleanVar(value=False)
            self.facility_vars[fac] = v
            ttk.Checkbutton(fac_box, text=fac, variable=v).pack(anchor="w")

        add_field("Contact Info (Operator Desk):", self.var_contact)
        add_field("Accessibility (e.g., Ramp / Ground Floor):", self.var_access)
        add_field("Notes:", self.var_notes)

        btn_grid = tk.Frame(form, bg=THEME["bg_card"])
        btn_grid.pack(fill="x", pady=(6, 4))
        btn_grid.columnconfigure(0, weight=1)
        btn_grid.columnconfigure(1, weight=1)
        ttk.Button(btn_grid, text="Register Shelter", style="Accent.TButton", command=self._register).grid(
            row=0, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btn_grid, text="Update Selected", command=self._update).grid(
            row=0, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btn_grid, text="Toggle Active/Inactive", command=self._toggle_active).grid(
            row=1, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btn_grid, text="Delete Selected", command=self._delete).grid(
            row=1, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(form, text="Clear Form / Use Centre Coords", command=self._clear_form).pack(fill="x", pady=(2, 4))

        if self.on_plan_route_to_shelter is not None:
            ttk.Button(
                form,
                text="Plan Evacuation Route in SafeRoute ->",
                style="Accent.TButton",
                command=self._send_to_saferoute,
            ).pack(fill="x", pady=(4, 2))

        # Right side: filter + summary + treeview
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
        ent_s = ttk.Entry(filt, textvariable=self.var_search, width=22)
        ent_s.pack(side="left", padx=(4, 10))
        ent_s.bind("<KeyRelease>", lambda _e: self.refresh())

        tk.Label(filt, text="Status:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.var_filter_status = tk.StringVar(value="All")
        cb_f = ttk.Combobox(
            filt,
            textvariable=self.var_filter_status,
            values=("All",) + SHELTER_STATUS_OPTIONS,
            state="readonly",
            width=12,
        )
        cb_f.pack(side="left", padx=(4, 10))
        cb_f.bind("<<ComboboxSelected>>", lambda _e: self.refresh())

        self.summary_lbl = tk.Label(
            filt,
            text="0 shelter(s)",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 8, "bold"),
        )
        self.summary_lbl.pack(side="right")

        cols = ("id", "name", "occ_tot", "avail", "status", "verified", "facilities", "address")
        tree_wrap = tk.Frame(right, bg=THEME["bg_card"])
        tree_wrap.grid(row=1, column=0, sticky="nsew")
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", selectmode="browse")
        specs = [
            ("id", "ID", 42),
            ("name", "Shelter Name", 170),
            ("occ_tot", "Occ / Total", 88),
            ("avail", "Avail", 55),
            ("status", "Status", 76),
            ("verified", "Verification", 125),
            ("facilities", "Facilities", 170),
            ("address", "Address", 170),
        ]
        for k, hdr_txt, w in specs:
            self.tree.heading(k, text=hdr_txt)
            self.tree.column(k, width=w, anchor="e" if k in ("id", "occ_tot", "avail") else "w")
        vsb_t = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb_t.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb_t.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

    def set_neighbourhood(self, neighbourhood: Neighbourhood | None) -> None:
        changed = (
            (neighbourhood.id if neighbourhood else None)
            != (self._neighbourhood.id if self._neighbourhood else None)
        )
        self._neighbourhood = neighbourhood
        if changed:
            self._selected_id = None
            self._clear_form()
        self.refresh()

    def refresh(self) -> None:
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)
        if self._neighbourhood is None or self._neighbourhood.id is None:
            self._shelters = []
            self.summary_lbl.configure(text="No active neighbourhood")
            return
        self._shelters = self.shelter_mgr.list_shelters(
            self._neighbourhood.id,
            status_filter=self.var_filter_status.get(),
            search=self.var_search.get(),
        )
        tot_cap = sum(s.total_capacity for s in self._shelters)
        avail_cap = sum(s.available_capacity for s in self._shelters)
        self.summary_lbl.configure(
            text=f"{len(self._shelters)} shelter(s) • Avail {avail_cap:,} / {tot_cap:,}"
        )
        for s in self._shelters:
            self.tree.insert(
                "",
                "end",
                iid=str(s.id),
                values=(
                    s.id,
                    s.name,
                    f"{s.occupied_capacity} / {s.total_capacity}",
                    s.available_capacity,
                    s.status,
                    s.verification_label,
                    s.facilities_summary,
                    s.address,
                ),
            )

    def _update_avail_preview(self) -> None:
        try:
            tot = int(self.var_total.get())
            occ = int(self.var_occupied.get())
            if occ > tot:
                self.avail_preview_lbl.configure(
                    text=f"INVALID: Occupied ({occ}) > Total ({tot})",
                    fg=THEME["error"],
                )
            else:
                self.avail_preview_lbl.configure(
                    text=f"Available Capacity: {max(0, tot - occ)} spaces",
                    fg=THEME["accent_teal"],
                )
        except ValueError:
            self.avail_preview_lbl.configure(text="Available Capacity: Enter whole integers", fg=THEME["warning"])

    def _selected_facilities(self) -> list[str]:
        return [fac for fac, var in self.facility_vars.items() if var.get()]

    def _clear_form(self) -> None:
        self._selected_id = None
        self.var_name.set("")
        self.var_address.set("")
        if self._neighbourhood is not None:
            self.var_lat.set(f"{self._neighbourhood.center_latitude:.6f}")
            self.var_lon.set(f"{self._neighbourhood.center_longitude:.6f}")
        else:
            self.var_lat.set("")
            self.var_lon.set("")
        self.var_total.set("100")
        self.var_occupied.set("0")
        self.var_contact.set("")
        self.var_status.set("Active")
        self.var_source.set("user-entered")
        self.var_verified.set(False)
        self.var_access.set("")
        self.var_notes.set("")
        for var in self.facility_vars.values():
            var.set(False)
        self._update_avail_preview()

    def _on_select(self, _evt=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        sid = int(sel[0])
        s = next((x for x in self._shelters if x.id == sid), None)
        if s is None:
            return
        self._selected_id = s.id
        self.var_name.set(s.name)
        self.var_address.set(s.address)
        self.var_lat.set(f"{s.latitude:.6f}")
        self.var_lon.set(f"{s.longitude:.6f}")
        self.var_total.set(str(s.total_capacity))
        self.var_occupied.set(str(s.occupied_capacity))
        self.var_contact.set(s.contact_info)
        self.var_status.set(s.status)
        self.var_source.set(s.source)
        self.var_verified.set(bool(s.is_verified))
        self.var_access.set(s.accessibility)
        self.var_notes.set(s.notes)
        fac_set = set(s.facilities)
        for fac, var in self.facility_vars.items():
            var.set(fac in fac_set)
        self._update_avail_preview()

    def _register(self) -> None:
        if self._neighbourhood is None or self._neighbourhood.id is None:
            messagebox.showinfo("No Workspace", "Load or create a neighbourhood workspace first.")
            return
        try:
            rec = self.shelter_mgr.register_shelter(
                neighbourhood_id=self._neighbourhood.id,
                name=self.var_name.get(),
                address=self.var_address.get(),
                latitude=self.var_lat.get(),
                longitude=self.var_lon.get(),
                total_capacity=self.var_total.get(),
                occupied_capacity=self.var_occupied.get(),
                contact_info=self.var_contact.get(),
                status=self.var_status.get(),
                facilities=self._selected_facilities(),
                accessibility=self.var_access.get(),
                source=self.var_source.get(),
                is_verified=bool(self.var_verified.get()),
                notes=self.var_notes.get(),
            )
            self._selected_id = rec.id
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _update(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Shelter", "Select an existing shelter row to update.")
            return
        try:
            self.shelter_mgr.update_shelter(
                shelter_id=self._selected_id,
                name=self.var_name.get(),
                address=self.var_address.get(),
                latitude=self.var_lat.get(),
                longitude=self.var_lon.get(),
                total_capacity=self.var_total.get(),
                occupied_capacity=self.var_occupied.get(),
                contact_info=self.var_contact.get(),
                status=self.var_status.get(),
                facilities=self._selected_facilities(),
                accessibility=self.var_access.get(),
                source=self.var_source.get(),
                is_verified=bool(self.var_verified.get()),
                notes=self.var_notes.get(),
            )
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))

    def _toggle_active(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Shelter", "Select a shelter first.")
            return
        cur = self.shelter_mgr.get_shelter(self._selected_id)
        if cur is None:
            return
        target = "Inactive" if cur.status in ("Active", "Full") else "Active"
        try:
            self.shelter_mgr.set_shelter_status(self._selected_id, target)
            self.on_data_changed()
        except ValidationError as exc:
            messagebox.showerror("Status Error", str(exc))

    def _delete(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Shelter", "Select a shelter row to delete.")
            return
        cur = self.shelter_mgr.get_shelter(self._selected_id)
        if cur is None:
            return
        if not messagebox.askyesno(
            "Confirm Shelter Deletion",
            f"Permanently delete shelter '{cur.name}' (#{cur.id}) from SQLite?",
        ):
            return
        self.shelter_mgr.delete_shelter(self._selected_id)
        self._clear_form()
        self.on_data_changed()

    def _send_to_saferoute(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select Shelter", "Select a registered shelter row first.")
            return
        if self.on_plan_route_to_shelter is not None:
            self.on_plan_route_to_shelter(self._selected_id)
