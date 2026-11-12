"""Phase 5 SafeRoute Evacuation & Flood-Aware Route Planning Screen."""

from __future__ import annotations

import copy
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from config import (
    DEFAULT_SPEED_ASSUMPTIONS_KMH,
    MAP_COLORS,
    ROAD_STATUS_OPTIONS,
    ROUTE_COLORS,
    THEME,
    TRAVEL_MODES,
)
from core.flood_statistics import extract_step_cell_data
from core.models import DrainageFeature, GridCell, Neighbourhood, OSMFeature
from core.risk_classifier import HeatmapColorScale, RiskThresholds
from core.simulation_engine import SimulationOutput, SimulationRunRecord
from core.validation import ValidationError
from routing.flood_exposure import (
    RoadExposureThresholds,
    RoadFloodExposure,
    analyze_road_network_exposure,
)
from routing.road_network import (
    EvacuationDestination,
    RoadNetworkGraph,
    build_road_network_from_osm,
    extract_evacuation_destinations,
)
from routing.route_comparison import RouteMetrics
from routing.route_planner import (
    RoadConditionRecord,
    RouteCostWeights,
    RoutePlanningResult,
    calculate_evacuation_routes,
)
from routing.travel_time import TravelSpeedConfig
from visualization.heatmap_renderer import HeatmapRenderer
from visualization.map_renderer import GeoViewport, MapRenderer
from visualization.route_renderer import RouteRenderer


