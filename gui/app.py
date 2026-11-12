"""Main Tkinter application shell, navigation, and background task orchestration."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

from config import APP_NAME, APP_SUBTITLE, APP_VERSION, BACKUPS_DIR, EXPORTS_DIR, THEME
from core.models import (
    DrainageFeature,
    GeocodingResult,
    GridCell,
    Neighbourhood,
    OSMFeature,
)
from core.risk_classifier import RiskThresholds
from core.validation import ValidationError, validate_drainage_inputs
from core.workspace import WorkspaceManager
from database.db import DatabaseManager
from database.repository import FloodGuardRepository
from gui.components import PlaceholderModuleView, SettingsView, configure_styles
from gui.dashboard import DashboardView
from gui.drainage_panel import DrainageManagerView
from gui.elevation_panel import ElevationManagerView
from gui.emergency_dashboard import EmergencyDashboardView
from gui.feature_panels import LandUseManagerView, RoadsBuildingsView, WaterBodiesView
from gui.map_editor import MapEditorView
from gui.quality_and_io_panel import DataQualityView, GridConfigView, ImportExportView
from gui.reports_screen import ReportsAnalyticsView
from gui.saferoute_screen import SafeRouteScreen
from gui.scenario_comparison import ScenarioComparisonView
from gui.simulation_lab import SimulationLabView
from gui.weather_panel import WeatherPanelView
from gui.what_if_lab import WhatIfLabView
from routing.flood_exposure import RoadExposureThresholds
from visualization.flood_charts import FloodChartsPanel
from visualization.flood_map import FloodMapView
from core.simulation_config import SimulationConfig
from core.simulation_engine import run_simulation
from services.cache_service import CacheService
from services.elevation_service import ElevationImportError, ElevationService
from services.geocoding_service import GeocodingError, GeocodingService
from services.geojson_io_service import GeoDataIOError, GeoJSONIOService
from services.osm_service import OSMImportError, OSMService
from services.weather_service import (
    WeatherService,
    WeatherServiceError,
    check_internet_connectivity,
)

logger = logging.getLogger(__name__)


class FloodGuardApp(tk.Tk):
    """Root desktop window for CHENNAI FLOODGUARD (Phases 1–7)."""

    NAV_ITEMS = (
        ("dashboard", "Dashboard", False),
        ("map_editor", "Advanced Map Editor", False),
        ("roads_buildings", "Roads and Buildings", False),
        ("water_bodies", "Water Bodies", False),
        ("elevation", "Elevation Manager", False),
        ("land_use", "Land-use Manager", False),
        ("drainage", "Drainage Manager", False),
        ("grid_config", "Grid Configuration", False),
        ("data_quality", "Data Quality", False),
        ("import_export", "Import and Export", False),
        ("weather", "Weather Monitor", False),
        ("simulation_lab", "Simulation Lab", False),
        ("flood_map", "Flood Map", False),
        ("flood_charts", "Flood Charts", False),
        ("flood_compare", "Scenario Comparison", False),
        ("what_if", "What-If Lab", False),
        ("saferoute", "SafeRoute", False),
        ("resources", "Emergency Resources", False),
        ("reports", "Reports & Analytics", False),
        ("settings", "Settings", False),
    )

    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION} — {APP_SUBTITLE}")
        self.geometry("1420x880")
        self.minsize(1200, 740)

        configure_styles(self)

        # Core Infrastructure
        self.db_manager = DatabaseManager()
        self.db_manager.initialize()
        self.repo = FloodGuardRepository(self.db_manager)
        self.workspace_mgr = WorkspaceManager(self.repo)
        self.cache_service = CacheService()
        self.geocoding_service = GeocodingService(cache_service=self.cache_service)
        self.osm_service = OSMService(cache_service=self.cache_service)
        self.weather_service = WeatherService(cache_service=self.cache_service)
        self.elevation_service = ElevationService()
        self.geojson_io = GeoJSONIOService()

        # Configurable User Preferences (loaded from SQLite app_settings)
        self._exports_dir = Path(self.repo.get_setting("pref_exports_dir") or EXPORTS_DIR)
        self._backups_dir = Path(self.repo.get_setting("pref_backups_dir") or BACKUPS_DIR)
        self._risk_thresholds = RiskThresholds(
            low_max_cm=float(self.repo.get_setting("pref_risk_low_cm") or 10.0),
            moderate_max_cm=float(self.repo.get_setting("pref_risk_mod_cm") or 30.0),
            high_max_cm=float(self.repo.get_setting("pref_risk_high_cm") or 60.0),
        )
        self._road_thresholds = RoadExposureThresholds(
            low_max_cm=float(self.repo.get_setting("pref_road_low_cm") or 10.0),
            moderate_max_cm=float(self.repo.get_setting("pref_road_mod_cm") or 30.0),
            high_max_cm=float(self.repo.get_setting("pref_road_high_cm") or 60.0),
        )

        # App State
        self._active_neighbourhood: Neighbourhood | None = None
        self._cells: list[GridCell] = []
        self._features: list[OSMFeature] = []
        self._drainage_features: list[DrainageFeature] = []
        self._internet_reachable: bool = False
        self._force_offline: bool = self.repo.get_setting("force_offline", "false") == "true"
        self._active_page: str = "dashboard"
        self._active_sim_output_id: int | None = None

        # Background Worker Queue
        self._result_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._cancel_event: threading.Event | None = None
        self._sim_pause_event: threading.Event | None = None
        self._is_busy: bool = False

        self._nav_buttons: dict[str, tk.Button] = {}
        self._pages: dict[str, tk.Frame] = {}

        self._build_layout()
        self._load_initial_workspace()
        self._update_header_status()
        self.after(80, self._poll_queue)
        self.after(200, self._run_connectivity_probe)

    @property
    def is_offline_mode(self) -> bool:
        return self._force_offline or (not self._internet_reachable)

    # -------------------------------------------------------------------------
    # Layout Construction
    # -------------------------------------------------------------------------

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=0, minsize=232)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(
            self,
            bg=THEME["bg_header"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        header.grid(row=0, column=0, columnspan=2, sticky="ew")

        brand_box = tk.Frame(header, bg=THEME["bg_header"])
        brand_box.pack(side="left")
        tk.Label(
            brand_box,
            text=APP_NAME,
            bg=THEME["bg_header"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w")
        tk.Label(
            brand_box,
            text=f"{APP_SUBTITLE}  •  v{APP_VERSION}",
            bg=THEME["bg_header"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
        ).pack(anchor="w")

        chips = tk.Frame(header, bg=THEME["bg_header"])
        chips.pack(side="right")

        self.hdr_ws_lbl = self._make_header_chip(chips, "Area: None")
        self.hdr_sim_lbl = self._make_header_chip(chips, "Sim: None")
        self.hdr_map_lbl = self._make_header_chip(chips, "Map: Never")
        self.hdr_db_lbl = self._make_header_chip(chips, "DB: Checking...")
        self.hdr_net_lbl = self._make_header_chip(chips, "Net: Checking...")
        self.hdr_mode_lbl = tk.Label(
            chips,
            text="OFFLINE",
            bg=THEME["warning_bg"],
            fg=THEME["warning"],
            font=("Segoe UI", 8, "bold"),
            padx=8,
            pady=4,
        )
        self.hdr_mode_lbl.pack(side="left", padx=(4, 0))

        # Left Persistent Sidebar (with scrollable nav canvas for smaller displays)
        sidebar = tk.Frame(
            self,
            bg=THEME["bg_sidebar"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            width=248,
        )
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.pack_propagate(False)

        tk.Label(
            sidebar,
            text="GIS & MONITORING MODULES",
            bg=THEME["bg_sidebar"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8, "bold"),
            padx=14,
            pady=8,
        ).pack(anchor="w")

        nav_container = tk.Frame(sidebar, bg=THEME["bg_sidebar"])
        nav_container.pack(fill="both", expand=True)

        nav_canvas = tk.Canvas(nav_container, bg=THEME["bg_sidebar"], highlightthickness=0)
        nav_scroll = ttk.Scrollbar(nav_container, orient="vertical", command=nav_canvas.yview)
        nav_inner = tk.Frame(nav_canvas, bg=THEME["bg_sidebar"])
        nav_inner.bind("<Configure>", lambda _e: nav_canvas.configure(scrollregion=nav_canvas.bbox("all")))
        nav_win = nav_canvas.create_window((0, 0), window=nav_inner, anchor="nw")
        nav_canvas.bind("<Configure>", lambda e: nav_canvas.itemconfigure(nav_win, width=e.width))
        nav_canvas.configure(yscrollcommand=nav_scroll.set)
        nav_canvas.pack(side="left", fill="both", expand=True)
        nav_scroll.pack(side="right", fill="y")

        for key, title, is_soon in self.NAV_ITEMS:
            label_text = f"{title}  [Soon]" if is_soon else title
            btn = tk.Button(
                nav_inner,
                text=label_text,
                anchor="w",
                padx=12,
                pady=3,
                bd=0,
                relief="flat",
                cursor="hand2",
                bg=THEME["bg_sidebar"],
                fg=THEME["text_muted"] if is_soon else THEME["text_secondary"],
                activebackground=THEME["bg_card"],
                activeforeground=THEME["text_primary"],
                font=("Segoe UI", 9, "italic" if is_soon else "bold"),
                command=lambda k=key: self.navigate_to(k),
            )
            btn.pack(fill="x", padx=6, pady=0)
            self._nav_buttons[key] = btn

        prog_box = tk.Frame(sidebar, bg=THEME["bg_sidebar"], padx=14, pady=6)
        prog_box.pack(side="bottom", fill="x")
        self.activity_lbl = tk.Label(
            prog_box,
            text="Ready",
            bg=THEME["bg_sidebar"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            anchor="w",
            wraplength=200,
            justify="left",
        )
        self.activity_lbl.pack(fill="x", pady=(0, 4))
        self.progress_bar = ttk.Progressbar(prog_box, mode="indeterminate")
        self.progress_bar.pack(fill="x")

        self.content_area = tk.Frame(self, bg=THEME["bg_root"])
        self.content_area.grid(row=1, column=1, sticky="nsew")
        self.content_area.rowconfigure(0, weight=1)
        self.content_area.columnconfigure(0, weight=1)

        self._create_pages()
        self.navigate_to("dashboard")

    @staticmethod
    def _make_header_chip(parent: tk.Misc, text: str) -> tk.Label:
        lbl = tk.Label(
            parent,
            text=text,
            bg=THEME["bg_card"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 8, "bold"),
            padx=7,
            pady=4,
        )
        lbl.pack(side="left", padx=3)
        return lbl

    def _create_pages(self) -> None:
        self.dashboard_view = DashboardView(
            self.content_area,
            on_navigate=self.navigate_to,
            on_refresh_weather=self.refresh_weather_async,
        )
        self.map_editor_view = MapEditorView(
            self.content_area,
            on_resolve_location=self.resolve_location_async,
            on_create_workspace=self.create_or_load_workspace,
            on_import_osm=self.import_osm_async,
            on_cancel_network=self.cancel_background_task,
            on_save_cell=self.save_single_cell,
            on_bulk_save_cells=self.save_bulk_cells,
            on_export_grid=self.export_active_grid,
            on_apply_grid_dims=lambda r, c: self.apply_grid_dimensions(r, c, True),
            on_get_feature_cells=self.repo.get_cells_for_osm_feature,
            on_place_drainage_at=self._handle_place_drainage_from_map,
        )
        self.roads_buildings_view = RoadsBuildingsView(
            self.content_area,
            on_update_feature=self.update_osm_feature_offline,
            on_get_feature_cells=self.repo.get_cells_for_osm_feature,
        )
        self.water_bodies_view = WaterBodiesView(
            self.content_area,
            on_get_feature_cells=self.repo.get_cells_for_osm_feature,
        )
        self.elevation_view = ElevationManagerView(
            self.content_area,
            on_import_geotiff=self.import_elevation_geotiff,
        )
        self.land_use_view = LandUseManagerView(
            self.content_area,
            on_assign_land_use=self.assign_land_use_batch,
            on_auto_suggest=self.auto_suggest_land_use,
        )
        self.drainage_view = DrainageManagerView(
            self.content_area,
            on_add_drainage=self.add_drainage_element,
            on_update_drainage=self.update_drainage_element,
            on_delete_drainage=self.delete_drainage_element,
        )
        self.grid_config_view = GridConfigView(
            self.content_area,
            on_regenerate_grid=self.apply_grid_dimensions,
            on_rebuild_links=self.rebuild_spatial_links,
        )
        self.data_quality_view = DataQualityView(
            self.content_area,
            on_rebuild_links=self.rebuild_spatial_links,
        )
        self.import_export_view = ImportExportView(
            self.content_area,
            on_export_geojson=self.export_neighbourhood_geojson,
            on_export_grid_csv=self.export_grid_csv_only,
            on_export_drainage_csv=self.export_drainage_csv_only,
            on_import_geojson=self.import_geojson_file,
            on_import_geotiff=self.import_elevation_geotiff,
        )
        self.weather_view = WeatherPanelView(
            self.content_area,
            on_refresh_weather=self.refresh_weather_async,
        )
        self.settings_view = SettingsView(
            self.content_area,
            on_toggle_offline_mode=self.set_force_offline_mode,
            on_test_connectivity=self._run_connectivity_probe,
            on_clear_cache=self.cache_service.clear,
            on_select_neighbourhood=self.switch_workspace_by_id,
            on_save_preferences=self._apply_user_preferences,
            get_db_manager=lambda: self.db_manager,
            on_database_restored=self._handle_database_restored,
        )

        self._pages["dashboard"] = self.dashboard_view
        self._pages["map_editor"] = self.map_editor_view
        self._pages["roads_buildings"] = self.roads_buildings_view
        self._pages["water_bodies"] = self.water_bodies_view
        self._pages["elevation"] = self.elevation_view
        self._pages["land_use"] = self.land_use_view
        self._pages["drainage"] = self.drainage_view
        self._pages["grid_config"] = self.grid_config_view
        self._pages["data_quality"] = self.data_quality_view
        self._pages["import_export"] = self.import_export_view
        self._pages["weather"] = self.weather_view
        self._pages["settings"] = self.settings_view

        self.simulation_lab_view = SimulationLabView(
            self.content_area,
            on_start_simulation=self.start_simulation_async,
            on_toggle_pause=self.toggle_simulation_pause,
            on_reset_simulation=self.reset_simulation_session,
            on_load_saved_run=self.load_saved_simulation,
            on_delete_saved_run=self.delete_saved_simulation,
        )
        self._pages["simulation_lab"] = self.simulation_lab_view

        self.flood_map_view = FloodMapView(
            self.content_area,
            on_select_run=self.load_saved_simulation,
        )
        self._pages["flood_map"] = self.flood_map_view

        self.flood_charts_view = FloodChartsPanel(
            self.content_area,
            on_select_run=self.load_saved_simulation,
        )
        self._pages["flood_charts"] = self.flood_charts_view

        self.scenario_comparison_view = ScenarioComparisonView(
            self.content_area,
            on_fetch_run=self.repo.load_simulation_output,
        )
        self._pages["flood_compare"] = self.scenario_comparison_view
        self.saferoute_view = SafeRouteScreen(
            self.content_area,
            on_fetch_simulation=self.repo.load_simulation_output,
            on_sync_road_network=self.repo.sync_road_network,
            on_load_road_conditions=self.repo.get_road_conditions,
            on_save_road_condition=self.repo.upsert_road_condition,
            on_sync_sim_conditions=self.repo.sync_simulation_road_conditions,
            on_save_route_history=self.repo.save_route_history,
            on_list_route_history=self.repo.list_route_history,
        )
        self._pages["saferoute"] = self.saferoute_view
        self.emergency_view = EmergencyDashboardView(
            self.content_area,
            db_manager=self.db_manager,
            on_shelters_changed=self._on_shelters_changed,
            on_open_shelter_in_saferoute=self._open_shelter_in_saferoute,
        )
        self._pages["resources"] = self.emergency_view

        self.what_if_view = WhatIfLabView(
            self.content_area,
            on_fetch_run=self.repo.load_simulation_output,
            on_save_run=self.repo.save_simulation_output,
            on_delete_run=self.repo.delete_simulation_run,
            on_runs_changed=lambda: self._refresh_all_views(reset_viewport=False),
            get_db_manager=lambda: self.db_manager,
            get_exports_dir=lambda: self._exports_dir,
        )
        self._pages["what_if"] = self.what_if_view

        self.reports_view = ReportsAnalyticsView(
            self.content_area,
            get_db_manager=lambda: self.db_manager,
            get_exports_dir=lambda: self._exports_dir,
        )
        self._pages["reports"] = self.reports_view

        for frame in self._pages.values():
            frame.grid(row=0, column=0, sticky="nsew")

    def _on_shelters_changed(self, shelters: list[Any]) -> None:
        self.saferoute_view.set_registered_shelters(shelters)
        self.flood_map_view._registered_shelters = list(shelters)
        self.flood_map_view._update_step_metrics_and_redraw()

    def _open_shelter_in_saferoute(self, shelter_id: int) -> None:
        nid = self._active_neighbourhood.id if self._active_neighbourhood else None
        if nid is not None:
            shelters = self.emergency_view.shelter_mgr.list_shelters(nid)
            self.saferoute_view.set_registered_shelters(shelters)
        self.saferoute_view.select_shelter_destination(shelter_id)
        self.navigate_to("saferoute")

    def navigate_to(self, page_key: str) -> None:
        if page_key not in self._pages:
            return
        self._active_page = page_key
        self._pages[page_key].tkraise()
        for key, btn in self._nav_buttons.items():
            if key == page_key:
                btn.configure(bg=THEME["accent_muted"], fg=THEME["accent_hover"])
            else:
                is_soon = any(k == key and s for k, _, s in self.NAV_ITEMS)
                btn.configure(
                    bg=THEME["bg_sidebar"],
                    fg=THEME["text_muted"] if is_soon else THEME["text_secondary"],
                )

    # -------------------------------------------------------------------------
    # Workspace & Data Refresh
    # -------------------------------------------------------------------------

    def _load_initial_workspace(self) -> None:
        saved_id = self.repo.get_setting("active_neighbourhood_id")
        ws: Neighbourhood | None = None
        if saved_id and saved_id.isdigit():
            ws = self.repo.get_neighbourhood_by_id(int(saved_id))
        if ws is None:
            all_ws = self.repo.list_neighbourhoods()
            ws = all_ws[0] if all_ws else None

        self._set_active_neighbourhood(ws, reset_viewport=True)

    def _set_active_neighbourhood(
        self,
        neighbourhood: Neighbourhood | None,
        reset_viewport: bool = False,
    ) -> None:
        self._active_neighbourhood = neighbourhood
        self._active_sim_output_id = None
        if hasattr(self, "flood_map_view"):
            self.flood_map_view.anim_controller.pause()
        if hasattr(self, "scenario_comparison_view"):
            self.scenario_comparison_view._comp = None
        if neighbourhood is not None and neighbourhood.id is not None:
            self.repo.set_setting("active_neighbourhood_id", str(neighbourhood.id))
            self._cells = self.repo.get_grid_cells(neighbourhood.id)
            self._features = self.repo.get_osm_features(neighbourhood.id)
            self._drainage_features = self.repo.list_drainage_features(neighbourhood.id)
        else:
            self._cells = []
            self._features = []
            self._drainage_features = []

        self._refresh_all_views(reset_viewport=reset_viewport)

    def _refresh_all_views(self, reset_viewport: bool = False, weather_note: str = "") -> None:
        nid = self._active_neighbourhood.id if self._active_neighbourhood else None
        if nid is not None:
            self._cells = self.repo.get_grid_cells(nid)
            self._features = self.repo.get_osm_features(nid)
            self._drainage_features = self.repo.list_drainage_features(nid)

        summary = self.repo.get_dashboard_summary(nid)
        dq = self.repo.get_data_quality_summary(nid)
        elev_sources = self.repo.list_elevation_sources(nid) if nid is not None else []
        lu_history = self.repo.get_land_use_history(nid) if nid is not None else []
        saved_runs = self.repo.list_simulation_runs(nid) if nid is not None else []
        links = self.repo.get_links_for_neighbourhood(nid) if nid is not None else []
        shelters = self.emergency_view.shelter_mgr.list_shelters(nid) if nid is not None else []

        valid_run_ids = {r.id for r in saved_runs if r.id is not None}
        active_sim_out = None
        if saved_runs:
            target_id = self._active_sim_output_id if (self._active_sim_output_id in valid_run_ids) else saved_runs[0].id
            if target_id is not None:
                active_sim_out = self.repo.load_simulation_output(target_id)
                self._active_sim_output_id = target_id

        em_stats = self.emergency_view.op_mgr.get_dashboard_overview(nid) if nid is not None else None
        em_ops = self.emergency_view.op_mgr.list_operations(nid) if nid is not None else []
        em_alerts = self.emergency_view.alert_mgr.list_alerts(nid, include_acknowledged=False) if nid is not None else []

        self.dashboard_view.refresh(
            summary,
            self._features,
            self._cells,
            self._drainage_features,
            is_offline_mode=self.is_offline_mode,
            internet_reachable=self._internet_reachable,
            sim_runs=saved_runs,
            selected_sim_output=active_sim_out,
            risk_thresholds=self._risk_thresholds,
            emergency_stats=em_stats,
            recent_operations=em_ops,
            active_alerts=em_alerts,
        )
        self.map_editor_view.set_workspace_data(
            self._active_neighbourhood,
            self._cells,
            self._features,
            drainage_features=self._drainage_features,
            reset_viewport=reset_viewport,
        )
        self.roads_buildings_view.refresh(self._features)
        self.water_bodies_view.refresh(self._features)
        self.elevation_view.refresh(self._cells, elev_sources)
        self.land_use_view.refresh(self._cells, lu_history)
        self.drainage_view.refresh(self._active_neighbourhood, self._cells, self._drainage_features)
        self.grid_config_view.refresh(self._active_neighbourhood, self._cells)
        self.data_quality_view.refresh(dq)
        self.weather_view.update_weather(
            self._active_neighbourhood,
            summary.weather,
            status_note=weather_note,
        )
        self.simulation_lab_view.refresh_workspace(
            self._active_neighbourhood,
            self._cells,
            self._drainage_features,
            saved_runs,
        )
        self.flood_map_view.refresh_workspace(
            self._active_neighbourhood,
            self._cells,
            self._features,
            self._drainage_features,
            links,
            saved_runs,
            shelters=shelters,
        )
        self.flood_charts_view.set_runs(saved_runs, active_run_id=self._active_sim_output_id)
        self.scenario_comparison_view.refresh_workspace(
            self._active_neighbourhood,
            self._cells,
            self._features,
            saved_runs,
        )
        self.what_if_view.refresh_workspace(
            self._active_neighbourhood,
            self._cells,
            self._features,
            self._drainage_features,
            saved_runs,
            thresholds=self._risk_thresholds,
            road_thresholds=self._road_thresholds,
        )
        self.reports_view.refresh_workspace(
            self._active_neighbourhood,
            self._cells,
            self._features,
            saved_runs,
            thresholds=self._risk_thresholds,
            road_thresholds=self._road_thresholds,
        )
        self.saferoute_view.refresh_workspace(
            self._active_neighbourhood,
            self._cells,
            self._features,
            self._drainage_features,
            saved_runs,
            shelters=shelters,
        )
        self.emergency_view.set_neighbourhood(self._active_neighbourhood)

        if active_sim_out is not None and active_sim_out.run.id is not None:
            self.load_saved_simulation(active_sim_out.run.id)
        elif not saved_runs:
            self._active_sim_output_id = None
            self.simulation_lab_view.display_output(None)
            self.flood_map_view.display_output(None)
            self.flood_charts_view.display_output(None)
            self.saferoute_view.set_simulation_output(None)

        if len(saved_runs) >= 2 and getattr(self.scenario_comparison_view, "_comp", None) is None:
            self.scenario_comparison_view.run_comparison()

        workspaces = self.repo.list_neighbourhoods()
        net_desc = (
            "Forced OFFLINE mode enabled by user."
            if self._force_offline
            else ("Internet reachable (ONLINE)." if self._internet_reachable else "No internet detected (OFFLINE).")
        )
        self.settings_view.set_state(self._force_offline, net_desc, workspaces, nid)
        self.settings_view.load_preferences(self._collect_preferences_dict())
        self._update_header_status(summary.last_map_update)

    def _update_header_status(self, last_map_update: str | None = None) -> None:
        ws_name = self._active_neighbourhood.name if self._active_neighbourhood else "None"
        self.hdr_ws_lbl.configure(text=f"Area: {ws_name}")
        sim_txt = f"Sim: #{self._active_sim_output_id}" if self._active_sim_output_id else "Sim: None"
        self.hdr_sim_lbl.configure(
            text=sim_txt,
            fg=THEME["accent_hover"] if self._active_sim_output_id else THEME["text_muted"],
        )

        if last_map_update is None and self._active_neighbourhood and self._active_neighbourhood.id:
            last_map_update = self.repo.get_last_osm_import_time(self._active_neighbourhood.id)

        if last_map_update:
            clean_ts = last_map_update.replace("T", " ").replace("+00:00", "Z")
            if len(clean_ts) > 17:
                clean_ts = clean_ts[:16] + "Z"
            self.hdr_map_lbl.configure(text=f"Map: {clean_ts}")
        else:
            self.hdr_map_lbl.configure(text="Map: Never")

        db_ok, db_msg = self.db_manager.verify_integrity()
        self.hdr_db_lbl.configure(
            text=db_msg,
            fg=THEME["success"] if db_ok else THEME["error"],
        )

        self.hdr_net_lbl.configure(
            text="Net: Reachable" if self._internet_reachable else "Net: Unavailable",
            fg=THEME["success"] if self._internet_reachable else THEME["warning"],
        )

        if self.is_offline_mode:
            self.hdr_mode_lbl.configure(text="OFFLINE", bg=THEME["warning_bg"], fg=THEME["warning"])
        else:
            self.hdr_mode_lbl.configure(text="ONLINE", bg=THEME["success_bg"], fg=THEME["success"])

        self.map_editor_view.set_network_state(self.is_offline_mode, self._is_busy)
        self.weather_view.set_network_state(self.is_offline_mode, self._is_busy)

    def _collect_preferences_dict(self) -> dict[str, str]:
        keys = (
            "pref_rain_mm_hr", "pref_duration_min", "pref_time_step_min", "pref_sim_mode",
            "pref_risk_low_cm", "pref_risk_mod_cm", "pref_risk_high_cm",
            "pref_road_low_cm", "pref_road_mod_cm", "pref_road_high_cm",
            "pref_speed_walk", "pref_speed_car", "pref_speed_emerg",
            "pref_exports_dir", "pref_backups_dir", "pref_weather_url",
            "pref_theme", "pref_show_grid",
        )
        out: dict[str, str] = {}
        for k in keys:
            val = self.repo.get_setting(k)
            if val is not None:
                out[k] = val
        return out

    def _apply_user_preferences(self, prefs: dict[str, str]) -> None:
        for k, v in prefs.items():
            self.repo.set_setting(k, v)
        self._exports_dir = Path(prefs.get("pref_exports_dir") or EXPORTS_DIR)
        self._backups_dir = Path(prefs.get("pref_backups_dir") or BACKUPS_DIR)
        self._risk_thresholds = RiskThresholds(
            low_max_cm=float(prefs.get("pref_risk_low_cm") or 10.0),
            moderate_max_cm=float(prefs.get("pref_risk_mod_cm") or 30.0),
            high_max_cm=float(prefs.get("pref_risk_high_cm") or 60.0),
        )
        self._road_thresholds = RoadExposureThresholds(
            low_max_cm=float(prefs.get("pref_road_low_cm") or 10.0),
            moderate_max_cm=float(prefs.get("pref_road_mod_cm") or 30.0),
            high_max_cm=float(prefs.get("pref_road_high_cm") or 60.0),
        )
        self._refresh_all_views(reset_viewport=False)

    def _handle_database_restored(self) -> None:
        self._active_sim_output_id = None
        self._load_initial_workspace()

    # -------------------------------------------------------------------------
    # Workspace, Feature, Drainage, Elevation & I/O Operations
    # -------------------------------------------------------------------------

    def create_or_load_workspace(
        self,
        name: str,
        candidate: GeocodingResult | None,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        rows: int,
        cols: int,
    ) -> None:
        try:
            existing = self.repo.get_neighbourhood_by_name(name)
            if existing is not None:
                self._set_active_neighbourhood(existing, reset_viewport=True)
                self.map_editor_view.set_status_message(
                    f"Loaded existing workspace '{existing.name}' (no duplicate cells created).",
                    THEME["info"],
                )
                return

            c_lat = candidate.latitude if candidate else (min_lat + max_lat) / 2.0
            c_lon = candidate.longitude if candidate else (min_lon + max_lon) / 2.0
            ws, created = self.workspace_mgr.create_or_get_workspace(
                name=name,
                center_latitude=c_lat,
                center_longitude=c_lon,
                min_latitude=min_lat,
                max_latitude=max_lat,
                min_longitude=min_lon,
                max_longitude=max_lon,
                district=candidate.district if candidate else "",
                state=candidate.state if candidate else "",
                country=candidate.country if candidate else "",
                grid_rows=rows,
                grid_cols=cols,
            )
            self._set_active_neighbourhood(ws, reset_viewport=True)
            msg = (
                f"Created workspace '{ws.name}' with {rows * cols} grid cells."
                if created
                else f"Loaded existing workspace '{ws.name}'."
            )
            self.map_editor_view.set_status_message(msg, THEME["success"])
        except ValidationError as exc:
            messagebox.showerror("Validation Error", str(exc))
        except Exception as exc:
            logger.exception("Failed creating workspace")
            messagebox.showerror("Workspace Error", f"Could not create workspace: {exc}")

    def switch_workspace_by_id(self, neighbourhood_id: int) -> None:
        ws = self.repo.get_neighbourhood_by_id(neighbourhood_id)
        if ws is None:
            messagebox.showwarning("Not Found", "Selected workspace could not be found in SQLite.")
            return
        self._set_active_neighbourhood(ws, reset_viewport=True)
        self.navigate_to("dashboard")

    def apply_grid_dimensions(self, rows: int, cols: int, preserve_existing: bool = True) -> None:
        if self._active_neighbourhood is None:
            return
        try:
            updated = self.workspace_mgr.regenerate_workspace_grid(
                neighbourhood=self._active_neighbourhood,
                min_latitude=self._active_neighbourhood.min_latitude,
                max_latitude=self._active_neighbourhood.max_latitude,
                min_longitude=self._active_neighbourhood.min_longitude,
                max_longitude=self._active_neighbourhood.max_longitude,
                grid_rows=rows,
                grid_cols=cols,
                preserve_existing=preserve_existing,
            )
            self._set_active_neighbourhood(updated, reset_viewport=False)
            self.map_editor_view.set_status_message(
                f"Regenerated {rows}×{cols} grid ({rows * cols} cells).",
                THEME["success"],
            )
        except ValidationError as exc:
            messagebox.showerror("Invalid Grid Dimensions", str(exc))
        except Exception as exc:
            logger.exception("Failed regenerating grid")
            messagebox.showerror("Grid Error", str(exc))

    def rebuild_spatial_links(self) -> int:
        if self._active_neighbourhood is None or self._active_neighbourhood.id is None:
            return 0
        count = self.workspace_mgr.rebuild_feature_grid_links(self._active_neighbourhood.id)
        self._refresh_all_views(reset_viewport=False)
        return count

    def save_single_cell(
        self,
        cell: GridCell,
        elev_in: str,
        elev_src_in: str,
        land_use_in: str,
        infil_in: str,
        drain_in: str,
        notes_in: str,
    ) -> GridCell | None:
        try:
            updated = self.workspace_mgr.validate_and_save_cell(
                cell=cell,
                elevation_input=elev_in,
                elevation_source_input=elev_src_in,
                land_use_input=land_use_in,
                infiltration_input=infil_in,
                drainage_input=drain_in,
                notes_input=notes_in,
            )
            self._refresh_all_views(reset_viewport=False)
            return updated
        except ValidationError as exc:
            messagebox.showerror("Invalid Cell Attribute", str(exc))
            return None
        except Exception as exc:
            logger.exception("Failed saving cell")
            messagebox.showerror("Save Error", str(exc))
            return None

    def save_bulk_cells(
        self,
        cells: list[GridCell],
        elev_in: str,
        elev_src_in: str,
        land_use_in: str,
        infil_in: str,
        drain_in: str,
        notes_in: str,
    ) -> int:
        try:
            count = self.workspace_mgr.validate_and_bulk_save_cells(
                cells=cells,
                elevation_input=elev_in,
                elevation_source_input=elev_src_in,
                land_use_input=land_use_in,
                infiltration_input=infil_in,
                drainage_input=drain_in,
                notes_input=notes_in,
            )
            self._refresh_all_views(reset_viewport=False)
            return count
        except ValidationError as exc:
            messagebox.showerror("Invalid Cell Attribute", str(exc))
            return 0
        except Exception as exc:
            logger.exception("Failed bulk saving cells")
            messagebox.showerror("Save Error", str(exc))
            return 0

    def update_osm_feature_offline(
        self,
        feature_id: int,
        name: str,
        road_category: str,
        building_category: str,
        user_notes: str,
    ) -> OSMFeature | None:
        updated = self.repo.update_osm_feature_attributes(
            feature_id=feature_id,
            name=name,
            road_category=road_category,
            building_category=building_category,
            user_notes=user_notes,
        )
        self._refresh_all_views(reset_viewport=False)
        return updated

    def assign_land_use_batch(self, cell_ids: list[int], land_use: str) -> int:
        if self._active_neighbourhood is None or self._active_neighbourhood.id is None:
            return 0
        src = "missing" if land_use == "Unknown" else "user-entered"
        updates = [(cid, land_use, src) for cid in cell_ids]
        count = self.repo.update_cells_land_use_batch(updates, self._active_neighbourhood.id)
        self._refresh_all_views(reset_viewport=False)
        return count

    def auto_suggest_land_use(self, overwrite_user_verified: bool) -> int:
        if self._active_neighbourhood is None or self._active_neighbourhood.id is None:
            return 0
        count = self.workspace_mgr.suggest_land_use_from_features(
            self._active_neighbourhood.id,
            overwrite_user_verified=overwrite_user_verified,
        )
        self._refresh_all_views(reset_viewport=False)
        return count

    def _handle_place_drainage_from_map(self, lat: float, lon: float) -> None:
        self.drainage_view.prefill_coordinates(lat, lon)
        self.navigate_to("drainage")

    def add_drainage_element(
        self,
        name: str,
        feature_type: str,
        lat_str: str,
        lon_str: str,
        cap_str: str,
        unit: str,
        status: str,
        notes: str,
    ) -> DrainageFeature | None:
        if self._active_neighbourhood is None or self._active_neighbourhood.id is None:
            return None
        try:
            cname, ctype, lat, lon, cap, cunit, cstatus = validate_drainage_inputs(
                name, feature_type, lat_str, lon_str, cap_str, unit, status
            )
            cell = self.workspace_mgr.find_cell_for_point(self._cells, lat, lon)
            dr = DrainageFeature(
                id=None,
                neighbourhood_id=self._active_neighbourhood.id,
                grid_cell_id=cell.id if cell else None,
                name=cname,
                feature_type=ctype,
                latitude=lat,
                longitude=lon,
                capacity=cap,
                capacity_unit=cunit,
                status=cstatus,
                source="user-entered",
                notes=notes.strip(),
            )
            created = self.repo.create_drainage_feature(dr)
            self.workspace_mgr.rebuild_feature_grid_links(self._active_neighbourhood.id)
            self._refresh_all_views(reset_viewport=False)
            return created
        except ValidationError as exc:
            messagebox.showerror("Invalid Drainage Input", str(exc))
            return None

    def update_drainage_element(
        self,
        drainage_id: int,
        name: str,
        feature_type: str,
        lat_str: str,
        lon_str: str,
        cap_str: str,
        unit: str,
        status: str,
        notes: str,
    ) -> DrainageFeature | None:
        if self._active_neighbourhood is None or self._active_neighbourhood.id is None:
            return None
        try:
            cname, ctype, lat, lon, cap, cunit, cstatus = validate_drainage_inputs(
                name, feature_type, lat_str, lon_str, cap_str, unit, status
            )
            cell = self.workspace_mgr.find_cell_for_point(self._cells, lat, lon)
            dr = DrainageFeature(
                id=drainage_id,
                neighbourhood_id=self._active_neighbourhood.id,
                grid_cell_id=cell.id if cell else None,
                name=cname,
                feature_type=ctype,
                latitude=lat,
                longitude=lon,
                capacity=cap,
                capacity_unit=cunit,
                status=cstatus,
                source="user-entered",
                notes=notes.strip(),
            )
            updated = self.repo.update_drainage_feature(dr)
            self.workspace_mgr.rebuild_feature_grid_links(self._active_neighbourhood.id)
            self._refresh_all_views(reset_viewport=False)
            return updated
        except ValidationError as exc:
            messagebox.showerror("Invalid Drainage Input", str(exc))
            return None

    def delete_drainage_element(self, drainage_id: int) -> None:
        self.repo.delete_drainage_feature(drainage_id)
        if self._active_neighbourhood and self._active_neighbourhood.id:
            self.workspace_mgr.rebuild_feature_grid_links(self._active_neighbourhood.id)
        self._refresh_all_views(reset_viewport=False)

    # -------------------------------------------------------------------------
    # Elevation GeoTIFF & GeoJSON/CSV Import-Export
    # -------------------------------------------------------------------------

    def import_elevation_geotiff(self, file_path: str, source_name: str = "") -> None:
        if self._active_neighbourhood is None or self._active_neighbourhood.id is None:
            messagebox.showinfo("Workspace Required", "Create or load a workspace first.")
            return
        try:
            summary = self.elevation_service.load_geotiff_for_grid(
                file_path=file_path,
                neighbourhood_id=self._active_neighbourhood.id,
                cells=self._cells,
                source_name=source_name,
            )
            self.repo.update_cells_elevation_batch(summary.cell_updates, self._active_neighbourhood.id)
            self.repo.save_elevation_source(summary.source_record)
            self._refresh_all_views(reset_viewport=False)
            msg = (
                f"Imported '{summary.file_name}' (CRS: {summary.crs_text}) — "
                f"{summary.cells_sampled} cell(s) updated, {summary.cells_missing} NULL/outside."
            )
            self.elevation_view.status_lbl.configure(text=msg, fg=THEME["success"])
            self.import_export_view.append_log(f"[GEOTIFF OK] {msg}")
            messagebox.showinfo("Elevation Import Complete", msg)
        except ElevationImportError as exc:
            self.import_export_view.append_log(f"[GEOTIFF ERR] {exc}")
            messagebox.showerror("Elevation Import Error", str(exc))

    def import_geojson_file(self, file_path: str) -> None:
        if self._active_neighbourhood is None or self._active_neighbourhood.id is None:
            messagebox.showinfo("Workspace Required", "Create or load a workspace first.")
            return
        try:
            feats = self.geojson_io.import_geojson_features(file_path, self._active_neighbourhood.id)
            saved = self.repo.upsert_osm_features(self._active_neighbourhood.id, feats)
            self.workspace_mgr.rebuild_feature_grid_links(self._active_neighbourhood.id)
            self._refresh_all_views(reset_viewport=False)
            msg = f"Imported {saved} GeoJSON feature(s) from '{file_path}'."
            self.import_export_view.append_log(f"[GEOJSON OK] {msg}")
            messagebox.showinfo("GeoJSON Imported", msg)
        except GeoDataIOError as exc:
            self.import_export_view.append_log(f"[GEOJSON ERR] {exc}")
            messagebox.showerror("GeoJSON Import Error", str(exc))

    def export_active_grid(self) -> tuple[str, str] | None:
        if self._active_neighbourhood is None:
            messagebox.showinfo("No Workspace", "Create or load a workspace before exporting.")
            return None
        try:
            geojson_path = self.workspace_mgr.export_grid_geojson(self._active_neighbourhood, self._cells)
            csv_path = self.export_grid_csv_only()
            return str(geojson_path), str(csv_path or "")
        except Exception as exc:
            logger.exception("Failed exporting grid")
            messagebox.showerror("Export Error", str(exc))
            return None

    def export_neighbourhood_geojson(self) -> str | None:
        if self._active_neighbourhood is None:
            messagebox.showinfo("No Workspace", "Create or load a workspace first.")
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in self._active_neighbourhood.name).strip("_")
        out_path = EXPORTS_DIR / f"{safe_name}_features_{stamp}.geojson"
        path = self.geojson_io.export_neighbourhood_geojson(
            self._active_neighbourhood, self._features, self._drainage_features, out_path
        )
        return str(path)

    def export_grid_csv_only(self) -> str | None:
        if self._active_neighbourhood is None:
            messagebox.showinfo("No Workspace", "Create or load a workspace first.")
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in self._active_neighbourhood.name).strip("_")
        out_path = EXPORTS_DIR / f"{safe_name}_grid_{stamp}.csv"
        return str(self.geojson_io.export_grid_csv(self._active_neighbourhood, self._cells, out_path))

    def export_drainage_csv_only(self) -> str | None:
        if self._active_neighbourhood is None:
            messagebox.showinfo("No Workspace", "Create or load a workspace first.")
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in self._active_neighbourhood.name).strip("_")
        out_path = EXPORTS_DIR / f"{safe_name}_drainage_{stamp}.csv"
        return str(
            self.geojson_io.export_drainage_csv(
                self._active_neighbourhood, self._drainage_features, out_path
            )
        )

    # -------------------------------------------------------------------------
    # Background Network Operations (Thread + Queue + after)
    # -------------------------------------------------------------------------

    def _start_background_task(
        self,
        label: str,
        worker: Callable[[threading.Event], tuple[str, Any]],
    ) -> None:
        if self._is_busy:
            messagebox.showinfo("Operation in Progress", "Please wait or cancel the current background operation.")
            return

        self._is_busy = True
        self._cancel_event = threading.Event()
        self.activity_lbl.configure(text=label, fg=THEME["accent_hover"])
        self.progress_bar.start(12)
        self._update_header_status()

        cancel_ev = self._cancel_event

        def _runner() -> None:
            try:
                result_kind, payload = worker(cancel_ev)
                self._result_queue.put((result_kind, payload))
            except Exception as exc:
                logger.exception("Unhandled error in background task '%s'", label)
                self._result_queue.put(("error", str(exc)))

        threading.Thread(target=_runner, daemon=True).start()

    def cancel_background_task(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self.activity_lbl.configure(text="Cancelling...", fg=THEME["warning"])

    def set_force_offline_mode(self, force_offline: bool) -> None:
        self._force_offline = force_offline
        self.repo.set_setting("force_offline", "true" if force_offline else "false")
        self._refresh_all_views(reset_viewport=False)

    def _run_connectivity_probe(self) -> None:
        def _probe() -> None:
            reachable = check_internet_connectivity()
            self._result_queue.put(("connectivity", reachable))

        threading.Thread(target=_probe, daemon=True).start()

    def resolve_location_async(self, query: str) -> None:
        if self.is_offline_mode:
            messagebox.showwarning(
                "Offline Mode",
                "Cannot resolve new locations via Nominatim while OFFLINE. "
                "You can still work with saved workspaces or turn off Forced Offline in Settings.",
            )
            return

        def _worker(cancel_ev: threading.Event) -> tuple[str, Any]:
            try:
                results, from_cache = self.geocoding_service.search_location(
                    query=query,
                    cancel_event=cancel_ev,
                )
                return "geocoding_ok", (results, from_cache)
            except GeocodingError as exc:
                return "geocoding_err", str(exc)

        self._start_background_task(f"Resolving '{query}'...", _worker)

    def import_osm_async(self, force_refresh: bool = False) -> None:
        if self._active_neighbourhood is None or self._active_neighbourhood.id is None:
            return
        if self.is_offline_mode:
            messagebox.showwarning(
                "Offline Mode",
                "Cannot import new OpenStreetMap features while OFFLINE. Previously saved features remain intact.",
            )
            return

        ws = self._active_neighbourhood
        nid = ws.id

        def _worker(cancel_ev: threading.Event) -> tuple[str, Any]:
            try:
                features, from_cache = self.osm_service.fetch_features(
                    neighbourhood_id=nid,
                    min_lat=ws.min_latitude,
                    max_lat=ws.max_latitude,
                    min_lon=ws.min_longitude,
                    max_lon=ws.max_longitude,
                    force_refresh=force_refresh,
                    cancel_event=cancel_ev,
                )
                return "osm_ok", (nid, features, from_cache)
            except OSMImportError as exc:
                return "osm_err", str(exc)

        self._start_background_task(f"Importing OSM features for {ws.name}...", _worker)

    def start_simulation_async(self, sim_config: SimulationConfig) -> None:
        if self._active_neighbourhood is None or self._active_neighbourhood.id is None:
            messagebox.showwarning("Workspace Required", "Create or load a neighbourhood workspace first.")
            return
        if self._is_busy:
            messagebox.showinfo("Task Running", "Wait for the current background task to finish or reset it.")
            return

        nid = self._active_neighbourhood.id
        cells_snapshot = list(self._cells)
        drain_snapshot = list(self._drainage_features)
        pause_ev = threading.Event()
        self._sim_pause_event = pause_ev
        self.simulation_lab_view.set_running_state(True, paused=False)

        def _on_step(step_idx: int, total_steps: int, step_rec: Any) -> None:
            self._result_queue.put(("sim_progress", (step_idx, total_steps, step_rec)))

        def _worker(cancel_ev: threading.Event) -> tuple[str, Any]:
            try:
                out = run_simulation(
                    cells=cells_snapshot,
                    config=sim_config,
                    drainage_features=drain_snapshot,
                    neighbourhood_id=nid,
                    progress_callback=_on_step,
                    pause_event=pause_ev,
                    cancel_event=cancel_ev,
                )
                return "sim_ok", out
            except ValidationError as exc:
                return "sim_err", str(exc)

        self._start_background_task(
            f"Simulating '{sim_config.scenario_name}'...",
            _worker,
        )

    def toggle_simulation_pause(self) -> bool:
        if self._sim_pause_event is None:
            return False
        if self._sim_pause_event.is_set():
            self._sim_pause_event.clear()
            return False
        self._sim_pause_event.set()
        return True

    def reset_simulation_session(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        if self._sim_pause_event is not None:
            self._sim_pause_event.clear()
        self._sim_pause_event = None
        self.simulation_lab_view.set_running_state(False, paused=False)

    def load_saved_simulation(self, simulation_id: int) -> None:
        out = self.repo.load_simulation_output(simulation_id)
        if out is None:
            messagebox.showwarning("Not Found", f"Saved simulation #{simulation_id} could not be loaded.")
            return
        self._active_sim_output_id = out.run.id
        self.simulation_lab_view.display_output(out)
        self.flood_map_view.display_output(out)
        self.flood_charts_view.display_output(out)
        self.saferoute_view.set_simulation_output(out)

    def delete_saved_simulation(self, simulation_id: int) -> None:
        if self._active_sim_output_id == simulation_id:
            self._active_sim_output_id = None
        if hasattr(self, "scenario_comparison_view"):
            self.scenario_comparison_view._comp = None
        self.repo.delete_simulation_run(simulation_id)
        self._refresh_all_views(reset_viewport=False)

    def refresh_weather_async(self) -> None:
        if self._active_neighbourhood is None or self._active_neighbourhood.id is None:
            messagebox.showinfo(
                "Workspace Required",
                "Create or load a neighbourhood workspace first to retrieve weather for its coordinates.",
            )
            return

        ws = self._active_neighbourhood
        nid = ws.id
        if self.is_offline_mode:
            cached_snap = self.repo.get_latest_weather_observation(nid)
            if cached_snap is None:
                cached_snap = self.weather_service.get_cached_file_weather(
                    nid, ws.center_latitude, ws.center_longitude
                )
            self.weather_view.update_weather(
                ws,
                cached_snap,
                status_note="Offline mode active — displaying locally cached data (if available).",
            )
            return

        def _worker(_cancel_ev: threading.Event) -> tuple[str, Any]:
            try:
                snapshot = self.weather_service.fetch_live_weather(
                    neighbourhood_id=nid,
                    latitude=ws.center_latitude,
                    longitude=ws.center_longitude,
                )
                return "weather_ok", (nid, snapshot)
            except WeatherServiceError as exc:
                return "weather_err", (nid, str(exc))

        self._start_background_task(f"Fetching Open-Meteo data for {ws.name}...", _worker)

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._result_queue.get_nowait()
                self._handle_queue_result(kind, payload)
        except queue.Empty:
            pass
        finally:
            self.after(80, self._poll_queue)

    def _finish_busy(self, status_text: str = "Ready", color: str = THEME["text_muted"]) -> None:
        self._is_busy = False
        self._cancel_event = None
        self.progress_bar.stop()
        self.activity_lbl.configure(text=status_text, fg=color)
        self._update_header_status()

    def _handle_queue_result(self, kind: str, payload: Any) -> None:
        if kind == "connectivity":
            self._internet_reachable = bool(payload)
            self._refresh_all_views(reset_viewport=False)
            return

        if kind == "geocoding_ok":
            results, from_cache = payload
            self.map_editor_view.set_geocoding_results(results)
            src = "cache" if from_cache else "Nominatim"
            self.map_editor_view.set_status_message(
                f"Resolved {len(results)} candidate(s) via {src}. Review bounds & click 'Create / Load Workspace'.",
                THEME["success"],
            )
            self._internet_reachable = True
            self._finish_busy("Location resolved", THEME["success"])
            return

        if kind == "geocoding_err":
            self.map_editor_view.set_status_message(str(payload), THEME["error"])
            self._finish_busy("Location lookup failed", THEME["error"])
            messagebox.showerror("Geocoding Error", str(payload))
            return

        if kind == "osm_ok":
            nid, features, from_cache = payload
            saved_count = self.repo.replace_osm_features(nid, features)
            link_count = self.workspace_mgr.rebuild_feature_grid_links(nid)
            self._internet_reachable = True
            self._refresh_all_views(reset_viewport=False)
            src_note = "local cache" if from_cache else "Overpass API"
            msg = f"Imported {saved_count} feature(s) from {src_note}; {link_count} grid links built."
            self.map_editor_view.set_status_message(msg, THEME["success"])
            self._finish_busy("OSM import complete", THEME["success"])
            return

        if kind == "osm_err":
            self.map_editor_view.set_status_message(str(payload), THEME["warning"])
            self._finish_busy("OSM import failed", THEME["warning"])
            messagebox.showwarning("OpenStreetMap Import", str(payload))
            return

        if kind == "weather_ok":
            nid, snapshot = payload
            self.repo.save_weather_observation(snapshot)
            self._internet_reachable = True
            self._refresh_all_views(
                reset_viewport=False,
                weather_note="Live Open-Meteo model/forecast retrieved.",
            )
            self._finish_busy("Weather updated", THEME["success"])
            return

        if kind == "weather_err":
            nid, err_msg = payload
            self._internet_reachable = False
            self._refresh_all_views(
                reset_viewport=False,
                weather_note=f"Live fetch failed ({err_msg}). Showing cached data if available.",
            )
            self._finish_busy("Weather unavailable (using cache)", THEME["warning"])
            return

        if kind == "sim_progress":
            step_idx, total_steps, step_rec = payload
            self.simulation_lab_view.on_step_progress(step_idx, total_steps, step_rec)
            return

        if kind == "sim_ok":
            output = payload
            sim_id = self.repo.save_simulation_output(output)
            output.run.id = sim_id
            self._active_sim_output_id = sim_id
            self._sim_pause_event = None
            self.simulation_lab_view.set_running_state(False, paused=False)
            self.simulation_lab_view.display_output(output)
            self.flood_map_view.display_output(output)
            self.flood_charts_view.display_output(output)
            self.saferoute_view.set_simulation_output(output)
            if hasattr(self, "scenario_comparison_view"):
                self.scenario_comparison_view._comp = None
            self._refresh_all_views(reset_viewport=False)
            self._finish_busy(f"Simulation #{sim_id} saved", THEME["success"])
            return

        if kind == "sim_err":
            self._sim_pause_event = None
            self.simulation_lab_view.set_running_state(False, paused=False)
            self._finish_busy("Simulation stopped / error", THEME["warning"])
            messagebox.showwarning("Simulation Validation / Run", str(payload))
            return

        if kind == "error":
            self._sim_pause_event = None
            self.simulation_lab_view.set_running_state(False, paused=False)
            self._finish_busy("Operation error", THEME["error"])
            messagebox.showerror("Unexpected Error", str(payload))
