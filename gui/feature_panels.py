"""Phase 2 GIS views: Roads & Buildings, Water Bodies & Green Areas, and Land-Use Manager."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from config import (
    BUILDING_CATEGORIES,
    LAND_USE_OPTIONS,
    LAND_USE_TINT_COLORS,
    ROAD_CATEGORIES,
    THEME,
)
from core.models import GridCell, LandUseHistoryEntry, Neighbourhood, OSMFeature
from gui.components import StatCard
from services.osm_service import classify_building_category, classify_road_category


class RoadsBuildingsView(tk.Frame):
    """Inspect, filter, and offline-edit imported Roads and Buildings."""

    def __init__(
        self,
        parent: tk.Misc,
        on_update_feature: Callable[[int, str, str, str, str], OSMFeature | None],
        on_get_feature_cells: Callable[[int], list[str]],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=20, pady=16)
        self.on_update_feature = on_update_feature
        self.on_get_feature_cells = on_get_feature_cells

        self._features: list[OSMFeature] = []
        self._feat_by_id: dict[int, OSMFeature] = {}
        self._selected_id: int | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        tk.Label(
            self,
            text="Roads & Buildings Classification Manager",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 17, "bold"),
        ).pack(anchor="w")
        tk.Label(
            self,
            text="Inspect classified OpenStreetMap roads (with geodesic lengths) and building footprints offline. Occupancy/population is never inferred.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 12))

        # Summary cards
        cards = tk.Frame(self, bg=THEME["bg_root"])
        cards.pack(fill="x", pady=(0, 12))
        for i in range(4):
            cards.columnconfigure(i, weight=1, uniform="rbcards")
        self.c_roads = StatCard(cards, "Classified Roads", "0", "Across 7 OSM road classes", THEME["accent"])
        self.c_road_len = StatCard(cards, "Total Road Length", "0 m", "Geodesic Haversine length", THEME["info"])
        self.c_bldgs = StatCard(cards, "Mapped Buildings", "0", "Polygon footprints", THEME["accent_teal"])
        self.c_edited = StatCard(cards, "User-Edited Features", "0", "Modified offline in SQLite", THEME["warning"])
        self.c_roads.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.c_road_len.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        self.c_bldgs.grid(row=0, column=2, sticky="nsew", padx=(0, 8))
        self.c_edited.grid(row=0, column=3, sticky="nsew")

        # Filter bar
        fbar = tk.Frame(
            self,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        fbar.pack(fill="x", pady=(0, 10))

        tk.Label(fbar, text="View:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.type_filter_var = tk.StringVar(value="Roads")
        type_cb = ttk.Combobox(
            fbar, textvariable=self.type_filter_var, values=("Roads", "Buildings"), state="readonly", width=12
        )
        type_cb.pack(side="left", padx=(0, 12))
        type_cb.bind("<<ComboboxSelected>>", lambda _e: self._populate_table())

        tk.Label(fbar, text="Class Filter:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.class_filter_var = tk.StringVar(value="All")
        self.class_filter_cb = ttk.Combobox(
            fbar, textvariable=self.class_filter_var, values=("All",) + ROAD_CATEGORIES, state="readonly", width=20
        )
        self.class_filter_cb.pack(side="left", padx=(0, 12))
        self.class_filter_cb.bind("<<ComboboxSelected>>", lambda _e: self._populate_table())

        tk.Label(fbar, text="Search Name:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._populate_table())
        ttk.Entry(fbar, textvariable=self.search_var, width=24).pack(side="left")

        # Main split: Table (left) + Edit Panel (right)
        split = tk.Frame(self, bg=THEME["bg_root"])
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=1)
        split.columnconfigure(1, weight=0, minsize=340)
        split.rowconfigure(0, weight=1)

        table_card = tk.Frame(
            split,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=10,
        )
        table_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        cols = ("id", "osm_id", "name", "class", "length", "source", "cells")
        self.tree = ttk.Treeview(table_card, columns=cols, show="headings")
        for col, heading, w in (
            ("id", "ID", 50),
            ("osm_id", "OSM ID", 95),
            ("name", "Name", 170),
            ("class", "Classification", 130),
            ("length", "Length (m)", 85),
            ("source", "Source", 130),
            ("cells", "Grid Cells", 130),
        ):
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=w, anchor="e" if col in ("id", "osm_id", "length") else "w")

        vsb = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

        # Right Edit Card
        edit_card = tk.Frame(
            split,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=14,
            pady=12,
            width=340,
        )
        edit_card.grid(row=0, column=1, sticky="nsew")
        edit_card.grid_propagate(False)

        tk.Label(edit_card, text="FEATURE ATTRIBUTE EDITOR", bg=THEME["bg_card"], fg=THEME["accent"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.sel_title_lbl = tk.Label(edit_card, text="Select a road or building", bg=THEME["bg_card"], fg=THEME["text_primary"], font=("Segoe UI", 12, "bold"))
        self.sel_title_lbl.pack(anchor="w", pady=(2, 8))

        self.meta_lbl = tk.Label(
            edit_card,
            text="OSM ID: —\nSource: —\nImported: —\nIntersecting Cells: —",
            bg=THEME["bg_input"],
            fg=THEME["text_secondary"],
            font=("Consolas", 8),
            justify="left",
            anchor="w",
            padx=8,
            pady=8,
        )
        self.meta_lbl.pack(fill="x", pady=(0, 10))

        tk.Label(edit_card, text="Name:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.edit_name_var = tk.StringVar()
        ttk.Entry(edit_card, textvariable=self.edit_name_var).pack(fill="x", pady=(2, 8))

        tk.Label(edit_card, text="Category Classification:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.edit_cat_var = tk.StringVar()
        self.edit_cat_cb = ttk.Combobox(edit_card, textvariable=self.edit_cat_var, state="readonly")
        self.edit_cat_cb.pack(fill="x", pady=(2, 8))

        tk.Label(edit_card, text="Notes:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.edit_notes = tk.Text(
            edit_card,
            height=4,
            bg=THEME["bg_input"],
            fg=THEME["text_primary"],
            insertbackground=THEME["text_primary"],
            relief="solid",
            bd=1,
            font=("Segoe UI", 9),
        )
        self.edit_notes.pack(fill="x", pady=(2, 10))

        self.save_btn = ttk.Button(edit_card, text="Save Attributes Offline", style="Accent.TButton", command=self._handle_save, state="disabled")
        self.save_btn.pack(fill="x")

        self.status_lbl = tk.Label(edit_card, text="", bg=THEME["bg_card"], fg=THEME["success"], font=("Segoe UI", 8), wraplength=310)
        self.status_lbl.pack(anchor="w", pady=(8, 0))

    def refresh(self, features: list[OSMFeature]) -> None:
        self._features = features
        self._feat_by_id = {f.id: f for f in features if f.id is not None}
        roads = [f for f in features if f.category == "road"]
        bldgs = [f for f in features if f.category == "building"]
        total_len = sum(f.length_m for f in roads)
        edited = sum(1 for f in (roads + bldgs) if f.is_user_edited)

        self.c_roads.update_card(f"{len(roads):,}", "Classified by OSM highway tag")
        self.c_road_len.update_card(f"{total_len / 1000.0:.2f} km", f"{total_len:,.0f} m total mapped length")
        self.c_bldgs.update_card(f"{len(bldgs):,}", "No occupancy/population inferred")
        self.c_edited.update_card(f"{edited:,}", "Saved in local SQLite")
        self._populate_table()

    def _populate_table(self) -> None:
        kind = self.type_filter_var.get()
        if kind == "Roads":
            self.class_filter_cb["values"] = ("All",) + ROAD_CATEGORIES
        else:
            self.class_filter_cb["values"] = ("All",) + BUILDING_CATEGORIES
        if self.class_filter_var.get() not in self.class_filter_cb["values"]:
            self.class_filter_var.set("All")

        for item in self.tree.get_children():
            self.tree.delete(item)

        target_cat = "road" if kind == "Roads" else "building"
        cls_filter = self.class_filter_var.get()
        search_q = self.search_var.get().strip().lower()

        for feat in self._features:
            if feat.category != target_cat:
                continue
            cls_val = (
                (feat.road_category or classify_road_category(feat.subcategory, feat.tags))
                if target_cat == "road"
                else (feat.building_category or classify_building_category(feat.subcategory, feat.tags))
            )
            if cls_filter != "All" and cls_val != cls_filter:
                continue
            if search_q and search_q not in (feat.name or "").lower() and search_q not in str(feat.osm_id):
                continue

            cells = self.on_get_feature_cells(feat.id) if feat.id is not None else []
            cells_txt = ", ".join(cells[:5]) + ("…" if len(cells) > 5 else "")
            self.tree.insert(
                "",
                "end",
                iid=str(feat.id),
                values=(
                    feat.id,
                    feat.osm_id,
                    feat.name or "(Unnamed)",
                    cls_val,
                    f"{feat.length_m:.1f}" if feat.length_m > 0 else "—",
                    feat.source,
                    cells_txt or "—",
                ),
            )

    def _on_row_select(self, _event: tk.Event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        fid = int(sel[0])
        feat = self._feat_by_id.get(fid)
        if feat is None:
            return
        self._selected_id = fid
        self.save_btn.configure(state="normal")
        self.sel_title_lbl.configure(text=f"{feat.category.title()} #{feat.id}")
        cells = self.on_get_feature_cells(fid)
        self.meta_lbl.configure(
            text=(
                f"OSM: {feat.element_type}/{feat.osm_id}\n"
                f"Source: {feat.source}\n"
                f"Imported: {feat.imported_at}\n"
                f"Length: {feat.length_m:.1f} m\n"
                f"Cells ({len(cells)}): {', '.join(cells) if cells else 'None linked'}"
            )
        )
        self.edit_name_var.set(feat.name)
        if feat.category == "road":
            self.edit_cat_cb["values"] = ROAD_CATEGORIES
            self.edit_cat_var.set(feat.road_category or classify_road_category(feat.subcategory, feat.tags))
        else:
            self.edit_cat_cb["values"] = BUILDING_CATEGORIES
            self.edit_cat_var.set(feat.building_category or classify_building_category(feat.subcategory, feat.tags))
        self.edit_notes.delete("1.0", tk.END)
        self.edit_notes.insert("1.0", feat.user_notes or "")

    def _handle_save(self) -> None:
        if self._selected_id is None:
            return
        feat = self._feat_by_id.get(self._selected_id)
        if feat is None:
            return
        name = self.edit_name_var.get().strip()
        cat_val = self.edit_cat_var.get().strip()
        notes = self.edit_notes.get("1.0", tk.END).strip()
        road_cat = cat_val if feat.category == "road" else feat.road_category
        bldg_cat = cat_val if feat.category == "building" else feat.building_category

        updated = self.on_update_feature(feat.id, name, road_cat, bldg_cat, notes)
        if updated is not None:
            self.status_lbl.configure(text=f"Saved feature #{updated.id} offline.")


class WaterBodiesView(tk.Frame):
    """Inspect lakes, ponds, rivers, canals, waterways, wetlands, and parks/green spaces."""

    def __init__(
        self,
        parent: tk.Misc,
        on_get_feature_cells: Callable[[int], list[str]],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=20, pady=16)
        self.on_get_feature_cells = on_get_feature_cells
        self._features: list[OSMFeature] = []
        self._feat_by_id: dict[int, OSMFeature] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        tk.Label(
            self,
            text="Water Bodies, Wetlands & Green Areas",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 17, "bold"),
        ).pack(anchor="w")
        tk.Label(
            self,
            text="Inspect mapped rivers, canals, lakes, ponds, wetlands, and green spaces. Note: storage & flood-retention capacity are NOT assumed from geometry.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(2, 12))

        fbar = tk.Frame(
            self,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        fbar.pack(fill="x", pady=(0, 10))
        tk.Label(fbar, text="Layer Filter:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 8))
        self.layer_var = tk.StringVar(value="All Water & Green")
        cb = ttk.Combobox(
            fbar,
            textvariable=self.layer_var,
            values=("All Water & Green", "Waterways & Waterbodies", "Wetlands", "Parks & Green Spaces"),
            state="readonly",
            width=26,
        )
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._populate())

        split = tk.Frame(self, bg=THEME["bg_root"])
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=1)
        split.columnconfigure(1, weight=0, minsize=340)
        split.rowconfigure(0, weight=1)

        tcard = tk.Frame(split, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=10, pady=10)
        tcard.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        cols = ("id", "cat", "sub", "name", "length", "cells")
        self.tree = ttk.Treeview(tcard, columns=cols, show="headings")
        for col, title, w in (
            ("id", "ID", 50),
            ("cat", "Layer", 100),
            ("sub", "Sub-Type", 105),
            ("name", "Name", 190),
            ("length", "Length (m)", 85),
            ("cells", "Intersecting Cells", 160),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w, anchor="e" if col in ("id", "length") else "w")
        vsb = ttk.Scrollbar(tcard, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        icard = tk.Frame(split, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=14, pady=12, width=340)
        icard.grid(row=0, column=1, sticky="nsew")
        icard.grid_propagate(False)
        tk.Label(icard, text="WATERBODY / GREEN ATTRIBUTES", bg=THEME["bg_card"], fg=THEME["accent"], font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 6))
        self.detail_text = tk.Text(
            icard,
            bg=THEME["bg_input"],
            fg=THEME["text_primary"],
            relief="solid",
            bd=1,
            font=("Consolas", 9),
            wrap="word",
            state="disabled",
        )
        self.detail_text.pack(fill="both", expand=True)

    def refresh(self, features: list[OSMFeature]) -> None:
        self._features = [f for f in features if f.category in ("waterway", "green_area")]
        self._feat_by_id = {f.id: f for f in self._features if f.id is not None}
        self._populate()

    def _populate(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)
        flt = self.layer_var.get()
        for f in self._features:
            if flt == "Waterways & Waterbodies" and f.category != "waterway":
                continue
            if flt == "Wetlands" and f.subcategory != "wetland":
                continue
            if flt == "Parks & Green Spaces" and (f.category != "green_area" or f.subcategory == "wetland"):
                continue

            cells = self.on_get_feature_cells(f.id) if f.id is not None else []
            self.tree.insert(
                "",
                "end",
                iid=str(f.id),
                values=(
                    f.id,
                    "Water" if f.category == "waterway" else ("Wetland" if f.subcategory == "wetland" else "Green Space"),
                    f.subcategory,
                    f.name or "(Unnamed)",
                    f"{f.length_m:.1f}" if f.length_m > 0 else "—",
                    ", ".join(cells[:5]) or "—",
                ),
            )

    def _on_select(self, _event: tk.Event) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        feat = self._feat_by_id.get(int(sel[0]))
        if feat is None:
            return
        cells = self.on_get_feature_cells(feat.id) if feat.id is not None else []
        lines = [
            f"Feature ID: #{feat.id} ({feat.element_type}/{feat.osm_id})",
            f"Category: {feat.category}",
            f"Subcategory: {feat.subcategory}",
            f"Name: {feat.name or '(Unnamed)'}",
            f"Geometry Type: {feat.geometry.get('type')}",
            f"Length: {feat.length_m:.1f} m" if feat.length_m > 0 else "Length: N/A (Polygon)",
            f"Source: {feat.source}",
            f"Imported: {feat.imported_at}",
            f"Intersecting Cells ({len(cells)}): {', '.join(cells) if cells else 'None'}",
            "",
            "Disclaimer: Storage volume & flood-retention capacity are NOT assumed from OSM data.",
            "",
            "--- Tags ---",
        ]
        for k, v in feat.tags.items():
            lines.append(f"  {k}: {v}")
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", "\n".join(lines))
        self.detail_text.configure(state="disabled")


class LandUseManagerView(tk.Frame):
    """Classify grid cells across 9 land-use categories, view provenance & history."""

    def __init__(
        self,
        parent: tk.Misc,
        on_assign_land_use: Callable[[list[int], str], int],
        on_auto_suggest: Callable[[bool], int],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=20, pady=16)
        self.on_assign_land_use = on_assign_land_use
        self.on_auto_suggest = on_auto_suggest
        self._cells: list[GridCell] = []
        self._build_ui()

    def _build_ui(self) -> None:
        top = tk.Frame(self, bg=THEME["bg_root"])
        top.pack(fill="x", pady=(0, 10))

        tbox = tk.Frame(top, bg=THEME["bg_root"])
        tbox.pack(side="left", fill="x", expand=True)
        tk.Label(tbox, text="Land-Use Classification Manager", bg=THEME["bg_root"], fg=THEME["text_primary"], font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(
            tbox,
            text="Assign categories manually or run rule-based suggestion from intersecting OSM features (automatically tagged 'inferred', never verified).",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        # Color Legend Bar
        leg = tk.Frame(self, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=10, pady=7)
        leg.pack(fill="x", pady=(0, 10))
        tk.Label(leg, text="Legend:", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 8))
        for cat in LAND_USE_OPTIONS:
            col = LAND_USE_TINT_COLORS.get(cat) or "#475569"
            tk.Frame(leg, bg=col, width=11, height=11).pack(side="left", padx=(0, 4))
            tk.Label(leg, text=cat, bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left", padx=(0, 10))

        # Action Toolbar
        act = tk.Frame(self, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=12, pady=8)
        act.pack(fill="x", pady=(0, 10))

        tk.Label(act, text="Assign Selected Cells to:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 6))
        self.assign_var = tk.StringVar(value="Residential")
        ttk.Combobox(act, textvariable=self.assign_var, values=LAND_USE_OPTIONS, state="readonly", width=18).pack(side="left", padx=(0, 8))
        ttk.Button(act, text="Apply (User-Entered)", style="Accent.TButton", command=self._handle_assign).pack(side="left", padx=(0, 14))

        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Button(act, text="Suggest from Intersecting Features", command=self._handle_suggest).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(act, text="Overwrite user-entered", variable=self.overwrite_var).pack(side="left")

        self.status_lbl = tk.Label(act, text="", bg=THEME["bg_card"], fg=THEME["accent_teal"], font=("Segoe UI", 8, "bold"))
        self.status_lbl.pack(side="right")

        # Notebook: Cell Classifications | Audit History
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        tab_cells = tk.Frame(nb, bg=THEME["bg_card"], padx=8, pady=8)
        tab_hist = tk.Frame(nb, bg=THEME["bg_card"], padx=8, pady=8)
        nb.add(tab_cells, text="Grid Cell Classifications")
        nb.add(tab_hist, text="Land-Use Change History")

        cols = ("code", "center", "land_use", "source", "updated")
        self.tree = ttk.Treeview(tab_cells, columns=cols, show="headings", selectmode="extended")
        for c, title, w in (
            ("code", "Cell", 80),
            ("center", "Center Lat, Lon", 190),
            ("land_use", "Land-Use Category", 160),
            ("source", "Data Provenance", 140),
            ("updated", "Updated At", 190),
        ):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, anchor="w")
        vsb = ttk.Scrollbar(tab_cells, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        hcols = ("cell", "prev", "new", "source", "when")
        self.hist_tree = ttk.Treeview(tab_hist, columns=hcols, show="headings")
        for c, title, w in (
            ("cell", "Cell", 80),
            ("prev", "Previous", 150),
            ("new", "New Category", 150),
            ("source", "Source", 130),
            ("when", "Timestamp", 200),
        ):
            self.hist_tree.heading(c, text=title)
            self.hist_tree.column(c, width=w, anchor="w")
        hvsb = ttk.Scrollbar(tab_hist, orient="vertical", command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=hvsb.set)
        self.hist_tree.pack(side="left", fill="both", expand=True)
        hvsb.pack(side="right", fill="y")

    def refresh(
        self,
        cells: list[GridCell],
        history: list[tuple[str, LandUseHistoryEntry]],
    ) -> None:
        self._cells = cells
        for item in self.tree.get_children():
            self.tree.delete(item)
        for c in cells:
            if c.id is None:
                continue
            self.tree.insert(
                "",
                "end",
                iid=str(c.id),
                values=(
                    c.cell_code,
                    f"{c.center_latitude:.5f}, {c.center_longitude:.5f}",
                    c.land_use,
                    c.land_use_source,
                    c.updated_at,
                ),
            )

        for item in self.hist_tree.get_children():
            self.hist_tree.delete(item)
        for code, entry in history:
            self.hist_tree.insert(
                "",
                "end",
                values=(
                    code,
                    entry.previous_category,
                    entry.new_category,
                    entry.source,
                    entry.updated_at,
                ),
            )

    def _handle_assign(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Select Cells", "Select one or more grid cells in the table first.")
            return
        ids = [int(x) for x in sel]
        cat = self.assign_var.get()
        n = self.on_assign_land_use(ids, cat)
        self.status_lbl.configure(text=f"Updated {n} cell(s) to '{cat}' (user-entered).")

    def _handle_suggest(self) -> None:
        n = self.on_auto_suggest(bool(self.overwrite_var.get()))
        self.status_lbl.configure(text=f"Suggested land-use for {n} cell(s) [marked 'inferred'].")
