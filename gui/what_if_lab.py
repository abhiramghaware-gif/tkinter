"""Phase 7 What-If Lab GUI: non-destructive scenario experiments and multi-run comparison."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from config import EXPORTS_DIR, MAP_COLORS, RAINFALL_DISTRIBUTIONS, THEME
from core.models import DrainageFeature, GridCell, Neighbourhood, OSMFeature
from core.risk_classifier import HeatmapColorScale, RiskThresholds
from core.scenario_comparator import (
    ExtendedScenarioComparison,
    compare_multiple_scenarios,
)
from core.scenario_manager import ScenarioManager, ScenarioVariant, clone_config_from_run
from core.simulation_engine import SimulationOutput, SimulationRunRecord
from core.validation import ValidationError
from routing.flood_exposure import RoadExposureThresholds
from routing.road_network import RoadNetworkGraph, build_road_network_from_osm
from services.report_generator import ReportGenerator
from visualization.heatmap_renderer import HeatmapRenderer
from visualization.map_renderer import GeoViewport, MapRenderer

logger = logging.getLogger(__name__)

EXPERIMENTS = (
    ("exp1_heavy_rainfall", "Exp 1: Heavy Rainfall (30 vs 60 vs 100 mm/hr)"),
    ("exp2_drainage_failure", "Exp 2: Drainage Failure (Normal vs 1 vs Multi Disabled)"),
    ("exp3_improved_drainage", "Exp 3: Improved Drainage (+50% vs Hypothetical Channel)"),
    ("exp4_land_use", "Exp 4: Land-Use / Infiltration (-40% vs +40%)"),
    ("exp5_road_closure", "Exp 5: Road Closure & Alternative SafeRoute"),
    ("exp6_combined_extreme", "Exp 6: Combined Extreme Stress-Test (Hypothetical)"),
)


class WhatIfLabView(tk.Frame):
    """Interactive What-If Lab for scenario experimentation & multi-scenario comparison."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_fetch_run: Callable[[int], SimulationOutput | None],
        on_save_run: Callable[[SimulationOutput], int],
        on_delete_run: Callable[[int], None],
        on_runs_changed: Callable[[], None],
        get_db_manager: Callable[[], object],
        get_exports_dir: Callable[[], Path] = lambda: EXPORTS_DIR,
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=14, pady=12)
        self.on_fetch_run = on_fetch_run
        self.on_save_run = on_save_run
        self.on_delete_run = on_delete_run
        self.on_runs_changed = on_runs_changed
        self.get_db_manager = get_db_manager
        self.get_exports_dir = get_exports_dir

        self._mgr = ScenarioManager()
        self._neighbourhood: Neighbourhood | None = None
        self._cells: list[GridCell] = []
        self._osm_features: list[OSMFeature] = []
        self._drainage_features: list[DrainageFeature] = []
        self._runs: list[SimulationRunRecord] = []
        self._network: RoadNetworkGraph | None = None

        self._thresholds = RiskThresholds()
        self._road_thresholds = RoadExposureThresholds()
        self._color_scale = HeatmapColorScale()
        self._map_renderer = MapRenderer()
        self._heatmap_renderer = HeatmapRenderer()

        self._last_comparison: ExtendedScenarioComparison | None = None
        self._compared_outputs: list[SimulationOutput] = []
        self._closed_edge_overrides: dict[int, set[int]] = {}
        self._vp_a: GeoViewport | None = None
        self._vp_b: GeoViewport | None = None

        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._busy = False
        self._run_check_vars: dict[int, tk.BooleanVar] = {}
        self._drain_map: dict[str, int] = {}
        self._road_map: dict[str, int] = {}
        self._cell_map: dict[str, int] = {}

        self._build_ui()
        self.after(120, self._poll_worker)

    def _build_ui(self) -> None:
        hdr = tk.Frame(self, bg=THEME["bg_root"])
        hdr.pack(fill="x", pady=(0, 6))
        tcol = tk.Frame(hdr, bg=THEME["bg_root"])
        tcol.pack(side="left", fill="x", expand=True)
        tk.Label(
            tcol,
            text="What-If Scenario Lab & Multi-Scenario Comparator",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            tcol,
            text="Clone saved configurations cleanly — modify rainfall, drainage, infiltration, initial depth, or roads without mutating Potheri base data.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        self.progress_lbl = tk.Label(
            hdr, text="Idle", bg=THEME["bg_card"], fg=THEME["accent_teal"],
            font=("Segoe UI", 8, "bold"), padx=10, pady=4,
        )
        self.progress_lbl.pack(side="right")

        # Main 2-column Paned / Grid Split
        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0, minsize=380)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_left_builder(body)
        self._build_right_workspace(body)

    def _build_left_builder(self, parent: tk.Misc) -> None:
        outer = tk.Frame(
            parent,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=385,
        )
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        outer.grid_propagate(False)

        canvas = tk.Canvas(outer, bg=THEME["bg_card"], highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=THEME["bg_card"], padx=10, pady=8)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # 1. Baseline & Copy Builder
        self._sec_hdr(inner, "1. BASE SCENARIO COPY")
        self._lbl(inner, "Clone Base Simulation:")
        self.base_run_var = tk.StringVar()
        self.base_run_cb = ttk.Combobox(inner, textvariable=self.base_run_var, state="readonly")
        self.base_run_cb.pack(fill="x", pady=(0, 6))
        self.base_run_cb.bind("<<ComboboxSelected>>", lambda _e: self._load_from_selected_base())

        self._lbl(inner, "New Scenario Name *:")
        self.var_name = tk.StringVar(value="What-If Scenario Copy")
        ttk.Entry(inner, textvariable=self.var_name).pack(fill="x", pady=(0, 6))

        # Rainfall overrides
        self._sec_hdr(inner, "2. RAINFALL & INITIAL DEPTH")
        rgrid = tk.Frame(inner, bg=THEME["bg_card"])
        rgrid.pack(fill="x", pady=(0, 4))
        rgrid.columnconfigure(0, weight=1)
        rgrid.columnconfigure(1, weight=1)

        self._lbl(rgrid, "Intensity (mm/hr):", row=0, col=0)
        self.var_rain = tk.StringVar(value="60")
        ttk.Entry(rgrid, textvariable=self.var_rain).grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(0, 4))

        self._lbl(rgrid, "Duration (min):", row=0, col=1)
        self.var_dur = tk.StringVar(value="60")
        ttk.Entry(rgrid, textvariable=self.var_dur).grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(0, 4))

        self._lbl(rgrid, "Time Step (min):", row=2, col=0)
        self.var_step = tk.StringVar(value="5")
        ttk.Entry(rgrid, textvariable=self.var_step).grid(row=3, column=0, sticky="ew", padx=(0, 4))

        self._lbl(rgrid, "Initial Depth (m):", row=2, col=1)
        self.var_init_depth = tk.StringVar(value="0.0")
        ttk.Entry(rgrid, textvariable=self.var_init_depth).grid(row=3, column=1, sticky="ew", padx=(4, 0))

        self._lbl(inner, "Rainfall Distribution:")
        self.var_dist = tk.StringVar(value="constant")
        ttk.Combobox(inner, textvariable=self.var_dist, values=list(RAINFALL_DISTRIBUTIONS), state="readonly").pack(fill="x", pady=(0, 6))

        # Drainage & Land-Use / Infiltration overrides
        self._sec_hdr(inner, "3. DRAINAGE & INFILTRATION OVERRIDES")
        dgrid = tk.Frame(inner, bg=THEME["bg_card"])
        dgrid.pack(fill="x", pady=(0, 4))
        dgrid.columnconfigure(0, weight=1)
        dgrid.columnconfigure(1, weight=1)

        self._lbl(dgrid, "Drainage Scale (x):", row=0, col=0)
        self.var_drain_scale = tk.StringVar(value="1.0")
        ttk.Entry(dgrid, textvariable=self.var_drain_scale).grid(row=1, column=0, sticky="ew", padx=(0, 4))

        self._lbl(dgrid, "Infiltration Scale (x):", row=0, col=1)
        self.var_infil_scale = tk.StringVar(value="1.0")
        ttk.Entry(dgrid, textvariable=self.var_infil_scale).grid(row=1, column=1, sticky="ew", padx=(4, 0))

        self._lbl(inner, "Disable Selected Drainage Feature (Optional):")
        self.var_disable_drain = tk.StringVar(value="None")
        self.disable_drain_cb = ttk.Combobox(inner, textvariable=self.var_disable_drain, state="readonly")
        self.disable_drain_cb.pack(fill="x", pady=(0, 4))

        self.var_add_hyp_drain = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            inner,
            text="Add hypothetical 450 L/s relief drain (labelled hypothetical)",
            variable=self.var_add_hyp_drain,
        ).pack(anchor="w", pady=(0, 4))

        cgrid = tk.Frame(inner, bg=THEME["bg_card"])
        cgrid.pack(fill="x", pady=(0, 6))
        cgrid.columnconfigure(0, weight=2)
        cgrid.columnconfigure(1, weight=1)
        self._lbl(cgrid, "Cell Infil Override:", row=0, col=0)
        self._lbl(cgrid, "Rate (mm/h):", row=0, col=1)
        self.var_override_cell = tk.StringVar(value="None")
        self.override_cell_cb = ttk.Combobox(cgrid, textvariable=self.var_override_cell, state="readonly")
        self.override_cell_cb.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self.var_override_rate = tk.StringVar(value="")
        ttk.Entry(cgrid, textvariable=self.var_override_rate).grid(row=1, column=1, sticky="ew")

        # Road condition overrides
        self._sec_hdr(inner, "4. ROAD CONDITION OVERRIDE (SAFEROUTE)")
        self._lbl(inner, "Simulate Closing Selected Road Segment:")
        self.var_close_road = tk.StringVar(value="None")
        self.close_road_cb = ttk.Combobox(inner, textvariable=self.var_close_road, state="readonly")
        self.close_road_cb.pack(fill="x", pady=(0, 6))

        ttk.Button(
            inner,
            text="Run & Save Custom What-If Scenario",
            style="Accent.TButton",
            command=self._run_custom_scenario_async,
        ).pack(fill="x", pady=(2, 8))

        # 5. Ready-Made Experiments (6 required)
        self._sec_hdr(inner, "5. READY-MADE EXPERIMENTS (EXPS 1–6)")
        self.var_exp = tk.StringVar(value=EXPERIMENTS[0][1])
        self.exp_cb = ttk.Combobox(
            inner, textvariable=self.var_exp, values=[lbl for _, lbl in EXPERIMENTS], state="readonly"
        )
        self.exp_cb.pack(fill="x", pady=(0, 6))
        ttk.Button(
            inner,
            text="Run Selected Experiment & Compare",
            command=self._run_selected_experiment_async,
        ).pack(fill="x")

    def _build_right_workspace(self, parent: tk.Misc) -> None:
        right = tk.Frame(parent, bg=THEME["bg_root"])
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        # Top Bar: Saved Runs Multi-Select & Actions
        top_card = tk.Frame(
            right,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        top_card.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top_card.columnconfigure(0, weight=1)

        hdr = tk.Frame(top_card, bg=THEME["bg_card"])
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        btns = tk.Frame(hdr, bg=THEME["bg_card"])
        btns.pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Compare Selected", style="Accent.TButton", command=self.compare_selected_runs).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="Export PDF", command=lambda: self._export_comparison("pdf")).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="Export CSV", command=lambda: self._export_comparison("csv")).pack(side="left", padx=(0, 4))
        ttk.Button(btns, text="Delete", style="Danger.TButton", command=self._delete_selected_run).pack(side="left")

        tk.Label(
            hdr, text="COMPARE 2+ RUNS",
            bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 9, "bold"),
        ).pack(side="left")

        self.checks_frame = tk.Frame(top_card, bg=THEME["bg_input"], padx=6, pady=4)
        self.checks_frame.grid(row=1, column=0, sticky="ew")

        # Compatibility & Config Diff Banner
        self.compat_lbl = tk.Label(
            right,
            text="Select two or more scenarios above (or run an Experiment 1–6 on the left).",
            bg=THEME["bg_card_alt"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 8, "bold"),
            padx=10,
            pady=6,
            anchor="w",
            wraplength=920,
            justify="left",
        )
        self.compat_lbl.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        # Notebook for Results: Heatmaps & Metrics | Delta & Config Diff | Charts
        self.res_nb = ttk.Notebook(right)
        self.res_nb.grid(row=2, column=0, sticky="nsew")

        # Tab 1: Comparison Table + Side-by-Side Heatmaps
        tab_summary = tk.Frame(self.res_nb, bg=THEME["bg_root"], padx=6, pady=6)
        tab_summary.rowconfigure(0, weight=1)
        tab_summary.rowconfigure(1, weight=1)
        tab_summary.columnconfigure(0, weight=1)

        cols = ("scenario", "rain", "drain", "max_d", "avg_d", "peak_t", "area", "cells", "risk_hv", "infil", "drain_m3", "roads")
        self.summary_tree = ttk.Treeview(tab_summary, columns=cols, show="headings", height=6)
        headings = [
            ("scenario", "Scenario", 175, "w"),
            ("rain", "Rain mm/h", 68, "e"),
            ("drain", "Drain x", 55, "e"),
            ("max_d", "Max cm", 62, "e"),
            ("avg_d", "Avg cm", 62, "e"),
            ("peak_t", "Peak t", 55, "e"),
            ("area", "Area m2", 78, "e"),
            ("cells", "Affected", 60, "e"),
            ("risk_hv", "High+VH", 60, "e"),
            ("infil", "Infil m3", 72, "e"),
            ("drain_m3", "Drain m3", 72, "e"),
            ("roads", "Exposed Rds", 82, "e"),
        ]
        for k, t, w, a in headings:
            self.summary_tree.heading(k, text=t)
            self.summary_tree.column(k, width=w, anchor=a)
        self.summary_tree.grid(row=0, column=0, sticky="nsew", pady=(0, 6))

        maps = tk.Frame(tab_summary, bg=THEME["bg_root"])
        maps.grid(row=1, column=0, sticky="nsew")
        maps.columnconfigure(0, weight=1, uniform="whm")
        maps.columnconfigure(1, weight=1, uniform="whm")
        maps.rowconfigure(0, weight=1)

        ca = tk.Frame(maps, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=6, pady=4)
        ca.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.hm_a_lbl = tk.Label(ca, text="Baseline Heatmap", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 8, "bold"))
        self.hm_a_lbl.pack(anchor="w")
        self.canvas_a = tk.Canvas(ca, bg=MAP_COLORS["canvas_bg"], highlightthickness=0)
        self.canvas_a.pack(fill="both", expand=True)
        self.canvas_a.bind("<Configure>", lambda _e: self._draw_side_heatmaps())

        cb = tk.Frame(maps, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=6, pady=4)
        cb.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self.hm_b_lbl = tk.Label(cb, text="Alternative Heatmap", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 8, "bold"))
        self.hm_b_lbl.pack(anchor="w")
        self.canvas_b = tk.Canvas(cb, bg=MAP_COLORS["canvas_bg"], highlightthickness=0)
        self.canvas_b.pack(fill="both", expand=True)
        self.canvas_b.bind("<Configure>", lambda _e: self._draw_side_heatmaps())

        # Tab 2: Delta, % Change & Config Diffs
        tab_deltas = tk.Frame(self.res_nb, bg=THEME["bg_root"], padx=6, pady=6)
        tab_deltas.rowconfigure(0, weight=2)
        tab_deltas.rowconfigure(1, weight=1)
        tab_deltas.columnconfigure(0, weight=1)

        dcols = ("pair", "metric", "base", "alt", "delta", "pct", "unit")
        self.delta_tree = ttk.Treeview(tab_deltas, columns=dcols, show="headings")
        for k, t, w, a in [
            ("pair", "Compared Scenario", 180, "w"),
            ("metric", "Metric", 160, "w"),
            ("base", "Baseline", 80, "e"),
            ("alt", "Target", 80, "e"),
            ("delta", "Difference", 85, "e"),
            ("pct", "% Change", 110, "e"),
            ("unit", "Unit", 55, "w"),
        ]:
            self.delta_tree.heading(k, text=t)
            self.delta_tree.column(k, width=w, anchor=a)
        self.delta_tree.grid(row=0, column=0, sticky="nsew", pady=(0, 6))

        self.cfg_diff_txt = tk.Text(
            tab_deltas, height=6, bg=THEME["bg_input"], fg=THEME["text_secondary"],
            font=("Consolas", 8), relief="flat", wrap="word",
        )
        self.cfg_diff_txt.grid(row=1, column=0, sticky="nsew")

        # Tab 3: Comparison Charts
        tab_charts = tk.Frame(self.res_nb, bg=THEME["bg_card"], padx=6, pady=6)
        self.fig = Figure(figsize=(7.0, 4.2), dpi=100, facecolor=THEME["bg_card"])
        self.chart_canvas = FigureCanvasTkAgg(self.fig, master=tab_charts)
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True)

        self.res_nb.add(tab_summary, text="Heatmaps & Summary Table")
        self.res_nb.add(tab_deltas, text="Metric Deltas & % Change")
        self.res_nb.add(tab_charts, text="Comparison Charts")

    @staticmethod
    def _sec_hdr(parent: tk.Misc, title: str) -> None:
        tk.Label(
            parent, text=title, bg=THEME["bg_card"], fg=THEME["accent_hover"],
            font=("Segoe UI", 8, "bold"), anchor="w",
        ).pack(fill="x", pady=(6, 3))

    @staticmethod
    def _lbl(parent: tk.Misc, text: str, row: int | None = None, col: int | None = None) -> None:
        lbl = tk.Label(parent, text=text, bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8), anchor="w")
        if row is not None and col is not None:
            lbl.grid(row=row, column=col, sticky="w", padx=(0 if col == 0 else 4, 0))
        else:
            lbl.pack(fill="x")

    # ------------------------------------------------------------------
    # Refresh & State
    # ------------------------------------------------------------------

    def refresh_workspace(
        self,
        neighbourhood: Neighbourhood | None,
        cells: list[GridCell],
        osm_features: list[OSMFeature],
        drainage_features: list[DrainageFeature],
        saved_runs: list[SimulationRunRecord],
        thresholds: RiskThresholds | None = None,
        road_thresholds: RoadExposureThresholds | None = None,
    ) -> None:
        self._neighbourhood = neighbourhood
        self._cells = cells
        self._osm_features = osm_features
        self._drainage_features = drainage_features
        self._runs = saved_runs
        if thresholds is not None:
            self._thresholds = thresholds
        if road_thresholds is not None:
            self._road_thresholds = road_thresholds

        if neighbourhood is not None:
            self._vp_a = GeoViewport(
                neighbourhood.min_latitude, neighbourhood.max_latitude,
                neighbourhood.min_longitude, neighbourhood.max_longitude, padding=16,
            )
            self._vp_b = GeoViewport(
                neighbourhood.min_latitude, neighbourhood.max_latitude,
                neighbourhood.min_longitude, neighbourhood.max_longitude, padding=16,
            )
        else:
            self._vp_a = None
            self._vp_b = None

        self._network = build_road_network_from_osm(neighbourhood.id, osm_features, cells) if (neighbourhood and neighbourhood.id and osm_features) else None

        run_labels = [f"#{r.id}: {r.scenario_name} ({r.rainfall_intensity:.0f} mm/h)" for r in saved_runs]
        self.base_run_cb.configure(values=run_labels)
        if run_labels and not self.base_run_var.get():
            self.base_run_var.set(run_labels[0])
            self._load_from_selected_base()
        elif not run_labels:
            self.base_run_var.set("")

        self._drain_map.clear()
        d_opts = ["None"]
        for d in drainage_features:
            if d.id is not None:
                lbl = f"#{d.id}: {d.name} ({d.status})"
                self._drain_map[lbl] = d.id
                d_opts.append(lbl)
        self.disable_drain_cb.configure(values=d_opts)
        if self.var_disable_drain.get() not in d_opts:
            self.var_disable_drain.set("None")

        self._cell_map.clear()
        c_opts = ["None"]
        for c in cells:
            if c.id is not None:
                lbl = f"{c.cell_code} ({c.land_use}, infil={c.infiltration_rate:.0f})"
                self._cell_map[lbl] = c.id
                c_opts.append(lbl)
        self.override_cell_cb.configure(values=c_opts)
        if self.var_override_cell.get() not in c_opts:
            self.var_override_cell.set("None")

        self._road_map.clear()
        r_opts = ["None"]
        if self._network is not None:
            for eid, edge in list(self._network.edges_by_id.items())[:80]:
                lbl = f"Edge #{eid}: {edge.road_name or 'Unnamed'} ({edge.distance_m:.0f}m)"
                self._road_map[lbl] = eid
                r_opts.append(lbl)
        self.close_road_cb.configure(values=r_opts)
        if self.var_close_road.get() not in r_opts:
            self.var_close_road.set("None")

        self._rebuild_run_checkboxes()

    def _rebuild_run_checkboxes(self) -> None:
        for w in self.checks_frame.winfo_children():
            w.destroy()
        old_states = {rid: var.get() for rid, var in self._run_check_vars.items()}
        self._run_check_vars.clear()

        if not self._runs:
            tk.Label(self.checks_frame, text="No saved simulations yet.", bg=THEME["bg_input"], fg=THEME["text_muted"], font=("Segoe UI", 8)).pack(anchor="w")
            return

        for idx, r in enumerate(self._runs[:12]):
            if r.id is None:
                continue
            default_on = old_states.get(r.id, idx < 2)
            var = tk.BooleanVar(value=default_on)
            self._run_check_vars[r.id] = var
            row_idx = idx // 3
            col_idx = idx % 3
            self.checks_frame.columnconfigure(col_idx, weight=1)
            ttk.Checkbutton(
                self.checks_frame,
                text=f"#{r.id}: {r.scenario_name[:26]}",
                variable=var,
            ).grid(row=row_idx, column=col_idx, sticky="w", padx=4, pady=1)

    def _load_from_selected_base(self) -> None:
        idx = self.base_run_cb.current()
        if 0 <= idx < len(self._runs):
            r = self._runs[idx]
            cfg = clone_config_from_run(r)
            self.var_name.set(f"{r.scenario_name} (Copy)")
            self.var_rain.set(f"{cfg.rainfall_intensity_mm_hr:.0f}")
            self.var_dur.set(f"{cfg.rainfall_duration_min:.0f}")
            self.var_step.set(f"{cfg.time_step_min:.0f}")
            self.var_init_depth.set(f"{cfg.initial_water_depth_m:.2f}")
            self.var_dist.set(cfg.distribution_pattern)
            self.var_drain_scale.set(f"{cfg.drainage_capacity_scale:.2f}")

    def _build_base_config(self) -> tuple[object, int | None]:
        idx = self.base_run_cb.current()
        base_rec = self._runs[idx] if 0 <= idx < len(self._runs) else None
        has_elev = any((c.mean_elevation_m or c.elevation_m) is not None for c in self._cells)
        cfg = clone_config_from_run(base_rec, has_elevations=has_elev)
        return cfg, (base_rec.id if base_rec else None)

    # ------------------------------------------------------------------
    # Execution (Background Thread -> Main GUI Thread)
    # ------------------------------------------------------------------

    def _run_custom_scenario_async(self) -> None:
        if self._busy or self._neighbourhood is None:
            return
        try:
            base_cfg, base_id = self._build_base_config()
            rain = float(self.var_rain.get().strip())
            dur = float(self.var_dur.get().strip())
            step = float(self.var_step.get().strip())
            init_d = float(self.var_init_depth.get().strip())
            d_scale = float(self.var_drain_scale.get().strip())
            i_scale = float(self.var_infil_scale.get().strip())

            disabled_ids: set[int] = set()
            if self.var_disable_drain.get() in self._drain_map:
                disabled_ids.add(self._drain_map[self.var_disable_drain.get()])

            extras: list[DrainageFeature] = []
            if self.var_add_hyp_drain.get() and self._cells:
                mid = self._cells[len(self._cells) // 2]
                extras.append(
                    DrainageFeature(
                        id=None,
                        neighbourhood_id=self._neighbourhood.id or 0,
                        grid_cell_id=mid.id,
                        name="Hypothetical Relief Channel (What-If)",
                        feature_type="Drainage channel",
                        latitude=mid.center_latitude,
                        longitude=mid.center_longitude,
                        capacity=450.0,
                        capacity_unit="L/s",
                        status="Operational",
                        source="what-if-hypothetical",
                        notes="HYPOTHETICAL INFRASTRUCTURE: What-If Lab addition.",
                    )
                )

            cell_ov: dict[int, float] = {}
            if self.var_override_cell.get() in self._cell_map and self.var_override_rate.get().strip():
                cell_ov[self._cell_map[self.var_override_cell.get()]] = float(self.var_override_rate.get().strip())

            closed_edges: set[int] = set()
            if self.var_close_road.get() in self._road_map:
                closed_edges.add(self._road_map[self.var_close_road.get()])

            variant = self._mgr.create_modified_variant(
                base_cfg,
                name=self.var_name.get().strip() or "What-If Scenario Copy",
                baseline_run_id=base_id,
                rainfall_intensity_mm_hr=rain,
                rainfall_duration_min=dur,
                distribution_pattern=self.var_dist.get(),
                time_step_min=step,
                initial_water_depth_m=init_d,
                disabled_drainage_ids=disabled_ids,
                drainage_capacity_scale=d_scale,
                extra_drainage_features=extras,
                infiltration_scale=i_scale,
                cell_land_use_infiltration_mm_hr=cell_ov,
                closed_edge_ids=closed_edges,
                is_hypothetical=True,
            )
        except (ValueError, ValidationError) as exc:
            messagebox.showerror("Invalid Scenario Parameter", str(exc))
            return

        self._launch_worker("custom", variant.name, [variant])

    def _run_selected_experiment_async(self) -> None:
        if self._busy or self._neighbourhood is None:
            return
        exp_lbl = self.var_exp.get()
        exp_key = next((k for k, lbl in EXPERIMENTS if lbl == exp_lbl), EXPERIMENTS[0][0])
        try:
            base_cfg, base_id = self._build_base_config()
            sel_drains = [self._drain_map[self.var_disable_drain.get()]] if self.var_disable_drain.get() in self._drain_map else None
            sel_roads = [self._road_map[self.var_close_road.get()]] if self.var_close_road.get() in self._road_map else (
                list(self._network.edges_by_id.keys())[:3] if self._network else None
            )
            title, variants = self._mgr.build_experiment_variants(
                exp_key,
                base_cfg,
                self._cells,
                self._drainage_features,
                selected_drainage_ids=sel_drains,
                selected_road_edge_ids=sel_roads,
                baseline_run_id=base_id,
            )
        except (ValueError, ValidationError) as exc:
            messagebox.showerror("Experiment Configuration Error", str(exc))
            return

        self._launch_worker(exp_key, title, variants)

    def _launch_worker(self, exp_key: str, title: str, variants: list[ScenarioVariant]) -> None:
        assert self._neighbourhood is not None
        self._busy = True
        self.progress_lbl.configure(text=f"Running {len(variants)} scenario(s)...", fg=THEME["warning"])
        nb = self._neighbourhood
        cells = list(self._cells)
        drains = list(self._drainage_features)

        def _worker() -> None:
            try:
                res = self._mgr.run_experiment_batch(nb, cells, drains, exp_key, title, variants)
                self._queue.put(("exp_ok", res))
            except Exception as exc:
                logger.exception("What-If execution error")
                self._queue.put(("exp_err", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()

    def _poll_worker(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "exp_ok":
                    self._busy = False
                    res = payload  # type: ignore[assignment]
                    saved_ids: list[int] = []
                    closed_overrides: dict[int, set[int]] = {}
                    for idx, (var, out) in enumerate(zip(res.variants, res.outputs)):
                        sid = self.on_save_run(out)
                        out.run.id = sid
                        saved_ids.append(sid)
                        if var.closed_edge_ids:
                            closed_overrides[idx] = set(var.closed_edge_ids)
                    self._closed_edge_overrides = closed_overrides
                    self.on_runs_changed()
                    for rid, var in self._run_check_vars.items():
                        var.set(rid in saved_ids)
                    self.progress_lbl.configure(text=f"Completed: {len(saved_ids)} saved", fg=THEME["success"])
                    if len(res.outputs) >= 2:
                        self._display_outputs(res.outputs)
                    elif len(res.outputs) == 1 and len(self._runs) >= 2:
                        self.compare_selected_runs()
                elif kind == "exp_err":
                    self._busy = False
                    self.progress_lbl.configure(text="Error", fg=THEME["error"])
                    messagebox.showerror("What-If Execution Error", str(payload))
                elif kind == "export_ok":
                    self._busy = False
                    self.progress_lbl.configure(text="Report saved", fg=THEME["success"])
                    messagebox.showinfo("Comparison Report Exported", f"Saved to:\n{payload}")
                elif kind == "export_err":
                    self._busy = False
                    self.progress_lbl.configure(text="Export failed", fg=THEME["error"])
                    messagebox.showerror("Export Error", str(payload))
        except queue.Empty:
            pass
        self.after(120, self._poll_worker)

    # ------------------------------------------------------------------
    # Comparison & Visualization
    # ------------------------------------------------------------------

    def compare_selected_runs(self) -> None:
        selected_ids = [rid for rid, var in self._run_check_vars.items() if var.get()]
        if len(selected_ids) < 2:
            messagebox.showinfo("Compare Scenarios", "Select at least two saved simulations using the checkboxes.")
            return
        outputs: list[SimulationOutput] = []
        for rid in selected_ids:
            out = self.on_fetch_run(rid)
            if out is not None:
                outputs.append(out)
        if len(outputs) < 2:
            messagebox.showwarning("Load Error", "Could not load selected simulations from SQLite.")
            return
        self._closed_edge_overrides = {}
        self._display_outputs(outputs)

    def _display_outputs(self, outputs: list[SimulationOutput]) -> None:
        node_ids = list(self._network.nodes_by_id.keys()) if self._network else []
        orig_id = node_ids[0] if len(node_ids) >= 2 else None
        dest_id = node_ids[-1] if len(node_ids) >= 2 else None

        comp = compare_multiple_scenarios(
            outputs,
            self._cells,
            thresholds=self._thresholds,
            network=self._network,
            origin_node_id=orig_id,
            dest_node_id=dest_id,
            closed_edge_ids_per_run=self._closed_edge_overrides,
            road_thresholds=self._road_thresholds,
        )
        self._last_comparison = comp
        self._compared_outputs = outputs

        if comp.compatibility_warnings:
            self.compat_lbl.configure(
                text="COMPATIBILITY WARNING: " + " | ".join(comp.compatibility_warnings),
                bg=THEME["warning_bg"], fg=THEME["warning"],
            )
        else:
            self.compat_lbl.configure(
                text=f"Compatible grids ({len(comp.rows)} scenarios). {comp.route_probe_note}",
                bg=THEME["bg_card_alt"], fg=THEME["accent_teal"],
            )

        for iid in self.summary_tree.get_children():
            self.summary_tree.delete(iid)
        for r in comp.rows:
            rds = str(r.exposed_high_roads) if r.exposed_high_roads is not None else "N/A"
            self.summary_tree.insert(
                "", "end",
                values=(
                    r.label[:30], f"{r.rainfall_intensity_mm_hr:.0f}", f"{r.drainage_scale:.2f}",
                    f"{r.max_depth_cm:.2f}", f"{r.avg_depth_cm:.2f}", f"{r.peak_depth_time_min:.0f}m",
                    f"{r.affected_area_m2:,.0f}", r.affected_cells,
                    r.high_risk_cells + r.very_high_risk_cells,
                    f"{r.total_infiltration_m3:,.1f}", f"{r.total_drainage_m3:,.1f}", rds,
                ),
            )

        for iid in self.delta_tree.get_children():
            self.delta_tree.delete(iid)
        for alt_lbl, dlist in comp.pairwise_deltas:
            for d in dlist:
                self.delta_tree.insert(
                    "", "end",
                    values=(alt_lbl[:28], d.metric_name, d.baseline_value, d.target_value, d.delta_value, d.pct_change_display, d.unit),
                )

        self.cfg_diff_txt.configure(state="normal")
        self.cfg_diff_txt.delete("1.0", "end")
        self.cfg_diff_txt.insert("end", "CONFIGURATION DIFFERENCES & SAFEROUTE NOTES:\n")
        for line in comp.config_differences:
            self.cfg_diff_txt.insert("end", f"• {line}\n")
        self.cfg_diff_txt.configure(state="disabled")

        self._draw_side_heatmaps()
        self._draw_comparison_chart()

    def _draw_side_heatmaps(self) -> None:
        self.canvas_a.delete("all")
        self.canvas_b.delete("all")
        if len(self._compared_outputs) < 2 or self._vp_a is None or self._vp_b is None:
            return
        out_a, out_b = self._compared_outputs[0], self._compared_outputs[1]
        self.hm_a_lbl.configure(text=f"Baseline: {out_a.run.scenario_name}")
        self.hm_b_lbl.configure(text=f"Alternative: {out_b.run.scenario_name}")

        for canvas, vp, out in ((self.canvas_a, self._vp_a, out_a), (self.canvas_b, self._vp_b, out_b)):
            w = max(120, canvas.winfo_width())
            h = max(100, canvas.winfo_height())
            vp.resize(w, h)
            vp.reset_view()
            step = out.steps[-1].timestep if out.steps else 1
            from core.flood_statistics import extract_step_cell_data
            d_map, _, _ = extract_step_cell_data(out, step)
            self._heatmap_renderer.render(
                canvas,
                vp,
                self._cells,
                d_map,
                thresholds=self._thresholds,
                color_scale=self._color_scale,
                show_heatmap=True,
                show_grid_lines=True,
                show_labels=False,
                translucent=True,
            )
            self._map_renderer.render(
                canvas,
                vp,
                self._neighbourhood,
                self._osm_features,
                show_buildings=False,
                show_green=False,
                show_drainage=False,
                draw_hud=False,
            )

    def _draw_comparison_chart(self) -> None:
        self.fig.clear()
        if not self._last_comparison:
            self.chart_canvas.draw_idle()
            return
        rows = self._last_comparison.rows
        names = [r.scenario_name[:15] for r in rows]
        x = list(range(len(names)))

        ax1 = self.fig.add_subplot(121)
        ax2 = self.fig.add_subplot(122)
        for ax in (ax1, ax2):
            ax.set_facecolor(THEME["bg_input"])
            ax.tick_params(colors=THEME["text_secondary"], labelsize=8)
            for sp in ax.spines.values():
                sp.set_color(THEME["border"])

        ax1.bar(x, [r.max_depth_cm for r in rows], color="#38BDF8", width=0.55)
        ax1.set_xticks(x)
        ax1.set_xticklabels(names, rotation=18, ha="right", fontsize=7.5)
        ax1.set_ylabel("Max Depth (cm)", color=THEME["text_secondary"], fontsize=8)
        ax1.set_title("Peak Flood Depth", color=THEME["text_primary"], fontsize=9, fontweight="bold")

        ax2.bar([i - 0.18 for i in x], [r.total_infiltration_m3 for r in rows], width=0.34, color="#10B981", label="Infiltration")
        ax2.bar([i + 0.18 for i in x], [r.total_drainage_m3 for r in rows], width=0.34, color="#F59E0B", label="Drainage")
        ax2.set_xticks(x)
        ax2.set_xticklabels(names, rotation=18, ha="right", fontsize=7.5)
        ax2.set_ylabel("Volume (m3)", color=THEME["text_secondary"], fontsize=8)
        ax2.set_title("Water Balance Loss", color=THEME["text_primary"], fontsize=9, fontweight="bold")
        ax2.legend(facecolor=THEME["bg_card"], edgecolor=THEME["border"], labelcolor=THEME["text_primary"], fontsize=7.5)

        self.fig.subplots_adjust(left=0.09, right=0.97, top=0.88, bottom=0.24, wspace=0.28)
        self.chart_canvas.draw_idle()

    def _delete_selected_run(self) -> None:
        ids = [rid for rid, var in self._run_check_vars.items() if var.get()]
        if not ids:
            messagebox.showinfo("Delete Scenario", "Select one or more saved simulation checkboxes to delete.")
            return
        if not messagebox.askyesno(
            "Confirm Scenario Deletion",
            f"Permanently delete {len(ids)} saved simulation run(s) ({ids}) from SQLite?\nThis action cannot be undone.",
        ):
            return
        for rid in ids:
            self.on_delete_run(rid)
        self.on_runs_changed()

    def _export_comparison(self, fmt: str) -> None:
        if self._busy or self._neighbourhood is None:
            return
        ids = [rid for rid, var in self._run_check_vars.items() if var.get()]
        if len(ids) < 2 and self._compared_outputs:
            ids = [o.run.id for o in self._compared_outputs if o.run.id is not None]
        if len(ids) < 2:
            messagebox.showinfo("Export Comparison", "Select or run at least two scenarios before exporting.")
            return
        exp_dir = self.get_exports_dir()
        ext = ".pdf" if fmt == "pdf" else ".csv"
        out_path = filedialog.asksaveasfilename(
            title=f"Save Scenario Comparison ({fmt.upper()})",
            initialdir=str(exp_dir),
            initialfile=f"floodguard_comparison_{self._neighbourhood.name.lower()}{ext}",
            defaultextension=ext,
            filetypes=[(f"{fmt.upper()} file", f"*{ext}")],
        )
        if not out_path:
            return
        self._busy = True
        self.progress_lbl.configure(text=f"Exporting {fmt.upper()}...", fg=THEME["warning"])
        db_mgr = self.get_db_manager()
        nid = self._neighbourhood.id
        net = self._network
        th, rth = self._thresholds, self._road_thresholds

        def _worker() -> None:
            try:
                gen = ReportGenerator(db_mgr, exports_dir=exp_dir)  # type: ignore[arg-type]
                res = gen.generate_report(
                    "scenario_comparison",
                    nid,
                    file_format=fmt,
                    output_path=out_path,
                    comparison_sim_ids=ids,
                    network=net,
                    thresholds=th,
                    road_thresholds=rth,
                )
                self._queue.put(("export_ok", str(res.output_path)))
            except Exception as exc:
                self._queue.put(("export_err", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()
