"""Simulation Lab UI for Phase 3 rainfall-runoff-drainage water-balance simulation."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from config import (
    DEFAULT_INFILTRATION_RATES_MM_HR,
    DEFAULT_MASS_BALANCE_TOLERANCE_M3,
    RAINFALL_DISTRIBUTIONS,
    RAINFALL_PRESETS,
    SIMULATION_MODE_ELEVATION,
    SIMULATION_MODE_ILLUSTRATIVE,
    THEME,
)
from core.models import DrainageFeature, GridCell, Neighbourhood
from core.simulation_config import SimulationConfig
from core.simulation_engine import SimulationOutput, SimulationRunRecord, SimulationStepRecord
from gui.components import StatCard


class SimulationLabView(tk.Frame):
    """Interactive Tkinter control & analysis workspace for the Phase 3 simulation engine."""

    _MODE_LABEL_TO_KEY = {
        "Elevation-based (Uses Saved Grid Elevation)": SIMULATION_MODE_ELEVATION,
        "Illustrative Assumed Terrain (Non-verified)": SIMULATION_MODE_ILLUSTRATIVE,
    }
    _MODE_KEY_TO_LABEL = {v: k for k, v in _MODE_LABEL_TO_KEY.items()}

    def __init__(
        self,
        parent: tk.Misc,
        on_start_simulation: Callable[[SimulationConfig], None],
        on_toggle_pause: Callable[[], bool],
        on_reset_simulation: Callable[[], None],
        on_load_saved_run: Callable[[int], None],
        on_delete_saved_run: Callable[[int], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=18, pady=14)
        self.on_start_simulation = on_start_simulation
        self.on_toggle_pause = on_toggle_pause
        self.on_reset_simulation = on_reset_simulation
        self.on_load_saved_run = on_load_saved_run
        self.on_delete_saved_run = on_delete_saved_run

        self._neighbourhood: Neighbourhood | None = None
        self._cells: list[GridCell] = []
        self._drainage_features: list[DrainageFeature] = []
        self._disabled_drain_ids: set[int] = set()
        self._saved_runs: list[SimulationRunRecord] = []
        self._current_output: SimulationOutput | None = None
        self._is_running = False

        self._build_ui()

    def _build_ui(self) -> None:
        # Header & Prototype Disclaimer
        hdr = tk.Frame(self, bg=THEME["bg_root"])
        hdr.pack(fill="x", pady=(0, 8))

        title_col = tk.Frame(hdr, bg=THEME["bg_root"])
        title_col.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_col,
            text="Simulation Lab — Urban Water-Balance Engine",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        self.ws_subtitle_lbl = tk.Label(
            title_col,
            text="No active workspace loaded.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        )
        self.ws_subtitle_lbl.pack(anchor="w")

        warn_banner = tk.Frame(
            self,
            bg=THEME["warning_bg"],
            highlightbackground=THEME["warning"],
            highlightthickness=1,
            padx=12,
            pady=6,
        )
        warn_banner.pack(fill="x", pady=(0, 10))
        warn_lbl = tk.Label(
            warn_banner,
            text=(
                "HYPOTHETICAL SCENARIO ENGINE: Inputs & outputs represent simplified experimental water-balance "
                "calculations, NOT verified real-world flood forecasts or official warnings. "
                "Illustrative infiltration & terrain values are explicitly labelled."
            ),
            bg=THEME["warning_bg"],
            fg="#FDE68A",
            font=("Segoe UI", 8, "bold"),
            wraplength=760,
            justify="left",
        )
        warn_lbl.pack(anchor="w", fill="x")
        warn_banner.bind(
            "<Configure>",
            lambda e: warn_lbl.configure(wraplength=max(320, e.width - 28)),
        )

        # Main 2-column split: Left Scrollable Config (355px) + Right Output Area
        body = tk.Frame(self, bg=THEME["bg_root"])
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_left_config_panel(body)
        self._build_right_results_panel(body)

    def _build_left_config_panel(self, parent: tk.Misc) -> None:
        outer = tk.Frame(
            parent,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=330,
        )
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        outer.grid_propagate(False)

        canvas = tk.Canvas(outer, bg=THEME["bg_card"], highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=THEME["bg_card"], padx=12, pady=10)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win_id, width=e.width))
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        def sec_hdr(text: str) -> None:
            tk.Label(
                inner,
                text=text,
                bg=THEME["bg_card"],
                fg=THEME["accent_hover"],
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w", pady=(8, 4))

        def lbl(parent_f: tk.Misc, text: str) -> None:
            tk.Label(
                parent_f,
                text=text,
                bg=THEME["bg_card"],
                fg=THEME["text_secondary"],
                font=("Segoe UI", 8),
            ).pack(anchor="w")

        # 1. Hypothetical Scenario Preset
        sec_hdr("1. HYPOTHETICAL RAINFALL SCENARIO")
        lbl(inner, "Scenario Preset (Hypothetical Input — Not Live Weather):")
        self.preset_var = tk.StringVar(value="Moderate rainfall (30 mm/hr)")
        preset_cb = ttk.Combobox(
            inner,
            textvariable=self.preset_var,
            values=list(RAINFALL_PRESETS.keys()),
            state="readonly",
        )
        preset_cb.pack(fill="x", pady=(1, 6))
        preset_cb.bind("<<ComboboxSelected>>", self._on_preset_selected)

        lbl(inner, "Scenario Name:")
        self.scenario_name_var = tk.StringVar(value="[Hypothetical] Moderate rainfall (30 mm/hr)")
        ttk.Entry(inner, textvariable=self.scenario_name_var).pack(fill="x", pady=(1, 6))

        row_rf = tk.Frame(inner, bg=THEME["bg_card"])
        row_rf.pack(fill="x", pady=(0, 6))
        row_rf.columnconfigure(0, weight=1)
        row_rf.columnconfigure(1, weight=1)
        row_rf.columnconfigure(2, weight=1)

        f_int = tk.Frame(row_rf, bg=THEME["bg_card"])
        f_int.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        lbl(f_int, "Intensity (mm/hr)")
        self.intensity_var = tk.StringVar(value="30.0")
        ttk.Entry(f_int, textvariable=self.intensity_var).pack(fill="x")

        f_dur = tk.Frame(row_rf, bg=THEME["bg_card"])
        f_dur.grid(row=0, column=1, sticky="ew", padx=2)
        lbl(f_dur, "Duration (min)")
        self.duration_var = tk.StringVar(value="60")
        ttk.Entry(f_dur, textvariable=self.duration_var).pack(fill="x")

        f_dt = tk.Frame(row_rf, bg=THEME["bg_card"])
        f_dt.grid(row=0, column=2, sticky="ew", padx=(4, 0))
        lbl(f_dt, "Step (min)")
        self.timestep_var = tk.StringVar(value="5")
        ttk.Entry(f_dt, textvariable=self.timestep_var).pack(fill="x")

        row_dist = tk.Frame(inner, bg=THEME["bg_card"])
        row_dist.pack(fill="x", pady=(0, 6))
        row_dist.columnconfigure(0, weight=1)
        row_dist.columnconfigure(1, weight=1)

        f_dist = tk.Frame(row_dist, bg=THEME["bg_card"])
        f_dist.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        lbl(f_dist, "Distribution")
        self.dist_var = tk.StringVar(value="constant")
        dist_cb = ttk.Combobox(
            f_dist, textvariable=self.dist_var, values=list(RAINFALL_DISTRIBUTIONS), state="readonly"
        )
        dist_cb.pack(fill="x")
        dist_cb.bind("<<ComboboxSelected>>", lambda _e: self._toggle_custom_entry())

        f_init = tk.Frame(row_dist, bg=THEME["bg_card"])
        f_init.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        lbl(f_init, "Initial Depth (m)")
        self.init_depth_var = tk.StringVar(value="0.0")
        ttk.Entry(f_init, textvariable=self.init_depth_var).pack(fill="x")

        lbl(inner, "Custom Step Intensities (mm/hr, comma-separated):")
        self.custom_rain_var = tk.StringVar(value="10, 25, 50, 35, 15")
        self.custom_rain_entry = ttk.Entry(inner, textvariable=self.custom_rain_var, state="disabled")
        self.custom_rain_entry.pack(fill="x", pady=(1, 6))

        # 2. Terrain & Simulation Mode
        sec_hdr("2. SIMULATION MODE & TERRAIN")
        lbl(inner, "Elevation Handling Mode:")
        self.mode_var = tk.StringVar(value="Illustrative Assumed Terrain (Non-verified)")
        mode_cb = ttk.Combobox(
            inner,
            textvariable=self.mode_var,
            values=list(self._MODE_LABEL_TO_KEY.keys()),
            state="readonly",
        )
        mode_cb.pack(fill="x", pady=(1, 4))
        mode_cb.bind("<<ComboboxSelected>>", lambda _e: self._toggle_illustrative_fields())

        self.elev_status_lbl = tk.Label(
            inner,
            text="Grid elevation coverage: 0 / 0 cells",
            bg=THEME["bg_card"],
            fg=THEME["warning"],
            font=("Segoe UI", 8),
            wraplength=285,
            justify="left",
        )
        self.elev_status_lbl.pack(anchor="w", pady=(0, 4))

        row_ill = tk.Frame(inner, bg=THEME["bg_card"])
        row_ill.pack(fill="x", pady=(0, 6))
        for c in range(3):
            row_ill.columnconfigure(c, weight=1)
        f_b = tk.Frame(row_ill, bg=THEME["bg_card"])
        f_b.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        lbl(f_b, "Assumed Base (m)")
        self.ill_base_var = tk.StringVar(value="15.0")
        self.ill_base_entry = ttk.Entry(f_b, textvariable=self.ill_base_var)
        self.ill_base_entry.pack(fill="x")

        f_ns = tk.Frame(row_ill, bg=THEME["bg_card"])
        f_ns.grid(row=0, column=1, sticky="ew", padx=3)
        lbl(f_ns, "N-S Drop (m)")
        self.ill_ns_var = tk.StringVar(value="2.0")
        self.ill_ns_entry = ttk.Entry(f_ns, textvariable=self.ill_ns_var)
        self.ill_ns_entry.pack(fill="x")

        f_we = tk.Frame(row_ill, bg=THEME["bg_card"])
        f_we.grid(row=0, column=2, sticky="ew", padx=(3, 0))
        lbl(f_we, "W-E Drop (m)")
        self.ill_we_var = tk.StringVar(value="1.0")
        self.ill_we_entry = ttk.Entry(f_we, textvariable=self.ill_we_var)
        self.ill_we_entry.pack(fill="x")

        # 3. Land-Use Infiltration Parameters (Illustrative Assumptions)
        sec_hdr("3. INFILTRATION PARAMETERS (ILLUSTRATIVE ASSUMPTIONS)")
        self.use_cell_infil_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            inner,
            text="Prefer saved cell infiltration rate when non-missing",
            variable=self.use_cell_infil_var,
        ).pack(anchor="w", pady=(0, 4))

        infil_grid = tk.Frame(inner, bg=THEME["bg_card"])
        infil_grid.pack(fill="x", pady=(0, 6))
        infil_grid.columnconfigure(0, weight=1)
        infil_grid.columnconfigure(1, weight=1)
        self._infil_vars: dict[str, tk.StringVar] = {}
        for idx, (cat, default_val) in enumerate(DEFAULT_INFILTRATION_RATES_MM_HR.items()):
            r = idx // 2
            c = idx % 2
            box = tk.Frame(infil_grid, bg=THEME["bg_card"])
            box.grid(row=r, column=c, sticky="ew", padx=(0 if c == 0 else 4, 4 if c == 0 else 0), pady=2)
            lbl(box, f"{cat} (mm/hr)")
            var = tk.StringVar(value=f"{default_val:.1f}")
            self._infil_vars[cat] = var
            ttk.Entry(box, textvariable=var).pack(fill="x")

        # 4. Drainage & What-If Experiment Multipliers
        sec_hdr("4. DRAINAGE & WHAT-IF OVERRIDES (NON-DESTRUCTIVE)")
        self.include_drain_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            inner,
            text="Include Phase 2 drainage features & cell drainage",
            variable=self.include_drain_var,
        ).pack(anchor="w", pady=(0, 4))

        row_wi = tk.Frame(inner, bg=THEME["bg_card"])
        row_wi.pack(fill="x", pady=(0, 4))
        row_wi.columnconfigure(0, weight=1)
        row_wi.columnconfigure(1, weight=1)

        f_rs = tk.Frame(row_wi, bg=THEME["bg_card"])
        f_rs.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        lbl(f_rs, "Rainfall Scale (x)")
        self.rain_scale_var = tk.StringVar(value="1.0")
        ttk.Entry(f_rs, textvariable=self.rain_scale_var).pack(fill="x")

        f_ds = tk.Frame(row_wi, bg=THEME["bg_card"])
        f_ds.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        lbl(f_ds, "Drainage Scale (x)")
        self.drain_scale_var = tk.StringVar(value="1.0")
        ttk.Entry(f_ds, textvariable=self.drain_scale_var).pack(fill="x")

        lbl(inner, "Double-click a drainage element to toggle Disabled (What-If):")
        self.drain_listbox = tk.Listbox(
            inner,
            height=4,
            bg=THEME["bg_input"],
            fg=THEME["text_primary"],
            selectbackground=THEME["accent_muted"],
            highlightthickness=1,
            highlightbackground=THEME["border"],
            font=("Segoe UI", 8),
        )
        self.drain_listbox.pack(fill="x", pady=(2, 8))
        self.drain_listbox.bind("<Double-Button-1>", self._on_toggle_drain_disabled)

        # 5. Simulation Action Buttons
        btn_row = tk.Frame(inner, bg=THEME["bg_card"])
        btn_row.pack(fill="x", pady=(6, 4))
        self.start_btn = ttk.Button(
            btn_row,
            text="Start Simulation",
            style="Accent.TButton",
            command=self._handle_start_clicked,
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.pause_btn = ttk.Button(
            btn_row,
            text="Pause",
            command=self._handle_pause_clicked,
            state="disabled",
        )
        self.pause_btn.pack(side="left", padx=(0, 4))

        self.reset_btn = ttk.Button(
            btn_row,
            text="Reset",
            command=self._handle_reset_clicked,
        )
        self.reset_btn.pack(side="left")

    def _build_right_results_panel(self, parent: tk.Misc) -> None:
        right = tk.Frame(parent, bg=THEME["bg_root"])
        right.grid(row=0, column=1, sticky="nsew")

        # Progress & Status Bar
        prog_card = tk.Frame(
            right,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        prog_card.pack(fill="x", pady=(0, 10))

        top_st = tk.Frame(prog_card, bg=THEME["bg_card"])
        top_st.pack(fill="x", pady=(0, 4))
        self.sim_clock_lbl = tk.Label(
            top_st,
            text="Step 0 / 0  •  t = 0.0 min",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
        )
        self.sim_clock_lbl.pack(side="right", padx=(8, 0))

        self.sim_status_lbl = tk.Label(
            top_st,
            text="Status: Idle — Configure a hypothetical scenario and click Start",
            bg=THEME["bg_card"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
            justify="left",
            wraplength=420,
        )
        self.sim_status_lbl.pack(side="left", fill="x", expand=True)
        top_st.bind(
            "<Configure>",
            lambda e: self.sim_status_lbl.configure(wraplength=max(200, e.width - 190)),
        )

        self.sim_progress = ttk.Progressbar(prog_card, mode="determinate", maximum=100)
        self.sim_progress.pack(fill="x", pady=(0, 4))

        self.sim_notes_lbl = tk.Label(
            prog_card,
            text="No active warnings.",
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            wraplength=560,
            justify="left",
        )
        self.sim_notes_lbl.pack(anchor="w", fill="x")
        prog_card.bind(
            "<Configure>",
            lambda e: self.sim_notes_lbl.configure(wraplength=max(280, e.width - 28)),
        )

        # KPI Cards (2 rows x 4 cols)
        kpi_grid = tk.Frame(right, bg=THEME["bg_root"])
        kpi_grid.pack(fill="x", pady=(0, 8))
        for c in range(4):
            kpi_grid.columnconfigure(c, weight=1, uniform="simkpis")

        self.kpi_max_depth = StatCard(kpi_grid, "Max Depth", "—", "Peak & time", THEME["info"])
        self.kpi_avg_depth = StatCard(kpi_grid, "Avg Depth", "—", "Grid mean", THEME["accent"])
        self.kpi_rain_vol = StatCard(kpi_grid, "Rainfall In", "—", "Hypothetical input", THEME["accent_teal"])
        self.kpi_infil_vol = StatCard(kpi_grid, "Infiltration", "—", "Soil-limited loss", THEME["success"])

        self.kpi_drain_vol = StatCard(kpi_grid, "Drainage Out", "—", "Capacity-limited", "#38BDF8")
        self.kpi_affected = StatCard(kpi_grid, "Affected Area", "—", "Peak wet cells", THEME["warning"])
        self.kpi_transfer = StatCard(kpi_grid, "Cell Transfers", "—", "Routed flux", THEME["text_secondary"])
        self.kpi_mass = StatCard(kpi_grid, "Mass Balance", "—", "Global residual", THEME["accent"])

        all_kpis = [
            self.kpi_max_depth, self.kpi_avg_depth, self.kpi_rain_vol, self.kpi_infil_vol,
            self.kpi_drain_vol, self.kpi_affected, self.kpi_transfer, self.kpi_mass,
        ]
        for card in all_kpis:
            card.value_lbl.configure(font=("Segoe UI", 12, "bold"))

        for col_idx, card in enumerate(all_kpis[:4]):
            card.grid(row=0, column=col_idx, sticky="nsew", padx=(0 if col_idx == 0 else 6, 0), pady=(0, 6))
        for col_idx, card in enumerate(all_kpis[4:]):
            card.grid(row=1, column=col_idx, sticky="nsew", padx=(0 if col_idx == 0 else 6, 0))

        # Tabbed Results Area
        notebook = ttk.Notebook(right)
        notebook.pack(fill="both", expand=True)

        tab_steps = tk.Frame(notebook, bg=THEME["bg_card"], padx=8, pady=6)
        tab_chart = tk.Frame(notebook, bg=THEME["bg_card"], padx=8, pady=6)
        tab_cells = tk.Frame(notebook, bg=THEME["bg_card"], padx=8, pady=6)
        tab_runs = tk.Frame(notebook, bg=THEME["bg_card"], padx=8, pady=6)

        notebook.add(tab_steps, text="Time-Step Progression")
        notebook.add(tab_chart, text="Hydrograph (Simulated)")
        notebook.add(tab_cells, text="Grid Cell Results")
        notebook.add(tab_runs, text="Saved Runs (SQLite)")

        # Tab 1: Time-Step Treeview
        step_cols = (
            "step",
            "time",
            "intensity",
            "rain",
            "infil",
            "drain",
            "transfer",
            "rem",
            "max_d",
            "wet",
            "area",
            "err",
        )
        self.steps_tree = ttk.Treeview(tab_steps, columns=step_cols, show="headings", height=12)
        step_headers = [
            ("step", "Step", 44),
            ("time", "Time (m)", 62),
            ("intensity", "Rain (mm/h)", 76),
            ("rain", "Rain (m³)", 78),
            ("infil", "Infil (m³)", 78),
            ("drain", "Drain (m³)", 78),
            ("transfer", "Flow (m³)", 78),
            ("rem", "Surf Vol (m³)", 88),
            ("max_d", "Max D (m)", 72),
            ("wet", "Wet Cells", 66),
            ("area", "Area (m²)", 82),
            ("err", "MB Err (m³)", 82),
        ]
        for key, label, width in step_headers:
            self.steps_tree.heading(key, text=label)
            self.steps_tree.column(key, width=width, anchor="e")
        svsb = ttk.Scrollbar(tab_steps, orient="vertical", command=self.steps_tree.yview)
        shsb = ttk.Scrollbar(tab_steps, orient="horizontal", command=self.steps_tree.xview)
        self.steps_tree.configure(yscrollcommand=svsb.set, xscrollcommand=shsb.set)
        self.steps_tree.grid(row=0, column=0, sticky="nsew")
        svsb.grid(row=0, column=1, sticky="ns")
        shsb.grid(row=1, column=0, sticky="ew")
        tab_steps.rowconfigure(0, weight=1)
        tab_steps.columnconfigure(0, weight=1)

        # Tab 2: Matplotlib Time-Series Chart
        self.fig = Figure(figsize=(5.6, 2.5), dpi=96, facecolor=THEME["bg_card"])
        self.ax_vol = self.fig.add_subplot(111)
        self.chart_canvas = FigureCanvasTkAgg(self.fig, master=tab_chart)
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True)
        self._draw_empty_chart()

        # Tab 3: Grid Cell Final Results Treeview
        cell_cols = ("code", "lu", "elev", "elev_src", "infil_r", "final_d", "max_d", "vol", "infil_v", "drain_v")
        self.cells_tree = ttk.Treeview(tab_cells, columns=cell_cols, show="headings", height=12)
        cell_headers = [
            ("code", "Cell", 54, "w"),
            ("lu", "Land Use", 95, "w"),
            ("elev", "Elev (m)", 68, "e"),
            ("elev_src", "Terrain Source", 145, "w"),
            ("infil_r", "Infil (mm/h)", 82, "e"),
            ("final_d", "Final D (m)", 78, "e"),
            ("max_d", "Max D (m)", 74, "e"),
            ("vol", "Rem Vol (m³)", 88, "e"),
            ("infil_v", "Infil (m³)", 78, "e"),
            ("drain_v", "Drain (m³)", 78, "e"),
        ]
        for key, label, width, anc in cell_headers:
            self.cells_tree.heading(key, text=label)
            self.cells_tree.column(key, width=width, anchor=anc)
        cvsb = ttk.Scrollbar(tab_cells, orient="vertical", command=self.cells_tree.yview)
        chsb = ttk.Scrollbar(tab_cells, orient="horizontal", command=self.cells_tree.xview)
        self.cells_tree.configure(yscrollcommand=cvsb.set, xscrollcommand=chsb.set)
        self.cells_tree.grid(row=0, column=0, sticky="nsew")
        cvsb.grid(row=0, column=1, sticky="ns")
        chsb.grid(row=1, column=0, sticky="ew")
        tab_cells.rowconfigure(0, weight=1)
        tab_cells.columnconfigure(0, weight=1)

        # Tab 4: Saved Runs (SQLite)
        runs_top = tk.Frame(tab_runs, bg=THEME["bg_card"])
        runs_top.pack(fill="x", pady=(0, 6))
        ttk.Button(
            runs_top,
            text="Load Selected Run",
            style="Accent.TButton",
            command=self._handle_load_run_clicked,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            runs_top,
            text="Delete Selected",
            style="Danger.TButton",
            command=self._handle_delete_run_clicked,
        ).pack(side="left")

        runs_wrap = tk.Frame(tab_runs, bg=THEME["bg_card"])
        runs_wrap.pack(fill="both", expand=True)
        run_cols = ("id", "scenario", "rain", "dur", "dt", "mode", "status", "completed")
        self.runs_tree = ttk.Treeview(runs_wrap, columns=run_cols, show="headings", height=10)
        run_headers = [
            ("id", "Run #", 50, "e"),
            ("scenario", "Scenario Name", 210, "w"),
            ("rain", "mm/hr", 65, "e"),
            ("dur", "Min", 55, "e"),
            ("dt", "Step", 55, "e"),
            ("mode", "Terrain Mode", 135, "w"),
            ("status", "Status", 95, "w"),
            ("completed", "Completed (UTC)", 145, "w"),
        ]
        for key, label, width, anc in run_headers:
            self.runs_tree.heading(key, text=label)
            self.runs_tree.column(key, width=width, anchor=anc)
        rvsb = ttk.Scrollbar(runs_wrap, orient="vertical", command=self.runs_tree.yview)
        self.runs_tree.configure(yscrollcommand=rvsb.set)
        self.runs_tree.pack(side="left", fill="both", expand=True)
        rvsb.pack(side="right", fill="y")

    # -------------------------------------------------------------------------
    # Public Workspace Refresh & Live Progress Hooks
    # -------------------------------------------------------------------------

    def refresh_workspace(
        self,
        neighbourhood: Neighbourhood | None,
        cells: list[GridCell],
        drainage_features: list[DrainageFeature],
        saved_runs: list[SimulationRunRecord],
    ) -> None:
        self._neighbourhood = neighbourhood
        self._cells = cells
        self._drainage_features = drainage_features
        self._saved_runs = saved_runs
        self._disabled_drain_ids = {
            did for did in self._disabled_drain_ids if any(d.id == did for d in drainage_features)
        }

        if neighbourhood is None:
            self.ws_subtitle_lbl.configure(
                text="No workspace active. Open Advanced Map Editor to create or load POTHERI."
            )
            self.elev_status_lbl.configure(text="Grid elevation coverage: 0 / 0 cells", fg=THEME["warning"])
        else:
            elev_ok = sum(
                1 for c in cells if (c.mean_elevation_m is not None or c.elevation_m is not None)
            )
            self.ws_subtitle_lbl.configure(
                text=(
                    f"Workspace: {neighbourhood.name} ({neighbourhood.grid_rows}×{neighbourhood.grid_cols}, "
                    f"{len(cells)} cells, {len(drainage_features)} drainage features)"
                )
            )
            if elev_ok == len(cells) and cells:
                self.elev_status_lbl.configure(
                    text=f"Grid elevation coverage: {elev_ok}/{len(cells)} cells populated (Elevation-based mode ready).",
                    fg=THEME["success"],
                )
            else:
                self.elev_status_lbl.configure(
                    text=(
                        f"Grid elevation coverage: {elev_ok}/{len(cells)} cells populated. "
                        "Use 'Illustrative Assumed Terrain' mode unless all cells have elevation."
                    ),
                    fg=THEME["warning"],
                )

        self._refresh_drain_listbox()
        self._refresh_saved_runs_tree()

    def set_running_state(self, running: bool, paused: bool = False) -> None:
        self._is_running = running
        self.start_btn.configure(state="disabled" if running else "normal")
        if running:
            self.pause_btn.configure(state="normal", text="Resume" if paused else "Pause")
        else:
            self.pause_btn.configure(state="disabled", text="Pause")

    def on_step_progress(self, step_idx: int, total_steps: int, step: SimulationStepRecord) -> None:
        pct = (step_idx / max(1, total_steps)) * 100.0
        self.sim_progress.configure(value=pct)
        self.sim_status_lbl.configure(
            text=f"Status: Running hypothetical simulation (Step {step_idx}/{total_steps})...",
            fg=THEME["accent_hover"],
        )
        self.sim_clock_lbl.configure(
            text=f"Step {step_idx} / {total_steps}  •  t = {step.sim_time_minutes:.1f} min"
        )

    def display_output(self, output: SimulationOutput | None) -> None:
        self._current_output = output
        if output is None:
            self.reset_display()
            return
        s = output.summary
        self.sim_progress.configure(value=100.0)
        self.sim_status_lbl.configure(
            text=f"Status: Completed — '{output.run.scenario_name}' (Saved Run #{output.run.id or 'mem'})",
            fg=THEME["success"] if s.mass_balance_passed else THEME["warning"],
        )
        self.sim_clock_lbl.configure(
            text=f"Step {s.total_steps} / {s.total_steps}  •  t = {output.config.rainfall_duration_min:.1f} min"
        )

        notes_text = " | ".join(output.warnings) if output.warnings else "No model warnings."
        self.sim_notes_lbl.configure(
            text=notes_text,
            fg=THEME["warning"] if output.warnings else THEME["text_secondary"],
        )

        # Update KPI Cards
        self.kpi_max_depth.update_card(
            f"{s.max_water_depth_m:.4f} m",
            f"Peak occurred at t = {s.time_of_max_depth_minutes:.1f} min",
            THEME["info"],
        )
        self.kpi_avg_depth.update_card(
            f"{s.avg_water_depth_m:.4f} m",
            "Final grid mean depth",
            THEME["accent"],
        )
        self.kpi_rain_vol.update_card(
            f"{s.total_rainfall_volume_m3:,.1f} m³",
            f"Initial water: {s.initial_water_volume_m3:,.1f} m³",
            THEME["accent_teal"],
        )
        self.kpi_infil_vol.update_card(
            f"{s.total_infiltration_volume_m3:,.1f} m³",
            "Illustrative unless cell rates measured",
            THEME["success"],
        )
        self.kpi_drain_vol.update_card(
            f"{s.total_drainage_volume_m3:,.1f} m³",
            f"Final surface vol: {s.final_surface_volume_m3:,.1f} m³",
            "#38BDF8",
        )
        self.kpi_affected.update_card(
            f"{s.max_affected_cells} cells",
            f"{s.total_affected_area_m2 / 10000.0:.2f} ha ({s.total_affected_area_m2:,.0f} m²)",
            THEME["warning"],
        )
        self.kpi_transfer.update_card(
            f"{s.total_transferred_volume_m3:,.1f} m³",
            "Conservative cell-to-cell transfers",
            THEME["text_secondary"],
        )
        mb_color = THEME["success"] if s.mass_balance_passed else THEME["error"]
        mb_label = "PASS" if s.mass_balance_passed else "FAIL"
        self.kpi_mass.update_card(
            mb_label,
            f"Err: {s.mass_balance_error_m3:.3e} m³ (tol {s.mass_balance_tolerance_m3:.1e})",
            mb_color,
        )

        # Populate Step Progression Table
        for item in self.steps_tree.get_children():
            self.steps_tree.delete(item)
        for st in output.steps:
            self.steps_tree.insert(
                "",
                "end",
                values=(
                    st.timestep,
                    f"{st.sim_time_minutes:.1f}",
                    f"{st.rainfall_intensity_mm_hr:.2f}",
                    f"{st.rainfall_input_m3:,.2f}",
                    f"{st.infiltration_loss_m3:,.2f}",
                    f"{st.drainage_loss_m3:,.2f}",
                    f"{st.water_transferred_m3:,.2f}",
                    f"{st.total_volume_remaining_m3:,.2f}",
                    f"{st.max_water_depth_m:.4f}",
                    st.affected_cell_count,
                    f"{st.total_area_affected_m2:,.0f}",
                    f"{st.mass_balance_error_m3:.2e}",
                ),
            )

        # Populate Cell Final Results Table
        for item in self.cells_tree.get_children():
            self.cells_tree.delete(item)
        for fc in output.final_cells:
            self.cells_tree.insert(
                "",
                "end",
                values=(
                    fc.cell_code,
                    fc.land_use,
                    f"{fc.elevation_m:.2f}",
                    fc.elevation_provenance,
                    f"{fc.infiltration_rate_mm_hr:.1f}",
                    f"{fc.final_water_depth_m:.4f}",
                    f"{fc.max_water_depth_m:.4f}",
                    f"{fc.final_water_volume_m3:,.2f}",
                    f"{fc.total_infiltration_m3:,.2f}",
                    f"{fc.total_drainage_m3:,.2f}",
                ),
            )

        self._draw_hydrograph_chart(output)

    def reset_display(self) -> None:
        self._current_output = None
        self.sim_progress.configure(value=0.0)
        self.sim_status_lbl.configure(
            text="Status: Reset — Ready for hypothetical simulation",
            fg=THEME["text_primary"],
        )
        self.sim_clock_lbl.configure(text="Step 0 / 0  •  t = 0.0 min")
        self.sim_notes_lbl.configure(text="No active warnings.", fg=THEME["text_muted"])
        for card in (
            self.kpi_max_depth,
            self.kpi_avg_depth,
            self.kpi_rain_vol,
            self.kpi_infil_vol,
            self.kpi_drain_vol,
            self.kpi_affected,
            self.kpi_transfer,
            self.kpi_mass,
        ):
            card.update_card("—", "")
        for tree in (self.steps_tree, self.cells_tree):
            for item in tree.get_children():
                tree.delete(item)
        self._draw_empty_chart()

    # -------------------------------------------------------------------------
    # Internal Handlers & Helpers
    # -------------------------------------------------------------------------

    def _on_preset_selected(self, _evt=None) -> None:
        preset = self.preset_var.get()
        val = RAINFALL_PRESETS.get(preset)
        if val is not None:
            self.intensity_var.set(f"{val:.1f}")
            self.scenario_name_var.set(f"[Hypothetical] {preset}")

    def _toggle_custom_entry(self) -> None:
        state = "normal" if self.dist_var.get() == "custom" else "disabled"
        self.custom_rain_entry.configure(state=state)

    def _toggle_illustrative_fields(self) -> None:
        mode = self._MODE_LABEL_TO_KEY.get(self.mode_var.get(), SIMULATION_MODE_ILLUSTRATIVE)
        state = "normal" if mode == SIMULATION_MODE_ILLUSTRATIVE else "disabled"
        for entry in (self.ill_base_entry, self.ill_ns_entry, self.ill_we_entry):
            entry.configure(state=state)

    def _refresh_drain_listbox(self) -> None:
        self.drain_listbox.delete(0, "end")
        if not self._drainage_features:
            self.drain_listbox.insert("end", "(No Phase 2 drainage elements entered yet)")
            return
        for d in self._drainage_features:
            did = d.id or 0
            state_tag = "[DISABLED What-If]" if did in self._disabled_drain_ids else "[ACTIVE]"
            cap_str = f"{d.capacity} {d.capacity_unit}" if d.capacity is not None else "Unknown cap"
            self.drain_listbox.insert("end", f"{state_tag} #{did} {d.name} ({d.feature_type}, {cap_str}, {d.status})")

    def _refresh_saved_runs_tree(self) -> None:
        for item in self.runs_tree.get_children():
            self.runs_tree.delete(item)
        for r in self._saved_runs:
            mode_short = "Elevation" if r.simulation_mode == SIMULATION_MODE_ELEVATION else "Illustrative"
            self.runs_tree.insert(
                "",
                "end",
                iid=str(r.id),
                values=(
                    r.id,
                    r.scenario_name,
                    f"{r.rainfall_intensity:.1f}",
                    f"{r.rainfall_duration:.0f}",
                    f"{r.time_step:.1f}",
                    mode_short,
                    r.status,
                    r.completion_time or r.start_time,
                ),
            )

    def _on_toggle_drain_disabled(self, _evt=None) -> None:
        sel = self.drain_listbox.curselection()
        if not sel or not self._drainage_features:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self._drainage_features):
            did = self._drainage_features[idx].id
            if did is not None:
                if did in self._disabled_drain_ids:
                    self._disabled_drain_ids.remove(did)
                else:
                    self._disabled_drain_ids.add(did)
                self._refresh_drain_listbox()

    def build_config_from_inputs(self) -> SimulationConfig:
        try:
            intensity = float(self.intensity_var.get().strip())
            duration = float(self.duration_var.get().strip())
            dt_min = float(self.timestep_var.get().strip())
            init_d = float(self.init_depth_var.get().strip())
            rain_scale = float(self.rain_scale_var.get().strip())
            drain_scale = float(self.drain_scale_var.get().strip())
            ill_base = float(self.ill_base_var.get().strip())
            ill_ns = float(self.ill_ns_var.get().strip())
            ill_we = float(self.ill_we_var.get().strip())
        except ValueError as exc:
            raise ValueError("Numeric simulation inputs must be valid numbers.") from exc

        infil_rates: dict[str, float] = {}
        for cat, var in self._infil_vars.items():
            try:
                infil_rates[cat] = float(var.get().strip())
            except ValueError as exc:
                raise ValueError(f"Invalid infiltration rate for '{cat}'.") from exc

        custom_vals: list[float] = []
        if self.dist_var.get() == "custom":
            raw_tokens = [t.strip() for t in self.custom_rain_var.get().split(",") if t.strip()]
            try:
                custom_vals = [float(t) for t in raw_tokens]
            except ValueError as exc:
                raise ValueError("Custom rainfall values must be comma-separated numbers.") from exc

        mode_key = self._MODE_LABEL_TO_KEY.get(self.mode_var.get(), SIMULATION_MODE_ILLUSTRATIVE)

        return SimulationConfig(
            scenario_name=self.scenario_name_var.get().strip(),
            rainfall_intensity_mm_hr=intensity,
            rainfall_duration_min=duration,
            time_step_min=dt_min,
            distribution_pattern=self.dist_var.get(),
            custom_intensities_mm_hr=custom_vals,
            initial_water_depth_m=init_d,
            simulation_mode=mode_key,
            illustrative_base_elevation_m=ill_base,
            illustrative_north_south_slope_m=ill_ns,
            illustrative_west_east_slope_m=ill_we,
            category_infiltration_rates_mm_hr=infil_rates,
            use_cell_infiltration_if_present=bool(self.use_cell_infil_var.get()),
            include_drainage_features=bool(self.include_drain_var.get()),
            include_cell_drainage_capacity=bool(self.include_drain_var.get()),
            rainfall_scale_factor=rain_scale,
            drainage_capacity_scale=drain_scale,
            disabled_drainage_ids=set(self._disabled_drain_ids),
            mass_balance_tolerance_m3=DEFAULT_MASS_BALANCE_TOLERANCE_M3,
        )

    def _handle_start_clicked(self) -> None:
        if self._neighbourhood is None:
            messagebox.showwarning("No Workspace", "Create or load a neighbourhood workspace first.")
            return
        try:
            cfg = self.build_config_from_inputs()
        except ValueError as exc:
            messagebox.showerror("Invalid Simulation Input", str(exc))
            return
        self.on_start_simulation(cfg)

    def _handle_pause_clicked(self) -> None:
        paused = self.on_toggle_pause()
        self.pause_btn.configure(text="Resume" if paused else "Pause")
        if paused:
            self.sim_status_lbl.configure(text="Status: Paused (click Resume or Reset)", fg=THEME["warning"])

    def _handle_reset_clicked(self) -> None:
        self.on_reset_simulation()
        self.reset_display()

    def _handle_load_run_clicked(self) -> None:
        sel = self.runs_tree.selection()
        if not sel:
            messagebox.showinfo("Select Run", "Select a saved simulation run from the table first.")
            return
        self.on_load_saved_run(int(sel[0]))

    def _handle_delete_run_clicked(self) -> None:
        sel = self.runs_tree.selection()
        if not sel:
            return
        run_id = int(sel[0])
        if messagebox.askyesno("Delete Run", f"Delete saved simulation run #{run_id}?"):
            self.on_delete_saved_run(run_id)

    def _draw_empty_chart(self) -> None:
        self.ax_vol.clear()
        self.ax_vol.set_facecolor(THEME["bg_input"])
        self.ax_vol.set_title(
            "Simulated Water-Balance Progression (Run a Scenario to Plot)",
            color=THEME["text_secondary"],
            fontsize=9,
        )
        self.ax_vol.tick_params(colors=THEME["text_muted"], labelsize=8)
        for spine in self.ax_vol.spines.values():
            spine.set_color(THEME["border"])
        self.fig.tight_layout()
        self.chart_canvas.draw_idle()

    def _draw_hydrograph_chart(self, output: SimulationOutput) -> None:
        self.ax_vol.clear()
        self.ax_vol.set_facecolor(THEME["bg_input"])
        if not output.steps:
            self._draw_empty_chart()
            return

        times = [s.sim_time_minutes for s in output.steps]
        rem_vols = [s.total_volume_remaining_m3 for s in output.steps]
        step_rain = [s.rainfall_input_m3 for s in output.steps]
        step_infil = [s.infiltration_loss_m3 for s in output.steps]
        step_drain = [s.drainage_loss_m3 for s in output.steps]

        self.ax_vol.plot(times, rem_vols, color="#38BDF8", linewidth=2.0, label="Remaining Surface Water (m³)")
        self.ax_vol.plot(times, step_rain, color="#22D3EE", linestyle="--", linewidth=1.4, label="Step Rainfall (m³)")
        self.ax_vol.plot(times, step_infil, color="#10B981", linewidth=1.4, label="Step Infiltration (m³)")
        self.ax_vol.plot(times, step_drain, color="#F59E0B", linewidth=1.4, label="Step Drainage (m³)")

        self.ax_vol.set_title(
            f"Simulated Water-Balance Hydrograph — {output.run.scenario_name}",
            color=THEME["text_primary"],
            fontsize=9,
            fontweight="bold",
        )
        self.ax_vol.set_xlabel("Simulation Time (minutes)", color=THEME["text_secondary"], fontsize=8)
        self.ax_vol.set_ylabel("Volume (m³)", color=THEME["text_secondary"], fontsize=8)
        self.ax_vol.tick_params(colors=THEME["text_muted"], labelsize=8)
        self.ax_vol.grid(True, color=THEME["border"], linestyle=":", alpha=0.5)
        for spine in self.ax_vol.spines.values():
            spine.set_color(THEME["border"])
        leg = self.ax_vol.legend(facecolor=THEME["bg_card"], edgecolor=THEME["border"], fontsize=7)
        for txt in leg.get_texts():
            txt.set_color(THEME["text_secondary"])
        self.fig.tight_layout()
        self.chart_canvas.draw_idle()
