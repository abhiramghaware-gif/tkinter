"""Phase 7 Home Dashboard: integrated GIS, weather, simulation, emergency & quick-launch hub."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from config import MAP_COLORS, THEME
from core.flood_statistics import compute_timestep_statistics
from core.models import DashboardSummary, GridCell, OSMFeature
from core.risk_classifier import RiskThresholds
from core.simulation_engine import SimulationOutput, SimulationRunRecord
from emergency.alert_manager import EmergencyAlertRecord
from emergency.operation_manager import DashboardOverviewStats, EmergencyOperationRecord
from gui.components import StatCard
from services.weather_service import compute_snapshot_age
from visualization.grid_renderer import GridRenderer
from visualization.map_renderer import GeoViewport, MapRenderer


class DashboardView(tk.Frame):
    """Comprehensive Phase 7 Home Dashboard backed strictly by SQLite & live/cached state."""

    def __init__(
        self,
        parent: tk.Misc,
        on_navigate: Callable[[str], None],
        on_refresh_weather: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=16, pady=12)
        self.on_navigate = on_navigate
        self.on_refresh_weather = on_refresh_weather

        self._map_renderer = MapRenderer()
        self._grid_renderer = GridRenderer()
        self._viewport: GeoViewport | None = None
        self._summary: DashboardSummary | None = None
        self._features: list[OSMFeature] = []
        self._cells: list[GridCell] = []
        self._drainage: list[Any] = []

        self._build_ui()

    def _build_ui(self) -> None:
        # Page Title + Quick Actions (pack right-side buttons first so they never clip)
        top_row = tk.Frame(self, bg=THEME["bg_root"])
        top_row.pack(fill="x", pady=(0, 8))

        actions = tk.Frame(top_row, bg=THEME["bg_root"])
        actions.pack(side="right", padx=(8, 0))
        ttk.Button(actions, text="Map Editor", style="Accent.TButton", command=lambda: self.on_navigate("map_editor")).pack(side="left", padx=(0, 5))
        ttk.Button(actions, text="Refresh Weather", command=self.on_refresh_weather).pack(side="left", padx=(0, 5))
        ttk.Button(actions, text="What-If Lab", command=lambda: self.on_navigate("what_if")).pack(side="left", padx=(0, 5))
        ttk.Button(actions, text="Reports", command=lambda: self.on_navigate("reports")).pack(side="left")

        title_box = tk.Frame(top_row, bg=THEME["bg_root"])
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_box,
            text="Operations & Decision Support Home",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 16, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_box,
            text="SQLite-backed metrics (Live / Cached / Manual / Simulated).",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w")

        # 8 Summary KPI Cards covering GIS, Connectivity, Weather, Simulation, Shelters, Teams/Vehicles & Alerts (§2)
        cards_grid = tk.Frame(self, bg=THEME["bg_root"])
        cards_grid.pack(fill="x", pady=(0, 10))
        for col in range(4):
            cards_grid.columnconfigure(col, weight=1, uniform="cards")

        self.card_neighbourhood = StatCard(cards_grid, "Neighbourhood & Connectivity", "No Workspace", "Offline • 0 features", THEME["accent"])
        self.card_weather = StatCard(cards_grid, "Weather Feed (Optional)", "Weather unavailable", "No saved observation", THEME["info"])
        self.card_sim_depth = StatCard(cards_grid, "Latest Simulation & Max Depth", "No Simulations", "Run Simulation Lab first", THEME["accent_teal"])
        self.card_sim_risk = StatCard(cards_grid, "Affected Cells & High Risk", "0 Cells", "0 High / 0 Very High", THEME["warning"])

        self.card_shelters = StatCard(cards_grid, "Registered Shelters", "0", "0 available capacity", THEME["success"])
        self.card_teams = StatCard(cards_grid, "Rescue Teams & Vehicles", "0 / 0", "Available teams / vehicles", THEME["info"])
        self.card_low_stock = StatCard(cards_grid, "Low-Stock Inventory Alerts", "0", "No inventory records", THEME["error"])
        self.card_gis_grid = StatCard(cards_grid, "GIS Map & 10×10 Grid", "0 × 0", "0 configured • Last sync Never", THEME["text_secondary"])

        row1 = [self.card_neighbourhood, self.card_weather, self.card_sim_depth, self.card_sim_risk]
        row2 = [self.card_shelters, self.card_teams, self.card_low_stock, self.card_gis_grid]
        for idx, card in enumerate(row1):
            card.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0), pady=(0, 8))
        for idx, card in enumerate(row2):
            card.grid(row=1, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0))

        # Lower split: Map Preview (left 54%) + Integrated Recent History, Alerts & Quick Launch (right 46%)
        lower = tk.Frame(self, bg=THEME["bg_root"])
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=6)
        lower.columnconfigure(1, weight=5)
        lower.rowconfigure(0, weight=1)

        preview_card = tk.Frame(lower, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1)
        preview_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        preview_hdr = tk.Frame(preview_card, bg=THEME["bg_card"], padx=12, pady=8)
        preview_hdr.pack(fill="x")
        tk.Label(preview_hdr, text="Neighbourhood GIS & Grid Preview", bg=THEME["bg_card"], fg=THEME["text_primary"], font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(preview_hdr, text="Cached local geometry • Not live telemetry", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 8)).pack(side="right")

        self.preview_canvas = tk.Canvas(preview_card, bg=MAP_COLORS["canvas_bg"], highlightthickness=0)
        self.preview_canvas.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.preview_canvas.bind("<Configure>", self._on_canvas_resize)

        # Right column: Quick-Access Modules + Recent Simulations / Operations / Alerts Lists
        right_col = tk.Frame(lower, bg=THEME["bg_root"])
        right_col.grid(row=0, column=1, sticky="nsew")
        right_col.rowconfigure(1, weight=1)
        right_col.columnconfigure(0, weight=1)

        quick_card = tk.Frame(right_col, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=10, pady=8)
        quick_card.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(quick_card, text="QUICK MODULE ACCESS (PHASES 1–7)", bg=THEME["bg_card"], fg=THEME["accent"], font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 4))

        qgrid = tk.Frame(quick_card, bg=THEME["bg_card"])
        qgrid.pack(fill="x")
        for col in range(4):
            qgrid.columnconfigure(col, weight=1)
        quick_buttons = [
            ("Weather", "weather"),
            ("Sim Lab", "simulation_lab"),
            ("Flood Map", "flood_map"),
            ("SafeRoute", "saferoute"),
            ("Shelters/Relief", "resources"),
            ("What-If Lab", "what_if"),
            ("PDF Reports", "reports"),
            ("Backup/Settings", "settings"),
        ]
        for idx, (lbl, target) in enumerate(quick_buttons):
            ttk.Button(qgrid, text=lbl, command=lambda k=target: self.on_navigate(k)).grid(
                row=idx // 4, column=idx % 4, sticky="ew", padx=2, pady=2
            )

        hist_nb = ttk.Notebook(right_col)
        hist_nb.grid(row=1, column=0, sticky="nsew")

        tab_sims = tk.Frame(hist_nb, bg=THEME["bg_card"], padx=6, pady=6)
        self.sim_hist_list = tk.Listbox(tab_sims, bg=THEME["bg_input"], fg=THEME["text_primary"], font=("Segoe UI", 8), bd=0, highlightthickness=0)
        self.sim_hist_list.pack(fill="both", expand=True)

        tab_ops = tk.Frame(hist_nb, bg=THEME["bg_card"], padx=6, pady=6)
        self.ops_hist_list = tk.Listbox(tab_ops, bg=THEME["bg_input"], fg=THEME["text_primary"], font=("Segoe UI", 8), bd=0, highlightthickness=0)
        self.ops_hist_list.pack(fill="both", expand=True)

        tab_alerts = tk.Frame(hist_nb, bg=THEME["bg_card"], padx=6, pady=6)
        self.alerts_hist_list = tk.Listbox(tab_alerts, bg=THEME["bg_input"], fg=THEME["warning"], font=("Segoe UI", 8), bd=0, highlightthickness=0)
        self.alerts_hist_list.pack(fill="both", expand=True)

        hist_nb.add(tab_sims, text="Recent Simulations")
        hist_nb.add(tab_ops, text="Emergency Operations")
        hist_nb.add(tab_alerts, text="Latest Alerts")

    def refresh(
        self,
        summary: DashboardSummary,
        features: list[OSMFeature],
        cells: list[GridCell],
        drainage: list | None = None,
        *,
        is_offline_mode: bool = True,
        internet_reachable: bool = False,
        sim_runs: list[SimulationRunRecord] | None = None,
        selected_sim_output: SimulationOutput | None = None,
        risk_thresholds: RiskThresholds | None = None,
        emergency_stats: DashboardOverviewStats | None = None,
        recent_operations: list[EmergencyOperationRecord] | None = None,
        active_alerts: list[EmergencyAlertRecord] | None = None,
    ) -> None:
        self._summary = summary
        self._features = features
        self._cells = cells
        self._drainage = drainage or []

        ws = summary.neighbourhood
        conn_label = "FORCED OFFLINE" if is_offline_mode and internet_reachable else (
            "ONLINE (Reachable)" if not is_offline_mode else "OFFLINE (Local SQLite/Cache)"
        )

        if ws is None:
            self.card_neighbourhood.update_card("No Workspace", conn_label, THEME["warning"])
            self.card_weather.update_card("Weather unavailable", "Create a workspace first", THEME["text_muted"])
            self.card_sim_depth.update_card("No Simulations", "Run Simulation Lab first", THEME["text_muted"])
            self.card_sim_risk.update_card("0 Cells", "0 High / 0 Very High", THEME["text_muted"])
            self.card_shelters.update_card("0", "0 available capacity", THEME["text_muted"])
            self.card_teams.update_card("0 / 0", "Teams / Vehicles available", THEME["text_muted"])
            self.card_low_stock.update_card("0", "No inventory records", THEME["text_muted"])
            self.card_gis_grid.update_card("0 × 0", "No OSM data imported", THEME["text_muted"])
            self._viewport = None
            self._fill_lists([], [], [])
            self._render_preview()
            return

        loc_parts = [p for p in (ws.district, ws.state) if p]
        loc_sub = ", ".join(loc_parts) if loc_parts else f"{ws.center_latitude:.4f}, {ws.center_longitude:.4f}"
        self.card_neighbourhood.update_card(f"{ws.name}", f"{loc_sub} • {conn_label}", THEME["accent"])

        # Weather Card (Live vs Cached vs Unavailable)
        if summary.weather is None:
            self.card_weather.update_card("Weather unavailable", "No saved Open-Meteo record", THEME["text_muted"])
        else:
            snap = compute_snapshot_age(summary.weather)
            temp_str = f"{snap.temperature_c:.1f} °C" if snap.temperature_c is not None else "N/A"
            rain_str = f"Rain {snap.rainfall_mm:.1f} mm" if snap.rainfall_mm is not None else "Rain N/A"
            feed_kind = "CACHED" if ("cache" in summary.weather.data_type.lower() or snap.is_stale) else "LIVE"
            self.card_weather.update_card(
                f"{temp_str} • {snap.weather_description}",
                f"[{feed_kind}] {rain_str} ({snap.age_label})",
                THEME["warning"] if snap.is_stale else THEME["info"],
            )

        # Latest / Selected Simulation Cards
        runs = sim_runs or []
        if not runs:
            self.card_sim_depth.update_card("No Simulations", "Run Simulation Lab first", THEME["text_muted"])
            self.card_sim_risk.update_card("0 Affected Cells", "0 High / 0 Very High Risk", THEME["text_muted"])
        else:
            latest_run = selected_sim_output.run if selected_sim_output else runs[0]
            date_lbl = (latest_run.completion_time or latest_run.start_time or "")[:16].replace("T", " ")
            if selected_sim_output and selected_sim_output.steps:
                th = risk_thresholds or RiskThresholds()
                st = compute_timestep_statistics(selected_sim_output, selected_sim_output.steps[-1].timestep, cells, th)
                self.card_sim_depth.update_card(
                    f"{st.max_depth_cm:.1f} cm Max",
                    f"[SIM] Run #{latest_run.id} ({date_lbl} UTC)",
                    THEME["accent_teal"],
                )
                self.card_sim_risk.update_card(
                    f"{st.affected_cells} / {st.total_cells} Cells",
                    f"{st.high_risk_cells} High • {st.very_high_risk_cells} Very High",
                    THEME["error"] if st.very_high_risk_cells > 0 else THEME["warning"],
                )
            else:
                self.card_sim_depth.update_card(f"Run #{latest_run.id}", f"Saved {date_lbl} • Select to inspect", THEME["accent_teal"])
                self.card_sim_risk.update_card("Select Run", f"{len(runs)} saved simulation(s)", THEME["info"])

        # Emergency Resource Cards (Strict SQLite counts — no fake defaults)
        em = emergency_stats
        if em is None or em.total_shelters == 0:
            self.card_shelters.update_card("0 Shelters", "Register shelters in Emergency Mgr", THEME["text_muted"])
        else:
            self.card_shelters.update_card(
                f"{em.total_shelters} Shelters",
                f"{em.available_shelter_capacity:,} / {em.total_shelter_capacity:,} capacity avail",
                THEME["success"],
            )

        if em is None or (em.total_teams == 0 and em.total_vehicles == 0):
            self.card_teams.update_card("0 Teams / 0 Veh", "No rescue resources registered", THEME["text_muted"])
        else:
            self.card_teams.update_card(
                f"{em.available_teams} Teams / {em.available_vehicles} Veh",
                f"Of {em.total_teams} teams & {em.total_vehicles} vehicles",
                THEME["info"],
            )

        low_cnt = em.low_stock_items if em else 0
        alert_cnt = len(active_alerts or [])
        self.card_low_stock.update_card(
            f"{low_cnt} Low Stock",
            f"{alert_cnt} active SQLite alert(s)",
            THEME["error"] if (low_cnt > 0 or alert_cnt > 0) else THEME["success"],
        )

        # GIS & Grid Card
        last_sync = summary.last_map_update[:16].replace("T", " ") + " UTC" if summary.last_map_update else "Never"
        self.card_gis_grid.update_card(
            f"{ws.grid_rows}×{ws.grid_cols} ({summary.configured_grid_cells}/{summary.total_grid_cells})",
            f"{summary.road_count} rds, {summary.building_count} bldg • Sync: {last_sync}",
            THEME["accent"],
        )

        self._fill_lists(runs, recent_operations or [], active_alerts or [])

        self._viewport = GeoViewport(
            ws.min_latitude, ws.max_latitude, ws.min_longitude, ws.max_longitude,
            width=max(200, self.preview_canvas.winfo_width()),
            height=max(200, self.preview_canvas.winfo_height()),
            padding=16,
        )
        self._render_preview()

    def _fill_lists(
        self,
        runs: list[SimulationRunRecord],
        operations: list[EmergencyOperationRecord],
        alerts: list[EmergencyAlertRecord],
    ) -> None:
        self.sim_hist_list.delete(0, "end")
        if not runs:
            self.sim_hist_list.insert("end", "Empty state: No saved flood simulations in SQLite yet.")
        else:
            for r in runs[:20]:
                ts = (r.completion_time or r.start_time or "")[:16].replace("T", " ")
                self.sim_hist_list.insert("end", f"#{r.id} [{ts}] {r.scenario_name} — {r.rainfall_intensity:.0f} mm/h ({r.simulation_mode})")

        self.ops_hist_list.delete(0, "end")
        if not operations:
            self.ops_hist_list.insert("end", "Empty state: No emergency operations recorded in SQLite yet.")
        else:
            for op in operations[:20]:
                self.ops_hist_list.insert("end", f"[{op.status}] {op.operation_name} ({op.operation_type}) -> {op.destination or 'Unassigned'}")

        self.alerts_hist_list.delete(0, "end")
        if not alerts:
            self.alerts_hist_list.insert("end", "No active unacknowledged resource/system alerts in SQLite.")
        else:
            for a in alerts[:20]:
                self.alerts_hist_list.insert("end", f"[{a.severity.upper()}] {a.title}: {a.description}")

    def _on_canvas_resize(self, event: tk.Event) -> None:
        if self._viewport is not None:
            self._viewport.resize(event.width, event.height)
        self._render_preview()

    def _render_preview(self) -> None:
        self.preview_canvas.delete("all")
        if self._summary is None or self._summary.neighbourhood is None or self._viewport is None:
            w = max(200, self.preview_canvas.winfo_width())
            h = max(200, self.preview_canvas.winfo_height())
            self.preview_canvas.create_text(
                w / 2.0, h / 2.0 - 10, text="No neighbourhood workspace loaded yet.",
                fill=THEME["text_secondary"], font=("Segoe UI", 11, "bold"),
            )
            self.preview_canvas.create_text(
                w / 2.0, h / 2.0 + 14, text="Open 'Advanced Map Editor' to search Potheri or load a saved DB.",
                fill=THEME["text_muted"], font=("Segoe UI", 9),
            )
            return

        self._map_renderer.render(
            self.preview_canvas, self._viewport, self._summary.neighbourhood, self._features,
            drainage_features=self._drainage, show_osm=True, draw_hud=True,
        )
        self._grid_renderer.render(
            self.preview_canvas, self._viewport, self._cells,
            selected_cell_ids=None, show_grid=True, show_land_use_tint=True, show_labels=False,
        )
