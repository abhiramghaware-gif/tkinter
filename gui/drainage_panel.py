"""Phase 2 Drainage Infrastructure Editor view."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from config import (
    DRAINAGE_CAPACITY_UNITS,
    DRAINAGE_STATUS_OPTIONS,
    DRAINAGE_TYPES,
    THEME,
)
from core.models import DrainageFeature, GridCell, Neighbourhood


class DrainageManagerView(tk.Frame):
    """Add, edit, and delete user-entered drainage infrastructure elements."""

    def __init__(
        self,
        parent: tk.Misc,
        on_add_drainage: Callable[[str, str, str, str, str, str, str, str], DrainageFeature | None],
        on_update_drainage: Callable[[int, str, str, str, str, str, str, str, str], DrainageFeature | None],
        on_delete_drainage: Callable[[int], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=20, pady=16)
        self.on_add_drainage = on_add_drainage
        self.on_update_drainage = on_update_drainage
        self.on_delete_drainage = on_delete_drainage

        self._neighbourhood: Neighbourhood | None = None
        self._cells: list[GridCell] = []
        self._drainage: list[DrainageFeature] = []
        self._selected_id: int | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        tk.Label(
            self,
            text="Drainage Infrastructure Manager",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 17, "bold"),
        ).pack(anchor="w")
        tk.Label(
            self,
            text="Manually record stormwater drains, inlets, outlets, channels, culverts, and pumping stations. All entries are explicitly labelled 'user-entered'.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 12))

        split = tk.Frame(self, bg=THEME["bg_root"])
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=1)
        split.columnconfigure(1, weight=0, minsize=360)
        split.rowconfigure(0, weight=1)

        # Left Table
        tcard = tk.Frame(
            split,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=10,
        )
        tcard.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        cols = ("id", "name", "type", "coords", "cell", "cap", "status", "source")
        self.tree = ttk.Treeview(tcard, columns=cols, show="headings")
        for c, title, w in (
            ("id", "ID", 45),
            ("name", "Name", 150),
            ("type", "Type", 130),
            ("coords", "Lat, Lon", 145),
            ("cell", "Cell", 60),
            ("cap", "Capacity", 90),
            ("status", "Status", 115),
            ("source", "Source", 95),
        ):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, anchor="e" if c in ("id", "cap") else "w")
        vsb = ttk.Scrollbar(tcard, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # Right Form
        fcard = tk.Frame(
            split,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=14,
            pady=12,
            width=360,
        )
        fcard.grid(row=0, column=1, sticky="nsew")
        fcard.grid_propagate(False)

        tk.Label(fcard, text="DRAINAGE ELEMENT FORM", bg=THEME["bg_card"], fg=THEME["accent"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.mode_lbl = tk.Label(fcard, text="Add New Drainage Element", bg=THEME["bg_card"], fg=THEME["text_primary"], font=("Segoe UI", 12, "bold"))
        self.mode_lbl.pack(anchor="w", pady=(2, 10))

        tk.Label(fcard, text="Name:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.name_var = tk.StringVar()
        ttk.Entry(fcard, textvariable=self.name_var).pack(fill="x", pady=(2, 8))

        tk.Label(fcard, text="Drainage Type:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.type_var = tk.StringVar(value=DRAINAGE_TYPES[0])
        ttk.Combobox(fcard, textvariable=self.type_var, values=DRAINAGE_TYPES, state="readonly").pack(fill="x", pady=(2, 8))

        coord_row = tk.Frame(fcard, bg=THEME["bg_card"])
        coord_row.pack(fill="x", pady=(0, 8))
        coord_row.columnconfigure(0, weight=1)
        coord_row.columnconfigure(1, weight=1)
        tk.Label(coord_row, text="Latitude:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(coord_row, text="Longitude:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.lat_var = tk.StringVar()
        self.lon_var = tk.StringVar()
        ttk.Entry(coord_row, textvariable=self.lat_var).grid(row=1, column=0, sticky="ew", pady=(2, 0))
        ttk.Entry(coord_row, textvariable=self.lon_var).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(2, 0))

        cap_row = tk.Frame(fcard, bg=THEME["bg_card"])
        cap_row.pack(fill="x", pady=(0, 8))
        cap_row.columnconfigure(0, weight=2)
        cap_row.columnconfigure(1, weight=1)
        tk.Label(cap_row, text="Capacity (optional):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(cap_row, text="Unit:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.cap_var = tk.StringVar()
        self.unit_var = tk.StringVar(value=DRAINAGE_CAPACITY_UNITS[1])
        ttk.Entry(cap_row, textvariable=self.cap_var).grid(row=1, column=0, sticky="ew", pady=(2, 0))
        ttk.Combobox(cap_row, textvariable=self.unit_var, values=DRAINAGE_CAPACITY_UNITS, state="readonly").grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(2, 0))

        tk.Label(fcard, text="Operational Status:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.status_var = tk.StringVar(value=DRAINAGE_STATUS_OPTIONS[0])
        ttk.Combobox(fcard, textvariable=self.status_var, values=DRAINAGE_STATUS_OPTIONS, state="readonly").pack(fill="x", pady=(2, 8))

        tk.Label(fcard, text="Notes:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.notes_text = tk.Text(
            fcard,
            height=4,
            bg=THEME["bg_input"],
            fg=THEME["text_primary"],
            insertbackground=THEME["text_primary"],
            relief="solid",
            bd=1,
            font=("Segoe UI", 9),
        )
        self.notes_text.pack(fill="x", pady=(2, 10))

        btns = tk.Frame(fcard, bg=THEME["bg_card"])
        btns.pack(fill="x", pady=(0, 6))
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)

        self.save_btn = ttk.Button(btns, text="Add Element", style="Accent.TButton", command=self._handle_save)
        self.save_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 6))
        ttk.Button(btns, text="New / Clear Form", command=self._clear_form).grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 6))
        self.del_btn = ttk.Button(fcard, text="Delete Selected Element", style="Danger.TButton", command=self._handle_delete, state="disabled")
        self.del_btn.pack(fill="x")

        self.msg_lbl = tk.Label(fcard, text="Tip: Use 'Place Drainage' click mode in Advanced Map Editor to pick coordinates directly from the map.", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 8), wraplength=325, justify="left")
        self.msg_lbl.pack(anchor="w", pady=(8, 0))

    def refresh(
        self,
        neighbourhood: Neighbourhood | None,
        cells: list[GridCell],
        drainage: list[DrainageFeature],
    ) -> None:
        self._neighbourhood = neighbourhood
        self._cells = cells
        self._drainage = drainage
        cell_codes = {c.id: c.cell_code for c in cells if c.id is not None}

        if neighbourhood is not None and not self.lat_var.get().strip():
            self.lat_var.set(f"{neighbourhood.center_latitude:.6f}")
            self.lon_var.set(f"{neighbourhood.center_longitude:.6f}")

        for item in self.tree.get_children():
            self.tree.delete(item)
        for dr in drainage:
            cap_txt = f"{dr.capacity:g} {dr.capacity_unit}" if dr.capacity is not None else "—"
            self.tree.insert(
                "",
                "end",
                iid=str(dr.id),
                values=(
                    dr.id,
                    dr.name,
                    dr.feature_type,
                    f"{dr.latitude:.5f}, {dr.longitude:.5f}",
                    cell_codes.get(dr.grid_cell_id, "—"),
                    cap_txt,
                    dr.status,
                    dr.source,
                ),
            )

    def prefill_coordinates(self, lat: float, lon: float) -> None:
        self._clear_form()
        self.lat_var.set(f"{lat:.6f}")
        self.lon_var.set(f"{lon:.6f}")
        self.msg_lbl.configure(text=f"Coordinates prefilled from map click ({lat:.5f}, {lon:.5f}). Complete details and click Add Element.", fg=THEME["accent_hover"])

    def _on_select(self, _event: tk.Event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        did = int(sel[0])
        dr = next((d for d in self._drainage if d.id == did), None)
        if dr is None:
            return
        self._selected_id = did
        self.mode_lbl.configure(text=f"Edit Drainage #{did}")
        self.save_btn.configure(text="Save Changes")
        self.del_btn.configure(state="normal")
        self.name_var.set(dr.name)
        self.type_var.set(dr.feature_type)
        self.lat_var.set(f"{dr.latitude:.6f}")
        self.lon_var.set(f"{dr.longitude:.6f}")
        self.cap_var.set("" if dr.capacity is None else f"{dr.capacity:g}")
        self.unit_var.set(dr.capacity_unit)
        self.status_var.set(dr.status)
        self.notes_text.delete("1.0", tk.END)
        self.notes_text.insert("1.0", dr.notes)

    def _clear_form(self) -> None:
        self._selected_id = None
        self.mode_lbl.configure(text="Add New Drainage Element")
        self.save_btn.configure(text="Add Element")
        self.del_btn.configure(state="disabled")
        self.name_var.set("")
        self.cap_var.set("")
        self.notes_text.delete("1.0", tk.END)
        if self._neighbourhood is not None:
            self.lat_var.set(f"{self._neighbourhood.center_latitude:.6f}")
            self.lon_var.set(f"{self._neighbourhood.center_longitude:.6f}")

    def _handle_save(self) -> None:
        if self._neighbourhood is None:
            messagebox.showinfo("Workspace Required", "Create or load a workspace first.")
            return
        name = self.name_var.get().strip()
        ftype = self.type_var.get()
        lat = self.lat_var.get().strip()
        lon = self.lon_var.get().strip()
        cap = self.cap_var.get().strip()
        unit = self.unit_var.get()
        status = self.status_var.get()
        notes = self.notes_text.get("1.0", tk.END).strip()

        if self._selected_id is None:
            created = self.on_add_drainage(name, ftype, lat, lon, cap, unit, status, notes)
            if created is not None:
                self._clear_form()
                self.msg_lbl.configure(text=f"Added drainage '{created.name}' (user-entered).", fg=THEME["success"])
        else:
            updated = self.on_update_drainage(self._selected_id, name, ftype, lat, lon, cap, unit, status, notes)
            if updated is not None:
                self.msg_lbl.configure(text=f"Updated drainage #{updated.id}.", fg=THEME["success"])

    def _handle_delete(self) -> None:
        if self._selected_id is None:
            return
        if messagebox.askyesno("Delete Drainage Element", f"Delete drainage element #{self._selected_id}?"):
            self.on_delete_drainage(self._selected_id)
            self._clear_form()
            self.msg_lbl.configure(text="Deleted drainage element.", fg=THEME["warning"])
