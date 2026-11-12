"""Phase 4 Scenario Comparison view with side-by-side heatmaps, metrics & charts."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from config import MAP_COLORS, THEME
from core.flood_statistics import (
    SimulationComparison,
    compare_simulations,
    extract_step_cell_data,
)
from core.models import GridCell, Neighbourhood, OSMFeature
from core.risk_classifier import HeatmapColorScale, RiskThresholds
from core.simulation_engine import SimulationOutput, SimulationRunRecord
from visualization.heatmap_renderer import HeatmapRenderer
from visualization.map_renderer import GeoViewport, MapRenderer


class ScenarioComparisonView(tk.Frame):
    """Side-by-side comparison of two saved Phase 3 simulations."""

    def __init__(
        self,
        parent: tk.Misc,
        on_fetch_run: Callable[[int], SimulationOutput | None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=16, pady=12)
        self.on_fetch_run = on_fetch_run

        self._neighbourhood: Neighbourhood | None = None
        self._cells: list[GridCell] = []
        self._osm_features: list[OSMFeature] = []
        self._runs: list[SimulationRunRecord] = []

        self._out_a: SimulationOutput | None = None
        self._out_b: SimulationOutput | None = None
        self._comp: SimulationComparison | None = None

        self._thresholds = RiskThresholds()
        self._color_scale = HeatmapColorScale()
        self._map_renderer = MapRenderer()
        self._heatmap_renderer = HeatmapRenderer()
        self._vp_a: GeoViewport | None = None
        self._vp_b: GeoViewport | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        top = tk.Frame(self, bg=THEME["bg_root"])
        top.pack(fill="x", pady=(0, 8))

        title_col = tk.Frame(top, bg=THEME["bg_root"])
        title_col.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_col,
            text="Compare Simulation Scenarios",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_col,
            text="Side-by-side comparison of two saved Phase 3 runs (final timestep). Not real-world observations.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        sel_bar = tk.Frame(
            self,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        sel_bar.pack(fill="x", pady=(0, 8))

        tk.Label(sel_bar, text="Scenario A (Baseline):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(
            side="left", padx=(0, 6)
        )
        self.run_a_var = tk.StringVar()
        self.run_a_cb = ttk.Combobox(sel_bar, textvariable=self.run_a_var, state="readonly", width=30)
        self.run_a_cb.pack(side="left", padx=(0, 14))

        tk.Label(sel_bar, text="Scenario B (Alternative):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9, "bold")).pack(
            side="left", padx=(0, 6)
        )
        self.run_b_var = tk.StringVar()
        self.run_b_cb = ttk.Combobox(sel_bar, textvariable=self.run_b_var, state="readonly", width=30)
        self.run_b_cb.pack(side="left", padx=(0, 12))

        ttk.Button(sel_bar, text="Compare Scenarios", style="Accent.TButton", command=self.run_comparison).pack(
            side="left"
        )

        # Compatibility warning banner
        self.compat_banner = tk.Frame(
            self,
            bg=THEME["bg_card_alt"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=5,
        )
        self.compat_banner.pack(fill="x", pady=(0, 8))
        self.compat_lbl = tk.Label(
            self.compat_banner,
            text="Select two saved simulations and click Compare Scenarios.",
            bg=THEME["bg_card_alt"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 8, "bold"),
            wraplength=920,
            justify="left",
        )
        self.compat_lbl.pack(anchor="w", fill="x")
        self.compat_banner.bind("<Configure>", lambda e: self.compat_lbl.configure(wraplength=max(320, e.width - 24)))

        # Upper Split: Side-by-side heatmaps (left & right)
        maps_row = tk.Frame(self, bg=THEME["bg_root"])
        maps_row.pack(fill="both", expand=True, pady=(0, 8))
        maps_row.columnconfigure(0, weight=1, uniform="cmpmaps")
        maps_row.columnconfigure(1, weight=1, uniform="cmpmaps")
        maps_row.rowconfigure(0, weight=1)

        card_a = tk.Frame(maps_row, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=8, pady=6)
        card_a.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.hdr_a_lbl = tk.Label(card_a, text="Scenario A Heatmap", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 9, "bold"))
        self.hdr_a_lbl.pack(anchor="w", pady=(0, 4))
        self.canvas_a = tk.Canvas(card_a, bg=MAP_COLORS["canvas_bg"], highlightthickness=0, height=220)
        self.canvas_a.pack(fill="both", expand=True)
        self.canvas_a.bind("<Configure>", lambda _e: self._draw_side_maps())

        card_b = tk.Frame(maps_row, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=8, pady=6)
        card_b.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.hdr_b_lbl = tk.Label(card_b, text="Scenario B Heatmap", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 9, "bold"))
        self.hdr_b_lbl.pack(anchor="w", pady=(0, 4))
        self.canvas_b = tk.Canvas(card_b, bg=MAP_COLORS["canvas_bg"], highlightthickness=0, height=220)
        self.canvas_b.pack(fill="both", expand=True)
        self.canvas_b.bind("<Configure>", lambda _e: self._draw_side_maps())

        # Lower Split: Comparison Metrics Table (left) + Comparison Chart (right)
        lower = tk.Frame(self, bg=THEME["bg_root"])
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=1, uniform="cmplow")
        lower.columnconfigure(1, weight=1, uniform="cmplow")
        lower.rowconfigure(0, weight=1)

        tbl_card = tk.Frame(lower, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=8, pady=8)
        tbl_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(tbl_card, text="Metric Comparison (Final Step)", bg=THEME["bg_card"], fg=THEME["text_primary"], font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(0, 4)
        )
        cols = ("metric", "a", "b", "delta", "unit")
        self.cmp_tree = ttk.Treeview(tbl_card, columns=cols, show="headings", height=9)
        for key, label, width, anc in [
            ("metric", "Metric", 160, "w"),
            ("a", "Scenario A", 90, "e"),
            ("b", "Scenario B", 90, "e"),
            ("delta", "Delta (B - A)", 95, "e"),
            ("unit", "Unit", 55, "w"),
        ]:
            self.cmp_tree.heading(key, text=label)
            self.cmp_tree.column(key, width=width, anchor=anc)
        self.cmp_tree.pack(fill="both", expand=True)

        chart_card = tk.Frame(lower, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=8, pady=8)
        chart_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.fig = Figure(figsize=(5.2, 2.6), dpi=96, facecolor=THEME["bg_card"])
        self.chart_canvas = FigureCanvasTkAgg(self.fig, master=chart_card)
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True)
        self._draw_empty_chart()

    def refresh_workspace(
        self,
        neighbourhood: Neighbourhood | None,
        cells: list[GridCell],
        osm_features: list[OSMFeature],
        saved_runs: list[SimulationRunRecord],
    ) -> None:
        self._neighbourhood = neighbourhood
        self._cells = cells
        self._osm_features = osm_features
        self._runs = saved_runs

        labels = [f"#{r.id}: {r.scenario_name} ({r.rainfall_intensity:.0f} mm/h)" for r in saved_runs]
        self.run_a_cb.configure(values=labels)
        self.run_b_cb.configure(values=labels)

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

        if len(labels) >= 2:
            self.run_a_var.set(labels[1])
            self.run_b_var.set(labels[0])
        elif len(labels) == 1:
            self.run_a_var.set(labels[0])
            self.run_b_var.set(labels[0])
        else:
            self.run_a_var.set("")
            self.run_b_var.set("")
            self._out_a = None
            self._out_b = None
            self._comp = None

        self._draw_side_maps()

    def run_comparison(self) -> None:
        idx_a = self.run_a_cb.current()
        idx_b = self.run_b_cb.current()
        if idx_a < 0 or idx_b < 0 or idx_a >= len(self._runs) or idx_b >= len(self._runs):
            messagebox.showinfo("Compare Scenarios", "Need at least one saved simulation to compare.")
            return
        id_a = self._runs[idx_a].id
        id_b = self._runs[idx_b].id
        if id_a is None or id_b is None:
            return
        out_a = self.on_fetch_run(id_a)
        out_b = self.on_fetch_run(id_b)
        if out_a is None or out_b is None:
            messagebox.showwarning("Load Failed", "Could not load one or both saved runs from SQLite.")
            return
        self.display_comparison(out_a, out_b)

    def display_comparison(self, out_a: SimulationOutput, out_b: SimulationOutput) -> None:
        self._out_a = out_a
        self._out_b = out_b
        self._comp = compare_simulations(out_a, out_b, self._cells, self._cells, self._thresholds)

        if self._comp.compatibility_warnings:
            self.compat_banner.configure(bg=THEME["warning_bg"], highlightbackground=THEME["warning"])
            self.compat_lbl.configure(
                text="COMPATIBILITY WARNING: " + " | ".join(self._comp.compatibility_warnings),
                bg=THEME["warning_bg"],
                fg="#FDE68A",
            )
        else:
            self.compat_banner.configure(bg=THEME["success_bg"], highlightbackground=THEME["success"])
            self.compat_lbl.configure(
                text="Compatible grids, modes, durations & model versions. Comparing final simulation states.",
                bg=THEME["success_bg"],
                fg="#A7F3D0",
            )

        self.hdr_a_lbl.configure(text=f"A: {self._comp.label_a} (Max {self._comp.stats_a.max_depth_cm:.1f} cm)")
        self.hdr_b_lbl.configure(text=f"B: {self._comp.label_b} (Max {self._comp.stats_b.max_depth_cm:.1f} cm)")

        for item in self.cmp_tree.get_children():
            self.cmp_tree.delete(item)
        sa = self._comp.stats_a
        sb = self._comp.stats_b
        rows = [
            ("Max Water Depth", f"{sa.max_depth_cm:.2f}", f"{sb.max_depth_cm:.2f}", f"{self._comp.max_depth_delta_cm:+.2f}", "cm"),
            ("Avg Water Depth", f"{sa.avg_depth_cm:.2f}", f"{sb.avg_depth_cm:.2f}", f"{self._comp.avg_depth_delta_cm:+.2f}", "cm"),
            ("Affected Area", f"{sa.affected_area_ha:.2f}", f"{sb.affected_area_ha:.2f}", f"{(self._comp.affected_area_delta_m2 / 10000.0):+.2f}", "ha"),
            ("Affected Grid Cells", str(sa.affected_cells), str(sb.affected_cells), f"{self._comp.affected_cells_delta:+d}", "cells"),
            ("High-Risk Cells", str(sa.high_risk_cells), str(sb.high_risk_cells), f"{self._comp.high_risk_delta:+d}", "cells"),
            ("Very-High-Risk Cells", str(sa.very_high_risk_cells), str(sb.very_high_risk_cells), f"{self._comp.very_high_risk_delta:+d}", "cells"),
            ("Total Drainage Removal", f"{sa.cumulative_drainage_m3:,.1f}", f"{sb.cumulative_drainage_m3:,.1f}", f"{self._comp.drainage_delta_m3:+,.1f}", "m³"),
            ("Total Rainfall Input", f"{sa.cumulative_rainfall_m3:,.1f}", f"{sb.cumulative_rainfall_m3:,.1f}", f"{(sb.cumulative_rainfall_m3 - sa.cumulative_rainfall_m3):+,.1f}", "m³"),
            ("Total Infiltration Loss", f"{sa.cumulative_infiltration_m3:,.1f}", f"{sb.cumulative_infiltration_m3:,.1f}", f"{(sb.cumulative_infiltration_m3 - sa.cumulative_infiltration_m3):+,.1f}", "m³"),
        ]
        for r in rows:
            self.cmp_tree.insert("", "end", values=r)

        self._draw_side_maps()
        self._draw_comparison_chart(out_a, out_b)

    def _draw_side_maps(self) -> None:
        self._render_one_map(self.canvas_a, self._vp_a, self._out_a)
        self._render_one_map(self.canvas_b, self._vp_b, self._out_b)

    def _render_one_map(
        self,
        canvas: tk.Canvas,
        vp: GeoViewport | None,
        out: SimulationOutput | None,
    ) -> None:
        canvas.delete("all")
        if self._neighbourhood is None or vp is None:
            return
        w = max(160, canvas.winfo_width())
        h = max(160, canvas.winfo_height())
        vp.resize(w, h)
        self._map_renderer.render(
            canvas=canvas,
            viewport=vp,
            neighbourhood=self._neighbourhood,
            features=self._osm_features,
            show_osm=True,
            show_roads=True,
            show_buildings=True,
            show_water=True,
            show_green=False,
            show_wetlands=False,
            show_drainage=False,
            draw_hud=False,
        )
        depths: dict[int, float] = {}
        if out is not None and out.steps:
            last_ts = out.steps[-1].timestep
            depths, _, _ = extract_step_cell_data(out, last_ts)
        self._heatmap_renderer.render(
            canvas=canvas,
            viewport=vp,
            cells=self._cells,
            depths_by_cell_id=depths,
            thresholds=self._thresholds,
            color_scale=self._color_scale,
            show_heatmap=True,
            show_grid_lines=True,
            show_labels=False,
            translucent=True,
        )

    def _draw_empty_chart(self) -> None:
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(THEME["bg_input"])
        ax.set_title("Scenario Comparison Progression (Select A & B)", color=THEME["text_secondary"], fontsize=9)
        ax.tick_params(colors=THEME["text_muted"], labelsize=7.5)
        for sp in ax.spines.values():
            sp.set_color(THEME["border"])
        self.fig.tight_layout()
        self.chart_canvas.draw_idle()

    def _draw_comparison_chart(self, out_a: SimulationOutput, out_b: SimulationOutput) -> None:
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(THEME["bg_input"])
        if out_a.steps:
            ax.plot(
                [s.sim_time_minutes for s in out_a.steps],
                [s.max_water_depth_m * 100.0 for s in out_a.steps],
                color="#38BDF8",
                linewidth=2.0,
                label=f"A: {out_a.run.scenario_name[:22]}",
            )
        if out_b.steps:
            ax.plot(
                [s.sim_time_minutes for s in out_b.steps],
                [s.max_water_depth_m * 100.0 for s in out_b.steps],
                color="#F97316",
                linewidth=2.0,
                linestyle="--",
                label=f"B: {out_b.run.scenario_name[:22]}",
            )
        ax.set_title("Max Simulated Water Depth Trajectory (A vs B)", color=THEME["text_primary"], fontsize=9, fontweight="bold")
        ax.set_xlabel("Simulation Time (min)", color=THEME["text_secondary"], fontsize=8)
        ax.set_ylabel("Max Depth (cm)", color=THEME["text_secondary"], fontsize=8)
        ax.tick_params(colors=THEME["text_muted"], labelsize=7.5)
        ax.grid(True, color=THEME["border"], linestyle=":", alpha=0.5)
        for sp in ax.spines.values():
            sp.set_color(THEME["border"])
        leg = ax.legend(facecolor=THEME["bg_card"], edgecolor=THEME["border"], fontsize=7.5)
        for txt in leg.get_texts():
            txt.set_color(THEME["text_secondary"])
        self.fig.tight_layout()
        self.chart_canvas.draw_idle()
