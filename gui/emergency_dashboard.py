"""Phase 6 Emergency Resource & Relief Management Dashboard hosting all 10 operational tabs."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from config import INVENTORY_CATEGORIES, THEME
from core.models import Neighbourhood
from database.db import DatabaseManager
from emergency.alert_manager import AlertManager, EmergencyAlertRecord
from emergency.inventory_manager import InventoryManager
from emergency.inventory_transactions import InventoryTransactionService
from emergency.operation_manager import DashboardOverviewStats, OperationManager
from emergency.rescue_team_manager import RescueTeamManager
from emergency.resource_allocator import ResourceAllocator
from emergency.shelter_manager import ShelterManager, ShelterRecord
from emergency.vehicle_manager import VehicleManager
from emergency.volunteer_manager import VolunteerManager
from gui.components import StatCard
from gui.inventory_screen import InventoryTab, ResourceAllocationTab
from gui.operation_screen import AlertsTab, OperationsTab, ReportsTab
from gui.rescue_team_screen import RescueTeamsTab, VehiclesTab, VolunteersTab
from gui.shelter_screen import SheltersTab


class EmergencyDashboardView(tk.Frame):
    """Main Phase 6 screen integrating overview analytics, 9 management tabs, and SafeRoute sync."""

    def __init__(
        self,
        parent: tk.Misc,
        db_manager: DatabaseManager,
        on_shelters_changed: Callable[[list[ShelterRecord]], None] | None = None,
        on_open_shelter_in_saferoute: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=14, pady=10)
        self.db = db_manager
        self.on_shelters_changed = on_shelters_changed
        self.on_open_shelter_in_saferoute = on_open_shelter_in_saferoute

        # Phase 6 Service Layer
        self.shelter_mgr = ShelterManager(db_manager)
        self.team_mgr = RescueTeamManager(db_manager)
        self.vehicle_mgr = VehicleManager(db_manager)
        self.volunteer_mgr = VolunteerManager(db_manager)
        self.tx_svc = InventoryTransactionService(db_manager)
        self.inv_mgr = InventoryManager(db_manager, self.tx_svc)
        self.allocator = ResourceAllocator(db_manager, self.tx_svc)
        self.op_mgr = OperationManager(db_manager)
        self.alert_mgr = AlertManager(db_manager)

        self._neighbourhood: Neighbourhood | None = None
        self._overview = DashboardOverviewStats()
        self._alerts: list[EmergencyAlertRecord] = []
        self._shelters: list[ShelterRecord] = []

        self._build_ui()

    def _build_ui(self) -> None:
        # Top Header Row
        top = tk.Frame(self, bg=THEME["bg_root"])
        top.pack(fill="x", pady=(0, 6))

        left_t = tk.Frame(top, bg=THEME["bg_root"])
        left_t.pack(side="left", fill="x", expand=True)
        tk.Label(
            left_t,
            text="Emergency Resource & Relief Management",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 15, "bold"),
            anchor="w",
        ).pack(anchor="w")
        self.sub_lbl = tk.Label(
            left_t,
            text="SQLite-backed shelters, rescue teams, vehicles, volunteers, relief inventory, allocations & reports.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(anchor="w")

        right_actions = tk.Frame(top, bg=THEME["bg_root"])
        right_actions.pack(side="right")
        ttk.Button(
            right_actions,
            text="Refresh & Reconcile Alerts",
            style="Accent.TButton",
            command=self.handle_data_changed,
        ).pack(side="right")

        # Prototype Notice Banner
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
                "EDUCATIONAL DECISION-SUPPORT PROTOTYPE ONLY: Not an official emergency dispatch system. "
                "All metrics reflect local SQLite entries only — no automatic dispatch, external messages, or invented counts."
            ),
            bg=THEME["warning_bg"],
            fg="#FDE68A",
            font=("Segoe UI", 8, "bold"),
            anchor="w",
            justify="left",
            wraplength=1040,
        )
        disc_lbl.pack(anchor="w", fill="x")
        disc.bind("<Configure>", lambda e: disc_lbl.configure(wraplength=max(360, e.width - 24)))

        # Notebook with all 10 tabs (§14)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.overview_tab = tk.Frame(self.notebook, bg=THEME["bg_root"], padx=10, pady=8)
        self._build_overview_tab(self.overview_tab)

        self.shelters_tab = SheltersTab(
            self.notebook,
            shelter_mgr=self.shelter_mgr,
            on_data_changed=self.handle_data_changed,
            on_plan_route_to_shelter=self.on_open_shelter_in_saferoute,
        )
        self.teams_tab = RescueTeamsTab(
            self.notebook,
            team_mgr=self.team_mgr,
            on_data_changed=self.handle_data_changed,
        )
        self.vehicles_tab = VehiclesTab(
            self.notebook,
            vehicle_mgr=self.vehicle_mgr,
            team_mgr=self.team_mgr,
            on_data_changed=self.handle_data_changed,
        )
        self.volunteers_tab = VolunteersTab(
            self.notebook,
            volunteer_mgr=self.volunteer_mgr,
            op_mgr=self.op_mgr,
            on_data_changed=self.handle_data_changed,
        )
        self.inventory_tab = InventoryTab(
            self.notebook,
            inv_mgr=self.inv_mgr,
            tx_svc=self.tx_svc,
            on_data_changed=self.handle_data_changed,
        )
        self.allocation_tab = ResourceAllocationTab(
            self.notebook,
            allocator=self.allocator,
            inv_mgr=self.inv_mgr,
            shelter_mgr=self.shelter_mgr,
            team_mgr=self.team_mgr,
            vehicle_mgr=self.vehicle_mgr,
            volunteer_mgr=self.volunteer_mgr,
            op_mgr=self.op_mgr,
            on_data_changed=self.handle_data_changed,
        )
        self.operations_tab = OperationsTab(
            self.notebook,
            op_mgr=self.op_mgr,
            shelter_mgr=self.shelter_mgr,
            team_mgr=self.team_mgr,
            vehicle_mgr=self.vehicle_mgr,
            on_data_changed=self.handle_data_changed,
        )
        self.alerts_tab = AlertsTab(
            self.notebook,
            alert_mgr=self.alert_mgr,
            on_data_changed=self.handle_data_changed,
        )
        self.reports_tab = ReportsTab(self.notebook, db=self.db)

        self._tab_frames = {
            "overview": self.overview_tab,
            "shelters": self.shelters_tab,
            "rescue_teams": self.teams_tab,
            "vehicles": self.vehicles_tab,
            "volunteers": self.volunteers_tab,
            "inventory": self.inventory_tab,
            "allocation": self.allocation_tab,
            "operations": self.operations_tab,
            "alerts": self.alerts_tab,
            "reports": self.reports_tab,
        }

        self.notebook.add(self.overview_tab, text="Overview")
        self.notebook.add(self.shelters_tab, text="Shelters")
        self.notebook.add(self.teams_tab, text="Rescue Teams")
        self.notebook.add(self.vehicles_tab, text="Vehicles")
        self.notebook.add(self.volunteers_tab, text="Volunteers")
        self.notebook.add(self.inventory_tab, text="Inventory")
        self.notebook.add(self.allocation_tab, text="Resource Allocation")
        self.notebook.add(self.operations_tab, text="Operations")
        self.notebook.add(self.alerts_tab, text="Alerts")
        self.notebook.add(self.reports_tab, text="Reports")

    def _build_overview_tab(self, parent: tk.Frame) -> None:
        # 8 Summary KPI Cards (§2)
        cards_grid = tk.Frame(parent, bg=THEME["bg_root"])
        cards_grid.pack(fill="x", pady=(0, 10))
        for col in range(4):
            cards_grid.columnconfigure(col, weight=1, uniform="e_cards")

        self.card_total_shelters = StatCard(cards_grid, "Total Registered Shelters", "0", "No shelters stored", THEME["accent"])
        self.card_avail_cap = StatCard(cards_grid, "Available Shelter Capacity", "0", "0 / 0 total capacity", THEME["success"])
        self.card_occ_cap = StatCard(cards_grid, "Occupied Shelter Capacity", "0", "0 full shelter(s)", THEME["info"])
        self.card_avail_teams = StatCard(cards_grid, "Available Rescue Teams", "0", "0 registered teams", THEME["accent_teal"])

        self.card_active_teams = StatCard(cards_grid, "Active Rescue Teams", "0", "Assigned or on operation", THEME["warning"])
        self.card_avail_vehicles = StatCard(cards_grid, "Available Vehicles", "0", "0 registered vehicles", THEME["info"])
        self.card_low_stock = StatCard(cards_grid, "Low-Stock Inventory Items", "0", "0 expired / near-expiry", THEME["error"])
        self.card_volunteers = StatCard(cards_grid, "Total Registered Volunteers", "0", "0 currently available", THEME["accent"])

        row1 = [self.card_total_shelters, self.card_avail_cap, self.card_occ_cap, self.card_avail_teams]
        row2 = [self.card_active_teams, self.card_avail_vehicles, self.card_low_stock, self.card_volunteers]
        for idx, c in enumerate(row1):
            c.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0), pady=(0, 8))
        for idx, c in enumerate(row2):
            c.grid(row=1, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0))

        # Lower 2-column split: Matplotlib Charts (Left) + Alerts & Activity Feed (Right)
        lower = tk.Frame(parent, bg=THEME["bg_root"])
        lower.pack(fill="both", expand=True)
        lower.columnconfigure(0, weight=3)
        lower.columnconfigure(1, weight=2)
        lower.rowconfigure(0, weight=1)

        chart_card = tk.Frame(
            lower,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        chart_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        chart_card.rowconfigure(1, weight=1)
        chart_card.columnconfigure(0, weight=1)

        tk.Label(
            chart_card,
            text="SHELTER OCCUPANCY & INVENTORY OVERVIEW (SQLite Derived)",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.fig = Figure(figsize=(7.2, 4.4), dpi=100, facecolor=THEME["bg_card"])
        self.ax_shelter = self.fig.add_subplot(211)
        self.ax_inventory = self.fig.add_subplot(212)
        self.fig.subplots_adjust(left=0.11, right=0.97, top=0.90, bottom=0.11, hspace=0.72)

        self.chart_canvas = FigureCanvasTkAgg(self.fig, master=chart_card)
        self.chart_widget = self.chart_canvas.get_tk_widget()
        self.chart_widget.configure(bg=THEME["bg_card"], highlightthickness=0)
        self.chart_widget.grid(row=1, column=0, sticky="nsew")

        # Right column: Active Alerts & Activity History
        right_col = tk.Frame(lower, bg=THEME["bg_root"])
        right_col.grid(row=0, column=1, sticky="nsew")
        right_col.rowconfigure(0, weight=1)
        right_col.rowconfigure(1, weight=1)
        right_col.columnconfigure(0, weight=1)

        alert_card = tk.Frame(
            right_col,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        alert_card.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        alert_card.rowconfigure(1, weight=1)
        alert_card.columnconfigure(0, weight=1)

        ahdr = tk.Frame(alert_card, bg=THEME["bg_card"])
        ahdr.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.alert_hdr_lbl = tk.Label(
            ahdr,
            text="ACTIVE RESOURCE ALERTS (0)",
            bg=THEME["bg_card"],
            fg=THEME["warning"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self.alert_hdr_lbl.pack(side="left")
        ttk.Button(ahdr, text="Open Alerts Tab", command=lambda: self.select_tab("alerts")).pack(side="right")

        self.alert_list = tk.Listbox(
            alert_card,
            bg=THEME["bg_input"],
            fg=THEME["text_primary"],
            selectbackground=THEME["accent_muted"],
            font=("Segoe UI", 8),
            bd=0,
            highlightthickness=0,
        )
        self.alert_list.grid(row=1, column=0, sticky="nsew")

        hist_card = tk.Frame(
            right_col,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=10,
            pady=8,
        )
        hist_card.grid(row=1, column=0, sticky="nsew")
        hist_card.rowconfigure(1, weight=1)
        hist_card.columnconfigure(0, weight=1)

        tk.Label(
            hist_card,
            text="RECENT EMERGENCY ACTIVITY LOG (SQLite)",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.activity_list = tk.Listbox(
            hist_card,
            bg=THEME["bg_input"],
            fg=THEME["text_secondary"],
            selectbackground=THEME["accent_muted"],
            font=("Segoe UI", 8),
            bd=0,
            highlightthickness=0,
        )
        self.activity_list.grid(row=1, column=0, sticky="nsew")

    # -------------------------------------------------------------------------
    # Public Workspace Refresh & Tab Selection
    # -------------------------------------------------------------------------

    def select_tab(self, tab_key: str) -> None:
        frame = self._tab_frames.get(tab_key)
        if frame is not None:
            self.notebook.select(frame)

    def set_neighbourhood(self, neighbourhood: Neighbourhood | None) -> None:
        self._neighbourhood = neighbourhood
        for tab in (
            self.shelters_tab,
            self.teams_tab,
            self.vehicles_tab,
            self.volunteers_tab,
            self.inventory_tab,
            self.allocation_tab,
            self.operations_tab,
            self.alerts_tab,
            self.reports_tab,
        ):
            tab.set_neighbourhood(neighbourhood)
        self.refresh_overview(reconcile_alerts=True)

    def handle_data_changed(self) -> None:
        """Reconcile alerts, refresh every Emergency sub-tab, and sync SafeRoute/FloodMap shelters."""
        self.refresh_overview(reconcile_alerts=True)
        for tab in (
            self.shelters_tab,
            self.teams_tab,
            self.vehicles_tab,
            self.volunteers_tab,
            self.inventory_tab,
            self.allocation_tab,
            self.operations_tab,
            self.alerts_tab,
        ):
            tab.refresh()
        if self.on_shelters_changed is not None:
            self.on_shelters_changed(self._shelters)

    def refresh_overview(self, reconcile_alerts: bool = False) -> None:
        if self._neighbourhood is None or self._neighbourhood.id is None:
            self._overview = DashboardOverviewStats()
            self._alerts = []
            self._shelters = []
        else:
            nid = self._neighbourhood.id
            if reconcile_alerts:
                self.alert_mgr.reconcile_alerts(nid)
            self._overview = self.op_mgr.get_dashboard_overview(nid)
            self._alerts = self.alert_mgr.list_alerts(nid, include_acknowledged=False)
            self._shelters = self.shelter_mgr.list_shelters(nid)

        s = self._overview
        self.card_total_shelters.update_card(
            f"{s.total_shelters:,}",
            f"{s.active_shelters} active • {s.full_shelters} full",
        )
        self.card_avail_cap.update_card(
            f"{s.available_shelter_capacity:,}",
            f"{s.available_shelter_capacity:,} / {s.total_shelter_capacity:,} total spaces",
        )
        self.card_occ_cap.update_card(
            f"{s.occupied_shelter_capacity:,}",
            f"{s.full_shelters} shelter(s) at full capacity",
        )
        self.card_avail_teams.update_card(
            f"{s.available_teams:,}",
            f"Of {s.total_teams} registered team(s)",
        )
        self.card_active_teams.update_card(
            f"{s.active_teams:,}",
            f"{s.active_operations} open emergency operation(s)",
        )
        self.card_avail_vehicles.update_card(
            f"{s.available_vehicles:,}",
            f"Of {s.total_vehicles} registered vehicle(s)",
        )
        self.card_low_stock.update_card(
            f"{s.low_stock_items:,}",
            f"{s.expiring_or_expired_items} expired / near-expiry item(s)",
            THEME["error"] if s.low_stock_items > 0 else THEME["success"],
        )
        self.card_volunteers.update_card(
            f"{s.total_volunteers:,}",
            f"{s.available_volunteers} currently available",
        )

        self.alert_hdr_lbl.configure(
            text=f"ACTIVE RESOURCE ALERTS ({len(self._alerts)})",
            fg=THEME["error"] if any(a.severity == "Critical" for a in self._alerts) else THEME["warning"],
        )
        self.alert_list.delete(0, "end")
        if not self._alerts:
            self.alert_list.insert("end", "No active unacknowledged resource alerts in SQLite.")
        else:
            for a in self._alerts[:25]:
                self.alert_list.insert("end", f"[{a.severity.upper()}] {a.title} — {a.description}")

        self.activity_list.delete(0, "end")
        if not s.recent_activity:
            self.activity_list.insert("end", "No emergency transactions, allocations, or operations recorded yet.")
        else:
            for line in s.recent_activity:
                self.activity_list.insert("end", line)

        self._redraw_charts()

    def _redraw_charts(self) -> None:
        self.ax_shelter.clear()
        self.ax_inventory.clear()

        for ax in (self.ax_shelter, self.ax_inventory):
            ax.set_facecolor(THEME["bg_input"])
            for sp in ax.spines.values():
                sp.set_color(THEME["border"])
            ax.tick_params(colors=THEME["text_secondary"], labelsize=8)

        # Chart 1: Shelter Occupancy
        self.ax_shelter.set_title(
            "Shelter Occupancy vs Available Capacity", color=THEME["text_primary"], fontsize=9, fontweight="bold"
        )
        shelters_vis = self._shelters[:6]
        if not shelters_vis:
            self.ax_shelter.text(
                0.5, 0.5, "No shelters registered in SQLite",
                ha="center", va="center", color=THEME["text_muted"], fontsize=9,
                transform=self.ax_shelter.transAxes,
            )
            self.ax_shelter.set_xticks([])
            self.ax_shelter.set_yticks([])
        else:
            names = [s.name[:13] + ("…" if len(s.name) > 13 else "") for s in shelters_vis]
            occ = [s.occupied_capacity for s in shelters_vis]
            avail = [s.available_capacity for s in shelters_vis]
            x = list(range(len(names)))
            self.ax_shelter.bar(x, occ, label="Occupied", color="#F59E0B", width=0.5)
            self.ax_shelter.bar(x, avail, bottom=occ, label="Available", color="#14B8A6", width=0.5)
            self.ax_shelter.set_xticks(x)
            self.ax_shelter.set_xticklabels(names, rotation=0, ha="center", fontsize=7.5)
            self.ax_shelter.set_ylabel("Capacity", color=THEME["text_secondary"], fontsize=8)
            self.ax_shelter.legend(
                loc="upper right", facecolor=THEME["bg_card"], edgecolor=THEME["border"],
                labelcolor=THEME["text_primary"], fontsize=7,
            )

        # Chart 2: Inventory Items by Category
        self.ax_inventory.set_title(
            "Registered Inventory Items by Category", color=THEME["text_primary"], fontsize=9, fontweight="bold"
        )
        counts_map = self._overview.inventory_by_category
        if not counts_map:
            self.ax_inventory.text(
                0.5, 0.5, "No inventory items registered in SQLite",
                ha="center", va="center", color=THEME["text_muted"], fontsize=9,
                transform=self.ax_inventory.transAxes,
            )
            self.ax_inventory.set_xticks([])
            self.ax_inventory.set_yticks([])
        else:
            cats = list(INVENTORY_CATEGORIES)
            vals = [counts_map.get(c, 0) for c in cats]
            short_cats = [c.replace("Rescue equipment", "Equipment").replace("Food and water", "Food/Water") for c in cats]
            self.ax_inventory.bar(short_cats, vals, color=["#38BDF8", "#EF4444", "#F59E0B", "#14B8A6"], width=0.5)
            self.ax_inventory.set_ylabel("Item Types", color=THEME["text_secondary"], fontsize=8)
            self.ax_inventory.yaxis.get_major_locator().set_params(integer=True)

        self.chart_canvas.draw_idle()
