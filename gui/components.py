"""Shared Tkinter styling, reusable dashboard cards, placeholders, and settings UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from config import (
    APP_NAME,
    APP_VERSION,
    BACKUPS_DIR,
    DB_PATH,
    DEFAULT_RISK_THRESHOLDS_CM,
    DEFAULT_ROAD_EXPOSURE_THRESHOLDS_CM,
    DEFAULT_SPEED_ASSUMPTIONS_KMH,
    EXPORTS_DIR,
    NOMINATIM_URL,
    OPEN_METEO_URL,
    OVERPASS_URLS,
    SCHEMA_VERSION,
    SIMULATION_MODE_ELEVATION,
    SIMULATION_MODE_ILLUSTRATIVE,
    THEME,
)


def configure_styles(root: tk.Misc) -> ttk.Style:
    """Configure a modern dark-navy & cyan/teal ttk theme based on 'clam'."""
    style = ttk.Style(root)
    style.theme_use("clam")

    root.configure(bg=THEME["bg_root"])

    style.configure(
        ".",
        background=THEME["bg_surface"],
        foreground=THEME["text_primary"],
        fieldbackground=THEME["bg_input"],
        bordercolor=THEME["border"],
        darkcolor=THEME["bg_root"],
        lightcolor=THEME["bg_card"],
        troughcolor=THEME["bg_root"],
        focuscolor=THEME["accent"],
        font=("Segoe UI", 10),
    )

    style.configure("Root.TFrame", background=THEME["bg_root"])
    style.configure("Surface.TFrame", background=THEME["bg_surface"])
    style.configure("Sidebar.TFrame", background=THEME["bg_sidebar"])
    style.configure("Header.TFrame", background=THEME["bg_header"])
    style.configure(
        "Card.TFrame",
        background=THEME["bg_card"],
        borderwidth=1,
        relief="solid",
    )

    style.configure("TLabel", background=THEME["bg_surface"], foreground=THEME["text_primary"])
    style.configure("Root.TLabel", background=THEME["bg_root"], foreground=THEME["text_primary"])
    style.configure("Header.TLabel", background=THEME["bg_header"], foreground=THEME["text_primary"])
    style.configure("HeaderMuted.TLabel", background=THEME["bg_header"], foreground=THEME["text_muted"])
    style.configure("Card.TLabel", background=THEME["bg_card"], foreground=THEME["text_primary"])
    style.configure("CardMuted.TLabel", background=THEME["bg_card"], foreground=THEME["text_muted"])
    style.configure(
        "CardTitle.TLabel",
        background=THEME["bg_card"],
        foreground=THEME["text_muted"],
        font=("Segoe UI", 9, "bold"),
    )
    style.configure(
        "CardValue.TLabel",
        background=THEME["bg_card"],
        foreground=THEME["text_primary"],
        font=("Segoe UI", 16, "bold"),
    )
    style.configure(
        "PageTitle.TLabel",
        background=THEME["bg_root"],
        foreground=THEME["text_primary"],
        font=("Segoe UI", 17, "bold"),
    )
    style.configure(
        "PageSubtitle.TLabel",
        background=THEME["bg_root"],
        foreground=THEME["text_muted"],
        font=("Segoe UI", 10),
    )

    # Buttons
    style.configure(
        "TButton",
        background=THEME["bg_card_alt"],
        foreground=THEME["text_primary"],
        bordercolor=THEME["border_strong"],
        padding=(12, 6),
        font=("Segoe UI", 9, "bold"),
    )
    style.map(
        "TButton",
        background=[("active", THEME["bg_hover"]), ("disabled", THEME["bg_surface"])],
        foreground=[("disabled", THEME["text_muted"])],
    )

    style.configure(
        "Accent.TButton",
        background=THEME["accent"],
        foreground="#042F2E",
        bordercolor=THEME["accent_hover"],
        padding=(14, 7),
        font=("Segoe UI", 9, "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[("active", THEME["accent_hover"]), ("disabled", THEME["bg_hover"])],
        foreground=[("disabled", THEME["text_muted"])],
    )

    style.configure(
        "Danger.TButton",
        background="#7F1D1D",
        foreground="#FEE2E2",
        bordercolor="#EF4444",
        padding=(10, 6),
        font=("Segoe UI", 9, "bold"),
    )
    style.map(
        "Danger.TButton",
        background=[("active", "#991B1B"), ("disabled", THEME["bg_surface"])],
    )

    # Entries & Comboboxes
    style.configure(
        "TEntry",
        fieldbackground=THEME["bg_input"],
        foreground=THEME["text_primary"],
        insertcolor=THEME["text_primary"],
        bordercolor=THEME["border_strong"],
        padding=6,
    )
    style.configure(
        "TCombobox",
        fieldbackground=THEME["bg_input"],
        background=THEME["bg_card_alt"],
        foreground=THEME["text_primary"],
        arrowcolor=THEME["accent"],
        bordercolor=THEME["border_strong"],
        padding=5,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", THEME["bg_input"])],
        foreground=[("readonly", THEME["text_primary"])],
        selectbackground=[("readonly", THEME["accent_muted"])],
    )

    # Checkbuttons
    style.configure(
        "TCheckbutton",
        background=THEME["bg_surface"],
        foreground=THEME["text_secondary"],
        indicatorcolor=THEME["bg_input"],
    )
    style.map(
        "TCheckbutton",
        background=[("active", THEME["bg_surface"])],
        indicatorcolor=[("selected", THEME["accent"])],
    )

    # Treeview
    style.configure(
        "Treeview",
        background=THEME["bg_input"],
        fieldbackground=THEME["bg_input"],
        foreground=THEME["text_primary"],
        bordercolor=THEME["border"],
        rowheight=26,
        font=("Segoe UI", 9),
    )
    style.configure(
        "Treeview.Heading",
        background=THEME["bg_card"],
        foreground=THEME["accent_hover"],
        bordercolor=THEME["border"],
        font=("Segoe UI", 9, "bold"),
        padding=6,
    )
    style.map(
        "Treeview",
        background=[("selected", THEME["accent_muted"])],
        foreground=[("selected", THEME["text_primary"])],
    )

    # Scrollbars
    style.configure(
        "Vertical.TScrollbar",
        background=THEME["bg_card"],
        troughcolor=THEME["bg_root"],
        bordercolor=THEME["border"],
        arrowcolor=THEME["text_muted"],
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=THEME["bg_card"],
        troughcolor=THEME["bg_root"],
        bordercolor=THEME["border"],
        arrowcolor=THEME["text_muted"],
    )

    # Notebook Tabs
    style.configure(
        "TNotebook",
        background=THEME["bg_root"],
        bordercolor=THEME["border"],
        tabmargins=(2, 4, 2, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background=THEME["bg_card"],
        foreground=THEME["text_secondary"],
        bordercolor=THEME["border"],
        padding=(10, 5),
        font=("Segoe UI", 9, "bold"),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", THEME["accent_muted"]), ("active", THEME["bg_hover"])],
        foreground=[("selected", THEME["accent_hover"]), ("active", THEME["text_primary"])],
    )

    return style


class StatCard(tk.Frame):
    """Dashboard metric card with accent bar, title, primary value, and subtitle."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        value: str = "—",
        subtitle: str = "",
        accent_color: str = THEME["accent"],
    ) -> None:
        super().__init__(
            parent,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            bd=0,
        )
        self.accent_strip = tk.Frame(self, bg=accent_color, height=3)
        self.accent_strip.pack(fill="x", side="top")

        body = tk.Frame(self, bg=THEME["bg_card"], padx=14, pady=10)
        body.pack(fill="both", expand=True)

        self.title_lbl = tk.Label(
            body,
            text=title.upper(),
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        self.title_lbl.pack(fill="x")

        self.value_lbl = tk.Label(
            body,
            text=value,
            bg=THEME["bg_card"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 15, "bold"),
            anchor="w",
            wraplength=230,
            justify="left",
        )
        self.value_lbl.pack(fill="x", pady=(4, 2))

        self.subtitle_lbl = tk.Label(
            body,
            text=subtitle,
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 8),
            anchor="w",
            wraplength=170,
            justify="left",
        )
        self.subtitle_lbl.pack(fill="x")
        body.bind(
            "<Configure>",
            lambda e: self._update_wrap(max(100, e.width - 28)),
        )

    def _update_wrap(self, wrap_px: int) -> None:
        self.value_lbl.configure(wraplength=wrap_px)
        self.subtitle_lbl.configure(wraplength=wrap_px)

    def update_card(
        self,
        value: str,
        subtitle: str = "",
        accent_color: str | None = None,
    ) -> None:
        self.value_lbl.configure(text=value)
        self.subtitle_lbl.configure(text=subtitle)
        if accent_color:
            self.accent_strip.configure(bg=accent_color)


