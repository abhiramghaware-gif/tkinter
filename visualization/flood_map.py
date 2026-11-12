"""Phase 4 Interactive Flood Map screen with layer toggles, cell inspector, animation & export."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from config import (
    DEFAULT_BUILDING_EXPOSURE_THRESHOLD_CM,
    DEFAULT_ROAD_EXPOSURE_THRESHOLD_CM,
    EXPORTS_DIR,
    MAP_COLORS,
    RISK_BADGE_COLORS,
    THEME,
)
from core.flood_statistics import (
    TimestepFloodStats,
    compute_timestep_statistics,
    extract_step_cell_data,
)
from core.models import DrainageFeature, GridCell, GridFeatureLink, Neighbourhood, OSMFeature
from core.risk_classifier import (
    PROTOTYPE_RISK_DISCLAIMER,
    HeatmapColorScale,
    RiskThresholds,
    classify_flood_depth,
)
from core.simulation_engine import SimulationOutput, SimulationRunRecord
from core.validation import ValidationError
from services.simulation_export import (
    export_flood_depth_grid_csv,
    export_risk_classification_csv,
    export_simulation_geojson,
    export_simulation_summary_pdf,
)
from visualization.flood_animation import FloodAnimationController
from visualization.grid_renderer import GridRenderer
from visualization.heatmap_renderer import HeatmapRenderer
from visualization.map_layers import (
    ExposureSummary,
    MapLayersOverlayRenderer,
    compute_infrastructure_exposure,
)
from visualization.map_renderer import GeoViewport, MapRenderer


class FloodMapView(tk.Frame):
    """Interactive GIS Flood Map viewer consuming saved Phase 3 simulation runs."""

    def __init__(
        self,
        parent: tk.Misc,
        on_select_run: Callable[[int], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=14, pady=12)
        self.on_select_run = on_select_run

        self._neighbourhood: Neighbourhood | None = None
        self._cells: list[GridCell] = []
        self._osm_features: list[OSMFeature] = []
        self._drainage_features: list[DrainageFeature] = []
        self._links: list[GridFeatureLink] = []
        self._runs: list[SimulationRunRecord] = []
        self._registered_shelters: list[Any] = []
        self._output: SimulationOutput | None = None

        self._thresholds = RiskThresholds()
        self._color_scale = HeatmapColorScale()
        self._road_exp_cm = DEFAULT_ROAD_EXPOSURE_THRESHOLD_CM
        self._bldg_exp_cm = DEFAULT_BUILDING_EXPOSURE_THRESHOLD_CM

        self._selected_cell_id: int | None = None
        self._current_step_idx: int = 0
        self._current_depths: dict[int, float] = {}
        self._current_volumes: dict[int, float] = {}
        self._current_exposure = ExposureSummary()
        self._current_stats: TimestepFloodStats | None = None

        self._viewport: GeoViewport | None = None
        self._map_renderer = MapRenderer()
        self._heatmap_renderer = HeatmapRenderer()
        self._exposure_renderer = MapLayersOverlayRenderer()

        self._drag_origin: tuple[int, int] | None = None
        self._drag_moved = False
        self._suppress_slider_cb = False

        self._build_ui()
        self.anim_controller = FloodAnimationController(
            self,
            on_step_changed=self._on_animation_step,
            on_state_changed=self._on_animation_state,
        )

    def _build_ui(self) -> None:
        # Top Header Row (Title left + Run selector right)
        top = tk.Frame(self, bg=THEME["bg_root"])
        top.pack(fill="x", pady=(0, 4))

        left_t = tk.Frame(top, bg=THEME["bg_root"])
        left_t.pack(side="left", fill="x", expand=True)
        tk.Label(
            left_t,
            text="Interactive Flood Risk & Depth Map",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        self.top_sub_lbl = tk.Label(
            left_t,
            text="Select a Phase 3 simulation run to inspect depth, risk classification & exposure.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
        )
        self.top_sub_lbl.pack(anchor="w")

        run_box = tk.Frame(top, bg=THEME["bg_root"])
        run_box.pack(side="right", anchor="n")
        tk.Label(run_box, text="Run:", bg=THEME["bg_root"], fg=THEME["text_secondary"], font=("Segoe UI", 8, "bold")).pack(
            side="left", padx=(0, 4)
        )
        self.run_var = tk.StringVar()
        self.run_cb = ttk.Combobox(run_box, textvariable=self.run_var, state="readonly", width=34)
        self.run_cb.pack(side="left")
        self.run_cb.bind("<<ComboboxSelected>>", self._on_run_selected)

        # Second compact action row: Config + Export buttons (never clips on narrower displays)
        action_bar = tk.Frame(self, bg=THEME["bg_root"])
        action_bar.pack(fill="x", pady=(0, 6))
        ttk.Button(action_bar, text="Thresholds / Colors", command=self._open_thresholds_dialog).pack(side="left", padx=(0, 6))
        ttk.Button(action_bar, text="Export CSV Depth", command=self._export_depth_csv).pack(side="left", padx=(0, 4))
        ttk.Button(action_bar, text="Export CSV Risk", command=self._export_risk_csv).pack(side="left", padx=(0, 4))
        ttk.Button(action_bar, text="Export GeoJSON", command=self._export_geojson).pack(side="left", padx=(0, 4))
        ttk.Button(action_bar, text="Export PDF Report", style="Accent.TButton", command=self._export_pdf).pack(side="left")

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
                "SIMULATED MODEL VISUALIZATION ONLY: Flood depth colours, risk classes, and road/building overlap "
                "estimates are experimental Phase 3 model outputs — NOT real-world flood observations or official safety ratings."
            ),
            bg=THEME["warning_bg"],
            fg="#FDE68A",
            font=("Segoe UI", 8, "bold"),
            wraplength=920,
            justify="left",
        )
        disc_lbl.pack(anchor="w", fill="x")
        disc.bind("<Configure>", lambda e: disc_lbl.configure(wraplength=max(320, e.width - 24)))

        # 3-Column Body: Left Layers/Legend/Stats (230) | Center Map+Timeline (expand) | Right Cell Info (252)
        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=0)
        body.rowconfigure(0, weight=1)

        self._build_left_sidebar(body)
        self._build_center_map_area(body)
        self._build_right_cell_inspector(body)

    def _build_left_sidebar(self, parent: tk.Misc) -> None:
        outer = tk.Frame(
            parent,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=268,
        )
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        outer.grid_propagate(False)
        outer.pack_propagate(False)

        canvas = tk.Canvas(outer, bg=THEME["bg_card"], highlightthickness=0, width=246)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=THEME["bg_card"], padx=10, pady=8)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
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
            ).pack(anchor="w", pady=(6, 3))

        hdr("MAP LAYERS")
        self.var_heatmap = tk.BooleanVar(value=True)
        self.var_translucent = tk.BooleanVar(value=True)
        self.var_grid_labels = tk.BooleanVar(value=True)
        self.var_roads = tk.BooleanVar(value=True)
        self.var_buildings = tk.BooleanVar(value=True)
        self.var_water = tk.BooleanVar(value=True)
        self.var_drainage = tk.BooleanVar(value=True)
        self.var_exposure = tk.BooleanVar(value=True)
        self.var_shelters = tk.BooleanVar(value=True)

        layer_specs = [
            ("Flood Depth Heatmap", self.var_heatmap),
            ("Translucent Overlay", self.var_translucent),
            ("Grid & Depth Labels", self.var_grid_labels),
            ("Roads (OSM)", self.var_roads),
            ("Buildings (OSM)", self.var_buildings),
            ("Waterbodies & Parks", self.var_water),
            ("Drainage Infrastructure", self.var_drainage),
            ("Exposed Roads & Bldgs", self.var_exposure),
            ("Shelters (if mapped)", self.var_shelters),
        ]
        for label_txt, var in layer_specs:
            ttk.Checkbutton(inner, text=label_txt, variable=var, command=self._redraw_canvas).pack(anchor="w", pady=1)

        hdr("FLOOD DEPTH LEGEND")
        self.legend_frame = tk.Frame(inner, bg=THEME["bg_card"])
        self.legend_frame.pack(fill="x", pady=(0, 4))
        self._rebuild_legend()

        hdr("NEIGHBOURHOOD STATISTICS")
        self.stats_frame = tk.Frame(inner, bg=THEME["bg_input"], padx=8, pady=6)
        self.stats_frame.pack(fill="x", pady=(0, 6))
        self._stat_labels: dict[str, tk.Label] = {}
        stat_keys = [
            ("max_d", "Max Depth:"),
            ("avg_d", "Avg Depth:"),
            ("affected", "Affected Cells:"),
            ("area", "Affected Area:"),
            ("high_risk", "High Risk:"),
            ("vhigh_risk", "Very High Risk:"),
            ("rain", "Rainfall In:"),
            ("infil", "Infiltration:"),
            ("drain", "Drainage Out:"),
            ("exp_roads", "Exposed Roads*:"),
            ("exp_bldgs", "Exposed Bldgs*:"),
            ("shelters", "Mapped Shelters:"),
        ]
        for key, label_txt in stat_keys:
            row_f = tk.Frame(self.stats_frame, bg=THEME["bg_input"])
            row_f.pack(fill="x", pady=1)
            tk.Label(
                row_f, text=label_txt, bg=THEME["bg_input"], fg=THEME["text_muted"], font=("Segoe UI", 8)
            ).pack(side="left")
            val_lbl = tk.Label(
                row_f, text="—", bg=THEME["bg_input"], fg=THEME["text_primary"], font=("Segoe UI", 8, "bold")
            )
            val_lbl.pack(side="right")
            self._stat_labels[key] = val_lbl

        tk.Label(
            inner,
            text="*Exposure = cell overlap estimate only, not confirmed damage or closure.",
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 7),
            wraplength=205,
            justify="left",
        ).pack(anchor="w", pady=(2, 4))

    def _build_center_map_area(self, parent: tk.Misc) -> None:
        center = tk.Frame(parent, bg=THEME["bg_root"])
        center.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        center.rowconfigure(1, weight=1)
        center.columnconfigure(0, weight=1)

        # Mini map controls bar (compact so cursor coords never collide)
        bar = tk.Frame(
            center,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=8,
            pady=5,
        )
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Button(bar, text="+", width=3, command=lambda: self._zoom_center(1.25)).pack(side="left", padx=(0, 3))
        ttk.Button(bar, text="-", width=3, command=lambda: self._zoom_center(0.8)).pack(side="left", padx=(0, 3))
        ttk.Button(bar, text="Reset", width=6, command=self._reset_view).pack(side="left", padx=(0, 8))

        self.cursor_lbl = tk.Label(
            bar,
            text="Cursor: —",
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 8),
        )
        self.cursor_lbl.pack(side="left")

        self.exposure_badge_lbl = tk.Label(
            bar,
            text="Road ≥ 15cm | Bldg ≥ 5cm",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 8, "bold"),
        )
        self.exposure_badge_lbl.pack(side="right")

        # Main Map Canvas
        canvas_wrap = tk.Frame(
            center,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
        )
        canvas_wrap.grid(row=1, column=0, sticky="nsew", pady=(0, 6))
        self.canvas = tk.Canvas(canvas_wrap, bg=MAP_COLORS["canvas_bg"], highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.canvas.bind("<Motion>", self._on_mouse_move)

        # Bottom Simulation Timeline & Animation Bar (2 clean rows so all controls fit at any width)
        timeline = tk.Frame(
            center,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=8,
            pady=5,
        )
        timeline.grid(row=2, column=0, sticky="ew")

        btn_row = tk.Frame(timeline, bg=THEME["bg_card"])
        btn_row.pack(fill="x", pady=(0, 3))

        self.btn_play = ttk.Button(btn_row, text="Start", style="Accent.TButton", command=self._anim_start)
        self.btn_play.pack(side="left", padx=(0, 4))
        self.btn_pause = ttk.Button(btn_row, text="Pause", command=self._anim_pause_resume)
        self.btn_pause.pack(side="left", padx=(0, 4))
        self.btn_stop = ttk.Button(btn_row, text="Stop", command=self._anim_stop)
        self.btn_stop.pack(side="left", padx=(0, 6))
        ttk.Button(btn_row, text="< Prev", command=self._anim_prev).pack(side="left", padx=(0, 4))
        ttk.Button(btn_row, text="Next >", command=self._anim_next).pack(side="left", padx=(0, 8))

        tk.Label(btn_row, text="Speed:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(
            side="left", padx=(2, 4)
        )
        self.speed_var = tk.StringVar(value="1x")
        speed_cb = ttk.Combobox(
            btn_row,
            textvariable=self.speed_var,
            values=("0.5x", "1x", "2x", "4x"),
            state="readonly",
            width=5,
        )
        speed_cb.pack(side="left")
        speed_cb.bind("<<ComboboxSelected>>", self._on_speed_change)

        status_row = tk.Frame(timeline, bg=THEME["bg_card"])
        status_row.pack(fill="x")
        self.anim_status_lbl = tk.Label(
            status_row,
            text="Step 0 / 0 • t = 0.0 min • Idle",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        self.anim_status_lbl.pack(side="left", padx=(0, 10))

        self.step_slider = tk.Scale(
            status_row,
            from_=1,
            to=1,
            orient="horizontal",
            showvalue=False,
            sliderlength=16,
            width=12,
            bg=THEME["bg_card"],
            fg=THEME["text_primary"],
            troughcolor=THEME["bg_input"],
            activebackground=THEME["accent"],
            highlightthickness=0,
            command=self._on_slider_moved,
        )
        self.step_slider.pack(side="left", fill="x", expand=True)

    def _build_right_cell_inspector(self, parent: tk.Misc) -> None:
        outer = tk.Frame(
            parent,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=285,
        )
        outer.grid(row=0, column=2, sticky="nsew")
        outer.grid_propagate(False)
        outer.pack_propagate(False)

        canvas = tk.Canvas(outer, bg=THEME["bg_card"], highlightthickness=0, width=263)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        right = tk.Frame(canvas, bg=THEME["bg_card"], padx=10, pady=8)
        right.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=right, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        tk.Label(
            right,
            text="SELECTED GRID CELL",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 5))

        self.risk_badge_lbl = tk.Label(
            right,
            text="No Cell Selected",
            bg=THEME["bg_card_alt"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=5,
            anchor="center",
        )
        self.risk_badge_lbl.pack(fill="x", pady=(0, 6))

        info_box = tk.Frame(right, bg=THEME["bg_input"], padx=8, pady=6)
        info_box.pack(fill="x", pady=(0, 6))

        self._cell_info_labels: dict[str, tk.Label] = {}
        fields = [
            ("cell_id", "Cell ID / Code:"),
            ("coords", "Center Coords:"),
            ("elev", "Ground Elevation:"),
            ("elev_src", "Elevation Status:"),
            ("depth_cm", "Water Depth (cm):"),
            ("vol_m3", "Water Volume:"),
            ("land_use", "Land Use:"),
            ("infil", "Infiltration Rate:"),
            ("drain", "Drainage Cap.:"),
            ("sim_time", "Simulation Time:"),
            ("exposure", "Cell Overlap*:"),
        ]
        for key, label_txt in fields:
            row = tk.Frame(info_box, bg=THEME["bg_input"])
            row.pack(fill="x", pady=1)
            tk.Label(
                row,
                text=label_txt,
                bg=THEME["bg_input"],
                fg=THEME["text_muted"],
                font=("Segoe UI", 8),
            ).pack(anchor="w")
            val_lbl = tk.Label(
                row,
                text="—",
                bg=THEME["bg_input"],
                fg=THEME["text_primary"],
                font=("Segoe UI", 8, "bold"),
                wraplength=205,
                justify="left",
            )
            val_lbl.pack(anchor="w")
            self._cell_info_labels[key] = val_lbl

        tk.Label(
            right,
            text=PROTOTYPE_RISK_DISCLAIMER,
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            wraplength=215,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

    # -------------------------------------------------------------------------
    # Public Data Refresh & Simulation Binding
    # -------------------------------------------------------------------------

    def refresh_workspace(
        self,
        neighbourhood: Neighbourhood | None,
        cells: list[GridCell],
        osm_features: list[OSMFeature],
        drainage_features: list[DrainageFeature],
        links: list[GridFeatureLink],
        saved_runs: list[SimulationRunRecord],
        shelters: list[Any] | None = None,
    ) -> None:
        self._neighbourhood = neighbourhood
        self._cells = cells
        self._osm_features = osm_features
        self._drainage_features = drainage_features
        self._links = links
        self._runs = saved_runs
        if shelters is not None:
            self._registered_shelters = list(shelters)
        elif neighbourhood is None:
            self._registered_shelters = []

        labels = [f"#{r.id}: {r.scenario_name} ({r.rainfall_intensity:.0f} mm/h)" for r in saved_runs]
        self.run_cb.configure(values=labels)

        if neighbourhood is not None:
            if self._viewport is None:
                self._viewport = GeoViewport(
                    neighbourhood.min_latitude,
                    neighbourhood.max_latitude,
                    neighbourhood.min_longitude,
                    neighbourhood.max_longitude,
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

        if not saved_runs:
            self.run_var.set("")
            self.display_output(None)
        elif self._output is not None and self._output.run.id is not None:
            # Keep active run highlighted if still in list
            matched = False
            for i, r in enumerate(saved_runs):
                if r.id == self._output.run.id:
                    self.run_var.set(labels[i])
                    matched = True
                    break
            if not matched:
                self.run_var.set(labels[0])
                self.display_output(None)
        else:
            self.run_var.set(labels[0])
        self._redraw_canvas()

    def display_output(self, output: SimulationOutput | None) -> None:
        self._output = output
        if output is None or not output.steps:
            self.anim_controller.configure_steps(0, 0)
            self.step_slider.configure(from_=0, to=0)
            self._sync_slider_programmatic(0)
            self._current_step_idx = 0
            self._current_depths = {}
            self._current_volumes = {}
            self.top_sub_lbl.configure(
                text="No simulation loaded — run a scenario in Simulation Lab to view flood maps."
            )
            self.anim_status_lbl.configure(text="Step 0 / 0 • t = 0.0 min • No data")
            self._update_step_metrics_and_redraw()
            return

        if output.run.id is not None:
            for i, r in enumerate(self._runs):
                if r.id == output.run.id:
                    vals = self.run_cb["values"]
                    if i < len(vals):
                        self.run_var.set(vals[i])
                    break

        total_steps = len(output.steps)
        last_idx = max(0, total_steps - 1)
        self.anim_controller.configure_steps(total_steps, start_index=last_idx)
        self.step_slider.configure(from_=1, to=total_steps)
        self._sync_slider_programmatic(total_steps)

        self._current_step_idx = last_idx
        self.top_sub_lbl.configure(
            text=(
                f"Loaded Run #{output.run.id or 'mem'}: {output.run.scenario_name} • "
                f"{output.run.rainfall_intensity:.0f} mm/hr × {output.run.rainfall_duration:.0f} min"
            )
        )
        self._update_step_metrics_and_redraw()

    # -------------------------------------------------------------------------
    # Step & Animation Callbacks
    # -------------------------------------------------------------------------

    def _clear_slider_suppress(self) -> None:
        self._suppress_slider_cb = False

    def _sync_slider_programmatic(self, step_one_based: int) -> None:
        self._suppress_slider_cb = True
        self.step_slider.set(step_one_based)
        self.after_idle(self._clear_slider_suppress)

    def _on_animation_step(self, step_idx: int) -> None:
        self._current_step_idx = step_idx
        self._sync_slider_programmatic(step_idx + 1)
        self._update_step_metrics_and_redraw()

    def _on_animation_state(self, state_str: str) -> None:
        if state_str == "Playing":
            self.btn_pause.configure(text="Pause")
        elif state_str == "Paused":
            self.btn_pause.configure(text="Resume")
        else:
            self.btn_pause.configure(text="Pause")
        self._refresh_anim_label(state_str)

    def _refresh_anim_label(self, state_str: str | None = None) -> None:
        if self._output is None or not self._output.steps:
            self.anim_status_lbl.configure(text="Step 0 / 0 • t = 0.0 min • No data")
            return
        idx = max(0, min(self._current_step_idx, len(self._output.steps) - 1))
        st = self._output.steps[idx]
        state = state_str or (
            "Playing"
            if self.anim_controller.is_playing
            else ("Paused" if self.anim_controller.is_paused else "Ready")
        )
        self.anim_status_lbl.configure(
            text=f"Step {st.timestep} / {len(self._output.steps)} • t = {st.sim_time_minutes:.1f} min • {state}"
        )

    def _anim_start(self) -> None:
        self.anim_controller.start()

    def _anim_pause_resume(self) -> None:
        if self.anim_controller.is_playing:
            self.anim_controller.pause()
        elif self.anim_controller.is_paused:
            self.anim_controller.resume()
        else:
            self.anim_controller.start()

    def _anim_stop(self) -> None:
        self.anim_controller.stop(notify=True)

    def _anim_prev(self) -> None:
        self.anim_controller.pause()
        self.anim_controller.prev_step()

    def _anim_next(self) -> None:
        self.anim_controller.pause()
        self.anim_controller.next_step()

    def _on_slider_moved(self, raw_val: str) -> None:
        if self._suppress_slider_cb or self._output is None or not self._output.steps:
            return
        try:
            step_num = int(float(raw_val))
        except ValueError:
            return
        if (step_num - 1) == self._current_step_idx:
            return
        self.anim_controller.pause()
        self.anim_controller.seek(step_num - 1)

    def _on_speed_change(self, _evt=None) -> None:
        txt = self.speed_var.get().replace("x", "").strip()
        try:
            self.anim_controller.set_speed(float(txt))
        except ValueError:
            pass

    def _on_run_selected(self, _evt=None) -> None:
        idx = self.run_cb.current()
        if 0 <= idx < len(self._runs) and self._runs[idx].id is not None:
            self.on_select_run(self._runs[idx].id)

    # -------------------------------------------------------------------------
    # State Update & Rendering
    # -------------------------------------------------------------------------

    def _active_timestep_number(self) -> int:
        if self._output is None or not self._output.steps:
            return 0
        idx = max(0, min(self._current_step_idx, len(self._output.steps) - 1))
        return self._output.steps[idx].timestep

    def _update_step_metrics_and_redraw(self) -> None:
        ts = self._active_timestep_number()
        if self._output is not None and ts > 0:
            self._current_depths, self._current_volumes, _ = extract_step_cell_data(self._output, ts)
            self._current_stats = compute_timestep_statistics(self._output, ts, self._cells, self._thresholds)
        else:
            self._current_depths = {}
            self._current_volumes = {}
            self._current_stats = compute_timestep_statistics(None, 0, self._cells, self._thresholds)

        self._current_exposure = compute_infrastructure_exposure(
            cells=self._cells,
            osm_features=self._osm_features,
            links=self._links,
            depths_by_cell_id=self._current_depths,
            road_threshold_cm=self._road_exp_cm,
            building_threshold_cm=self._bldg_exp_cm,
        )
        self._refresh_stats_panel()
        self._refresh_cell_inspector()
        self._refresh_anim_label()
        self._redraw_canvas()

    def _refresh_stats_panel(self) -> None:
        st = self._current_stats
        exp = self._current_exposure
        if st is None or st.is_empty:
            for k, lbl in self._stat_labels.items():
                lbl.configure(text="0" if k == "shelters" else "—")
            self._stat_labels["shelters"].configure(
                text=str(len(exp.shelter_features) + len(self._registered_shelters))
            )
            return
        self._stat_labels["max_d"].configure(text=f"{st.max_depth_cm:.1f} cm ({st.max_depth_m:.3f} m)")
        self._stat_labels["avg_d"].configure(text=f"{st.avg_depth_cm:.1f} cm ({st.avg_depth_m:.3f} m)")
        self._stat_labels["affected"].configure(text=f"{st.affected_cells}/{st.total_cells} ({st.affected_grid_pct:.0f}%)")
        self._stat_labels["area"].configure(text=f"{st.affected_area_ha:.2f} ha")
        self._stat_labels["high_risk"].configure(text=str(st.high_risk_cells))
        self._stat_labels["vhigh_risk"].configure(text=str(st.very_high_risk_cells))
        self._stat_labels["rain"].configure(text=f"{st.cumulative_rainfall_m3:,.0f} m³")
        self._stat_labels["infil"].configure(text=f"{st.cumulative_infiltration_m3:,.0f} m³")
        self._stat_labels["drain"].configure(text=f"{st.cumulative_drainage_m3:,.0f} m³")
        self._stat_labels["exp_roads"].configure(text=str(len(exp.exposed_road_ids)))
        self._stat_labels["exp_bldgs"].configure(text=str(len(exp.exposed_building_ids)))
        self._stat_labels["shelters"].configure(
            text=str(len(exp.shelter_features) + len(self._registered_shelters))
        )

    def _refresh_cell_inspector(self) -> None:
        cell = next((c for c in self._cells if c.id == self._selected_cell_id), None)
        if cell is None:
            self.risk_badge_lbl.configure(text="Click Any Grid Cell", bg=THEME["bg_card_alt"], fg=THEME["text_primary"])
            for lbl in self._cell_info_labels.values():
                lbl.configure(text="—")
            return

        cid = cell.id or 0
        depth_m = float(self._current_depths.get(cid, 0.0))
        vol_m3 = float(self._current_volumes.get(cid, 0.0))
        risk_cat = classify_flood_depth(depth_m, self._thresholds)
        badge_bg = RISK_BADGE_COLORS.get(risk_cat, THEME["bg_card_alt"])
        badge_fg = "#0B1120" if risk_cat in ("Low", "Moderate", "High") else "#F8FAFC"
        self.risk_badge_lbl.configure(text=f"Risk: {risk_cat} (Simulated)", bg=badge_bg, fg=badge_fg)

        # Elevation status — clearly identify assumed vs real vs NULL
        real_elev = cell.mean_elevation_m if cell.mean_elevation_m is not None else cell.elevation_m
        if real_elev is not None:
            elev_txt = f"{real_elev:.2f} m"
            elev_src = cell.elevation_source or "stored"
        elif self._output is not None:
            fc = next((f for f in self._output.final_cells if f.cell_id == cid), None)
            if fc is not None and self._output.summary.used_illustrative_terrain:
                elev_txt = f"{fc.elevation_m:.2f} m (Assumed)"
                elev_src = "Illustrative Assumed Terrain (Non-verified)"
            else:
                elev_txt = "NULL (Unavailable)"
                elev_src = "Unset (NULL)"
        else:
            elev_txt = "NULL (Unavailable)"
            elev_src = "Unset (NULL)"

        sim_t = self._current_stats.sim_time_minutes if self._current_stats else 0.0
        exp_r = self._current_exposure.exposed_roads_by_cell.get(cid, 0)
        exp_b = self._current_exposure.exposed_buildings_by_cell.get(cid, 0)
        local_drains = [d for d in self._drainage_features if d.grid_cell_id == cid]
        drain_txt = f"{cell.drainage_capacity:.1f} mm/hr ({len(local_drains)} drain obj)"

        self._cell_info_labels["cell_id"].configure(text=f"{cell.cell_code} (ID={cid})")
        self._cell_info_labels["coords"].configure(text=f"{cell.center_latitude:.5f}, {cell.center_longitude:.5f}")
        self._cell_info_labels["elev"].configure(text=elev_txt)
        self._cell_info_labels["elev_src"].configure(text=elev_src)
        self._cell_info_labels["depth_cm"].configure(text=f"{depth_m * 100.0:.2f} cm ({depth_m:.4f} m)")
        self._cell_info_labels["vol_m3"].configure(text=f"{vol_m3:,.2f} m³")
        self._cell_info_labels["land_use"].configure(text=f"{cell.land_use} ({cell.land_use_source})")
        self._cell_info_labels["infil"].configure(text=f"{cell.infiltration_rate:.1f} mm/hr ({cell.infiltration_source})")
        self._cell_info_labels["drain"].configure(text=drain_txt)
        self._cell_info_labels["sim_time"].configure(text=f"t = {sim_t:.1f} min (Step {self._active_timestep_number()})")
        self._cell_info_labels["exposure"].configure(text=f"{exp_r} road(s), {exp_b} building(s) overlapping")

    def _rebuild_legend(self) -> None:
        for child in self.legend_frame.winfo_children():
            child.destroy()
        th = self._thresholds
        cs = self._color_scale
        entries = [
            (cs.no_water, "No water (0 cm)"),
            (cs.low, f"Low (>0–{th.low_max_cm:.0f} cm)"),
            (cs.moderate, f"Moderate ({th.low_max_cm:.0f}–{th.moderate_max_cm:.0f} cm)"),
            (cs.high, f"High ({th.moderate_max_cm:.0f}–{th.high_max_cm:.0f} cm)"),
            (cs.very_high, f"Very High ({th.high_max_cm:.0f}–{th.critical_min_cm:.0f} cm)"),
            (cs.critical, f"Critical (≥{th.critical_min_cm:.0f} cm)"),
        ]
        for color, label in entries:
            row = tk.Frame(self.legend_frame, bg=THEME["bg_card"])
            row.pack(fill="x", pady=1)
            tk.Frame(row, bg=color, width=14, height=11).pack(side="left", padx=(0, 6))
            tk.Label(row, text=label, bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(
                side="left"
            )

    def _redraw_canvas(self) -> None:
        self.canvas.delete("all")
        if self._neighbourhood is None or self._viewport is None:
            w = max(200, self.canvas.winfo_width())
            h = max(200, self.canvas.winfo_height())
            self.canvas.create_text(
                w / 2,
                h / 2,
                text="No neighbourhood loaded.\nCreate or open POTHERI first.",
                fill=THEME["text_muted"],
                font=("Segoe UI", 11),
                justify="center",
            )
            return

        w = max(200, self.canvas.winfo_width())
        h = max(200, self.canvas.winfo_height())
        self._viewport.resize(w, h)

        show_water_layers = bool(self.var_water.get())
        self._map_renderer.render(
            canvas=self.canvas,
            viewport=self._viewport,
            neighbourhood=self._neighbourhood,
            features=self._osm_features,
            drainage_features=self._drainage_features,
            show_osm=True,
            show_roads=bool(self.var_roads.get()),
            show_buildings=bool(self.var_buildings.get()),
            show_water=show_water_layers,
            show_green=show_water_layers,
            show_wetlands=show_water_layers,
            show_drainage=bool(self.var_drainage.get()),
            draw_hud=True,
        )

        self._heatmap_renderer.render(
            canvas=self.canvas,
            viewport=self._viewport,
            cells=self._cells,
            depths_by_cell_id=self._current_depths,
            thresholds=self._thresholds,
            color_scale=self._color_scale,
            selected_cell_id=self._selected_cell_id,
            show_heatmap=bool(self.var_heatmap.get()),
            show_grid_lines=bool(self.var_grid_labels.get()),
            show_labels=bool(self.var_grid_labels.get()),
            translucent=bool(self.var_translucent.get()),
        )

        self._exposure_renderer.render_exposure(
            canvas=self.canvas,
            viewport=self._viewport,
            osm_features=self._osm_features,
            exposure=self._current_exposure,
            highlight_exposed_roads=bool(self.var_exposure.get()),
            highlight_exposed_buildings=bool(self.var_exposure.get()),
            show_shelters=bool(self.var_shelters.get()),
            registered_shelters=self._registered_shelters,
        )

        if self._output is not None and self._output.steps:
            idx = max(0, min(self._current_step_idx, len(self._output.steps) - 1))
            st = self._output.steps[idx]
            self._heatmap_renderer.render_timestamp_hud(
                self.canvas,
                self._output.run.scenario_name,
                st.timestep,
                len(self._output.steps),
                st.sim_time_minutes,
                is_empty=False,
            )
        else:
            self._heatmap_renderer.render_timestamp_hud(self.canvas, "", 0, 0, 0.0, is_empty=True)

    # -------------------------------------------------------------------------
    # Canvas Pan / Zoom / Cell Selection
    # -------------------------------------------------------------------------

    def _on_canvas_resize(self, _event=None) -> None:
        self._redraw_canvas()

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
        if was_drag or self._viewport is None:
            return
        hit = GridRenderer.hit_test(self._cells, self._viewport, event.x, event.y)
        if hit is not None and hit.id is not None:
            self._selected_cell_id = hit.id
            self._refresh_cell_inspector()
            self._redraw_canvas()

    def _on_mouse_move(self, event) -> None:
        if self._viewport is None:
            return
        lat, lon = self._viewport.screen_to_geo(event.x, event.y)
        self.cursor_lbl.configure(text=f"Cursor: {lat:.5f}, {lon:.5f}")

    # -------------------------------------------------------------------------
    # Configurable Thresholds / Colors Dialog & Exports
    # -------------------------------------------------------------------------

    def _open_thresholds_dialog(self) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("Configure Risk Thresholds & Heatmap Colours (Prototype Assumptions)")
        dlg.configure(bg=THEME["bg_surface"])
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()
        dlg.resizable(False, False)

        body = tk.Frame(dlg, bg=THEME["bg_surface"], padx=16, pady=12)
        body.pack(fill="both", expand=True)

        tk.Label(
            body,
            text="Editable Prototype Thresholds (cm) — Not Official Safety Standards",
            bg=THEME["bg_surface"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        vars_map = {
            "low": tk.StringVar(value=f"{self._thresholds.low_max_cm:.1f}"),
            "mod": tk.StringVar(value=f"{self._thresholds.moderate_max_cm:.1f}"),
            "high": tk.StringVar(value=f"{self._thresholds.high_max_cm:.1f}"),
            "crit": tk.StringVar(value=f"{self._thresholds.critical_min_cm:.1f}"),
            "road_exp": tk.StringVar(value=f"{self._road_exp_cm:.1f}"),
            "bldg_exp": tk.StringVar(value=f"{self._bldg_exp_cm:.1f}"),
        }
        rows_cfg = [
            ("Low Max Depth (cm):", "low"),
            ("Moderate Max Depth (cm):", "mod"),
            ("High Max Depth (cm):", "high"),
            ("Critical Heatmap Min (cm):", "crit"),
            ("Road Exposure Threshold (cm):", "road_exp"),
            ("Building Exposure Threshold (cm):", "bldg_exp"),
        ]
        for r_idx, (lbl_txt, key) in enumerate(rows_cfg, start=1):
            tk.Label(body, text=lbl_txt, bg=THEME["bg_surface"], fg=THEME["text_secondary"], font=("Segoe UI", 9)).grid(
                row=r_idx, column=0, sticky="w", pady=3, padx=(0, 12)
            )
            ttk.Entry(body, textvariable=vars_map[key], width=14).grid(row=r_idx, column=1, sticky="ew", pady=3)

        tk.Label(
            body, text="No-Water Cell Colour:", bg=THEME["bg_surface"], fg=THEME["text_secondary"], font=("Segoe UI", 9)
        ).grid(row=7, column=0, sticky="w", pady=4, padx=(0, 12))
        no_water_var = tk.StringVar(
            value="Green (#22C55E)" if self._color_scale.no_water == "#22C55E" else "Light Grey (#64748B)"
        )
        ttk.Combobox(
            body,
            textvariable=no_water_var,
            values=("Light Grey (#64748B)", "Green (#22C55E)"),
            state="readonly",
            width=18,
        ).grid(row=7, column=1, sticky="ew", pady=4)

        def _apply() -> None:
            try:
                th = RiskThresholds(
                    low_max_cm=float(vars_map["low"].get()),
                    moderate_max_cm=float(vars_map["mod"].get()),
                    high_max_cm=float(vars_map["high"].get()),
                    critical_min_cm=float(vars_map["crit"].get()),
                )
                th.validate()
                r_cm = max(0.0, float(vars_map["road_exp"].get()))
                b_cm = max(0.0, float(vars_map["bldg_exp"].get()))
            except (ValueError, ValidationError) as exc:
                messagebox.showerror("Invalid Thresholds", str(exc), parent=dlg)
                return

            self._thresholds = th
            self._road_exp_cm = r_cm
            self._bldg_exp_cm = b_cm
            self._color_scale.no_water = "#22C55E" if "Green" in no_water_var.get() else "#64748B"
            self.exposure_badge_lbl.configure(text=f"Road ≥ {r_cm:.0f} cm | Bldg ≥ {b_cm:.0f} cm")
            self._rebuild_legend()
            self._update_step_metrics_and_redraw()
            dlg.destroy()

        btn_f = tk.Frame(body, bg=THEME["bg_surface"])
        btn_f.grid(row=8, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btn_f, text="Cancel", command=dlg.destroy).pack(side="left", padx=(0, 6))
        ttk.Button(btn_f, text="Apply", style="Accent.TButton", command=_apply).pack(side="left")

    def _require_export_context(self) -> tuple[Neighbourhood, SimulationOutput, int] | None:
        if self._neighbourhood is None or self._output is None or not self._output.steps:
            messagebox.showinfo("Export Unavailable", "Select a saved simulation before exporting.")
            return None
        return self._neighbourhood, self._output, self._active_timestep_number()

    def _export_depth_csv(self) -> None:
        ctx = self._require_export_context()
        if not ctx:
            return
        nb, out, ts = ctx
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="Export Flood Depth Grid CSV",
            initialdir=str(EXPORTS_DIR),
            initialfile=f"{nb.name.lower()}_flood_depth_run{out.run.id or 0}_step{ts}.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        saved = export_flood_depth_grid_csv(nb, out, self._cells, ts, Path(path), self._thresholds)
        messagebox.showinfo("Exported", f"Flood depth CSV saved to:\n{saved}")

    def _export_risk_csv(self) -> None:
        ctx = self._require_export_context()
        if not ctx:
            return
        nb, out, ts = ctx
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="Export Risk Classification CSV",
            initialdir=str(EXPORTS_DIR),
            initialfile=f"{nb.name.lower()}_risk_class_run{out.run.id or 0}_step{ts}.csv",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        saved = export_risk_classification_csv(nb, out, self._cells, ts, Path(path), self._thresholds)
        messagebox.showinfo("Exported", f"Risk classification CSV saved to:\n{saved}")

    def _export_geojson(self) -> None:
        ctx = self._require_export_context()
        if not ctx:
            return
        nb, out, ts = ctx
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="Export Simulation Grid GeoJSON",
            initialdir=str(EXPORTS_DIR),
            initialfile=f"{nb.name.lower()}_flood_grid_run{out.run.id or 0}_step{ts}.geojson",
            defaultextension=".geojson",
            filetypes=[("GeoJSON", "*.geojson"), ("JSON", "*.json")],
        )
        if not path:
            return
        saved = export_simulation_geojson(nb, out, self._cells, ts, Path(path), self._thresholds)
        messagebox.showinfo("Exported", f"Simulation GeoJSON saved to:\n{saved}")

    def _export_pdf(self) -> None:
        ctx = self._require_export_context()
        if not ctx:
            return
        nb, out, ts = ctx
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="Export Simulation Summary PDF",
            initialdir=str(EXPORTS_DIR),
            initialfile=f"{nb.name.lower()}_flood_report_run{out.run.id or 0}.pdf",
            defaultextension=".pdf",
            filetypes=[("PDF Document", "*.pdf")],
        )
        if not path:
            return
        saved = export_simulation_summary_pdf(nb, out, self._cells, ts, Path(path), self._thresholds)
        messagebox.showinfo("Exported", f"Simulation PDF summary saved to:\n{saved}")
