"""Phase 2 Advanced GIS Map & Simulation Grid Editor view."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from config import (
    DEFAULT_GRID_COLS,
    DEFAULT_GRID_ROWS,
    DEFAULT_LOCATION_QUERY,
    DEFAULT_WORKSPACE_NAME,
    ELEVATION_SOURCE_OPTIONS,
    LAND_USE_OPTIONS,
    MAP_COLORS,
    THEME,
)
from core.models import (
    DrainageFeature,
    GeocodingResult,
    GridCell,
    Neighbourhood,
    OSMFeature,
    approximate_cell_dimensions_m,
)
from core.validation import ValidationError, validate_bounding_box, validate_grid_dimensions
from visualization.grid_renderer import GridRenderer
from visualization.map_renderer import GeoViewport, MapRenderer


class MapEditorView(tk.Frame):
    """Dual-layer OSM + Drainage + Simulation Grid interactive GIS workspace."""

    def __init__(
        self,
        parent: tk.Misc,
        on_resolve_location: Callable[[str], None],
        on_create_workspace: Callable[[str, GeocodingResult | None, float, float, float, float, int, int], None],
        on_import_osm: Callable[[bool], None],
        on_cancel_network: Callable[[], None],
        on_save_cell: Callable[[GridCell, str, str, str, str, str, str], GridCell | None],
        on_bulk_save_cells: Callable[[list[GridCell], str, str, str, str, str, str], int],
        on_export_grid: Callable[[], tuple[str, str] | None],
        on_apply_grid_dims: Callable[[int, int], None],
        on_get_feature_cells: Callable[[int], list[str]] | None = None,
        on_place_drainage_at: Callable[[float, float], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=14, pady=10)
        self.on_resolve_location = on_resolve_location
        self.on_create_workspace = on_create_workspace
        self.on_import_osm = on_import_osm
        self.on_cancel_network = on_cancel_network
        self.on_save_cell = on_save_cell
        self.on_bulk_save_cells = on_bulk_save_cells
        self.on_export_grid = on_export_grid
        self.on_apply_grid_dims = on_apply_grid_dims
        self.on_get_feature_cells = on_get_feature_cells
        self.on_place_drainage_at = on_place_drainage_at

        self._map_renderer = MapRenderer()
        self._grid_renderer = GridRenderer()
        self._viewport: GeoViewport | None = None

        self._neighbourhood: Neighbourhood | None = None
        self._cells: list[GridCell] = []
        self._features: list[OSMFeature] = []
        self._drainage_features: list[DrainageFeature] = []
        self._selected_cell_ids: set[int] = set()
        self._selected_osm_id: int | None = None
        self._selected_drainage_id: int | None = None
        self._resolved_candidates: list[GeocodingResult] = []
        self._active_candidate: GeocodingResult | None = None
        self._is_offline: bool = False
        self._is_busy: bool = False

        # Pan / Click state
        self._drag_start: tuple[int, int] | None = None
        self._drag_last: tuple[int, int] | None = None
        self._drag_moved: bool = False

        self._build_ui()

    def _build_ui(self) -> None:
        # ---------------------------------------------------------------------
        # Top Location & Import Control Bar
        # ---------------------------------------------------------------------
        top_bar = tk.Frame(
            self,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        top_bar.pack(fill="x", pady=(0, 8))

        r1 = tk.Frame(top_bar, bg=THEME["bg_card"])
        r1.pack(fill="x", pady=(0, 6))

        tk.Label(
            r1,
            text="Location Query:",
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(0, 6))

        self.search_var = tk.StringVar(value=DEFAULT_LOCATION_QUERY)
        ttk.Entry(r1, textvariable=self.search_var, width=38).pack(
            side="left", padx=(0, 8), fill="x", expand=True
        )

        self.resolve_btn = ttk.Button(
            r1,
            text="1. Resolve Location",
            command=self._handle_resolve,
        )
        self.resolve_btn.pack(side="left", padx=(0, 8))

        tk.Label(
            r1,
            text="Workspace:",
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=(0, 6))

        self.ws_name_var = tk.StringVar(value=DEFAULT_WORKSPACE_NAME)
        ttk.Entry(r1, textvariable=self.ws_name_var, width=15).pack(side="left", padx=(0, 8))

        self.create_ws_btn = ttk.Button(
            r1,
            text="2. Create / Load Workspace",
            style="Accent.TButton",
            command=self._handle_create_workspace,
        )
        self.create_ws_btn.pack(side="left", padx=(0, 8))

        self.import_osm_btn = ttk.Button(
            r1,
            text="3. Import OSM Features",
            command=self._handle_import_osm,
        )
        self.import_osm_btn.pack(side="left", padx=(0, 6))

        self.force_refresh_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r1, text="Force Refresh", variable=self.force_refresh_var).pack(
            side="left", padx=(0, 6)
        )

        self.cancel_btn = ttk.Button(
            r1,
            text="Cancel",
            style="Danger.TButton",
            command=self.on_cancel_network,
            state="disabled",
        )
        self.cancel_btn.pack(side="left")

        r2 = tk.Frame(top_bar, bg=THEME["bg_card"])
        r2.pack(fill="x")

        tk.Label(
            r2,
            text="Resolved Place:",
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(0, 6))

        self.candidate_var = tk.StringVar()
        self.candidate_combo = ttk.Combobox(
            r2, textvariable=self.candidate_var, state="readonly", width=40
        )
        self.candidate_combo.pack(side="left", padx=(0, 8))
        self.candidate_combo.bind("<<ComboboxSelected>>", self._on_candidate_selected)

        self.min_lat_var = tk.StringVar()
        self.max_lat_var = tk.StringVar()
        self.min_lon_var = tk.StringVar()
        self.max_lon_var = tk.StringVar()

        for lbl, var in (
            ("S Lat:", self.min_lat_var),
            ("N Lat:", self.max_lat_var),
            ("W Lon:", self.min_lon_var),
            ("E Lon:", self.max_lon_var),
        ):
            tk.Label(r2, text=lbl, bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 8)).pack(
                side="left", padx=(2, 2)
            )
            ttk.Entry(r2, textvariable=var, width=9).pack(side="left", padx=(0, 5))

        self.bbox_info_lbl = tk.Label(
            r2,
            text="Resolve a location to review bounding box.",
            bg=THEME["bg_card"],
            fg=THEME["info"],
            font=("Segoe UI", 8),
        )
        self.bbox_info_lbl.pack(side="left", padx=(6, 0))

        # ---------------------------------------------------------------------
        # Main Split: Left Map Canvas | Right Inspector Panel
        # ---------------------------------------------------------------------
        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0, minsize=370)
        body.rowconfigure(0, weight=1)

        map_panel = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
        )
        map_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # Toolbar Row 1: Zoom / Mode / Grid Dimensions
        tools1 = tk.Frame(map_panel, bg=THEME["bg_card_alt"], padx=10, pady=5)
        tools1.pack(fill="x")

        ttk.Button(tools1, text="Zoom +", width=7, command=lambda: self._zoom_center(1.25)).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(tools1, text="Zoom -", width=7, command=lambda: self._zoom_center(0.8)).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(tools1, text="Reset View", width=10, command=self._reset_view).pack(
            side="left", padx=(0, 12)
        )

        tk.Label(
            tools1,
            text="Click Mode:",
            bg=THEME["bg_card_alt"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(0, 4))
        self.click_mode_var = tk.StringVar(value="Select Grid Cell")
        mode_combo = ttk.Combobox(
            tools1,
            textvariable=self.click_mode_var,
            values=("Select Grid Cell", "Inspect Feature", "Place Drainage"),
            state="readonly",
            width=16,
        )
        mode_combo.pack(side="left", padx=(0, 10))

        self.cursor_coord_lbl = tk.Label(
            tools1,
            text="Lat: —, Lon: —",
            bg=THEME["bg_card_alt"],
            fg=THEME["accent_hover"],
            font=("Consolas", 8, "bold"),
        )
        self.cursor_coord_lbl.pack(side="left", padx=(4, 0))

        dim_box = tk.Frame(tools1, bg=THEME["bg_card_alt"])
        dim_box.pack(side="right")
        tk.Label(
            dim_box,
            text="Grid:",
            bg=THEME["bg_card_alt"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(0, 4))
        self.rows_var = tk.StringVar(value=str(DEFAULT_GRID_ROWS))
        self.cols_var = tk.StringVar(value=str(DEFAULT_GRID_COLS))
        ttk.Entry(dim_box, textvariable=self.rows_var, width=4).pack(side="left")
        tk.Label(dim_box, text="×", bg=THEME["bg_card_alt"], fg=THEME["text_secondary"]).pack(
            side="left", padx=2
        )
        ttk.Entry(dim_box, textvariable=self.cols_var, width=4).pack(side="left", padx=(0, 6))
        ttk.Button(dim_box, text="Apply Grid", command=self._handle_apply_grid_dims).pack(side="left")

        # Toolbar Row 2: Granular Layer Visibility Controls
        tools2 = tk.Frame(map_panel, bg=THEME["bg_surface"], padx=10, pady=4)
        tools2.pack(fill="x")

        tk.Label(
            tools2,
            text="Layers:",
            bg=THEME["bg_surface"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8, "bold"),
        ).pack(side="left", padx=(0, 6))

        self.show_roads_var = tk.BooleanVar(value=True)
        self.show_buildings_var = tk.BooleanVar(value=True)
        self.show_water_var = tk.BooleanVar(value=True)
        self.show_green_var = tk.BooleanVar(value=True)
        self.show_wetlands_var = tk.BooleanVar(value=True)
        self.show_drainage_var = tk.BooleanVar(value=True)
        self.show_grid_var = tk.BooleanVar(value=True)
        self.show_tint_var = tk.BooleanVar(value=True)
        self.show_labels_var = tk.BooleanVar(value=True)

        for text, var in (
            ("Roads", self.show_roads_var),
            ("Buildings", self.show_buildings_var),
            ("Water", self.show_water_var),
            ("Parks/Green", self.show_green_var),
            ("Wetlands", self.show_wetlands_var),
            ("Drainage", self.show_drainage_var),
            ("Grid", self.show_grid_var),
            ("Land-Use Tint", self.show_tint_var),
            ("Cell IDs", self.show_labels_var),
        ):
            ttk.Checkbutton(tools2, text=text, variable=var, command=self._render_canvas).pack(
                side="left", padx=3
            )

        # Interactive Canvas
        self.canvas = tk.Canvas(
            map_panel,
            bg=MAP_COLORS["canvas_bg"],
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonPress-1>", self._on_left_press)
        self.canvas.bind("<B1-Motion>", self._on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_left_release)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_press)
        self.canvas.bind("<B3-Motion>", self._on_pan_drag)
        self.canvas.bind("<ButtonPress-2>", self._on_pan_press)
        self.canvas.bind("<B2-Motion>", self._on_pan_drag)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._zoom_at_event(1.15, e))
        self.canvas.bind("<Button-5>", lambda e: self._zoom_at_event(0.87, e))

        # Bottom Legend & Grid Resolution Bar
        legend_bar = tk.Frame(map_panel, bg=THEME["bg_card_alt"], padx=10, pady=5)
        legend_bar.pack(fill="x")
        legend_items = [
            ("Major", MAP_COLORS["road_motorway"]),
            ("Primary", MAP_COLORS["road_primary"]),
            ("Secondary", MAP_COLORS["road_secondary"]),
            ("Water", MAP_COLORS["waterway_line"]),
            ("Building", MAP_COLORS["building_outline"]),
            ("Green", MAP_COLORS["green_outline"]),
            ("Drainage", MAP_COLORS["drainage_operational"]),
            ("Selected", MAP_COLORS["grid_selected"]),
        ]
        for label, color in legend_items:
            swatch = tk.Frame(legend_bar, bg=color, width=10, height=10)
            swatch.pack(side="left", padx=(0, 3))
            tk.Label(
                legend_bar,
                text=label,
                bg=THEME["bg_card_alt"],
                fg=THEME["text_secondary"],
                font=("Segoe UI", 8),
            ).pack(side="left", padx=(0, 8))

        self.grid_res_lbl = tk.Label(
            legend_bar,
            text="Pan: drag • Zoom: scroll",
            bg=THEME["bg_card_alt"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
        )
        self.grid_res_lbl.pack(side="right")

        # ---------------------------------------------------------------------
        # Right Inspector Panel (Notebook: Grid Cell Editor | Selected Feature)
        # ---------------------------------------------------------------------
        props_panel = tk.Frame(
            body,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=370,
            padx=12,
            pady=10,
        )
        props_panel.grid(row=0, column=1, sticky="nsew")
        props_panel.grid_propagate(False)

        self.inspector_tabs = ttk.Notebook(props_panel)
        self.inspector_tabs.pack(fill="both", expand=True)

        self.cell_tab = tk.Frame(self.inspector_tabs, bg=THEME["bg_card"], padx=4, pady=8)
        self.feat_tab = tk.Frame(self.inspector_tabs, bg=THEME["bg_card"], padx=4, pady=8)
        self.inspector_tabs.add(self.cell_tab, text="Grid Cell Editor")
        self.inspector_tabs.add(self.feat_tab, text="Feature Inspector")

        self._build_cell_tab(self.cell_tab)
        self._build_feature_tab(self.feat_tab)

    def _build_cell_tab(self, parent: tk.Frame) -> None:
        self.sel_header_lbl = tk.Label(
            parent,
            text="No Cell Selected",
            bg=THEME["bg_card"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 12, "bold"),
        )
        self.sel_header_lbl.pack(anchor="w")

        self.sel_meta_lbl = tk.Label(
            parent,
            text="Click any cell on the grid to inspect coordinates and edit attributes.",
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            wraplength=325,
            justify="left",
        )
        self.sel_meta_lbl.pack(anchor="w", pady=(0, 8))

        geo_box = tk.Frame(
            parent,
            bg=THEME["bg_input"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=7,
        )
        geo_box.pack(fill="x", pady=(0, 8))
        self.geo_details_lbl = tk.Label(
            geo_box,
            text="Cell ID: —\nRow / Col: —\nCenter: —\nApprox Size & Area: —\nElev Min/Max/Mean: —",
            bg=THEME["bg_input"],
            fg=THEME["text_secondary"],
            font=("Consolas", 8),
            justify="left",
            anchor="w",
        )
        self.geo_details_lbl.pack(fill="x")

        form = tk.Frame(parent, bg=THEME["bg_card"])
        form.pack(fill="x")

        tk.Label(
            form,
            text="Land-Use Classification:",
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")
        self.land_use_var = tk.StringVar(value="Unknown")
        self.land_use_combo = ttk.Combobox(
            form, textvariable=self.land_use_var, values=LAND_USE_OPTIONS, state="readonly"
        )
        self.land_use_combo.pack(fill="x", pady=(2, 6))

        elev_row = tk.Frame(form, bg=THEME["bg_card"])
        elev_row.pack(fill="x", pady=(0, 6))
        elev_row.columnconfigure(0, weight=1)
        elev_row.columnconfigure(1, weight=1)

        tk.Label(elev_row, text="Elevation (m):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(elev_row, text="Elevation Source:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.elev_var = tk.StringVar()
        ttk.Entry(elev_row, textvariable=self.elev_var).grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.elev_src_var = tk.StringVar(value="Unset (NULL)")
        ttk.Combobox(
            elev_row, textvariable=self.elev_src_var, values=ELEVATION_SOURCE_OPTIONS, state="readonly"
        ).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(2, 0))

        rate_row = tk.Frame(form, bg=THEME["bg_card"])
        rate_row.pack(fill="x", pady=(0, 6))
        rate_row.columnconfigure(0, weight=1)
        rate_row.columnconfigure(1, weight=1)

        tk.Label(rate_row, text="Infiltration (mm/hr):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(rate_row, text="Drainage Cap (mm/hr):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.infil_var = tk.StringVar(value="0.0")
        self.drain_var = tk.StringVar(value="0.0")
        ttk.Entry(rate_row, textvariable=self.infil_var).grid(row=1, column=0, sticky="ew", pady=(2, 0))
        ttk.Entry(rate_row, textvariable=self.drain_var).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(2, 0))

        tk.Label(form, text="Field / Engineering Notes:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.notes_text = tk.Text(
            form,
            height=3,
            bg=THEME["bg_input"],
            fg=THEME["text_primary"],
            insertbackground=THEME["text_primary"],
            relief="solid",
            bd=1,
            font=("Segoe UI", 9),
            wrap="word",
        )
        self.notes_text.pack(fill="x", pady=(2, 8))

        btn_grid = tk.Frame(parent, bg=THEME["bg_card"])
        btn_grid.pack(fill="x", pady=(0, 6))
        btn_grid.columnconfigure(0, weight=1)
        btn_grid.columnconfigure(1, weight=1)

        self.save_cell_btn = ttk.Button(
            btn_grid, text="Save Cell", style="Accent.TButton", command=self._handle_save_cell
        )
        self.save_cell_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 5))

        self.reset_cell_btn = ttk.Button(
            btn_grid, text="Reset Changes", command=self._handle_reset_cell
        )
        self.reset_cell_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 5))

        ttk.Button(btn_grid, text="Select All", command=self._handle_select_all).grid(
            row=1, column=0, sticky="ew", padx=(0, 4), pady=(0, 5)
        )
        ttk.Button(btn_grid, text="Clear Selection", command=self._handle_clear_selection).grid(
            row=1, column=1, sticky="ew", padx=(4, 0), pady=(0, 5)
        )

        ttk.Button(parent, text="Export Grid (GeoJSON + CSV)", command=self._handle_export_grid).pack(
            fill="x", pady=(2, 6)
        )

        self.status_msg_lbl = tk.Label(
            parent,
            text="",
            bg=THEME["bg_card"],
            fg=THEME["accent_teal"],
            font=("Segoe UI", 8),
            wraplength=325,
            justify="left",
        )
        self.status_msg_lbl.pack(anchor="w")
        self._set_form_enabled(False)

    def _build_feature_tab(self, parent: tk.Frame) -> None:
        tk.Label(
            parent,
            text="Selected Geographical Feature",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        tk.Label(
            parent,
            text="Switch Click Mode above to 'Inspect Feature', then click any road, building, waterbody, park, or drainage point.",
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            wraplength=325,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))

        self.feat_info_text = tk.Text(
            parent,
            height=20,
            bg=THEME["bg_input"],
            fg=THEME["text_primary"],
            relief="solid",
            bd=1,
            font=("Consolas", 9),
            wrap="word",
            state="disabled",
        )
        self.feat_info_text.pack(fill="both", expand=True)

    # -------------------------------------------------------------------------
    # State Updates from App Controller
    # -------------------------------------------------------------------------

    def set_workspace_data(
        self,
        neighbourhood: Neighbourhood | None,
        cells: list[GridCell],
        features: list[OSMFeature],
        drainage_features: list[DrainageFeature] | None = None,
        reset_viewport: bool = False,
    ) -> None:
        self._neighbourhood = neighbourhood
        self._cells = cells
        self._features = features
        if drainage_features is not None:
            self._drainage_features = drainage_features

        if neighbourhood is not None:
            self.ws_name_var.set(neighbourhood.name)
            self.rows_var.set(str(neighbourhood.grid_rows))
            self.cols_var.set(str(neighbourhood.grid_cols))
            self.min_lat_var.set(f"{neighbourhood.min_latitude:.6f}")
            self.max_lat_var.set(f"{neighbourhood.max_latitude:.6f}")
            self.min_lon_var.set(f"{neighbourhood.min_longitude:.6f}")
            self.max_lon_var.set(f"{neighbourhood.max_longitude:.6f}")
            w_m, h_m = neighbourhood.approx_dimensions_m()
            cell_w = w_m / max(1, neighbourhood.grid_cols)
            cell_h = h_m / max(1, neighbourhood.grid_rows)
            self.bbox_info_lbl.configure(
                text=f"Area ~{w_m:.0f}m × {h_m:.0f}m | Cell ~{cell_w:.0f}m × {cell_h:.0f}m"
            )
            self.grid_res_lbl.configure(
                text=f"Grid {neighbourhood.grid_rows}×{neighbourhood.grid_cols} | Cell ~{cell_w:.0f}m × {cell_h:.0f}m"
            )

            if self._viewport is None or reset_viewport:
                self._viewport = GeoViewport(
                    neighbourhood.min_latitude,
                    neighbourhood.max_latitude,
                    neighbourhood.min_longitude,
                    neighbourhood.max_longitude,
                    width=max(200, self.canvas.winfo_width()),
                    height=max(200, self.canvas.winfo_height()),
                )
            else:
                self._viewport.set_bounds(
                    neighbourhood.min_latitude,
                    neighbourhood.max_latitude,
                    neighbourhood.min_longitude,
                    neighbourhood.max_longitude,
                )
        else:
            self._viewport = None

        valid_ids = {c.id for c in cells if c.id is not None}
        self._selected_cell_ids &= valid_ids
        self._populate_selection_panel()
        self._render_canvas()

    def set_geocoding_results(self, results: list[GeocodingResult]) -> None:
        self._resolved_candidates = results
        labels = [
            f"{r.name} ({r.latitude:.4f}, {r.longitude:.4f}) — {r.display_name[:60]}"
            for r in results
        ]
        self.candidate_combo["values"] = labels
        if results:
            self.candidate_combo.current(0)
            self._apply_candidate(results[0])

    def set_network_state(self, is_offline: bool, is_busy: bool) -> None:
        self._is_offline = is_offline
        self._is_busy = is_busy
        net_state = "disabled" if (is_offline or is_busy) else "normal"
        self.resolve_btn.configure(state=net_state)
        self.import_osm_btn.configure(state=net_state if self._neighbourhood else "disabled")
        self.create_ws_btn.configure(state="disabled" if is_busy else "normal")
        self.cancel_btn.configure(state="normal" if is_busy else "disabled")

    def set_status_message(self, msg: str, color: str = THEME["accent_teal"]) -> None:
        self.status_msg_lbl.configure(text=msg, fg=color)

    # -------------------------------------------------------------------------
    # Geocoding & Workspace Handlers
    # -------------------------------------------------------------------------

    def _on_candidate_selected(self, _event: tk.Event) -> None:
        idx = self.candidate_combo.current()
        if 0 <= idx < len(self._resolved_candidates):
            self._apply_candidate(self._resolved_candidates[idx])

    def _apply_candidate(self, cand: GeocodingResult) -> None:
        self._active_candidate = cand
        self.min_lat_var.set(f"{cand.min_latitude:.6f}")
        self.max_lat_var.set(f"{cand.max_latitude:.6f}")
        self.min_lon_var.set(f"{cand.min_longitude:.6f}")
        self.max_lon_var.set(f"{cand.max_longitude:.6f}")
        if not self.ws_name_var.get().strip() or self.ws_name_var.get().strip().upper() == DEFAULT_WORKSPACE_NAME:
            if cand.name:
                self.ws_name_var.set(cand.name.upper())
        w_m, h_m = approximate_cell_dimensions_m(
            cand.min_latitude, cand.max_latitude, cand.min_longitude, cand.max_longitude
        )
        note = f" ({cand.bbox_adjusted_note})" if cand.bbox_adjusted_note else ""
        self.bbox_info_lbl.configure(text=f"Resolved: ~{w_m:.0f}m × {h_m:.0f}m{note}")

    def _handle_resolve(self) -> None:
        query = self.search_var.get().strip()
        if not query:
            messagebox.showwarning("Location Query Empty", "Enter a neighbourhood location to resolve.")
            return
        self.on_resolve_location(query)

    def _handle_create_workspace(self) -> None:
        name = self.ws_name_var.get().strip()
        if not name:
            messagebox.showerror("Invalid Name", "Please enter a non-empty workspace name.")
            return
        try:
            s, n, w, e = validate_bounding_box(
                self.min_lat_var.get(),
                self.max_lat_var.get(),
                self.min_lon_var.get(),
                self.max_lon_var.get(),
            )
            rows, cols = validate_grid_dimensions(self.rows_var.get(), self.cols_var.get())
        except ValidationError as exc:
            messagebox.showerror(
                "Bounding Box / Grid Validation Error",
                f"{exc}\n\nTip: Click '1. Resolve Location' first when online to populate verified coordinates.",
            )
            return

        self.on_create_workspace(name, self._active_candidate, s, n, w, e, rows, cols)

    def _handle_import_osm(self) -> None:
        if self._neighbourhood is None:
            messagebox.showinfo("Workspace Required", "Create or load a workspace before importing OSM features.")
            return
        self.on_import_osm(bool(self.force_refresh_var.get()))

    def _handle_apply_grid_dims(self) -> None:
        if self._neighbourhood is None:
            messagebox.showinfo("No Workspace", "Create or load a workspace first.")
            return
        try:
            rows, cols = validate_grid_dimensions(self.rows_var.get(), self.cols_var.get())
        except ValidationError as exc:
            messagebox.showerror("Invalid Grid Dimensions", str(exc))
            return

        if rows == self._neighbourhood.grid_rows and cols == self._neighbourhood.grid_cols:
            return

        if messagebox.askyesno(
            "Regenerate Simulation Grid",
            f"Change grid from {self._neighbourhood.grid_rows}×{self._neighbourhood.grid_cols} "
            f"to {rows}×{cols} ({rows * cols} cells)?\n\n"
            "Existing cell attributes overlapping the new cell centers will be preserved.",
        ):
            self.on_apply_grid_dims(rows, cols)

    # -------------------------------------------------------------------------
    # Canvas Rendering & Mouse Interaction
    # -------------------------------------------------------------------------

    def _on_canvas_resize(self, event: tk.Event) -> None:
        if self._viewport is not None:
            self._viewport.resize(event.width, event.height)
        self._render_canvas()

    def _on_mouse_move(self, event: tk.Event) -> None:
        if self._viewport is None:
            return
        lat, lon = self._viewport.screen_to_geo(event.x, event.y)
        self.cursor_coord_lbl.configure(text=f"Lat: {lat:.5f}, Lon: {lon:.5f}")

    def _render_canvas(self) -> None:
        self.canvas.delete("all")
        if self._neighbourhood is None or self._viewport is None:
            w = max(200, self.canvas.winfo_width())
            h = max(200, self.canvas.winfo_height())
            self.canvas.create_text(
                w / 2.0,
                h / 2.0 - 12,
                text="Advanced GIS Map Editor Ready",
                fill=THEME["text_primary"],
                font=("Segoe UI", 13, "bold"),
            )
            self.canvas.create_text(
                w / 2.0,
                h / 2.0 + 14,
                text="1. Resolve Location  →  2. Create / Load Workspace  →  3. Import OSM Features",
                fill=THEME["text_muted"],
                font=("Segoe UI", 9),
            )
            return

        self._map_renderer.render(
            self.canvas,
            self._viewport,
            self._neighbourhood,
            self._features,
            drainage_features=self._drainage_features,
            show_osm=True,
            show_roads=bool(self.show_roads_var.get()),
            show_buildings=bool(self.show_buildings_var.get()),
            show_water=bool(self.show_water_var.get()),
            show_green=bool(self.show_green_var.get()),
            show_wetlands=bool(self.show_wetlands_var.get()),
            show_drainage=bool(self.show_drainage_var.get()),
            selected_osm_id=self._selected_osm_id,
            selected_drainage_id=self._selected_drainage_id,
            draw_hud=True,
        )
        self._grid_renderer.render(
            self.canvas,
            self._viewport,
            self._cells,
            selected_cell_ids=self._selected_cell_ids,
            show_grid=bool(self.show_grid_var.get()),
            show_land_use_tint=bool(self.show_tint_var.get()),
            show_labels=bool(self.show_labels_var.get()),
        )

    def _zoom_center(self, factor: float) -> None:
        if self._viewport is None:
            return
        self._viewport.zoom_at(factor, self.canvas.winfo_width() / 2.0, self.canvas.winfo_height() / 2.0)
        self._render_canvas()

    def _reset_view(self) -> None:
        if self._viewport is None:
            return
        self._viewport.reset_view()
        self._render_canvas()

    def _on_mouse_wheel(self, event: tk.Event) -> None:
        self._zoom_at_event(1.15 if event.delta > 0 else 0.87, event)

    def _zoom_at_event(self, factor: float, event: tk.Event) -> None:
        if self._viewport is None:
            return
        self._viewport.zoom_at(factor, event.x, event.y)
        self._render_canvas()

    def _on_left_press(self, event: tk.Event) -> None:
        self._drag_start = (event.x, event.y)
        self._drag_last = (event.x, event.y)
        self._drag_moved = False

    def _on_left_drag(self, event: tk.Event) -> None:
        if self._viewport is None or self._drag_last is None or self._drag_start is None:
            return
        if abs(event.x - self._drag_start[0]) > 4 or abs(event.y - self._drag_start[1]) > 4:
            self._drag_moved = True
        if self._drag_moved:
            dx = event.x - self._drag_last[0]
            dy = event.y - self._drag_last[1]
            self._viewport.pan_by(dx, dy)
            self._drag_last = (event.x, event.y)
            self._render_canvas()

    def _on_left_release(self, event: tk.Event) -> None:
        was_drag = self._drag_moved
        self._drag_start = None
        self._drag_last = None
        self._drag_moved = False
        if was_drag or self._viewport is None:
            return

        mode = self.click_mode_var.get()
        if mode == "Place Drainage":
            lat, lon = self._viewport.screen_to_geo(event.x, event.y)
            if self.on_place_drainage_at is not None:
                self.on_place_drainage_at(lat, lon)
            return

        if mode == "Inspect Feature":
            visible_osm = self._get_visible_osm_features()
            visible_drain = self._drainage_features if self.show_drainage_var.get() else []
            hit = self._map_renderer.hit_test_feature(
                visible_osm, visible_drain, self._viewport, event.x, event.y
            )
            if hit is not None:
                kind, obj = hit
                self._display_selected_feature(kind, obj)
                self.inspector_tabs.select(self.feat_tab)
                self._render_canvas()
            return

        hit = self._grid_renderer.hit_test(self._cells, self._viewport, event.x, event.y)
        if hit is None or hit.id is None:
            return

        ctrl_pressed = bool(event.state & 0x0004)
        if ctrl_pressed:
            if hit.id in self._selected_cell_ids:
                self._selected_cell_ids.remove(hit.id)
            else:
                self._selected_cell_ids.add(hit.id)
        else:
            self._selected_cell_ids = {hit.id}

        self._populate_selection_panel()
        self.inspector_tabs.select(self.cell_tab)
        self._render_canvas()

    def _get_visible_osm_features(self) -> list[OSMFeature]:
        out: list[OSMFeature] = []
        for f in self._features:
            if f.category == "road" and not self.show_roads_var.get():
                continue
            if f.category == "building" and not self.show_buildings_var.get():
                continue
            if f.category == "waterway" and not self.show_water_var.get():
                continue
            if f.category == "green_area" and f.subcategory == "wetland" and not self.show_wetlands_var.get():
                continue
            if f.category == "green_area" and f.subcategory != "wetland" and not self.show_green_var.get():
                continue
            out.append(f)
        return out

    def _display_selected_feature(self, kind: str, obj: OSMFeature | DrainageFeature) -> None:
        self.feat_info_text.configure(state="normal")
        self.feat_info_text.delete("1.0", tk.END)
        if kind == "drainage" and isinstance(obj, DrainageFeature):
            self._selected_drainage_id = obj.id
            self._selected_osm_id = None
            lines = [
                f"Type: Drainage Element ({obj.feature_type})",
                f"ID: #{obj.id}",
                f"Name: {obj.name}",
                f"Status: {obj.status}",
                f"Coordinates: {obj.latitude:.6f}, {obj.longitude:.6f}",
                f"Grid Cell ID: {obj.grid_cell_id or 'Unlinked'}",
                f"Capacity: {obj.capacity if obj.capacity is not None else 'N/A'} {obj.capacity_unit}",
                f"Source: {obj.source}",
                f"Notes: {obj.notes or '—'}",
            ]
        elif isinstance(obj, OSMFeature):
            self._selected_osm_id = obj.id
            self._selected_drainage_id = None
            linked_cells = (
                self.on_get_feature_cells(obj.id)
                if (self.on_get_feature_cells and obj.id is not None)
                else []
            )
            lines = [
                f"Category: {obj.category} ({obj.subcategory})",
                f"DB ID: #{obj.id} | OSM: {obj.element_type}/{obj.osm_id}",
                f"Name: {obj.name or '(Unnamed)'}",
            ]
            if obj.road_category:
                lines.append(f"Road Class: {obj.road_category}")
            if obj.building_category:
                lines.append(f"Building Class: {obj.building_category}")
            if obj.length_m > 0:
                lines.append(f"Length (Geodesic): {obj.length_m:.1f} m")
            lines.extend(
                [
                    f"Source: {obj.source}",
                    f"Imported At: {obj.imported_at}",
                    f"User Edited: {'Yes' if obj.is_user_edited else 'No'}",
                    f"Intersecting Cells ({len(linked_cells)}): {', '.join(linked_cells) if linked_cells else 'Run Spatial Link Rebuild'}",
                    f"User Notes: {obj.user_notes or '—'}",
                    "",
                    "--- OSM Tags ---",
                ]
            )
            for k, v in list(obj.tags.items())[:20]:
                lines.append(f"  {k}: {v}")
            if obj.category == "waterway":
                lines.append("\nNote: Storage & flood-retention capacity are NOT assumed from OSM geometry.")
            if obj.category == "building":
                lines.append("\nNote: Occupancy & population are NOT inferred from geometry.")
        else:
            lines = ["No feature selected."]

        self.feat_info_text.insert("1.0", "\n".join(lines))
        self.feat_info_text.configure(state="disabled")

    def _on_pan_press(self, event: tk.Event) -> None:
        self._drag_last = (event.x, event.y)

    def _on_pan_drag(self, event: tk.Event) -> None:
        if self._viewport is None or self._drag_last is None:
            return
        dx = event.x - self._drag_last[0]
        dy = event.y - self._drag_last[1]
        self._drag_last = (event.x, event.y)
        self._viewport.pan_by(dx, dy)
        self._render_canvas()

    # -------------------------------------------------------------------------
    # Cell Selection & Editing Panel
    # -------------------------------------------------------------------------

    def _get_selected_cells(self) -> list[GridCell]:
        return [c for c in self._cells if c.id is not None and c.id in self._selected_cell_ids]

    def _set_form_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        ro_state = "readonly" if enabled else "disabled"
        self.land_use_combo.configure(state=ro_state)
        self.save_cell_btn.configure(state=state)
        self.reset_cell_btn.configure(state=state)

    def _populate_selection_panel(self) -> None:
        selected = self._get_selected_cells()
        if not selected:
            self.sel_header_lbl.configure(text="No Cell Selected")
            self.sel_meta_lbl.configure(
                text="Click any cell on the grid to inspect coordinates and edit attributes."
            )
            self.geo_details_lbl.configure(
                text="Cell ID: —\nRow / Col: —\nCenter: —\nApprox Size & Area: —\nElev Min/Max/Mean: —"
            )
            self.land_use_var.set("Unknown")
            self.elev_var.set("")
            self.elev_src_var.set("Unset (NULL)")
            self.infil_var.set("0.0")
            self.drain_var.set("0.0")
            self.notes_text.delete("1.0", tk.END)
            self._set_form_enabled(False)
            return

        self._set_form_enabled(True)
        if len(selected) == 1:
            cell = selected[0]
            w_m, h_m = cell.approx_dimensions_m()
            area_m2 = cell.approx_area_sq_m()
            min_e = "—" if cell.min_elevation_m is None else f"{cell.min_elevation_m:.2f}m"
            max_e = "—" if cell.max_elevation_m is None else f"{cell.max_elevation_m:.2f}m"
            mean_e = "—" if cell.mean_elevation_m is None else f"{cell.mean_elevation_m:.2f}m"

            self.sel_header_lbl.configure(text=f"Cell {cell.cell_code} (ID #{cell.id})")
            self.sel_meta_lbl.configure(
                text=f"Land-use src: {cell.land_use_source} | Updated: {cell.updated_at or 'Initial'}"
            )
            self.geo_details_lbl.configure(
                text=(
                    f"Cell ID: #{cell.id} ({cell.cell_code}) | R{cell.row_number + 1}, C{cell.column_number + 1}\n"
                    f"Center: {cell.center_latitude:.6f}, {cell.center_longitude:.6f}\n"
                    f"Approx: ~{w_m:.1f}m × {h_m:.1f}m (~{area_m2:,.0f} m²)\n"
                    f"Elev Min/Max/Mean: {min_e} / {max_e} / {mean_e}"
                )
            )
            self.land_use_var.set(cell.land_use)
            self.elev_var.set("" if cell.elevation_m is None else f"{cell.elevation_m:g}")
            self.elev_src_var.set(cell.elevation_source or "Unset (NULL)")
            self.infil_var.set(f"{cell.infiltration_rate:g}")
            self.drain_var.set(f"{cell.drainage_capacity:g}")
            self.notes_text.delete("1.0", tk.END)
            self.notes_text.insert("1.0", cell.notes or "")
            self.save_cell_btn.configure(text="Save Cell")
        else:
            self.sel_header_lbl.configure(text=f"{len(selected)} Cells Selected")
            self.sel_meta_lbl.configure(
                text="Batch edit mode: saving applies these attributes to all selected cells."
            )
            self.geo_details_lbl.configure(
                text=(
                    f"Selection Count: {len(selected)} cells\n"
                    f"Range: {selected[0].cell_code} .. {selected[-1].cell_code}\n"
                    "Coordinates and areas remain unique per cell."
                )
            )
            self.save_cell_btn.configure(text=f"Save {len(selected)} Cells")

    def _handle_save_cell(self) -> None:
        selected = self._get_selected_cells()
        if not selected:
            return
        elev_in = self.elev_var.get().strip()
        elev_src_in = self.elev_src_var.get()
        land_use_in = self.land_use_var.get()
        infil_in = self.infil_var.get().strip()
        drain_in = self.drain_var.get().strip()
        notes_in = self.notes_text.get("1.0", tk.END).strip()

        if len(selected) == 1:
            updated = self.on_save_cell(
                selected[0], elev_in, elev_src_in, land_use_in, infil_in, drain_in, notes_in
            )
            if updated is not None:
                for idx, c in enumerate(self._cells):
                    if c.id == updated.id:
                        self._cells[idx] = updated
                        break
                self._populate_selection_panel()
                self._render_canvas()
                self.set_status_message(f"Saved {updated.cell_code} to SQLite.", THEME["success"])
        else:
            if not messagebox.askyesno(
                "Confirm Batch Cell Update",
                f"Apply these properties to all {len(selected)} selected cells?",
            ):
                return
            count = self.on_bulk_save_cells(
                selected, elev_in, elev_src_in, land_use_in, infil_in, drain_in, notes_in
            )
            if count > 0:
                self.set_status_message(f"Updated {count} cells in SQLite.", THEME["success"])

    def _handle_reset_cell(self) -> None:
        self._populate_selection_panel()
        self.set_status_message("Reverted unsaved edits.", THEME["text_muted"])

    def _handle_select_all(self) -> None:
        self._selected_cell_ids = {c.id for c in self._cells if c.id is not None}
        self._populate_selection_panel()
        self._render_canvas()

    def _handle_clear_selection(self) -> None:
        self._selected_cell_ids.clear()
        self._populate_selection_panel()
        self._render_canvas()

    def _handle_export_grid(self) -> None:
        result = self.on_export_grid()
        if result is not None:
            geojson_path, csv_path = result
            self.set_status_message(f"Exported grid to {geojson_path}", THEME["success"])
            messagebox.showinfo(
                "Grid Exported",
                f"Exported simulation grid files:\n\nGeoJSON:\n{geojson_path}\n\nCSV:\n{csv_path}",
            )
