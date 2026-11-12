"""Optional Open-Meteo Weather Monitor view with offline cache & forecast chart."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from config import THEME
from core.models import Neighbourhood, WeatherSnapshot
from gui.components import StatCard
from services.weather_service import compute_snapshot_age, decode_wmo_weather_code


class WeatherPanelView(tk.Frame):
    """Displays Open-Meteo current model estimates, hourly forecast, and data provenance."""

    def __init__(
        self,
        parent: tk.Misc,
        on_refresh_weather: Callable[[], None],
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=20, pady=16)
        self.on_refresh_weather = on_refresh_weather
        self._is_offline = False
        self._is_busy = False
        self._has_workspace = False
        self._build_ui()

    def _build_ui(self) -> None:
        # Top Header Row
        top = tk.Frame(self, bg=THEME["bg_root"])
        top.pack(fill="x", pady=(0, 12))

        title_box = tk.Frame(top, bg=THEME["bg_root"])
        title_box.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_box,
            text="Hybrid Weather & Rainfall Monitor",
            bg=THEME["bg_root"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 17, "bold"),
        ).pack(anchor="w")
        self.coords_lbl = tk.Label(
            title_box,
            text="No active neighbourhood workspace selected.",
            bg=THEME["bg_root"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 10),
        )
        self.coords_lbl.pack(anchor="w")

        self.refresh_btn = ttk.Button(
            top,
            text="Refresh Weather (Manual)",
            style="Accent.TButton",
            command=self.on_refresh_weather,
        )
        self.refresh_btn.pack(side="right")

        # Status / Provenance Banner
        self.status_banner = tk.Frame(
            self,
            bg=THEME["bg_card_alt"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=14,
            pady=10,
        )
        self.status_banner.pack(fill="x", pady=(0, 12))

        self.banner_title_lbl = tk.Label(
            self.status_banner,
            text="Weather Status: Unavailable",
            bg=THEME["bg_card_alt"],
            fg=THEME["text_primary"],
            font=("Segoe UI", 10, "bold"),
        )
        self.banner_title_lbl.pack(anchor="w")

        self.banner_meta_lbl = tk.Label(
            self.status_banner,
            text="Click 'Refresh Weather' when online to retrieve Open-Meteo model & forecast data for the active workspace.",
            bg=THEME["bg_card_alt"],
            fg=THEME["text_secondary"],
            font=("Segoe UI", 9),
            wraplength=920,
            justify="left",
        )
        self.banner_meta_lbl.pack(anchor="w", pady=(2, 0))

        # 4 Current Model Metric Cards
        cards_row = tk.Frame(self, bg=THEME["bg_root"])
        cards_row.pack(fill="x", pady=(0, 12))
        for i in range(4):
            cards_row.columnconfigure(i, weight=1, uniform="wcards")

        self.card_temp = StatCard(cards_row, "Model Temperature", "—", "2m air temperature (Open-Meteo)", THEME["accent"])
        self.card_humidity = StatCard(cards_row, "Relative Humidity", "—", "2m relative humidity", THEME["accent_teal"])
        self.card_precip = StatCard(cards_row, "Model Precipitation", "—", "Total model step precipitation", THEME["info"])
        self.card_rain = StatCard(cards_row, "Model Rainfall", "—", "Liquid rain component", "#38BDF8")

        self.card_temp.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.card_humidity.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        self.card_precip.grid(row=0, column=2, sticky="nsew", padx=(0, 8))
        self.card_rain.grid(row=0, column=3, sticky="nsew")

        # Middle Split: Hourly Forecast Table (left) + Forecast Chart (right)
        split = tk.Frame(self, bg=THEME["bg_root"])
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=1)
        split.columnconfigure(1, weight=1)
        split.rowconfigure(0, weight=1)

        # Left: Hourly Forecast Table
        table_card = tk.Frame(
            split,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        table_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        tk.Label(
            table_card,
            text="Hourly Forecast Precipitation & Conditions (FORECAST DATA — Not Measured)",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        tree_wrap = tk.Frame(table_card, bg=THEME["bg_card"])
        tree_wrap.pack(fill="both", expand=True)

        cols = ("time", "temp", "hum", "precip", "rain", "cond")
        self.tree = ttk.Treeview(tree_wrap, columns=cols, show="headings", height=12)
        self.tree.heading("time", text="Local Time")
        self.tree.heading("temp", text="Temp (°C)")
        self.tree.heading("hum", text="RH (%)")
        self.tree.heading("precip", text="Precip (mm)")
        self.tree.heading("rain", text="Rain (mm)")
        self.tree.heading("cond", text="Forecast Condition")

        self.tree.column("time", width=125, anchor="w")
        self.tree.column("temp", width=70, anchor="e")
        self.tree.column("hum", width=65, anchor="e")
        self.tree.column("precip", width=80, anchor="e")
        self.tree.column("rain", width=75, anchor="e")
        self.tree.column("cond", width=130, anchor="w")

        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Right: Matplotlib Forecast Chart
        chart_card = tk.Frame(
            split,
            bg=THEME["bg_card"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=10,
        )
        chart_card.grid(row=0, column=1, sticky="nsew")

        tk.Label(
            chart_card,
            text="48-Hour Forecast Rainfall Profile (Open-Meteo)",
            bg=THEME["bg_card"],
            fg=THEME["accent_hover"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", pady=(0, 6))

        self.figure = Figure(figsize=(5.2, 3.6), dpi=100, facecolor=THEME["bg_card"])
        self.ax = self.figure.add_subplot(111)
        self.canvas_mpl = FigureCanvasTkAgg(self.figure, master=chart_card)
        self.canvas_mpl.get_tk_widget().pack(fill="both", expand=True)
        self._draw_empty_chart()

        # Bottom Data Distinction Legend
        dist_bar = tk.Frame(
            self,
            bg=THEME["bg_surface"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=12,
            pady=8,
        )
        dist_bar.pack(fill="x", pady=(10, 0))
        tk.Label(
            dist_bar,
            text=(
                "Data Distinction Policy:  [Observed Data] = physical station/gauge (none connected in Phase 1)  •  "
                "[Forecast / Model Data] = Open-Meteo numerical forecast  •  "
                "[Scenario Data] = hypothetical user rainfall (Phase 2)  •  "
                "[Simulated Output] = calculated flood depth (Phase 2)."
            ),
            bg=THEME["bg_surface"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            wraplength=960,
            justify="left",
        ).pack(anchor="w")

    def set_network_state(self, is_offline: bool, is_busy: bool) -> None:
        self._is_offline = is_offline
        self._is_busy = is_busy
        can_refresh = self._has_workspace and (not is_offline) and (not is_busy)
        self.refresh_btn.configure(state="normal" if can_refresh else "disabled")

    def update_weather(
        self,
        neighbourhood: Neighbourhood | None,
        snapshot: WeatherSnapshot | None,
        status_note: str = "",
    ) -> None:
        self._has_workspace = neighbourhood is not None
        if neighbourhood is None:
            self.coords_lbl.configure(text="Create or load a neighbourhood workspace to retrieve weather.")
        else:
            self.coords_lbl.configure(
                text=f"Target Workspace: {neighbourhood.name} ({neighbourhood.center_latitude:.5f}, {neighbourhood.center_longitude:.5f})"
            )

        self.set_network_state(self._is_offline, self._is_busy)

        for item in self.tree.get_children():
            self.tree.delete(item)

        if snapshot is None:
            self.banner_title_lbl.configure(
                text="Weather Status: Weather unavailable",
                fg=THEME["warning"],
            )
            self.banner_meta_lbl.configure(
                text=status_note
                or "No cached or live weather data is stored for this workspace yet."
            )
            self.card_temp.update_card("Unavailable", "No cached data")
            self.card_humidity.update_card("Unavailable", "No cached data")
            self.card_precip.update_card("Unavailable", "No cached data")
            self.card_rain.update_card("Unavailable", "No cached data")
            self._draw_empty_chart()
            return

        snap = compute_snapshot_age(snapshot)
        stale_badge = "  [STALE / CACHED]" if snap.is_stale else "  [RECENT]"
        title_color = THEME["warning"] if snap.is_stale else THEME["success"]
        self.banner_title_lbl.configure(
            text=f"Weather Status: {snap.weather_description}{stale_badge}",
            fg=title_color,
        )
        note_prefix = f"{status_note}  |  " if status_note else ""
        self.banner_meta_lbl.configure(
            text=(
                f"{note_prefix}Data Type: {snap.data_type}  |  Source: {snap.source}\n"
                f"Model Timestamp: {snap.observed_at or 'N/A'}  |  "
                f"Last Retrieved: {snap.retrieved_at} ({snap.age_label})"
            )
        )

        self.card_temp.update_card(
            f"{snap.temperature_c:.1f} °C" if snap.temperature_c is not None else "N/A",
            f"Condition: {snap.weather_description}",
        )
        self.card_humidity.update_card(
            f"{snap.humidity_pct:.0f} %" if snap.humidity_pct is not None else "N/A",
            "Model surface relative humidity",
        )
        self.card_precip.update_card(
            f"{snap.precipitation_mm:.2f} mm" if snap.precipitation_mm is not None else "N/A",
            "Current model step precipitation",
        )
        self.card_rain.update_card(
            f"{snap.rainfall_mm:.2f} mm" if snap.rainfall_mm is not None else "N/A",
            "Current model step liquid rain",
        )

        # Populate hourly forecast table & chart
        times_lbl: list[str] = []
        precip_vals: list[float] = []
        for pt in snap.hourly_forecast:
            t_disp = pt.time_iso.replace("T", " ")
            self.tree.insert(
                "",
                "end",
                values=(
                    t_disp,
                    f"{pt.temperature_c:.1f}" if pt.temperature_c is not None else "—",
                    f"{pt.humidity_pct:.0f}" if pt.humidity_pct is not None else "—",
                    f"{pt.precipitation_mm:.2f}" if pt.precipitation_mm is not None else "—",
                    f"{pt.rain_mm:.2f}" if pt.rain_mm is not None else "—",
                    decode_wmo_weather_code(pt.weather_code),
                ),
            )
            times_lbl.append(pt.time_iso[-5:] if len(pt.time_iso) >= 5 else pt.time_iso)
            precip_vals.append(pt.precipitation_mm or 0.0)

        self._draw_forecast_chart(times_lbl, precip_vals, snap.is_stale)

    def _draw_empty_chart(self) -> None:
        self.ax.clear()
        self.ax.set_facecolor("#0A101D")
        self.ax.text(
            0.5,
            0.5,
            "No hourly forecast data cached.\nRefresh Weather when online.",
            color=THEME["text_muted"],
            ha="center",
            va="center",
            transform=self.ax.transAxes,
            fontsize=9,
        )
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        for spine in self.ax.spines.values():
            spine.set_color(THEME["border"])
        self.canvas_mpl.draw_idle()

    def _draw_forecast_chart(self, labels: list[str], values: list[float], is_stale: bool) -> None:
        self.ax.clear()
        self.ax.set_facecolor("#0A101D")
        if not labels:
            self._draw_empty_chart()
            return

        x = list(range(len(values)))
        bar_color = THEME["warning"] if is_stale else THEME["accent"]
        self.ax.bar(x, values, color=bar_color, alpha=0.85, width=0.75)
        self.ax.set_ylabel("Forecast Precip (mm/hr)", color=THEME["text_secondary"], fontsize=8)
        self.ax.set_xlabel("Forecast Hour", color=THEME["text_secondary"], fontsize=8)
        self.ax.set_title(
            "Forecast Precipitation (Open-Meteo Model — Not Observed)",
            color=THEME["text_primary"],
            fontsize=9,
        )
        step = max(1, len(labels) // 8)
        tick_idx = list(range(0, len(labels), step))
        self.ax.set_xticks(tick_idx)
        self.ax.set_xticklabels([labels[i] for i in tick_idx], color=THEME["text_muted"], fontsize=7, rotation=25)
        self.ax.tick_params(axis="y", colors=THEME["text_muted"], labelsize=8)
        self.ax.grid(axis="y", color=THEME["border"], linestyle="--", alpha=0.45)
        for spine in self.ax.spines.values():
            spine.set_color(THEME["border"])
        self.figure.tight_layout()
        self.canvas_mpl.draw_idle()

