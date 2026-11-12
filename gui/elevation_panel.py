"""Phase 2 Elevation Manager view with GeoTIFF DEM import and provenance tracking."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from config import THEME
from core.models import ElevationSourceRecord, GridCell
from gui.components import StatCard
from services.elevation_service import RASTERIO_AVAILABLE


class ElevationManagerView(tk.Frame):
    """Manage GeoTIFF elevation imports, cell min/max/mean stats, and missing/manual distinctions."""

    def __init__(
        self,
        parent: tk.Misc,
        on_import_geotiff: Callable[[str, str], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=20, pady=16)
        self.on_import_geotiff = on_import_geotiff
        self._has_workspace = False
        self._build_ui()

    def _build_ui(self) -> None:
        top = tk.Frame(self, bg=THEME["bg_root"])
        top.pack(fill="x", pady=(0, 12))

        tbox = tk.Frame(top, bg=THEME["bg_root"])
        tbox.pack(side="left", fill="x", expand=True)
        tk.Label(
            tbox,
            text="Elevation Data Manager (DEM / GeoTIFF)",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 17, "bold"),
        ).pack(anchor="w")
        tk.Label(
            tbox,
            text="Import GeoTIFF elevation rasters, reproject cell bounds to raster CRS, and distinguish imported vs user-entered vs missing (NULL) elevations.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        # Cards
        cards = tk.Frame(self, bg=THEME["bg_root"])
        cards.pack(fill="x", pady=(0, 12))
        for i in range(4):
            cards.columnconfigure(i, weight=1, uniform="ecards")

        self.c_imported = StatCard(cards, "Imported Raster Cells", "0", "From GeoTIFF DEM", THEME["success"])
        self.c_manual = StatCard(cards, "User-Entered / Illustrative", "0", "Manually entered in Map Editor", THEME["info"])
        self.c_missing = StatCard(cards, "Missing (NULL)", "0", "Never fabricated", THEME["warning"])
        self.c_support = StatCard(
            cards,
            "GeoTIFF Engine",
            "Rasterio Ready" if RASTERIO_AVAILABLE else "Missing Dependency",
            "rasterio + pyproj" if RASTERIO_AVAILABLE else "Install: pip install rasterio pyproj",
            THEME["accent_teal"] if RASTERIO_AVAILABLE else THEME["error"],
        )
        self.c_imported.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.c_manual.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        self.c_missing.grid(row=0, column=2, sticky="nsew", padx=(0, 8))
        self.c_support.grid(row=0, column=3, sticky="nsew")

        # Import Bar
        ibar = tk.Frame(
            self,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=14,
            pady=10,
        )
        ibar.pack(fill="x", pady=(0, 12))

        tk.Label(
            ibar,
            text="Source Label (optional):",
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(0, 6))
        self.src_name_var = tk.StringVar(value="SRTM / Local DEM")
        ttk.Entry(ibar, textvariable=self.src_name_var, width=26).pack(side="left", padx=(0, 12))

        self.import_btn = ttk.Button(
            ibar,
            text="Import Elevation GeoTIFF (.tif / .tiff)",
            style="Accent.TButton",
            command=self._handle_browse,
        )
        self.import_btn.pack(side="left", padx=(0, 12))

        self.status_lbl = tk.Label(
            ibar,
            text="Cells without raster coverage or nodata remain NULL.",
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        )
        self.status_lbl.pack(side="left")

        # Split: Cell Elevation Table (top) + Elevation Sources Log (bottom)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        tab_cells = tk.Frame(nb, bg=THEME["bg_card"], padx=10, pady=10)
        tab_srcs = tk.Frame(nb, bg=THEME["bg_card"], padx=10, pady=10)
        nb.add(tab_cells, text="Grid Cell Elevation Values")
        nb.add(tab_srcs, text="Imported Elevation Sources")

        cols = ("code", "center_el", "min_el", "max_el", "mean_el", "source", "updated")
        self.tree = ttk.Treeview(tab_cells, columns=cols, show="headings")
        for c, title, w in (
            ("code", "Cell", 75),
            ("center_el", "Center Elev (m)", 115),
            ("min_el", "Min (m)", 90),
            ("max_el", "Max (m)", 90),
            ("mean_el", "Mean (m)", 95),
            ("source", "Elevation Provenance", 230),
            ("updated", "Updated", 170),
        ):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, anchor="e" if "el" in c else "w")
        vsb = ttk.Scrollbar(tab_cells, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        scols = ("name", "file", "crs", "imported", "desc")
        self.src_tree = ttk.Treeview(tab_srcs, columns=scols, show="headings")
        for c, title, w in (
            ("name", "Source Name", 150),
            ("file", "File Name", 170),
            ("crs", "CRS", 140),
            ("imported", "Imported At", 160),
            ("desc", "Summary", 280),
        ):
            self.src_tree.heading(c, text=title)
            self.src_tree.column(c, width=w, anchor="w")
        svsb = ttk.Scrollbar(tab_srcs, orient="vertical", command=self.src_tree.yview)
        self.src_tree.configure(yscrollcommand=svsb.set)
        self.src_tree.pack(side="left", fill="both", expand=True)
        svsb.pack(side="right", fill="y")

    def refresh(self, cells: list[GridCell], sources: list[ElevationSourceRecord]) -> None:
        self._has_workspace = bool(cells)
        imported = 0
        manual = 0
        missing = 0

        for item in self.tree.get_children():
            self.tree.delete(item)

        for c in cells:
            has_val = c.elevation_m is not None or c.mean_elevation_m is not None
            src = c.elevation_source or "NULL (Missing)"
            if not has_val:
                missing += 1
            elif src.startswith("Imported Raster"):
                imported += 1
            else:
                manual += 1

            self.tree.insert(
                "",
                "end",
                values=(
                    c.cell_code,
                    "NULL" if c.elevation_m is None else f"{c.elevation_m:.2f}",
                    "NULL" if c.min_elevation_m is None else f"{c.min_elevation_m:.2f}",
                    "NULL" if c.max_elevation_m is None else f"{c.max_elevation_m:.2f}",
                    "NULL" if c.mean_elevation_m is None else f"{c.mean_elevation_m:.2f}",
                    src,
                    c.updated_at,
                ),
            )

        self.c_imported.update_card(f"{imported}", "Raster-sampled elevations")
        self.c_manual.update_card(f"{manual}", "User-provided / illustrative")
        self.c_missing.update_card(f"{missing}", "Left NULL until trusted data exists")

        for item in self.src_tree.get_children():
            self.src_tree.delete(item)
        for s in sources:
            self.src_tree.insert(
                "",
                "end",
                values=(s.source_name, s.file_name, s.coordinate_reference_system, s.imported_at, s.source_description),
            )

    def _handle_browse(self) -> None:
        if not self._has_workspace:
            messagebox.showinfo("Workspace Required", "Create or load a neighbourhood workspace first.")
            return
        file_path = filedialog.askopenfilename(
            title="Select Elevation GeoTIFF",
            filetypes=[("GeoTIFF Raster", "*.tif *.tiff"), ("All Files", "*.*")],
        )
        if file_path:
            self.on_import_geotiff(file_path, self.src_name_var.get().strip())