class PlaceholderModuleView(tk.Frame):
    """Clean Phase 2+ placeholder view with clear roadmap scope and no fake metrics."""

    def __init__(
        self,
        parent: tk.Misc,
        module_title: str,
        tagline: str,
        planned_capabilities: list[str],
        phase1_dependencies: str,
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=28, pady=24)

        badge = tk.Label(
            self,
            text="COMING SOON — PLANNED FOR PHASE 2+",
            bg=THEME["info_bg"],
            fg=THEME["info"],
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=4,
        )
        badge.pack(anchor="w")

        tk.Label(
            self,
            text=module_title,
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w", pady=(12, 4))

        tk.Label(
            self,
            text=tagline,
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 11),
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(0, 18))

        card = tk.Frame(
            self,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=20,
            pady=18,
        )
        card.pack(fill="x", pady=(0, 16))

        tk.Label(
            card,
            text="Planned Capabilities (Not Yet Implemented in Phase 1)",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 10))

        for item in planned_capabilities:
            tk.Label(
                card,
                text=f"•  {item}",
                bg=THEME["bg_card"],
                fg=THEME["text_secondary"],
                font=("Segoe UI", 10),
                anchor="w",
                wraplength=740,
                justify="left",
            ).pack(anchor="w", pady=3)

        dep_card = tk.Frame(
            self,
            bg=THEME["bg_card_alt"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=20,
            pady=14,
        )
        dep_card.pack(fill="x")

        tk.Label(
            dep_card,
            text="How Phase 1 Prepares This Module",
            bg=THEME["bg_card_alt"],
            fg=THEME["accent_teal"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        tk.Label(
            dep_card,
            text=phase1_dependencies,
            bg=THEME["bg_card_alt"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 9),
            wraplength=740,
            justify="left",
        ).pack(anchor="w")

        tk.Label(
            self,
            text=(
                "Note: CHENNAI FLOODGUARD is an educational and experimental decision-support prototype. "
                "No simulated flood depths or operational forecasts are generated in Phase 1."
            ),
            bg=THEME["bg_root"],
            fg=THEME["warning"],
            font=("Segoe UI", 9, "italic"),
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(18, 0))


class SettingsView(tk.Frame):
    """Phase 7 Application Settings, Preferences, Offline Mode & SQLite Backup/Restore."""

    def __init__(
        self,
        parent: tk.Misc,
        on_toggle_offline_mode: Callable[[bool], None],
        on_test_connectivity: Callable[[], None],
        on_clear_cache: Callable[[], int],
        on_select_neighbourhood: Callable[[int], None],
        on_save_preferences: Callable[[dict[str, str]], None] | None = None,
        get_db_manager: Callable[[], object] | None = None,
        on_database_restored: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=18, pady=14)
        self.on_toggle_offline_mode = on_toggle_offline_mode
        self.on_test_connectivity = on_test_connectivity
        self.on_clear_cache = on_clear_cache
        self.on_select_neighbourhood = on_select_neighbourhood
        self.on_save_preferences = on_save_preferences
        self.get_db_manager = get_db_manager
        self.on_database_restored = on_database_restored

        tk.Label(
            self,
            text="Application Settings, Preferences & Database Maintenance",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            self,
            text="Configure offline controls, simulation/risk/routing defaults, export & backup paths, and SQLite backup/restore.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 10))

        # Scrollable container for clean fit at 760–900px heights
        outer = tk.Frame(self, bg=THEME["bg_root"])
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=THEME["bg_root"], highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=THEME["bg_root"])
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # 1. Network & Offline Mode + Workspaces
        conn_card = self._make_card(body, "Network, Weather Feed & Offline Mode")
        self.offline_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            conn_card,
            text="Force OFFLINE Mode (disable external API calls and run strictly on SQLite + cache)",
            variable=self.offline_var,
            command=self._handle_offline_toggle,
        ).pack(anchor="w", pady=(0, 8))

        api_row = tk.Frame(conn_card, bg=THEME["bg_card"])
        api_row.pack(fill="x", pady=(0, 8))
        tk.Label(api_row, text="Weather API Endpoint (no key needed):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).pack(side="left", padx=(0, 6))
        self.var_weather_url = tk.StringVar(value=OPEN_METEO_URL)
        ttk.Entry(api_row, textvariable=self.var_weather_url, width=42).pack(side="left", fill="x", expand=True)

        btn_row = tk.Frame(conn_card, bg=THEME["bg_card"])
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Check Internet Connectivity", command=self.on_test_connectivity).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Clear Local JSON Cache", command=self._handle_clear_cache).pack(side="left")

        self.conn_status_lbl = tk.Label(conn_card, text="", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9))
        self.conn_status_lbl.pack(anchor="w", pady=(6, 0))

        ws_card = self._make_card(body, "Default & Active Neighbourhood Workspace (SQLite)")
        ws_row = tk.Frame(ws_card, bg=THEME["bg_card"])
        ws_row.pack(fill="x")
        self.ws_combo_var = tk.StringVar()
        self.ws_combo = ttk.Combobox(ws_row, textvariable=self.ws_combo_var, state="readonly", width=42)
        self.ws_combo.pack(side="left", padx=(0, 8))
        self._ws_map: dict[str, int] = {}
        ttk.Button(ws_row, text="Load Selected Workspace", style="Accent.TButton", command=self._handle_load_workspace).pack(side="left")

        # 2. Simulation, Risk, Road Exposure, Travel Speed & Theme Preferences
        pref_card = self._make_card(body, "Simulation, Risk Thresholds, Routing Speeds, Paths & Display Preferences")
        pgrid = tk.Frame(pref_card, bg=THEME["bg_card"])
        pgrid.pack(fill="x", pady=(0, 8))
        for c in range(4):
            pgrid.columnconfigure(c, weight=1)

        self.var_def_rain = tk.StringVar(value="30")
        self.var_def_dur = tk.StringVar(value="60")
        self.var_def_step = tk.StringVar(value="5")
        self.var_def_mode = tk.StringVar(value=SIMULATION_MODE_ELEVATION)
        self._grid_field(pgrid, 0, 0, "Default Rain (mm/hr):", self.var_def_rain)
        self._grid_field(pgrid, 0, 1, "Default Duration (min):", self.var_def_dur)
        self._grid_field(pgrid, 0, 2, "Default Step (min):", self.var_def_step)
        tk.Label(pgrid, text="Default Sim Mode:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Combobox(pgrid, textvariable=self.var_def_mode, values=[SIMULATION_MODE_ELEVATION, SIMULATION_MODE_ILLUSTRATIVE], state="readonly").grid(row=1, column=3, sticky="ew", padx=4, pady=(0, 6))

        self.var_risk_low = tk.StringVar(value=str(DEFAULT_RISK_THRESHOLDS_CM["low_max_cm"]))
        self.var_risk_mod = tk.StringVar(value=str(DEFAULT_RISK_THRESHOLDS_CM["moderate_max_cm"]))
        self.var_risk_high = tk.StringVar(value=str(DEFAULT_RISK_THRESHOLDS_CM["high_max_cm"]))
        self.var_theme = tk.StringVar(value="Dark Navy & Teal")
        self._grid_field(pgrid, 2, 0, "Risk Low Max (cm):", self.var_risk_low)
        self._grid_field(pgrid, 2, 1, "Risk Mod Max (cm):", self.var_risk_mod)
        self._grid_field(pgrid, 2, 2, "Risk High Max (cm):", self.var_risk_high)
        tk.Label(pgrid, text="UI Theme Variant:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(row=2, column=3, sticky="w", padx=4)
        ttk.Combobox(pgrid, textvariable=self.var_theme, values=["Dark Navy & Teal", "High-Contrast Midnight"], state="readonly").grid(row=3, column=3, sticky="ew", padx=4, pady=(0, 6))

        self.var_road_low = tk.StringVar(value=str(DEFAULT_ROAD_EXPOSURE_THRESHOLDS_CM["low_max_cm"]))
        self.var_road_mod = tk.StringVar(value=str(DEFAULT_ROAD_EXPOSURE_THRESHOLDS_CM["moderate_max_cm"]))
        self.var_road_high = tk.StringVar(value=str(DEFAULT_ROAD_EXPOSURE_THRESHOLDS_CM["high_max_cm"]))
        self.var_map_grid_default = tk.BooleanVar(value=True)
        self._grid_field(pgrid, 4, 0, "Road Exp Low (cm):", self.var_road_low)
        self._grid_field(pgrid, 4, 1, "Road Exp Mod (cm):", self.var_road_mod)
        self._grid_field(pgrid, 4, 2, "Road Exp High (cm):", self.var_road_high)
        ttk.Checkbutton(pgrid, text="Show Grid Overlay", variable=self.var_map_grid_default).grid(row=5, column=3, sticky="w", padx=4)

        self.var_spd_walk = tk.StringVar(value=str(DEFAULT_SPEED_ASSUMPTIONS_KMH["Walking"]["Residential"]))
        self.var_spd_car = tk.StringVar(value=str(DEFAULT_SPEED_ASSUMPTIONS_KMH["Two-wheeler/Car"]["Residential"]))
        self.var_spd_emerg = tk.StringVar(value="35.0")
        self._grid_field(pgrid, 6, 0, "Walk Speed (km/h):", self.var_spd_walk)
        self._grid_field(pgrid, 6, 1, "Car Speed (km/h):", self.var_spd_car)
        self._grid_field(pgrid, 6, 2, "Emergency Speed (km/h):", self.var_spd_emerg)

        dir_grid = tk.Frame(pref_card, bg=THEME["bg_card"])
        dir_grid.pack(fill="x", pady=(4, 8))
        dir_grid.columnconfigure(1, weight=1)
        self.var_exports_dir = tk.StringVar(value=str(EXPORTS_DIR))
        self.var_backups_dir = tk.StringVar(value=str(BACKUPS_DIR))
        tk.Label(dir_grid, text="Export Directory:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(dir_grid, textvariable=self.var_exports_dir).grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=2)
        ttk.Button(dir_grid, text="Browse", command=lambda: self._browse_dir(self.var_exports_dir)).grid(row=0, column=2, pady=2)

        tk.Label(dir_grid, text="Backup Directory:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(row=1, column=0, sticky="w", padx=(0, 6), pady=2)
        ttk.Entry(dir_grid, textvariable=self.var_backups_dir).grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=2)
        ttk.Button(dir_grid, text="Browse", command=lambda: self._browse_dir(self.var_backups_dir)).grid(row=1, column=2, pady=2)

        ttk.Button(pref_card, text="Save Preferences to SQLite", style="Accent.TButton", command=self._save_all_preferences).pack(anchor="w")

        # 3. Database Integrity Audit, Backup & Restore (§10)
        db_card = self._make_card(body, "SQLite Database Integrity Verification, Backup & Safe Restore")
        db_btns = tk.Frame(db_card, bg=THEME["bg_card"])
        db_btns.pack(fill="x", pady=(0, 6))
        ttk.Button(db_btns, text="Run Integrity Audit", command=self._run_db_audit).pack(side="left", padx=(0, 8))
        ttk.Button(db_btns, text="Create Verified Backup", style="Accent.TButton", command=self._create_backup).pack(side="left", padx=(0, 8))
        ttk.Button(db_btns, text="Validate & Restore Backup", style="Danger.TButton", command=self._restore_backup).pack(side="left")

        self.db_status_lbl = tk.Label(
            db_card,
            text=f"Active SQLite: {DB_PATH} (Schema v{SCHEMA_VERSION}) • Nominatim: {NOMINATIM_URL} • Overpass: {OVERPASS_URLS[0]}",
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 8),
            wraplength=960,
            justify="left",
        )
        self.db_status_lbl.pack(anchor="w", pady=(4, 0))

    @staticmethod
    def _make_card(parent: tk.Misc, title: str) -> tk.Frame:
        card = tk.Frame(parent, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=14, pady=10)
        card.pack(fill="x", pady=(0, 10))
        tk.Label(card, text=title, bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        return card

    @staticmethod
    def _grid_field(parent: tk.Misc, row_lbl: int, col: int, label: str, var: tk.StringVar) -> None:
        tk.Label(parent, text=label, bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8)).grid(row=row_lbl, column=col, sticky="w", padx=4)
        ttk.Entry(parent, textvariable=var).grid(row=row_lbl + 1, column=col, sticky="ew", padx=4, pady=(0, 6))

    @staticmethod
    def _browse_dir(var: tk.StringVar) -> None:
        from tkinter import filedialog
        chosen = filedialog.askdirectory(initialdir=var.get() or str(EXPORTS_DIR))
        if chosen:
            var.set(chosen)

    def load_preferences(self, prefs: dict[str, str]) -> None:
        mapping = {
            "pref_rain_mm_hr": self.var_def_rain,
            "pref_duration_min": self.var_def_dur,
            "pref_time_step_min": self.var_def_step,
            "pref_sim_mode": self.var_def_mode,
            "pref_risk_low_cm": self.var_risk_low,
            "pref_risk_mod_cm": self.var_risk_mod,
            "pref_risk_high_cm": self.var_risk_high,
            "pref_road_low_cm": self.var_road_low,
            "pref_road_mod_cm": self.var_road_mod,
            "pref_road_high_cm": self.var_road_high,
            "pref_speed_walk": self.var_spd_walk,
            "pref_speed_car": self.var_spd_car,
            "pref_speed_emerg": self.var_spd_emerg,
            "pref_exports_dir": self.var_exports_dir,
            "pref_backups_dir": self.var_backups_dir,
            "pref_weather_url": self.var_weather_url,
            "pref_theme": self.var_theme,
        }
        for key, var in mapping.items():
            if key in prefs and prefs[key]:
                var.set(prefs[key])
        if "pref_show_grid" in prefs:
            self.var_map_grid_default.set(prefs["pref_show_grid"] != "false")

    def _save_all_preferences(self) -> None:
        try:
            r_low, r_mod, r_high = float(self.var_risk_low.get()), float(self.var_risk_mod.get()), float(self.var_risk_high.get())
            e_low, e_mod, e_high = float(self.var_road_low.get()), float(self.var_road_mod.get()), float(self.var_road_high.get())
            sw, sc, se = float(self.var_spd_walk.get()), float(self.var_spd_car.get()), float(self.var_spd_emerg.get())
            rn, dr, st = float(self.var_def_rain.get()), float(self.var_def_dur.get()), float(self.var_def_step.get())
            if not (0 < r_low <= r_mod <= r_high) or not (0 < e_low <= e_mod <= e_high):
                raise ValueError("Thresholds must satisfy 0 < Low <= Moderate <= High (cm).")
            if min(sw, sc, se) <= 0 or rn < 0 or dr <= 0 or st <= 0 or st > dr:
                raise ValueError("Speeds, duration, and time step must be positive; time step <= duration.")
        except ValueError as exc:
            messagebox.showerror("Invalid Preference", str(exc))
            return

        payload = {
            "pref_rain_mm_hr": self.var_def_rain.get().strip(),
            "pref_duration_min": self.var_def_dur.get().strip(),
            "pref_time_step_min": self.var_def_step.get().strip(),
            "pref_sim_mode": self.var_def_mode.get().strip(),
            "pref_risk_low_cm": self.var_risk_low.get().strip(),
            "pref_risk_mod_cm": self.var_risk_mod.get().strip(),
            "pref_risk_high_cm": self.var_risk_high.get().strip(),
            "pref_road_low_cm": self.var_road_low.get().strip(),
            "pref_road_mod_cm": self.var_road_mod.get().strip(),
            "pref_road_high_cm": self.var_road_high.get().strip(),
            "pref_speed_walk": self.var_spd_walk.get().strip(),
            "pref_speed_car": self.var_spd_car.get().strip(),
            "pref_speed_emerg": self.var_spd_emerg.get().strip(),
            "pref_exports_dir": self.var_exports_dir.get().strip(),
            "pref_backups_dir": self.var_backups_dir.get().strip(),
            "pref_weather_url": self.var_weather_url.get().strip(),
            "pref_theme": self.var_theme.get().strip(),
            "pref_show_grid": "true" if self.var_map_grid_default.get() else "false",
        }
        if self.on_save_preferences:
            self.on_save_preferences(payload)
        messagebox.showinfo("Settings Saved", "Application preferences saved cleanly to SQLite app_settings.")

    def _run_db_audit(self) -> None:
        if not self.get_db_manager:
            return
        from database.backup_manager import DatabaseBackupManager
        mgr = DatabaseBackupManager(self.get_db_manager(), backup_dir=self.var_backups_dir.get() or BACKUPS_DIR)  # type: ignore[arg-type]
        report = mgr.audit_database()
        summary = (
            f"Audit Result: {'PASSED' if report.overall_ok else 'ISSUES FOUND'}\n"
            f"Schema v{report.schema_version} | FK={'ON' if report.foreign_keys_enabled else 'OFF'} | Indexes={report.index_count}\n"
            f"Neighbourhoods={report.table_row_counts.get('neighbourhoods', 0)}, "
            f"Cells={report.table_row_counts.get('grid_cells', 0)}, "
            f"Runs={report.table_row_counts.get('simulation_runs', 0)}, "
            f"Shelters={report.table_row_counts.get('shelters', 0)}"
        )
        self.db_status_lbl.configure(text=summary, fg=THEME["success"] if report.overall_ok else THEME["error"])
        messagebox.showinfo("SQLite Database Audit", summary)

    def _create_backup(self) -> None:
        if not self.get_db_manager:
            return
        from database.backup_manager import DatabaseBackupManager
        bdir = self.var_backups_dir.get().strip() or str(BACKUPS_DIR)
        mgr = DatabaseBackupManager(self.get_db_manager(), backup_dir=bdir)  # type: ignore[arg-type]
        path, val = mgr.create_backup(label="user_backup")
        self.db_status_lbl.configure(text=f"Backup created: {path} ({val.file_size_bytes:,} bytes)", fg=THEME["success"])
        messagebox.showinfo("Backup Created & Verified", f"Saved verified backup:\n{path}\n\n{val.message}")

    def _restore_backup(self) -> None:
        if not self.get_db_manager:
            return
        from tkinter import filedialog
        from database.backup_manager import DatabaseBackupManager
        bdir = self.var_backups_dir.get().strip() or str(BACKUPS_DIR)
        chosen = filedialog.askopenfilename(
            title="Select SQLite Backup to Validate & Restore",
            initialdir=bdir,
            filetypes=[("SQLite Database", "*.db *.sqlite"), ("All files", "*.*")],
        )
        if not chosen:
            return
        mgr = DatabaseBackupManager(self.get_db_manager(), backup_dir=bdir)  # type: ignore[arg-type]
        val = mgr.validate_backup(chosen)
        if not val.is_valid:
            messagebox.showerror("Invalid Backup Rejected", f"Validation failed — active database was NOT modified:\n\n{val.message}")
            return
        if not messagebox.askyesno(
            "Confirm Database Restore",
            f"Backup validated cleanly:\n{val.message}\n\n"
            "An automatic safety backup of your current active database will be saved before restoring.\n"
            "Proceed with restoring this backup?",
        ):
            return
        safety_path, _ = mgr.restore_backup(chosen, user_confirmed=True, safety_backup_dir=bdir)
        self.db_status_lbl.configure(text=f"Restored from {chosen}. Safety snapshot: {safety_path}", fg=THEME["success"])
        if self.on_database_restored:
            self.on_database_restored()
        messagebox.showinfo("Database Restored", f"Database restored cleanly.\nPre-restore safety backup saved at:\n{safety_path}")

    def set_state(self, force_offline: bool, status_text: str, workspaces: list, active_id: int | None) -> None:
        self.offline_var.set(force_offline)
        self.conn_status_lbl.configure(text=status_text)
        self._ws_map.clear()
        labels = []
        active_label = ""
        for ws in workspaces:
            label = f"{ws.name} (ID {ws.id} • {ws.grid_rows}×{ws.grid_cols})"
            self._ws_map[label] = ws.id
            labels.append(label)
            if ws.id == active_id:
                active_label = label
        self.ws_combo["values"] = labels
        if active_label:
            self.ws_combo_var.set(active_label)
        elif labels:
            self.ws_combo_var.set(labels[0])
        else:
            self.ws_combo_var.set("")

    def _handle_offline_toggle(self) -> None:
        self.on_toggle_offline_mode(bool(self.offline_var.get()))

    def _handle_clear_cache(self) -> None:
        if messagebox.askyesno(
            "Clear Local Cache",
            "Remove cached geocoding, Overpass, and weather JSON files?\n"
            "Your saved SQLite workspaces and edited grid cells will NOT be deleted.",
        ):
            removed = self.on_clear_cache()
            self.conn_status_lbl.configure(text=f"Cleared {removed} cached JSON file(s).")

    def _handle_load_workspace(self) -> None:
        label = self.ws_combo_var.get()
        nid = self._ws_map.get(label)
        if nid is not None:
            self.on_select_neighbourhood(nid)

