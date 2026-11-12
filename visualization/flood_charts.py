"""Phase 4 Matplotlib multi-chart panel using actual Phase 3 simulation results."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from config import EXPORTS_DIR, THEME
from core.simulation_engine import SimulationOutput, SimulationRunRecord
from services.simulation_export import export_charts_png


class FloodChartsPanel(tk.Frame):
    """Displays 6 synchronized Phase 3 simulation progression charts and exports PNG."""

    def __init__(
        self,
        parent: tk.Misc,
        on_select_run: Callable[[int], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=18, pady=14)
        self.on_select_run = on_select_run
        self._runs: list[SimulationRunRecord] = []
        self._output: SimulationOutput | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        top = tk.Frame(self, bg=THEME["bg_root"])
        top.pack(fill="x", pady=(0, 8))

        title_col = tk.Frame(top, bg=THEME["bg_root"])
        title_col.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_col,
            text="Flood Simulation Time-Series Charts",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        self.subtitle_lbl = tk.Label(
            title_col,
            text="Plotted directly from stored Phase 3 simulation outputs (no fabricated series).",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        )
        self.subtitle_lbl.pack(anchor="w")

        ctrl = tk.Frame(top, bg=THEME["bg_root"])
        ctrl.pack(side="right")
        tk.Label(ctrl, text="Simulation:", bg=THEME["bg_root"], fg=THEME["text_secondary"], font=("Segoe UI", 9)).pack(
            side="left", padx=(0, 6)
        )
        self.run_var = tk.StringVar()
        self.run_cb = ttk.Combobox(ctrl, textvariable=self.run_var, state="readonly", width=34)
        self.run_cb.pack(side="left", padx=(0, 8))
        self.run_cb.bind("<<ComboboxSelected>>", self._on_run_combo)

        ttk.Button(
            ctrl,
            text="Export PNG",
            style="Accent.TButton",
            command=self._handle_export_png,
        ).pack(side="left")

        chart_card = tk.Frame(
            self,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=8,
            pady=8,
        )
        chart_card.pack(fill="both", expand=True)

        self.fig = Figure(figsize=(10.5, 6.2), dpi=100, facecolor=THEME["bg_card"])
        self.canvas = FigureCanvasTkAgg(self.fig, master=chart_card)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self._draw_empty()

    def set_runs(self, runs: list[SimulationRunRecord], active_run_id: int | None = None) -> None:
        self._runs = runs
        labels = [f"#{r.id}: {r.scenario_name} ({r.rainfall_intensity:.0f} mm/h)" for r in runs]
        self.run_cb.configure(values=labels)
        if not runs:
            self.run_var.set("")
            self.display_output(None)
            return
        idx = 0
        if active_run_id is not None:
            for i, r in enumerate(runs):
                if r.id == active_run_id:
                    idx = i
                    break
        self.run_var.set(labels[idx])

    def _on_run_combo(self, _evt=None) -> None:
        idx = self.run_cb.current()
        if 0 <= idx < len(self._runs) and self._runs[idx].id is not None:
            self.on_select_run(self._runs[idx].id)

    def display_output(self, output: SimulationOutput | None) -> None:
        self._output = output
        if output is None or not output.steps:
            self._draw_empty()
            return

        if output.run.id is not None:
            for i, r in enumerate(self._runs):
                if r.id == output.run.id:
                    vals = self.run_cb["values"]
                    if i < len(vals):
                        self.run_var.set(vals[i])
                    break

        self.subtitle_lbl.configure(
            text=(
                f"Run #{output.run.id or 'mem'}: {output.run.scenario_name} • "
                f"{output.run.simulation_mode} • Model {output.run.model_version} (Simulated Data)"
            )
        )
        self._draw_six_charts(output)

    def _draw_empty(self) -> None:
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        ax.set_facecolor(THEME["bg_input"])
        ax.text(
            0.5,
            0.5,
            "No saved Phase 3 simulation selected.\nRun a simulation in Simulation Lab first.",
            color=THEME["text_muted"],
            ha="center",
            va="center",
            fontsize=11,
        )
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color(THEME["border"])
        self.canvas.draw_idle()

    def _draw_six_charts(self, output: SimulationOutput) -> None:
        self.fig.clear()
        steps = sorted(output.steps, key=lambda s: s.timestep)
        t = [s.sim_time_minutes for s in steps]

        series_specs = [
            (
                "1. Maximum Water Depth vs Time",
                "Depth (cm)",
                [s.max_water_depth_m * 100.0 for s in steps],
                "#38BDF8",
                "Max Depth (cm)",
            ),
            (
                "2. Total Affected Area vs Time",
                "Area (ha)",
                [s.total_area_affected_m2 / 10_000.0 for s in steps],
                "#F97316",
                "Affected Area (ha)",
            ),
            (
                "3. Flooded Grid Cells vs Time",
                "Cells (count)",
                [float(s.affected_cell_count) for s in steps],
                "#FACC15",
                "Flooded Cells",
            ),
            (
                "4. Step Rainfall Input vs Time",
                "Volume (m³)",
                [s.rainfall_input_m3 for s in steps],
                "#22D3EE",
                "Rainfall Input (m³)",
            ),
            (
                "5. Step Infiltration Loss vs Time",
                "Volume (m³)",
                [s.infiltration_loss_m3 for s in steps],
                "#10B981",
                "Infiltration (m³)",
            ),
            (
                "6. Step Drainage Removal vs Time",
                "Volume (m³)",
                [s.drainage_loss_m3 for s in steps],
                "#A855F7",
                "Drainage Removal (m³)",
            ),
        ]

        for idx, (title, ylabel, vals, color, leg_label) in enumerate(series_specs, start=1):
            ax = self.fig.add_subplot(2, 3, idx)
            ax.set_facecolor(THEME["bg_input"])
            ax.plot(t, vals, color=color, linewidth=1.9, marker="o", markersize=3, label=leg_label)
            ax.set_title(title, color=THEME["text_primary"], fontsize=8.5, fontweight="bold")
            ax.set_xlabel("Time (min)", color=THEME["text_secondary"], fontsize=7.5)
            ax.set_ylabel(ylabel, color=THEME["text_secondary"], fontsize=7.5)
            ax.tick_params(colors=THEME["text_muted"], labelsize=7.5)
            ax.grid(True, color=THEME["border"], linestyle=":", alpha=0.5)
            for spine in ax.spines.values():
                spine.set_color(THEME["border"])
            leg = ax.legend(facecolor=THEME["bg_card"], edgecolor=THEME["border"], fontsize=7, loc="best")
            for txt in leg.get_texts():
                txt.set_color(THEME["text_secondary"])

        self.fig.suptitle(
            f"Simulated Hydrological Charts — {output.run.scenario_name} (Prototype Estimates)",
            color=THEME["accent_hover"],
            fontsize=10,
            fontweight="bold",
        )
        self.fig.tight_layout(rect=(0, 0, 1, 0.95))
        self.canvas.draw_idle()

    def _handle_export_png(self) -> None:
        if self._output is None or not self._output.steps:
            messagebox.showinfo("Export PNG", "Select or run a simulation before exporting charts.")
            return
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        default_name = f"flood_charts_run_{self._output.run.id or 'mem'}.png"
        target = filedialog.asksaveasfilename(
            title="Export Flood Simulation Charts as PNG",
            initialdir=str(EXPORTS_DIR),
            initialfile=default_name,
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png")],
        )
        if not target:
            return
        try:
            saved = export_charts_png(self.fig, Path(target))
            messagebox.showinfo("PNG Exported", f"Saved charts to:\n{saved}")
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc))
