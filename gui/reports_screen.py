"""Phase 7 Reports & Analytics GUI covering all 12 PDF & CSV project reports."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from config import EXPORTS_DIR, REPORT_TYPES, THEME
from core.models import GridCell, Neighbourhood, OSMFeature
from core.risk_classifier import RiskThresholds
from core.simulation_engine import SimulationRunRecord
from routing.flood_exposure import RoadExposureThresholds
from routing.road_network import build_road_network_from_osm
from services.report_generator import DISCLAIMER_TEXT, ReportGenerator

logger = logging.getLogger(__name__)


class ReportsAnalyticsView(tk.Frame):
    """Unified Reports & Analytics screen generating all 12 PDF and CSV reports."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        get_db_manager: Callable[[], object],
        get_exports_dir: Callable[[], Path] = lambda: EXPORTS_DIR,
    ) -> None:
        super().__init__(parent, bg=THEME["bg_root"], padx=18, pady=14)
        self.get_db_manager = get_db_manager
        self.get_exports_dir = get_exports_dir

        self._neighbourhood: Neighbourhood | None = None
        self._cells: list[GridCell] = []
        self._osm_features: list[OSMFeature] = []
        self._runs: list[SimulationRunRecord] = []
        self._thresholds = RiskThresholds()
        self._road_thresholds = RoadExposureThresholds()
        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._busy = False

        self._build_ui()
        self.after(120, self._poll_queue)

    def _build_ui(self) -> None:
        hdr = tk.Frame(self, bg=THEME["bg_root"])
        hdr.pack(fill="x", pady=(0, 8))
        tk.Label(
            hdr, text="Reports & Analytics Center (PDF & CSV)",
            bg=THEME["bg_root"], fg=THEME["text_primary"], font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            hdr,
            text="Generate all 12 academic, simulation, SafeRoute, emergency resource & complete project reports offline from SQLite.",
            bg=THEME["bg_root"], fg=THEME["text_muted"], font=("Segoe UI", 9),
        ).pack(anchor="w")

        warn = tk.Frame(self, bg=THEME["warning_bg"], highlightbackground=THEME["warning"], highlightthickness=1, padx=10, pady=6)
        warn.pack(fill="x", pady=(0, 10))
        tk.Label(
            warn, text=DISCLAIMER_TEXT, bg=THEME["warning_bg"], fg="#FDE68A",
            font=("Segoe UI", 8, "bold"), wraplength=1040, justify="left",
        ).pack(anchor="w")

        split = tk.Frame(self, bg=THEME["bg_root"])
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=3, minsize=310)
        split.columnconfigure(1, weight=4)
        split.rowconfigure(0, weight=1)

        # Left: Report Catalog (12 reports)
        left = tk.Frame(split, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=10, pady=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        tk.Label(left, text="AVAILABLE REPORTS (1–12)", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.report_list = tk.Listbox(
            left, bg=THEME["bg_input"], fg=THEME["text_primary"],
            selectbackground=THEME["accent_muted"], selectforeground=THEME["accent_hover"],
            font=("Segoe UI", 9, "bold"), bd=0, highlightthickness=0, activestyle="none",
        )
        for _k, title in REPORT_TYPES:
            self.report_list.insert("end", title)
        self.report_list.select_set(3)  # Default: Flood Simulation Report
        self.report_list.grid(row=1, column=0, sticky="nsew")
        self.report_list.bind("<<ListboxSelect>>", lambda _e: self._update_details())

        # Right: Configuration, Preview & Export
        right = tk.Frame(split, bg=THEME["bg_card"], highlightbackground=THEME["border"], highlightthickness=1, padx=14, pady=12)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(4, weight=1)
        right.columnconfigure(0, weight=1)

        tk.Label(right, text="REPORT PARAMETERS & GENERATION", bg=THEME["bg_card"], fg=THEME["accent_hover"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))

        form = tk.Frame(right, bg=THEME["bg_card"])
        form.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        form.columnconfigure(1, weight=1)

        tk.Label(form, text="Primary Simulation Run:", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=3)
        self.sim_var = tk.StringVar()
        self.sim_cb = ttk.Combobox(form, textvariable=self.sim_var, state="readonly")
        self.sim_cb.grid(row=0, column=1, sticky="ew", pady=3)

        tk.Label(form, text="Compare Against (Option):", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self.sim_b_var = tk.StringVar()
        self.sim_b_cb = ttk.Combobox(form, textvariable=self.sim_b_var, state="readonly")
        self.sim_b_cb.grid(row=1, column=1, sticky="ew", pady=3)

        btn_row = tk.Frame(right, bg=THEME["bg_card"])
        btn_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(btn_row, text="Generate PDF Report", style="Accent.TButton", command=lambda: self._generate("pdf")).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="Export CSV Dataset", command=lambda: self._generate("csv")).pack(side="left", padx=(0, 8))
        self.status_lbl = tk.Label(btn_row, text="Ready", bg=THEME["bg_card"], fg=THEME["accent_teal"], font=("Segoe UI", 9, "bold"))
        self.status_lbl.pack(side="right")

        tk.Label(right, text="REPORT STRUCTURE & PROVENANCE NOTES", bg=THEME["bg_card"], fg=THEME["text_secondary"], font=("Segoe UI", 8, "bold")).grid(row=3, column=0, sticky="w", pady=(4, 4))
        self.desc_txt = tk.Text(right, bg=THEME["bg_input"], fg=THEME["text_secondary"], font=("Consolas", 9), relief="flat", wrap="word", height=12)
        self.desc_txt.grid(row=4, column=0, sticky="nsew")
        self._update_details()

    def refresh_workspace(
        self,
        neighbourhood: Neighbourhood | None,
        cells: list[GridCell],
        osm_features: list[OSMFeature],
        runs: list[SimulationRunRecord],
        thresholds: RiskThresholds | None = None,
        road_thresholds: RoadExposureThresholds | None = None,
    ) -> None:
        self._neighbourhood = neighbourhood
        self._cells = cells
        self._osm_features = osm_features
        self._runs = runs
        if thresholds is not None:
            self._thresholds = thresholds
        if road_thresholds is not None:
            self._road_thresholds = road_thresholds

        opts = [f"#{r.id}: {r.scenario_name} ({r.rainfall_intensity:.0f} mm/h)" for r in runs]
        self.sim_cb.configure(values=opts)
        self.sim_b_cb.configure(values=opts)
        if opts:
            self.sim_var.set(opts[0])
            self.sim_b_var.set(opts[1] if len(opts) >= 2 else opts[0])
        else:
            self.sim_var.set("")
            self.sim_b_var.set("")
        self._update_details()

    def _selected_key(self) -> tuple[str, str]:
        sel = self.report_list.curselection()
        idx = sel[0] if sel else 3
        return REPORT_TYPES[idx]

    def _update_details(self) -> None:
        key, title = self._selected_key()
        nb_lbl = self._neighbourhood.name if self._neighbourhood else "None"
        details = {
            "flood_simulation": (
                "Includes Cover Page (CHENNAI FLOODGUARD, Neighbourhood, Simulation ID, Date),\n"
                "Section 1: Scenario Details (Rainfall, Duration, Step, Mode, Model Version),\n"
                "Section 2: Data Sources (OSM, Elevation status or Assumed, Manual edits),\n"
                "Section 3: Simulation Results (Max/Avg depth, Area, Cells, Risk Breakdown),\n"
                "Section 4: 4 Visualizations (Heatmap, Risk Map, Max Depth vs Time, Area vs Time),\n"
                "Section 5: Interpretation & Limitations,\n"
                "Section 6: Prototype Disclaimer."
            ),
            "complete_project": (
                "Multi-page master report uniting Neighbourhood Profile, Flood Simulation Summary,\n"
                "4 Simulation Charts, GIS/Weather/SafeRoute/Database Integrity Audit, and SQLite-only\n"
                "Emergency Shelters, Teams, Vehicles, Inventory & Alert metrics."
            ),
            "emergency_resource": "Lists rescue teams, vehicles, and volunteers directly from SQLite with phone contacts REDACTED by default.",
        }
        extra = details.get(key, "Generated directly from live SQLite records without fabricated metrics; missing fields display 'Not recorded'.")
        self.desc_txt.configure(state="normal")
        self.desc_txt.delete("1.0", "end")
        self.desc_txt.insert(
            "end",
            f"Report: {title}\nActive Neighbourhood: {nb_lbl}\nSaved Simulations Available: {len(self._runs)}\n"
            f"Default Export Directory: {self.get_exports_dir()}\n\n{extra}\n",
        )
        self.desc_txt.configure(state="disabled")

    def _generate(self, fmt: str) -> None:
        if self._busy:
            return
        key, _title = self._selected_key()
        exp_dir = self.get_exports_dir()
        ext = ".pdf" if fmt == "pdf" else ".csv"
        out_path = filedialog.asksaveasfilename(
            title=f"Save {fmt.upper()} Report",
            initialdir=str(exp_dir),
            initialfile=f"floodguard_{key}{ext}",
            defaultextension=ext,
            filetypes=[(f"{fmt.upper()} Document", f"*{ext}")],
        )
        if not out_path:
            return

        sim_id = self._runs[self.sim_cb.current()].id if (0 <= self.sim_cb.current() < len(self._runs)) else None
        sim_b_id = self._runs[self.sim_b_cb.current()].id if (0 <= self.sim_b_cb.current() < len(self._runs)) else None
        cmp_ids = [sid for sid in (sim_b_id, sim_id) if sid is not None]
        if len(set(cmp_ids)) < 2:
            cmp_ids = [r.id for r in self._runs[:2] if r.id is not None]

        nid = self._neighbourhood.id if self._neighbourhood else None
        net = build_road_network_from_osm(nid, self._osm_features, self._cells) if (nid and self._osm_features) else None
        db_mgr = self.get_db_manager()
        th, rth = self._thresholds, self._road_thresholds

        self._busy = True
        self.status_lbl.configure(text=f"Generating {fmt.upper()}...", fg=THEME["warning"])

        def _worker() -> None:
            try:
                gen = ReportGenerator(db_mgr, exports_dir=exp_dir)  # type: ignore[arg-type]
                res = gen.generate_report(
                    key,
                    nid,
                    file_format=fmt,
                    output_path=out_path,
                    simulation_id=sim_id,
                    comparison_sim_ids=cmp_ids,
                    network=net,
                    thresholds=th,
                    road_thresholds=rth,
                )
                self._queue.put(("ok", res))
            except Exception as exc:
                logger.exception("Report generation error")
                self._queue.put(("err", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                self._busy = False
                if kind == "ok":
                    res = payload
                    self.status_lbl.configure(text=f"Saved ({res.file_format.upper()})", fg=THEME["success"])
                    messagebox.showinfo(
                        "Report Generated",
                        f"{res.report_title}\nFormat: {res.file_format.upper()} ({res.page_count} page(s))\nSaved to:\n{res.output_path}",
                    )
                else:
                    self.status_lbl.configure(text="Failed", fg=THEME["error"])
                    messagebox.showerror("Report Generation Error", str(payload))
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)