class SafeRouteScreen(tk.Frame):
    """Interactive SafeRoute evacuation planner integrated with Phases 1–4."""

    def __init__(
        self,
        parent: tk.Misc,
        on_fetch_simulation: Callable[[int], SimulationOutput | None],
        on_sync_road_network: Callable[[RoadNetworkGraph], None],
        on_load_road_conditions: Callable[[int], dict[int, RoadConditionRecord]],
        on_save_road_condition: Callable[..., None],
        on_sync_sim_conditions: Callable[
            [int, dict[int, RoadFloodExposure], dict[int, RoadConditionRecord]],
            dict[int, RoadConditionRecord],
        ],
        on_save_route_history: Callable[[int, RouteMetrics, int | None, int | None], int],
        on_list_route_history: Callable[[int], list[dict[str, Any]]],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=14, pady=10)
        self.on_fetch_simulation = on_fetch_simulation
        self.on_sync_road_network = on_sync_road_network
        self.on_load_road_conditions = on_load_road_conditions
        self.on_save_road_condition = on_save_road_condition
        self.on_sync_sim_conditions = on_sync_sim_conditions
        self.on_save_route_history = on_save_route_history
        self.on_list_route_history = on_list_route_history

        self._neighbourhood: Neighbourhood | None = None
        self._cells: list[GridCell] = []
        self._osm_features: list[OSMFeature] = []
        self._drainage_features: list[DrainageFeature] = []
        self._shelters: list[Any] = []
        self._runs: list[SimulationRunRecord] = []
        self._sim_output: SimulationOutput | None = None

        self._network: RoadNetworkGraph | None = None
        self._exposures: dict[int, RoadFloodExposure] = {}
        self._conditions: dict[int, RoadConditionRecord] = {}
        self._destinations: list[EvacuationDestination] = []
        self._selected_destination: EvacuationDestination | None = None
        self._searchable_nodes: list[tuple[str, int]] = []
        self._edge_choices: list[tuple[str, int]] = []

        self._selected_origin_id: int | None = None
        self._selected_dest_id: int | None = None
        self._selected_edge_id: int | None = None
        self._pick_mode: str = ""  # "" | "origin" | "dest" | "road"

        self._weights = RouteCostWeights()
        self._exp_thresholds = RoadExposureThresholds()
        self._speed_cfg = TravelSpeedConfig()
        self._plan_result: RoutePlanningResult | None = None
        self._route_history: list[dict[str, Any]] = []

        self._heatmap_thresholds = RiskThresholds()
        self._heatmap_colors = HeatmapColorScale()
        self._viewport: GeoViewport | None = None
        self._map_renderer = MapRenderer()
        self._heatmap_renderer = HeatmapRenderer()
        self._route_renderer = RouteRenderer()

        self._drag_origin: tuple[int, int] | None = None
        self._drag_moved = False

        self._route_queue: queue.Queue[RoutePlanningResult | Exception] = queue.Queue()
        self._is_routing = False

        self._build_ui()
        self.after(60, self._poll_route_queue)

    # -------------------------------------------------------------------------
    # UI Construction (3-Column Responsive Layout matching Phases 1–4)
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Top Header Row
        top = tk.Frame(self, bg=THEME["bg_root"])
        top.pack(fill="x", pady=(0, 6))

        left_t = tk.Frame(top, bg=THEME["bg_root"])
        left_t.pack(side="left", fill="x", expand=True)
        tk.Label(
            left_t,
            text="SafeRoute — Flood-Aware Evacuation Planning",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        self.sub_lbl = tk.Label(
            left_t,
            text="NetworkX Dijkstra over imported OSM roads with Phase 3/4 flood exposure & manual closures.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
        )
        self.sub_lbl.pack(anchor="w")

        self.net_stats_lbl = tk.Label(
            top,
            text="Road Graph: Not built",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 8, "bold"),
            padx=10,
            pady=5,
        )
        self.net_stats_lbl.pack(side="right")

        # Disclaimer Banner
        disc = tk.Frame(
            self,
            bg=THEME["warning_bg"],
            highlightbackground=THEME["warning"],
            highlightthickness=1,
            padx=10,
            pady=4,
        )
        disc.pack(fill="x", pady=(0, 6))
        disc_lbl = tk.Label(
            disc,
            text=(
                "DECISION-SUPPORT PROTOTYPE ONLY: Routes and assumed-speed travel times are educational exploration estimates "
                "— NOT official emergency evacuation guidance or live traffic routing. Unknown exposure must NEVER be treated as safe."
            ),
            bg=THEME["warning_bg"],
            fg="#FDE68A",
            font=("Segoe UI", 8, "bold"),
            wraplength=960,
            justify="left",
        )
        disc_lbl.pack(anchor="w", fill="x")
        disc.bind("<Configure>", lambda e: disc_lbl.configure(wraplength=max(320, e.width - 24)))

        # 3-Column Body
        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=0)
        body.rowconfigure(0, weight=1)

        self._build_left_controls(body)
        self._build_center_map(body)
        self._build_right_comparison(body)

    def _build_left_controls(self, parent: tk.Misc) -> None:
        outer = tk.Frame(
            parent,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=318,
        )
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        outer.grid_propagate(False)
        outer.pack_propagate(False)

        canvas = tk.Canvas(outer, bg=THEME["bg_card"], highlightthickness=0, width=296)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=THEME["bg_card"], padx=10, pady=8)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw", width=296)
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def hdr(txt: str) -> None:
            tk.Label(
                inner,
                text=txt,
                bg=THEME["bg_card"],
                fg=THEME["accent_hover"],
                font=("Segoe UI", 8, "bold"),
                anchor="w",
            ).pack(anchor="w", fill="x", pady=(7, 3))

        # 1. Simulation & Time Step
        hdr("1. FLOOD SIMULATION CONTEXT")
        self.sim_var = tk.StringVar()
        self.sim_cb = ttk.Combobox(inner, textvariable=self.sim_var, state="readonly")
        self.sim_cb.pack(fill="x", pady=(0, 4))
        self.sim_cb.bind("<<ComboboxSelected>>", self._on_sim_selected)

        step_row = tk.Frame(inner, bg=THEME["bg_card"])
        step_row.pack(fill="x", pady=(0, 3))
        tk.Label(step_row, text="Time Step:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            side="left"
        )
        self.step_var = tk.StringVar()
        self.step_cb = ttk.Combobox(step_row, textvariable=self.step_var, state="readonly", width=18)
        self.step_cb.pack(side="right", fill="x", expand=True, padx=(6, 0))
        self.step_cb.bind("<<ComboboxSelected>>", self._on_step_selected)

        self.exposure_summary_lbl = tk.Label(
            inner,
            text="Exposure: No simulation selected (all Unknown)",
            bg=THEME["bg_input"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 8),
            padx=6,
            pady=4,
            anchor="w",
            wraplength=270,
            justify="left",
        )
        self.exposure_summary_lbl.pack(fill="x", pady=(2, 2))

        # 2. Origin & Destination Selection
        hdr("2. ORIGIN & DESTINATION")
        pick_row = tk.Frame(inner, bg=THEME["bg_card"])
        pick_row.pack(fill="x", pady=(0, 4))
        ttk.Button(
            pick_row, text="Pick Origin (Map)", command=lambda: self._set_pick_mode("origin")
        ).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(
            pick_row, text="Pick Dest (Map)", command=lambda: self._set_pick_mode("dest")
        ).pack(side="left", fill="x", expand=True, padx=(3, 0))

        self.pick_status_lbl = tk.Label(
            inner,
            text="Map Mode: Pan / Select",
            bg=THEME["bg_card"],
            fg=THEME["accent"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            wraplength=272,
            justify="left",
        )
        self.pick_status_lbl.pack(anchor="w", fill="x", pady=(0, 4))

        tk.Label(inner, text="Search Intersections / Filter:", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(inner, textvariable=self.search_var)
        search_entry.pack(fill="x", pady=(0, 4))
        search_entry.bind("<KeyRelease>", self._on_search_filter)

        tk.Label(inner, text="Starting Point (Origin Node):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        self.origin_var = tk.StringVar()
        self.origin_cb = ttk.Combobox(inner, textvariable=self.origin_var, state="readonly")
        self.origin_cb.pack(fill="x", pady=(0, 4))
        self.origin_cb.bind("<<ComboboxSelected>>", self._on_origin_combo)

        tk.Label(inner, text="Destination Node:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(
            anchor="w", fill="x"
        )
        self.dest_var = tk.StringVar()
        self.dest_cb = ttk.Combobox(inner, textvariable=self.dest_var, state="readonly")
        self.dest_cb.pack(fill="x", pady=(0, 4))
        self.dest_cb.bind("<<ComboboxSelected>>", self._on_dest_combo)

        tk.Label(
            inner,
            text="Evacuation Destinations (Registered Shelters & OSM):",
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(anchor="w", fill="x")
        self.evac_dest_var = tk.StringVar()
        self.evac_dest_cb = ttk.Combobox(inner, textvariable=self.evac_dest_var, state="readonly")
        self.evac_dest_cb.pack(fill="x", pady=(0, 4))
        self.evac_dest_cb.bind("<<ComboboxSelected>>", self._on_evac_dest_selected)

        # 3. Travel Mode & Preferences
        hdr("3. TRAVEL MODE & PREFERENCES")
        mode_row = tk.Frame(inner, bg=THEME["bg_card"])
        mode_row.pack(fill="x", pady=(0, 4))
        tk.Label(mode_row, text="Mode:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w").pack(side="left")
        self.mode_var = tk.StringVar(value=TRAVEL_MODES[1])
        mode_cb = ttk.Combobox(mode_row, textvariable=self.mode_var, values=TRAVEL_MODES, state="readonly", width=13)
        mode_cb.pack(side="left", padx=(6, 6), fill="x", expand=True)
        mode_cb.bind("<<ComboboxSelected>>", self._on_mode_change)
        ttk.Button(mode_row, text="Speeds", command=self._open_speeds_dialog).pack(side="right")

        self.pref_var = tk.StringVar(value="Compare All (Recommended)")
        ttk.Combobox(
            inner,
            textvariable=self.pref_var,
            values=(
                "Compare All (Recommended)",
                "Flood-aware route",
                "Shortest distance",
            ),
            state="readonly",
        ).pack(fill="x", pady=(0, 4))

        self.var_avoid_high = tk.BooleanVar(value=False)
        self.var_avoid_closed = tk.BooleanVar(value=True)
        ttk.Checkbutton(inner, text="Avoid high-exposure roads", variable=self.var_avoid_high).pack(anchor="w", fill="x")
        ttk.Checkbutton(inner, text="Avoid closed / blocked roads", variable=self.var_avoid_closed).pack(anchor="w", fill="x")

        pen_row = tk.Frame(inner, bg=THEME["bg_card"])
        pen_row.pack(fill="x", pady=(4, 4))
        ttk.Button(pen_row, text="Adjust Risk Penalties...", command=self._open_penalties_dialog).pack(side="left", fill="x", expand=True)

        # 4. Route Action Controls
        btn_g = tk.Frame(inner, bg=THEME["bg_card"])
        btn_g.pack(fill="x", pady=(4, 4))
        btn_g.columnconfigure(0, weight=1)
        btn_g.columnconfigure(1, weight=1)
        ttk.Button(btn_g, text="Find Route", style="Accent.TButton", command=self.find_routes_async).grid(
            row=0, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btn_g, text="Compare Routes", command=self.find_routes_async).grid(
            row=0, column=1, sticky="ew", padx=(3, 0), pady=2
        )
        ttk.Button(btn_g, text="Recalculate", command=self.find_routes_async).grid(
            row=1, column=0, sticky="ew", padx=(0, 3), pady=2
        )
        ttk.Button(btn_g, text="Clear Route", command=self.clear_routes).grid(
            row=1, column=1, sticky="ew", padx=(3, 0), pady=2
        )

        # 5. Manual Road Closure & Status Manager
        hdr("4. ROAD CLOSURE MANAGER")
        ttk.Button(
            inner, text="Select Road Segment on Map", command=lambda: self._set_pick_mode("road")
        ).pack(fill="x", pady=(0, 4))

        self.edge_var = tk.StringVar()
        self.edge_cb = ttk.Combobox(inner, textvariable=self.edge_var, state="readonly")
        self.edge_cb.pack(fill="x", pady=(0, 4))
        self.edge_cb.bind("<<ComboboxSelected>>", self._on_edge_combo)

        st_row = tk.Frame(inner, bg=THEME["bg_card"])
        st_row.pack(fill="x", pady=(0, 3))
        tk.Label(st_row, text="Status:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left")
        self.road_status_var = tk.StringVar(value="Normal")
        ttk.Combobox(st_row, textvariable=self.road_status_var, values=ROAD_STATUS_OPTIONS, state="readonly").pack(
            side="right", fill="x", expand=True, padx=(6, 0)
        )

        self.road_note_var = tk.StringVar()
        ttk.Entry(inner, textvariable=self.road_note_var).pack(fill="x", pady=(0, 3))

        self.road_prov_lbl = tk.Label(
            inner,
            text="Segment Source: — | Exposure: —",
            bg=THEME["bg_input"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            padx=6,
            pady=4,
            anchor="w",
            wraplength=270,
            justify="left",
        )
        self.road_prov_lbl.pack(fill="x", pady=(0, 4))

        cl_btns = tk.Frame(inner, bg=THEME["bg_card"])
        cl_btns.pack(fill="x", pady=(0, 4))
        ttk.Button(cl_btns, text="Apply Status", command=self._apply_road_status).pack(
            side="left", fill="x", expand=True, padx=(0, 3)
        )
        ttk.Button(cl_btns, text="Restore Normal", command=self._restore_road_normal).pack(
            side="left", fill="x", expand=True, padx=(3, 0)
        )

    def _build_center_map(self, parent: tk.Misc) -> None:
        center = tk.Frame(parent, bg=THEME["bg_root"])
        center.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        center.rowconfigure(1, weight=1)
        center.columnconfigure(0, weight=1)

        # Toolbar (2 neat rows so all checkboxes + Cursor fit cleanly at 1200-1440px)
        bar = tk.Frame(
            center,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=8,
            pady=5,
        )
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        bar_row1 = tk.Frame(bar, bg=THEME["bg_card"])
        bar_row1.pack(fill="x", pady=(0, 3))
        ttk.Button(bar_row1, text="+", width=3, command=lambda: self._zoom_center(1.25)).pack(side="left", padx=(0, 3))
        ttk.Button(bar_row1, text="-", width=3, command=lambda: self._zoom_center(0.8)).pack(side="left", padx=(0, 3))
        ttk.Button(bar_row1, text="Reset", width=6, command=self._reset_view).pack(side="left", padx=(0, 8))
        self.cursor_lbl = tk.Label(bar_row1, text="Cursor: —", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 8))
        self.cursor_lbl.pack(side="right")

        bar_row2 = tk.Frame(bar, bg=THEME["bg_card"])
        bar_row2.pack(fill="x")
        self.var_show_heatmap = tk.BooleanVar(value=True)
        self.var_show_unknown = tk.BooleanVar(value=True)
        self.var_show_closed = tk.BooleanVar(value=True)
        self.var_show_labels = tk.BooleanVar(value=True)
        self.var_show_shelters = tk.BooleanVar(value=True)

        ttk.Checkbutton(bar_row2, text="Heatmap", variable=self.var_show_heatmap, command=self._redraw_canvas).pack(side="left", padx=(0, 3))
        ttk.Checkbutton(bar_row2, text="Unk", variable=self.var_show_unknown, command=self._redraw_canvas).pack(side="left", padx=(0, 3))
        ttk.Checkbutton(bar_row2, text="Closed", variable=self.var_show_closed, command=self._redraw_canvas).pack(side="left", padx=(0, 3))
        ttk.Checkbutton(bar_row2, text="Names", variable=self.var_show_labels, command=self._redraw_canvas).pack(side="left", padx=(0, 3))
        ttk.Checkbutton(bar_row2, text="Shelters", variable=self.var_show_shelters, command=self._redraw_canvas).pack(side="left")

        # Map Canvas
        canvas_wrap = tk.Frame(
            center,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
        )
        canvas_wrap.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        self.canvas = tk.Canvas(canvas_wrap, bg=MAP_COLORS["canvas_bg"], highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Configure>", lambda _e: self._redraw_canvas())
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Motion>", self._on_mouse_move)

        # Route Legend Bar
        legend = tk.Frame(
            center,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=5,
        )
        legend.grid(row=2, column=0, sticky="ew")
        tk.Label(legend, text="LEGEND:", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 8, "bold")).pack(
            side="left", padx=(0, 6)
        )
        legend_items = [
            (ROUTE_COLORS["shortest"], "Shortest"),
            (ROUTE_COLORS["flood_aware"], "Flood-Aware"),
            (ROUTE_COLORS["alternative"], "Alt"),
            (ROUTE_COLORS["closed"], "Closed"),
            (ROUTE_COLORS["unknown"], "Unknown"),
        ]
        for color, lbl_txt in legend_items:
            tk.Frame(legend, bg=color, width=10, height=4).pack(side="left", padx=(2, 2), pady=5)
            tk.Label(legend, text=lbl_txt, bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(
                side="left", padx=(0, 4)
            )

    def _build_right_comparison(self, parent: tk.Misc) -> None:
        outer = tk.Frame(
            parent,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=364,
        )
        outer.grid(row=0, column=2, sticky="nsew")
        outer.grid_propagate(False)
        outer.pack_propagate(False)

        canvas = tk.Canvas(outer, bg=THEME["bg_card"], highlightthickness=0, width=342)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        right = tk.Frame(canvas, bg=THEME["bg_card"], padx=10, pady=8)
        right.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=right, anchor="nw", width=342)
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        tk.Label(
            right,
            text="ROUTE COMPARISON & METRICS",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(0, 5))

        # Route summary cards (one card per calculated route so nothing truncates)
        self.routes_container = tk.Frame(right, bg=THEME["bg_card"])
        self.routes_container.pack(fill="x", pady=(0, 6))
        tk.Label(
            self.routes_container,
            text="Select Origin & Destination, then click 'Find Route' or 'Compare Routes'.",
            bg=THEME["bg_input"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            padx=8,
            pady=8,
            anchor="w",
            wraplength=310,
            justify="left",
        ).pack(fill="x")

        # Selected Destination / Shelter Details Card (Phase 6 integration)
        tk.Label(
            right,
            text="SELECTED DESTINATION / SHELTER",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(4, 3))
        self.shelter_info_card = tk.Frame(
            right,
            bg=THEME["bg_input"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=8,
            pady=6,
        )
        self.shelter_info_card.pack(fill="x", pady=(0, 6))
        self.shelter_info_lbl = tk.Label(
            self.shelter_info_card,
            text="Pick a registered shelter from Evacuation Destinations (or click Shelters tab -> Plan Route).",
            bg=THEME["bg_input"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            anchor="w",
            wraplength=306,
            justify="left",
        )
        self.shelter_info_lbl.pack(anchor="w", fill="x")

        tk.Label(
            right,
            text="COMPARISON ANALYSIS & CAVEATS",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(4, 3))
        self.notes_box = tk.Text(
            right,
            height=6,
            bg=THEME["bg_input"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 8),
            wrap="word",
            bd=0,
            padx=8,
            pady=6,
            state="disabled",
        )
        self.notes_box.pack(fill="x", pady=(0, 8))

        tk.Label(
            right,
            text="SAVED ROUTE HISTORY (SQLite)",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(anchor="w", fill="x", pady=(2, 3))
        cols = ("type", "dist", "time", "mode")
        self.history_tree = ttk.Treeview(right, columns=cols, show="headings", height=6)
        for k, h, w in [("type", "Route", 92), ("dist", "Dist km", 64), ("time", "Est min", 64), ("mode", "Mode", 92)]:
            self.history_tree.heading(k, text=h)
            self.history_tree.column(k, width=w, anchor="w" if k in ("type", "mode") else "e")
        self.history_tree.pack(fill="x", pady=(0, 6))

    # -------------------------------------------------------------------------
    # Workspace & Simulation Synchronization
    # -------------------------------------------------------------------------

    def refresh_workspace(
        self,
        neighbourhood: Neighbourhood | None,
        cells: list[GridCell],
        osm_features: list[OSMFeature],
        drainage_features: list[DrainageFeature],
        saved_runs: list[SimulationRunRecord],
        shelters: list[Any] | None = None,
    ) -> None:
        nid_changed = (
            (neighbourhood.id if neighbourhood else None)
            != (self._neighbourhood.id if self._neighbourhood else None)
        )
        self._neighbourhood = neighbourhood
        self._cells = cells
        self._osm_features = osm_features
        self._drainage_features = drainage_features
        if shelters is not None:
            self._shelters = list(shelters)
        elif neighbourhood is None:
            self._shelters = []
        self._runs = saved_runs

        if neighbourhood is not None:
            if self._viewport is None or nid_changed:
                self._viewport = GeoViewport(
                    neighbourhood.min_latitude,
                    neighbourhood.max_latitude,
                    neighbourhood.min_longitude,
                    neighbourhood.max_longitude,
                    padding=20,
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

        if neighbourhood is not None and neighbourhood.id is not None:
            self._network = build_road_network_from_osm(neighbourhood.id, osm_features, cells)
            self.on_sync_road_network(self._network)
            self._conditions = self.on_load_road_conditions(neighbourhood.id)
            for eid, cond in self._conditions.items():
                if eid in self._network.edges_by_id:
                    self._network.edges_by_id[eid].manual_status = cond.status
                    self._network.edges_by_id[eid].status_source = cond.status_source

            self._destinations = extract_evacuation_destinations(
                self._network, osm_features, shelters=self._shelters
            )
            self._searchable_nodes = self._network.searchable_locations()
            self._edge_choices = [
                (
                    f"E{e.edge_id:03d}: {e.road_name} [{e.road_type}]",
                    e.edge_id,
                )
                for e in sorted(self._network.edges_by_id.values(), key=lambda x: x.edge_id)
            ]

            comps = self._network.get_connected_components()
            main_sz = len(comps[0]) if comps else 0
            self.net_stats_lbl.configure(
                text=f"Graph: {self._network.node_count} nodes, {self._network.edge_count} edges (main comp {main_sz})"
            )

            # Set sensible defaults if empty
            if self._searchable_nodes and (nid_changed or self._selected_origin_id not in self._network.nodes_by_id):
                # Prefer nodes in largest connected component so initial demo routes succeed cleanly
                main_comp = sorted(comps[0]) if comps else [nid for _, nid in self._searchable_nodes]
                self._selected_origin_id = main_comp[0]
                self._selected_dest_id = main_comp[len(main_comp) // 2] if len(main_comp) > 1 else main_comp[0]

            if self._edge_choices and (nid_changed or self._selected_edge_id not in self._network.edges_by_id):
                self._selected_edge_id = self._edge_choices[0][1]

            self._route_history = self.on_list_route_history(neighbourhood.id)
        else:
            self._network = None
            self._conditions = {}
            self._destinations = []
            self._searchable_nodes = []
            self._edge_choices = []
            self._selected_origin_id = None
            self._selected_dest_id = None
            self._selected_edge_id = None
            self._route_history = []
            self.net_stats_lbl.configure(text="Road Graph: No workspace")

        self._populate_selectors()
        self._refresh_history_table()

        sim_labels = ["None (All Road Exposure Unknown)"] + [
            f"#{r.id}: {r.scenario_name} ({r.rainfall_intensity:.0f} mm/h)" for r in saved_runs
        ]
        self.sim_cb.configure(values=sim_labels)
        if saved_runs:
            target_idx = 1
            if self._sim_output is not None and self._sim_output.run.id is not None:
                for i, r in enumerate(saved_runs, start=1):
                    if r.id == self._sim_output.run.id:
                        target_idx = i
                        break
            self.sim_var.set(sim_labels[target_idx])
            run_id = saved_runs[target_idx - 1].id
            if run_id is not None and (self._sim_output is None or self._sim_output.run.id != run_id):
                out = self.on_fetch_simulation(run_id)
                self.set_simulation_output(out)
            else:
                self._refresh_road_exposures()
        else:
            self.sim_var.set(sim_labels[0])
            self.set_simulation_output(None)

    def set_simulation_output(self, output: SimulationOutput | None) -> None:
        self._sim_output = output
        if output is None or not output.steps:
            self.step_cb.configure(values=[])
            self.step_var.set("")
            if self._runs:
                self.sim_var.set("None (All Road Exposure Unknown)")
        else:
            if output.run.id is not None:
                for i, r in enumerate(self._runs):
                    if r.id == output.run.id:
                        vals = self.sim_cb["values"]
                        if i + 1 < len(vals):
                            self.sim_var.set(vals[i + 1])
                        break
            step_labels = [f"Step {s.timestep} (t = {s.sim_time_minutes:.1f} min)" for s in output.steps]
            self.step_cb.configure(values=step_labels)
            self.step_var.set(step_labels[-1])
        self._refresh_road_exposures()

    def _active_timestep(self) -> int | None:
        if self._sim_output is None or not self._sim_output.steps:
            return None
        idx = self.step_cb.current()
        if 0 <= idx < len(self._sim_output.steps):
            return self._sim_output.steps[idx].timestep
        return self._sim_output.steps[-1].timestep

    def _refresh_road_exposures(self) -> None:
        if self._network is None:
            self._exposures = {}
            self._redraw_canvas()
            return
        ts = self._active_timestep()
        self._exposures = analyze_road_network_exposure(
            network=self._network,
            cells=self._cells,
            output=self._sim_output,
            timestep=ts,
            thresholds=self._exp_thresholds,
        )
        if self._neighbourhood and self._neighbourhood.id is not None:
            self._conditions = self.on_sync_sim_conditions(
                self._neighbourhood.id, self._exposures, self._conditions
            )
            for eid, cond in self._conditions.items():
                if eid in self._network.edges_by_id:
                    self._network.edges_by_id[eid].manual_status = cond.status
                    self._network.edges_by_id[eid].status_source = cond.status_source

        # Exposure stats summary
        counts: dict[str, int] = {}
        for exp in self._exposures.values():
            counts[exp.exposure_category] = counts.get(exp.exposure_category, 0) + 1
        closed_cnt = sum(
            1 for c in self._conditions.values() if c.status in ("Closed", "Blocked")
        )
        self.exposure_summary_lbl.configure(
            text=(
                f"Roads: High/V.High={counts.get('High', 0) + counts.get('Very high', 0)}, "
                f"Mod={counts.get('Moderate', 0)}, Low={counts.get('Low', 0)}, "
                f"Unknown={counts.get('Unknown', 0)}, Closed={closed_cnt}"
            )
        )
        self._refresh_selected_edge_display()
        self._redraw_canvas()

    def _populate_selectors(self) -> None:
        q = self.search_var.get().strip().lower()
        filtered_nodes = [
            lbl for lbl, _ in self._searchable_nodes if (not q or q in lbl.lower())
        ]
        if not filtered_nodes:
            filtered_nodes = [lbl for lbl, _ in self._searchable_nodes]

        self.origin_cb.configure(values=filtered_nodes)
        self.dest_cb.configure(values=filtered_nodes)

        if self._selected_origin_id is not None and self._network and self._selected_origin_id in self._network.nodes_by_id:
            self.origin_var.set(self._network.nodes_by_id[self._selected_origin_id].label)
        elif filtered_nodes:
            self.origin_var.set(filtered_nodes[0])

        if self._selected_dest_id is not None and self._network and self._selected_dest_id in self._network.nodes_by_id:
            self.dest_var.set(self._network.nodes_by_id[self._selected_dest_id].label)
        elif filtered_nodes:
            self.dest_var.set(filtered_nodes[-1])

        dest_labels = [d.label for d in self._destinations if (not q or q in d.label.lower())]
        if not dest_labels and self._destinations:
            dest_labels = [d.label for d in self._destinations]
        self.evac_dest_cb.configure(values=dest_labels)
        if not dest_labels:
            self.evac_dest_var.set("No shelters/landmarks imported — pick on map")

        edge_labels = [lbl for lbl, _ in self._edge_choices if (not q or q in lbl.lower())]
        if not edge_labels:
            edge_labels = [lbl for lbl, _ in self._edge_choices]
        self.edge_cb.configure(values=edge_labels)
        self._refresh_selected_edge_display()

    def _refresh_selected_edge_display(self) -> None:
        if self._network is None or self._selected_edge_id is None:
            self.road_prov_lbl.configure(text="Segment Source: — | Exposure: —")
            return
        edge = self._network.edges_by_id.get(self._selected_edge_id)
        if edge is None:
            return
        for lbl, eid in self._edge_choices:
            if eid == edge.edge_id:
                self.edge_var.set(lbl)
                break
        cond = self._conditions.get(edge.edge_id)
        exp = self._exposures.get(edge.edge_id)
        status = cond.status if cond else edge.manual_status
        src = cond.status_source if cond else edge.status_source
        exp_cat = exp.exposure_category if exp else edge.exposure_category
        max_cm = f"{exp.max_depth_cm:.1f} cm" if exp and exp.max_depth_cm is not None else "N/A"
        self.road_status_var.set(status)
        if cond and cond.notes:
            self.road_note_var.set(cond.notes)
        else:
            self.road_note_var.set("")
        self.road_prov_lbl.configure(
            text=f"Edge #{edge.edge_id} ({edge.distance_m:.0f}m) | Exposure: {exp_cat} ({max_cm}) | Source: {src}"
        )

    # -------------------------------------------------------------------------
    # Combobox, Search & Closure Callbacks
    # -------------------------------------------------------------------------

    def _on_sim_selected(self, _evt=None) -> None:
        idx = self.sim_cb.current()
        if idx <= 0:
            self.set_simulation_output(None)
            return
        run = self._runs[idx - 1]
        if run.id is not None:
            out = self.on_fetch_simulation(run.id)
            self.set_simulation_output(out)

    def _on_step_selected(self, _evt=None) -> None:
        self._refresh_road_exposures()

    def _on_search_filter(self, _evt=None) -> None:
        self._populate_selectors()

    def _on_origin_combo(self, _evt=None) -> None:
        sel = self.origin_var.get()
        for lbl, nid in self._searchable_nodes:
            if lbl == sel:
                self._selected_origin_id = nid
                self._redraw_canvas()
                return

    def _on_dest_combo(self, _evt=None) -> None:
        sel = self.dest_var.get()
        for lbl, nid in self._searchable_nodes:
            if lbl == sel:
                self._selected_dest_id = nid
                self._selected_destination = None
                self._refresh_selected_shelter_card()
                self._redraw_canvas()
                return

    def _on_evac_dest_selected(self, _evt=None) -> None:
        sel = self.evac_dest_var.get()
        for d in self._destinations:
            if d.label == sel and d.nearest_node_id is not None:
                self._selected_dest_id = d.nearest_node_id
                self._selected_destination = d
                if self._network and d.nearest_node_id in self._network.nodes_by_id:
                    self.dest_var.set(self._network.nodes_by_id[d.nearest_node_id].label)
                self._refresh_selected_shelter_card()
                self._redraw_canvas()
                return

    def set_registered_shelters(self, shelters: list[Any]) -> None:
        """Update registered shelters dynamically when edited in Emergency Resources."""
        self._shelters = list(shelters)
        if self._network is not None:
            self._destinations = extract_evacuation_destinations(
                self._network, self._osm_features, shelters=self._shelters
            )
            if self._selected_destination and self._selected_destination.shelter_id is not None:
                sid = self._selected_destination.shelter_id
                self._selected_destination = next(
                    (d for d in self._destinations if d.shelter_id == sid), None
                )
            self._populate_selectors()
            self._refresh_selected_shelter_card()
            self._redraw_canvas()

    def select_shelter_destination(self, shelter_id: int) -> bool:
        """Select a registered shelter as destination and highlight it on SafeRoute."""
        if self._network is None:
            return False
        target = next((d for d in self._destinations if d.shelter_id == shelter_id), None)
        if target is None or target.nearest_node_id is None:
            return False
        self._selected_destination = target
        self._selected_dest_id = target.nearest_node_id
        self.evac_dest_var.set(target.label)
        if target.nearest_node_id in self._network.nodes_by_id:
            self.dest_var.set(self._network.nodes_by_id[target.nearest_node_id].label)
        self._refresh_selected_shelter_card()
        self._redraw_canvas()
        return True

    def _refresh_selected_shelter_card(self) -> None:
        d = self._selected_destination
        if d is None:
            self.shelter_info_card.configure(highlightbackground=THEME["border"])
            self.shelter_info_lbl.configure(
                text="Pick a registered shelter from Evacuation Destinations (or click Shelters tab -> Plan Route).",
                fg=THEME["text_muted"],
            )
            return

        if d.shelter_id is not None:
            warn_parts: list[str] = []
            if d.shelter_status in ("Inactive", "Closed"):
                warn_parts.append(f"SHELTER IS {d.shelter_status.upper()} (Not accepting evacuees)")
            elif d.shelter_status == "Full" or (d.available_capacity is not None and d.available_capacity <= 0):
                warn_parts.append("SHELTER FULL (0 spaces remaining)")
            if not d.is_verified_shelter:
                warn_parts.append("Unverified registry location")

            route_line = ""
            if self._plan_result and (self._plan_result.flood_aware or self._plan_result.shortest):
                r = self._plan_result.flood_aware or self._plan_result.shortest
                assert r is not None
                route_line = (
                    f"\nRoute ({r.route_type}): {r.total_distance_km:.2f} km • "
                    f"{r.estimated_time_display} • Unknown segments: {r.unknown_segment_count}"
                )

            border_col = THEME["error"] if d.shelter_status in ("Inactive", "Closed", "Full") else (
                THEME["accent_teal"] if d.is_verified_shelter else THEME["warning"]
            )
            fg_col = "#FCA5A5" if d.shelter_status in ("Inactive", "Closed", "Full") else THEME["text_primary"]
            self.shelter_info_card.configure(highlightbackground=border_col)
            msg = (
                f"{d.label}\n"
                f"Address: {d.address or 'Not listed'}\n"
                f"Facilities: {d.facilities or 'None listed'}\n"
                f"Snap Distance to Road: {d.snap_distance_m:.0f} m"
                f"{route_line}"
            )
            if warn_parts:
                msg += f"\nALERT: {'; '.join(warn_parts)}"
            msg += (
                "\nWARNING: A routing path to a shelter does NOT confirm physical shelter accessibility "
                "or real-world road conditions."
            )
            self.shelter_info_lbl.configure(text=msg, fg=fg_col)
        else:
            self.shelter_info_card.configure(highlightbackground=THEME["warning"])
            self.shelter_info_lbl.configure(
                text=(
                    f"{d.label}\nSource: {d.source} • Snap distance: {d.snap_distance_m:.0f} m\n"
                    "WARNING: Routing to an OSM landmark does NOT confirm shelter readiness or road access."
                ),
                fg=THEME["text_secondary"],
            )

    def _on_edge_combo(self, _evt=None) -> None:
        sel = self.edge_var.get()
        for lbl, eid in self._edge_choices:
            if lbl == sel:
                self._selected_edge_id = eid
                self._refresh_selected_edge_display()
                self._redraw_canvas()
                return

    def _on_mode_change(self, _evt=None) -> None:
        try:
            self._speed_cfg.mode = self.mode_var.get()
            self._speed_cfg.validate()
        except ValidationError:
            self._speed_cfg.mode = TRAVEL_MODES[1]

    def _set_pick_mode(self, mode: str) -> None:
        self._pick_mode = "" if self._pick_mode == mode else mode
        labels = {
            "": "Map Mode: Pan / Select",
            "origin": "Click anywhere on Map to snap ORIGIN node...",
            "dest": "Click anywhere on Map to snap DESTINATION node...",
            "road": "Click any road on Map to select segment...",
        }
        self.pick_status_lbl.configure(text=labels.get(self._pick_mode, ""))

    def _apply_road_status(self) -> None:
        if self._neighbourhood is None or self._neighbourhood.id is None or self._network is None:
            return
        if self._selected_edge_id is None or self._selected_edge_id not in self._network.edges_by_id:
            messagebox.showinfo("Select Road", "Select a road segment first.")
            return
        eid = self._selected_edge_id
        status = self.road_status_var.get()
        note = self.road_note_var.get().strip()
        exp = self._exposures.get(eid)
        src = "user-entered" if status != "Normal" else (exp.status_source if exp else "imported")

        self.on_save_road_condition(
            neighbourhood_id=self._neighbourhood.id,
            road_edge_id=eid,
            status=status,
            exposure_category=exp.exposure_category if exp else "Unknown",
            maximum_water_depth=exp.max_depth_m if exp else None,
            simulation_id=exp.simulation_id if exp else None,
            time_step=exp.timestep if exp else None,
            status_source=src,
            notes=note,
        )
        self._conditions = self.on_load_road_conditions(self._neighbourhood.id)
        if eid in self._network.edges_by_id:
            self._network.edges_by_id[eid].manual_status = status
            self._network.edges_by_id[eid].status_source = src
        self._refresh_road_exposures()
        if self._plan_result is not None:
            self.find_routes_async()

    def _restore_road_normal(self) -> None:
        self.road_status_var.set("Normal")
        self.road_note_var.set("")
        self._apply_road_status()

    # -------------------------------------------------------------------------
    # Non-Blocking Route Calculation (Background Thread + after Poll)
    # -------------------------------------------------------------------------

    def find_routes_async(self) -> None:
        if self._network is None or self._network.edge_count == 0:
            messagebox.showinfo("Road Network Unavailable", "Import OpenStreetMap roads in Advanced Map Editor first.")
            return
        if self._selected_origin_id is None or self._selected_dest_id is None:
            messagebox.showinfo("Endpoints Required", "Select both a starting point and destination.")
            return
        if self._is_routing:
            return

        net = self._network
        o_id = self._selected_origin_id
        d_id = self._selected_dest_id
        o_lbl = net.nodes_by_id[o_id].label if o_id in net.nodes_by_id else str(o_id)
        d_lbl = net.nodes_by_id[d_id].label if d_id in net.nodes_by_id else str(d_id)
        exposures = dict(self._exposures)
        manual_statuses = {
            eid: cond.status for eid, cond in self._conditions.items()
        }
        sp_cfg = copy.deepcopy(self._speed_cfg)
        wt_cfg = copy.deepcopy(self._weights)
        wt_cfg.avoid_high_exposure = bool(self.var_avoid_high.get())
        wt_cfg.avoid_closed_roads = bool(self.var_avoid_closed.get())
        sim_id = self._sim_output.run.id if self._sim_output else None
        ts = self._active_timestep()

        self._is_routing = True

        def _worker() -> None:
            try:
                res = calculate_evacuation_routes(
                    network=net,
                    start_node_id=o_id,
                    dest_node_id=d_id,
                    origin_label=o_lbl,
                    destination_label=d_lbl,
                    exposures=exposures,
                    manual_statuses=manual_statuses,
                    speed_config=sp_cfg,
                    weights=wt_cfg,
                    simulation_id=sim_id,
                    timestep=ts,
                )
                self._route_queue.put(res)
            except Exception as exc:
                self._route_queue.put(exc)

        threading.Thread(target=_worker, daemon=True).start()

    def _poll_route_queue(self) -> None:
        try:
            while True:
                item = self._route_queue.get_nowait()
                self._is_routing = False
                if isinstance(item, Exception):
                    messagebox.showerror("Route Calculation Error", str(item))
                else:
                    self.apply_planning_result(item, persist_history=True)
        except queue.Empty:
            pass
        finally:
            self.after(60, self._poll_route_queue)

    def calculate_routes_sync(self) -> RoutePlanningResult | None:
        """Synchronous helper for deterministic tests & automation."""
        if self._network is None or self._selected_origin_id is None or self._selected_dest_id is None:
            return None
        o_lbl = self._network.nodes_by_id[self._selected_origin_id].label
        d_lbl = self._network.nodes_by_id[self._selected_dest_id].label
        manual_statuses = {eid: cond.status for eid, cond in self._conditions.items()}
        wt_cfg = copy.deepcopy(self._weights)
        wt_cfg.avoid_high_exposure = bool(self.var_avoid_high.get())
        wt_cfg.avoid_closed_roads = bool(self.var_avoid_closed.get())
        res = calculate_evacuation_routes(
            network=self._network,
            start_node_id=self._selected_origin_id,
            dest_node_id=self._selected_dest_id,
            origin_label=o_lbl,
            destination_label=d_lbl,
            exposures=self._exposures,
            manual_statuses=manual_statuses,
            speed_config=self._speed_cfg,
            weights=wt_cfg,
            simulation_id=self._sim_output.run.id if self._sim_output else None,
            timestep=self._active_timestep(),
        )
        self.apply_planning_result(res, persist_history=True)
        return res

    def apply_planning_result(self, result: RoutePlanningResult, persist_history: bool = True) -> None:
        pref = self.pref_var.get()
        self._plan_result = result

        displayed_routes: list[RouteMetrics] = []
        if pref == "Shortest distance" and result.shortest:
            displayed_routes = [result.shortest]
        elif pref == "Flood-aware route" and result.flood_aware:
            displayed_routes = [result.flood_aware]
        else:
            displayed_routes = result.routes

        if persist_history and self._neighbourhood and self._neighbourhood.id is not None:
            for r in result.routes:
                self.on_save_route_history(
                    self._neighbourhood.id, r, result.simulation_id, result.timestep
                )
            self._route_history = self.on_list_route_history(self._neighbourhood.id)
            self._refresh_history_table()

        self._render_comparison_panel(displayed_routes, result)
        self._refresh_selected_shelter_card()
        self._redraw_canvas()

    def clear_routes(self) -> None:
        self._plan_result = None
        for child in self.routes_container.winfo_children():
            child.destroy()
        tk.Label(
            self.routes_container,
            text="Routes cleared. Choose origin & destination to compute new evacuation routes.",
            bg=THEME["bg_input"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            padx=8,
            pady=8,
            wraplength=290,
            justify="left",
        ).pack(fill="x")
        self._set_notes_text("No active route comparison.")
        self._redraw_canvas()

    def _render_comparison_panel(self, routes: list[RouteMetrics], result: RoutePlanningResult) -> None:
        for child in self.routes_container.winfo_children():
            child.destroy()

        color_map = {
            "Shortest": ROUTE_COLORS["shortest"],
            "Flood-aware": ROUTE_COLORS["flood_aware"],
            "Alternative": ROUTE_COLORS["alternative"],
        }

        if not routes:
            tk.Label(
                self.routes_container,
                text="No navigable route found for the selected constraints.",
                bg=THEME["error_bg"],
                fg="#FCA5A5",
                font=("Segoe UI", 8, "bold"),
                padx=8,
                pady=8,
                wraplength=290,
                justify="left",
            ).pack(fill="x")
        else:
            for r in routes:
                accent = color_map.get(r.route_type, THEME["accent"])
                card = tk.Frame(
                    self.routes_container,
                    bg=THEME["bg_input"],
                    highlightbackground=accent,
                    highlightthickness=1,
                    padx=8,
                    pady=6,
                )
                card.pack(fill="x", pady=(0, 6))

                tk.Label(
                    card,
                    text=r.route_name,
                    bg=THEME["bg_input"],
                    fg=accent,
                    font=("Segoe UI", 9, "bold"),
                    anchor="w",
                ).pack(anchor="w", fill="x")
                tk.Label(
                    card,
                    text=f"Distance: {r.total_distance_km:.2f} km  •  Time: {r.estimated_time_display}",
                    bg=THEME["bg_input"],
                    fg=THEME["text_primary"],
                    font=("Segoe UI", 8, "bold"),
                    anchor="w",
                    wraplength=304,
                    justify="left",
                ).pack(anchor="w", fill="x", pady=(2, 1))
                tk.Label(
                    card,
                    text=(
                        f"Segments: {r.segment_count}  |  Exposed: {r.exposed_segment_count}  |  "
                        f"High Risk: {r.high_risk_segment_count}"
                    ),
                    bg=THEME["bg_input"],
                    fg=THEME["text_secondary"],
                    font=("Segoe UI", 8),
                    anchor="w",
                    wraplength=304,
                    justify="left",
                ).pack(anchor="w", fill="x")
                tk.Label(
                    card,
                    text=(
                        f"Closed: {r.closed_segment_count}  |  Unknown: {r.unknown_segment_count}  |  "
                        f"Max Depth: {r.max_water_depth_cm:.1f} cm"
                    ),
                    bg=THEME["bg_input"],
                    fg=THEME["text_muted"],
                    font=("Segoe UI", 8),
                    anchor="w",
                    wraplength=304,
                    justify="left",
                ).pack(anchor="w", fill="x")
                if r.road_names:
                    streets = ", ".join(r.road_names[:5])
                    if len(r.road_names) > 5:
                        streets += f" (+{len(r.road_names) - 5} more)"
                    tk.Label(
                        card,
                        text=f"Via: {streets}",
                        bg=THEME["bg_input"],
                        fg=THEME["text_muted"],
                        font=("Segoe UI", 7),
                        anchor="w",
                        wraplength=304,
                        justify="left",
                    ).pack(anchor="w", fill="x", pady=(2, 0))

        lines: list[str] = []
        if result.comparison:
            lines.extend(result.comparison.comparison_notes)
            lines.append("")
            lines.append(result.comparison.disclaimer)
        for fail in result.failures:
            lines.append(f"[{fail.route_type} unavailable] {fail.reason} Suggestion: {fail.suggestion}")
        self._set_notes_text("\n".join(lines).strip())

    def _set_notes_text(self, text: str) -> None:
        self.notes_box.configure(state="normal")
        self.notes_box.delete("1.0", "end")
        self.notes_box.insert("1.0", text)
        self.notes_box.configure(state="disabled")

    def _refresh_history_table(self) -> None:
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        for row in self._route_history[:30]:
            self.history_tree.insert(
                "",
                "end",
                values=(
                    row["route_type"],
                    f"{row['total_distance_m'] / 1000.0:.2f}",
                    f"{row['estimated_time_min']:.1f}",
                    row["travel_mode"][:10],
                ),
            )

    # -------------------------------------------------------------------------
    # Configurable Speeds & Risk Penalties Dialogs
    # -------------------------------------------------------------------------

    def _open_speeds_dialog(self) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Configure Assumed Travel Speeds (Not Live Traffic)")
        dlg.configure(bg=THEME["bg_surface"])
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        dlg.resizable(False, False)

        body = tk.Frame(dlg, bg=THEME["bg_surface"], padx=14, pady=12)
        body.pack(fill="both", expand=True)
        mode = self.mode_var.get()
        tk.Label(
            body,
            text=f"Assumed Speeds for Mode: {mode} (km/hr) — 0 disables road type",
            bg=THEME["bg_surface"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        cur_map = self._speed_cfg.speeds_by_mode.get(mode, DEFAULT_SPEED_ASSUMPTIONS_KMH[mode])
        vars_map: dict[str, tk.StringVar] = {}
        for idx, (rtype, spd) in enumerate(cur_map.items(), start=1):
            tk.Label(body, text=f"{rtype}:", bg=THEME["bg_surface"], fg=THEME["text_secondary"], font=("Segoe UI", 9)).grid(
                row=idx, column=0, sticky="w", pady=3, padx=(0, 12)
            )
            sv = tk.StringVar(value=f"{spd:.1f}")
            vars_map[rtype] = sv
            ttk.Entry(body, textvariable=sv, width=10).grid(row=idx, column=1, sticky="ew", pady=3)

        def _save() -> None:
            try:
                updated = {rt: float(sv.get()) for rt, sv in vars_map.items()}
                candidate = copy.deepcopy(self._speed_cfg)
                candidate.mode = mode
                candidate.speeds_by_mode[mode] = updated
                candidate.validate()
            except (ValueError, ValidationError) as exc:
                messagebox.showerror("Invalid Speed", str(exc), parent=dlg)
                return
            self._speed_cfg = candidate
            dlg.destroy()

        btns = tk.Frame(body, bg=THEME["bg_surface"])
        btns.grid(row=len(cur_map) + 1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Apply", style="Accent.TButton", command=_save).pack(side="left")

    def _open_penalties_dialog(self) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Configure Flood Exposure Route Penalties")
        dlg.configure(bg=THEME["bg_surface"])
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        dlg.resizable(False, False)

        body = tk.Frame(dlg, bg=THEME["bg_surface"], padx=14, pady=12)
        body.pack(fill="both", expand=True)
        tk.Label(
            body,
            text="Dijkstra Cost = Distance(m) + Exposure Penalty (higher avoids water)",
            bg=THEME["bg_surface"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        fields = [
            ("Low exposure penalty:", "penalty_low"),
            ("Moderate exposure penalty:", "penalty_moderate"),
            ("High exposure penalty:", "penalty_high"),
            ("Very high exposure penalty:", "penalty_very_high"),
            ("Unknown exposure penalty:", "penalty_unknown"),
            ("Under inspection penalty:", "penalty_under_inspection"),
        ]
        vars_map: dict[str, tk.StringVar] = {}
        for idx, (label_txt, attr) in enumerate(fields, start=1):
            tk.Label(body, text=label_txt, bg=THEME["bg_surface"], fg=THEME["text_secondary"], font=("Segoe UI", 9)).grid(
                row=idx, column=0, sticky="w", pady=3, padx=(0, 12)
            )
            sv = tk.StringVar(value=f"{getattr(self._weights, attr):.0f}")
            vars_map[attr] = sv
            ttk.Entry(body, textvariable=sv, width=12).grid(row=idx, column=1, sticky="ew", pady=3)

        def _save() -> None:
            try:
                for attr, sv in vars_map.items():
                    val = float(sv.get())
                    if val < 0.0:
                        raise ValidationError("Penalties must be >= 0.")
                    setattr(self._weights, attr, val)
            except (ValueError, ValidationError) as exc:
                messagebox.showerror("Invalid Penalty", str(exc), parent=dlg)
                return
            dlg.destroy()

        btns = tk.Frame(body, bg=THEME["bg_surface"])
        btns.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btns, text="Cancel", command=dlg.destroy).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Apply", style="Accent.TButton", command=_save).pack(side="left")

    # -------------------------------------------------------------------------
    # Map Rendering & Canvas Mouse Interactions
    # -------------------------------------------------------------------------

    def _redraw_canvas(self) -> None:
        self.canvas.delete("all")
        if self._neighbourhood is None or self._viewport is None:
            w = max(200, self.canvas.winfo_width())
            h = max(200, self.canvas.winfo_height())
            self.canvas.create_text(
                w / 2,
                h / 2,
                text="No neighbourhood workspace loaded.\nImport OSM roads in Advanced Map Editor first.",
                fill=THEME["text_muted"],
                font=("Segoe UI", 11),
                justify="center",
            )
            return

        w = max(200, self.canvas.winfo_width())
        h = max(200, self.canvas.winfo_height())
        self._viewport.resize(w, h)

        self._map_renderer.render(
            canvas=self.canvas,
            viewport=self._viewport,
            neighbourhood=self._neighbourhood,
            features=self._osm_features,
            drainage_features=self._drainage_features,
            show_osm=True,
            show_roads=True,
            show_buildings=True,
            show_water=True,
            show_green=False,
            show_wetlands=True,
            show_drainage=False,
            draw_hud=True,
        )

        if self.var_show_heatmap.get() and self._sim_output is not None and self._sim_output.steps:
            ts = self._active_timestep() or self._sim_output.steps[-1].timestep
            depths, _, _ = extract_step_cell_data(self._sim_output, ts)
            self._heatmap_renderer.render(
                canvas=self.canvas,
                viewport=self._viewport,
                cells=self._cells,
                depths_by_cell_id=depths,
                thresholds=self._heatmap_thresholds,
                color_scale=self._heatmap_colors,
                show_heatmap=True,
                show_grid_lines=False,
                show_labels=False,
                translucent=True,
            )

        if self._network is not None:
            manual_statuses = {eid: c.status for eid, c in self._conditions.items()}
            self._route_renderer.render_road_conditions(
                canvas=self.canvas,
                viewport=self._viewport,
                network=self._network,
                exposures=self._exposures,
                manual_statuses=manual_statuses,
                show_unknown_roads=bool(self.var_show_unknown.get()),
                show_closed_roads=bool(self.var_show_closed.get()),
                selected_edge_id=self._selected_edge_id,
            )

            pref = self.pref_var.get()
            routes_to_draw: list[RouteMetrics] = []
            if self._plan_result is not None:
                if pref == "Shortest distance" and self._plan_result.shortest:
                    routes_to_draw = [self._plan_result.shortest]
                elif pref == "Flood-aware route" and self._plan_result.flood_aware:
                    routes_to_draw = [self._plan_result.flood_aware]
                else:
                    routes_to_draw = self._plan_result.routes

            o_node = self._network.nodes_by_id.get(self._selected_origin_id) if self._selected_origin_id else None
            d_node = self._network.nodes_by_id.get(self._selected_dest_id) if self._selected_dest_id else None
            self._route_renderer.render_routes(
                canvas=self.canvas,
                viewport=self._viewport,
                network=self._network,
                routes=routes_to_draw,
                origin_node=o_node,
                dest_node=d_node,
                show_labels=bool(self.var_show_labels.get()),
            )
            if self.var_show_shelters.get() and self._shelters:
                sel_sid = self._selected_destination.shelter_id if self._selected_destination else None
                self._route_renderer.render_shelters(
                    canvas=self.canvas,
                    viewport=self._viewport,
                    shelters=self._shelters,
                    selected_shelter_id=sel_sid,
                )

    def _zoom_center(self, factor: float) -> None:
        if self._viewport is None:
            return
        self._viewport.zoom_at(factor, self.canvas.winfo_width() / 2.0, self.canvas.winfo_height() / 2.0)
        self._redraw_canvas()

    def _reset_view(self) -> None:
        if self._viewport is None:
            return
        self._viewport.reset_view()
        self._redraw_canvas()

    def _on_mouse_wheel(self, event) -> None:
        if self._viewport is None:
            return
        factor = 1.18 if event.delta > 0 else 0.85
        self._viewport.zoom_at(factor, event.x, event.y)
        self._redraw_canvas()

    def _on_mouse_down(self, event) -> None:
        self._drag_origin = (event.x, event.y)
        self._drag_moved = False

    def _on_mouse_drag(self, event) -> None:
        if self._viewport is None or self._drag_origin is None:
            return
        dx = event.x - self._drag_origin[0]
        dy = event.y - self._drag_origin[1]
        if abs(dx) > 3 or abs(dy) > 3:
            self._drag_moved = True
        self._drag_origin = (event.x, event.y)
        self._viewport.pan_by(dx, dy)
        self._redraw_canvas()

    def _on_mouse_up(self, event) -> None:
        was_drag = self._drag_moved
        self._drag_origin = None
        self._drag_moved = False
        if was_drag or self._viewport is None or self._network is None:
            return
        lat, lon = self._viewport.screen_to_geo(event.x, event.y)
        if self._pick_mode == "origin":
            hit = self._network.find_nearest_node(lat, lon)
            if hit:
                node, dist_m = hit
                self._selected_origin_id = node.node_id
                self.origin_var.set(node.label)
                self._set_pick_mode("")
                self.pick_status_lbl.configure(text=f"Origin snapped ({dist_m:.0f}m to N{node.node_id:03d})")
                self._redraw_canvas()
        elif self._pick_mode == "dest":
            hit = self._network.find_nearest_node(lat, lon)
            if hit:
                node, dist_m = hit
                self._selected_dest_id = node.node_id
                self.dest_var.set(node.label)
                self._set_pick_mode("")
                self.pick_status_lbl.configure(text=f"Dest snapped ({dist_m:.0f}m to N{node.node_id:03d})")
                self._redraw_canvas()
        else:
            # Default click or road pick selects nearest road segment for closure inspection
            edge_hit = self._network.find_nearest_edge(lat, lon, max_distance_m=150.0)
            if edge_hit:
                edge, _ = edge_hit
                self._selected_edge_id = edge.edge_id
                self._refresh_selected_edge_display()
                if self._pick_mode == "road":
                    self._set_pick_mode("")
                self._redraw_canvas()

    def _on_mouse_move(self, event) -> None:
        if self._viewport is None:
            return
        lat, lon = self._viewport.screen_to_geo(event.x, event.y)
        self.cursor_lbl.configure(text=f"Cursor: {lat:.5f}, {lon:.5f}")
