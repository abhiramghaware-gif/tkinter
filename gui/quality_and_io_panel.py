"""Phase 2 Grid Configuration, Data Quality Dashboard, and Import/Export views."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from config import DEFAULT_GRID_COLS, DEFAULT_GRID_ROWS, THEME
from core.models import DataQualitySummary, GridCell, Neighbourhood
from core.validation import ValidationError, validate_grid_dimensions
from gui.components import StatCard


class GridConfigView(tk.Frame):
    """Manage grid dimensions, inspect cell area metrics, and rebuild spatial links."""

    def __init__(
        self,
        parent: tk.Misc,
        on_regenerate_grid: Callable[[int, int, bool], None],
        on_rebuild_links: Callable[[], int],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=20, pady=16)
        self.on_regenerate_grid = on_regenerate_grid
        self.on_rebuild_links = on_rebuild_links
        self._neighbourhood: Neighbourhood | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        tk.Label(self, text="Simulation Grid Configuration & Spatial Links", bg=THEME["bg_root"], fg=THEME["text_primary"], font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(
            self,
            text="Configure grid dimensions with spherical Earth area/width/height calculations and rebuild feature-to-grid intersections.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 12))

        ctrl = tk.Frame(self, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=14, pady=12)
        ctrl.pack(fill="x", pady=(0, 12))

        tk.Label(ctrl, text="Rows:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        self.rows_var = tk.StringVar(value=str(DEFAULT_GRID_ROWS))
        ttk.Entry(ctrl, textvariable=self.rows_var, width=6).pack(side="left", padx=(0, 10))

        tk.Label(ctrl, text="Columns:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        self.cols_var = tk.StringVar(value=str(DEFAULT_GRID_COLS))
        ttk.Entry(ctrl, textvariable=self.cols_var, width=6).pack(side="left", padx=(0, 12))

        self.preserve_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctrl, text="Preserve existing cell attributes on resize", variable=self.preserve_var).pack(side="left", padx=(0, 12))

        ttk.Button(ctrl, text="Regenerate Grid", style="Accent.TButton", command=self._handle_regen).pack(side="left", padx=(0, 10))
        ttk.Button(ctrl, text="Rebuild Feature-to-Grid Links", command=self._handle_links).pack(side="left")

        self.status_lbl = tk.Label(ctrl, text="", bg=THEME["bg_card"], fg=THEME["accent_teal"], font=("Segoe UI", 9))
        self.status_lbl.pack(side="right")

        tcard = tk.Frame(self, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=10, pady=10)
        tcard.pack(fill="both", expand=True)

        cols = ("code", "bounds", "dims", "area", "elev", "lu", "infil", "drain")
        self.tree = ttk.Treeview(tcard, columns=cols, show="headings")
        for c, title, w in (
            ("code", "Cell", 65),
            ("bounds", "Bounding Box (S..N, W..E)", 240),
            ("dims", "Width × Height (m)", 140),
            ("area", "Approx Area (m²)", 120),
            ("elev", "Elev Mean (m)", 100),
            ("lu", "Land-Use (Src)", 150),
            ("infil", "Infil (mm/hr)", 95),
            ("drain", "Drain (mm/hr)", 95),
        ):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, anchor="e" if c in ("area", "elev", "infil", "drain") else "w")
        vsb = ttk.Scrollbar(tcard, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def refresh(self, neighbourhood: Neighbourhood | None, cells: list[GridCell]) -> None:
        self._neighbourhood = neighbourhood
        if neighbourhood is not None:
            self.rows_var.set(str(neighbourhood.grid_rows))
            self.cols_var.set(str(neighbourhood.grid_cols))
        for item in self.tree.get_children():
            self.tree.delete(item)
        for c in cells:
            w_m, h_m = c.approx_dimensions_m()
            area = c.approx_area_sq_m()
            el = c.mean_elevation_m if c.mean_elevation_m is not None else c.elevation_m
            self.tree.insert(
                "",
                "end",
                values=(
                    c.cell_code,
                    f"[{c.min_latitude:.4f}..{c.max_latitude:.4f}], [{c.min_longitude:.4f}..{c.max_longitude:.4f}]",
                    f"{w_m:.1f} × {h_m:.1f}",
                    f"{area:,.1f}",
                    "NULL" if el is None else f"{el:.2f}",
                    f"{c.land_use} ({c.land_use_source})",
                    f"{c.infiltration_rate:g}",
                    f"{c.drainage_capacity:g}",
                ),
            )

    def _handle_regen(self) -> None:
        if self._neighbourhood is None:
            messagebox.showinfo("No Workspace", "Create or load a workspace first.")
            return
        try:
            r, c = validate_grid_dimensions(self.rows_var.get(), self.cols_var.get())
        except ValidationError as exc:
            messagebox.showerror("Invalid Dimensions", str(exc))
            return
        preserve = bool(self.preserve_var.get())
        msg = f"Regenerate grid as {r}×{c} ({r * c} cells)?"
        msg += "\nExisting attributes will be carried over where cell centers overlap." if preserve else "\nWARNING: Existing cell attributes will be reset."
        if messagebox.askyesno("Confirm Grid Regeneration", msg):
            self.on_regenerate_grid(r, c, preserve)
            self.status_lbl.configure(text=f"Grid updated to {r}×{c}.")

    def _handle_links(self) -> None:
        if self._neighbourhood is None:
            return
        cnt = self.on_rebuild_links()
        self.status_lbl.configure(text=f"Built {cnt} spatial feature-to-grid link(s).")


class DataQualityView(tk.Frame):
    """Neighbourhood data-quality dashboard with transparent provenance counts."""

    def __init__(self, parent: tk.Misc, on_rebuild_links: Callable[[], int]) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=20, pady=16)
        self.on_rebuild_links = on_rebuild_links
        self._build_ui()

    def _build_ui(self) -> None:
        top = tk.Frame(self, bg=THEME["bg_root"])
        top.pack(fill="x", pady=(0, 12))
        tbox = tk.Frame(top, bg=THEME["bg_root"])
        tbox.pack(side="left", fill="x", expand=True)
        tk.Label(tbox, text="Neighbourhood Data Quality & Provenance", bg=THEME["bg_root"], fg=THEME["text_primary"], font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(
            tbox,
            text="Completeness metrics across imported, user-entered, inferred, and missing datasets. No synthetic overall accuracy percentage is fabricated.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        ttk.Button(top, text="Recalculate Spatial Links", command=self.on_rebuild_links).pack(side="right")

        # 9 required indicator cards (3 rows x 3 columns)
        grid = tk.Frame(self, bg=THEME["bg_root"])
        grid.pack(fill="x", pady=(0, 14))
        for col in range(3):
            grid.columnconfigure(col, weight=1, uniform="dq")

        self.c_roads = StatCard(grid, "Mapped Roads", "0", "", THEME["accent"])
        self.c_bldgs = StatCard(grid, "Mapped Buildings", "0", "", THEME["info"])
        self.c_water = StatCard(grid, "Water Features (+ Green)", "0", "", "#38BDF8")
        self.c_drain = StatCard(grid, "Drainage Elements", "0", "", THEME["accent_teal"])
        self.c_cells = StatCard(grid, "Total Grid Cells", "0", "", THEME["text_secondary"])
        self.c_miss_elev = StatCard(grid, "Cells Missing Elevation", "0", "", THEME["warning"])
        self.c_miss_lu = StatCard(grid, "Cells Missing Land-Use", "0", "", THEME["warning"])
        self.c_miss_inf = StatCard(grid, "Cells Missing Infiltration", "0", "", THEME["warning"])
        self.c_miss_dr = StatCard(grid, "Cells Missing Drainage", "0", "", THEME["warning"])

        cards_list = [
            self.c_roads, self.c_bldgs, self.c_water,
            self.c_drain, self.c_cells, self.c_miss_elev,
            self.c_miss_lu, self.c_miss_inf, self.c_miss_dr,
        ]
        for idx, card in enumerate(cards_list):
            card.grid(row=idx // 3, column=idx % 3, sticky="nsew", padx=(0 if idx % 3 == 0 else 8, 0), pady=(0, 8))

        # Provenance Breakdown Table
        pcard = tk.Frame(self, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=16, pady=14)
        pcard.pack(fill="both", expand=True)
        tk.Label(pcard, text="DATA PROVENANCE BREAKDOWN", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 8))

        self.prov_label = tk.Label(
            pcard,
            text="",
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            font=("Consolas", 10),
            justify="left",
            anchor="nw",
        )
        self.prov_label.pack(fill="both", expand=True)

    def refresh(self, dq: DataQualitySummary) -> None:
        self.c_roads.update_card(f"{dq.road_count:,}", "OpenStreetMap / GeoJSON")
        self.c_bldgs.update_card(f"{dq.building_count:,}", "Mapped footprints")
        self.c_water.update_card(f"{dq.water_feature_count:,}", f"Plus {dq.green_area_count:,} parks/green/wetlands")
        self.c_drain.update_card(f"{dq.drainage_count:,}", "User-entered drainage points")
        self.c_cells.update_card(f"{dq.total_grid_cells:,}", f"{dq.grid_links_count:,} feature-to-grid links")
        self.c_miss_elev.update_card(f"{dq.missing_elevation_cells} / {dq.total_grid_cells}", "NULL until GeoTIFF or user input")
        self.c_miss_lu.update_card(f"{dq.missing_land_use_cells} / {dq.total_grid_cells}", "Classified as 'Unknown'")
        self.c_miss_inf.update_card(f"{dq.missing_infiltration_cells} / {dq.total_grid_cells}", "No soil infiltration rate set")
        self.c_miss_dr.update_card(f"{dq.missing_drainage_cells} / {dq.total_grid_cells}", "No drainage capacity set")

        lines = [
            f"IMPORTED DATA     : {dq.imported_osm_count:,} OSM/GeoJSON features  |  {dq.imported_elevation_cells} grid cells with raster elevation",
            f"USER-ENTERED DATA : {dq.user_edited_osm_count:,} edited features  |  {dq.user_drainage_count} drainage elements  |  {dq.user_land_use_cells} cell land-use  |  {dq.user_elevation_cells} manual cell elevations",
            f"INFERRED DATA     : {dq.inferred_land_use_cells} grid cell(s) with rule-suggested land-use (requires human verification)",
            f"MISSING DATA      : {dq.missing_elevation_cells} elevation  |  {dq.missing_land_use_cells} land-use  |  {dq.missing_infiltration_cells} infiltration  |  {dq.missing_drainage_cells} drainage",
        ]
        self.prov_label.configure(text="\n\n".join(lines))


class ImportExportView(tk.Frame):
    """GeoJSON/GeoTIFF import and GeoJSON/CSV export workbench."""

    def __init__(
        self,
        parent: tk.Misc,
        on_export_geojson: Callable[[], str | None],
        on_export_grid_csv: Callable[[], str | None],
        on_export_drainage_csv: Callable[[], str | None],
        on_import_geojson: Callable[[str], None],
        on_import_geotiff: Callable[[str, str], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=20, pady=16)
        self.on_export_geojson = on_export_geojson
        self.on_export_grid_csv = on_export_grid_csv
        self.on_export_drainage_csv = on_export_drainage_csv
        self.on_import_geojson = on_import_geojson
        self.on_import_geotiff = on_import_geotiff
        self._build_ui()

    def _build_ui(self) -> None:
        tk.Label(self, text="Import & Export GIS Data", bg=THEME["bg_root"], fg=THEME["text_primary"], font=("Segoe UI", 17, "bold")).pack(anchor="w")
        tk.Label(
            self,
            text="Export neighbourhood layers and grid tables with source metadata, or import validated GeoJSON and GeoTIFF elevation files offline.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 16))

        split = tk.Frame(self, bg=THEME["bg_root"])
        split.pack(fill="x", pady=(0, 14))
        split.columnconfigure(0, weight=1)
        split.columnconfigure(1, weight=1)

        exp_card = tk.Frame(split, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=16, pady=14)
        exp_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        tk.Label(exp_card, text="EXPORT DATA (to data/exports/ or chosen path)", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 10))

        ttk.Button(exp_card, text="Export Neighbourhood Features (GeoJSON)", style="Accent.TButton", command=lambda: self._log_export(self.on_export_geojson())).pack(fill="x", pady=(0, 8))
        ttk.Button(exp_card, text="Export Simulation Grid Cells (CSV)", command=lambda: self._log_export(self.on_export_grid_csv())).pack(fill="x", pady=(0, 8))
        ttk.Button(exp_card, text="Export Drainage Infrastructure (CSV)", command=lambda: self._log_export(self.on_export_drainage_csv())).pack(fill="x")

        imp_card = tk.Frame(split, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=16, pady=14)
        imp_card.grid(row=0, column=1, sticky="nsew")
        tk.Label(imp_card, text="IMPORT VALIDATED FILES (Offline-Compatible)", bg=THEME["bg_card"], fg=THEME["accent_teal"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 10))

        ttk.Button(imp_card, text="Import GeoJSON Features (.geojson / .json)", style="Accent.TButton", command=self._browse_geojson).pack(fill="x", pady=(0, 8))
        ttk.Button(imp_card, text="Import Elevation GeoTIFF (.tif / .tiff)", command=self._browse_geotiff).pack(fill="x", pady=(0, 8))
        tk.Label(
            imp_card,
            text="All imported coordinates and GeoJSON geometries are validated before saving to SQLite.",
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            wraplength=380,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        log_card = tk.Frame(self, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=14, pady=12)
        log_card.pack(fill="both", expand=True)
        tk.Label(log_card, text="IMPORT / EXPORT LOG", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 6))
        self.log_text = tk.Text(log_card, bg=THEME["bg_input"], fg=THEME["text_secondary"], font=("Consolas", 9), relief="solid", bd=1, state="disabled")
        self.log_text.pack(fill="both", expand=True)

    def append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _log_export(self, path: str | None) -> None:
        if path:
            self.append_log(f"[EXPORT OK] {path}")
            messagebox.showinfo("Export Complete", f"Saved to:\n{path}")

    def _browse_geojson(self) -> None:
        path = filedialog.askopenfilename(
            title="Select GeoJSON Feature File",
            filetypes=[("GeoJSON Files", "*.geojson *.json"), ("All Files", "*.*")],
        )
        if path:
            self.on_import_geojson(path)

    def _browse_geotiff(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Elevation GeoTIFF",
            filetypes=[("GeoTIFF Raster", "*.tif *.tiff"), ("All Files", "*.*")],
        )
        if path:
            self.on_import_geotiff(path, "Imported GeoTIFF")
