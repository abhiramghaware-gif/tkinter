"""Comprehensive PDF & CSV Report Generator (12 professional Phase 7 reports)."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from config import (
    APP_NAME,
    APP_SUBTITLE,
    APP_VERSION,
    EXPORTS_DIR,
    REPORT_TYPES,
    RISK_BADGE_COLORS,
    RISK_CATEGORIES,
)
from core.flood_statistics import compute_timestep_statistics, extract_step_cell_data
from core.models import DrainageFeature, GridCell, Neighbourhood, OSMFeature, WeatherSnapshot
from core.risk_classifier import PROTOTYPE_RISK_DISCLAIMER, RiskThresholds, classify_flood_depth
from core.scenario_comparator import ExtendedScenarioComparison, compare_multiple_scenarios
from core.simulation_engine import SimulationOutput
from database.backup_manager import DatabaseBackupManager
from database.db import DatabaseManager
from database.repository import FloodGuardRepository
from emergency.emergency_exports import (
    export_inventory_report,
    export_operations_report,
    export_rescue_teams_report,
    export_shelter_occupancy_report,
)
from emergency.operation_manager import OperationManager
from routing.flood_exposure import RoadExposureThresholds, analyze_road_network_exposure
from routing.road_network import RoadNetworkGraph

DISCLAIMER_TEXT = (
    "EDUCATIONAL PROTOTYPE DISCLAIMER: CHENNAI FLOODGUARD is an academic urban flood simulation "
    "and emergency decision-support prototype. Simulated water depths, risk categories, and route "
    "estimates depend on simplified water-balance assumptions, editable infiltration rates, and local "
    "inputs. They are NOT official flood forecasts, meteorological warnings, or emergency dispatch directives."
)


@dataclass(slots=True)
class ReportGenerationResult:
    """Metadata describing a generated PDF or CSV report."""

    report_key: str
    report_title: str
    output_path: Path
    file_format: str
    page_count: int
    generated_at_utc: str
    notes: str = ""


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_elev(cell: GridCell) -> float | None:
    if cell.mean_elevation_m is not None and math.isfinite(cell.mean_elevation_m):
        return float(cell.mean_elevation_m)
    if cell.elevation_m is not None and math.isfinite(cell.elevation_m):
        return float(cell.elevation_m)
    return None


def _draw_page_chrome(
    fig: Figure,
    title: str,
    subtitle: str,
    page_num: int,
    total_pages: int | str,
    generated_utc: str,
    neighbourhood_name: str,
) -> None:
    """Apply consistent navy/teal academic branding, header bar, and page footer."""
    fig.patch.set_facecolor("#FFFFFF")
    # Header strip
    fig.text(
        0.05, 0.96, f"{APP_NAME}  |  {neighbourhood_name}",
        fontsize=9, fontweight="bold", color="#0F766E",
    )
    fig.text(
        0.95, 0.96, f"v{APP_VERSION}",
        fontsize=8, color="#475569", ha="right",
    )
    fig.text(0.05, 0.932, title, fontsize=14, fontweight="bold", color="#0F172A")
    fig.text(0.05, 0.910, subtitle, fontsize=9, color="#475569")
    ax_line = fig.add_axes([0.05, 0.896, 0.90, 0.004])
    ax_line.set_axis_off()
    ax_line.axhspan(0, 1, color="#06B6D4")

    # Footer
    fig.text(
        0.05, 0.025,
        f"Generated: {generated_utc}  |  Educational Prototype — Not Official Guidance",
        fontsize=7.5, color="#64748B",
    )
    fig.text(
        0.95, 0.025,
        f"Page {page_num} of {total_pages}",
        fontsize=8, fontweight="bold", color="#334155", ha="right",
    )


def _draw_text_and_tables(
    pdf: PdfPages,
    *,
    title: str,
    subtitle: str,
    neighbourhood_name: str,
    generated_utc: str,
    page_counter: list[int],
    total_pages: int | str,
    sections: list[tuple[str, list[list[str]]]],
    prose_blocks: list[tuple[str, str]] | None = None,
) -> None:
    """Render clean multi-table / structured text page into PdfPages."""
    fig = Figure(figsize=(11, 8.5), dpi=130)
    page_counter[0] += 1
    _draw_page_chrome(fig, title, subtitle, page_counter[0], total_pages, generated_utc, neighbourhood_name)

    y_cursor = 0.86
    if prose_blocks:
        for heading, body in prose_blocks:
            fig.text(0.05, y_cursor, heading, fontsize=10.5, fontweight="bold", color="#0F172A")
            y_cursor -= 0.022
            wrapped_lines = _wrap_text(body, 118)
            fig.text(0.06, y_cursor, "\n".join(wrapped_lines), fontsize=8.5, color="#1E293B", va="top")
            y_cursor -= 0.018 * max(1, len(wrapped_lines)) + 0.02

    for sec_title, rows in sections:
        if y_cursor < 0.20:
            pdf.savefig(fig)
            fig.clf()
            fig = Figure(figsize=(11, 8.5), dpi=130)
            page_counter[0] += 1
            _draw_page_chrome(fig, title + " (cont.)", subtitle, page_counter[0], total_pages, generated_utc, neighbourhood_name)
            y_cursor = 0.86

        fig.text(0.05, y_cursor, sec_title, fontsize=10.5, fontweight="bold", color="#0E7490")
        y_cursor -= 0.016

        if not rows or len(rows) <= 1:
            fig.text(0.06, y_cursor - 0.01, "No records recorded in SQLite for this section.", fontsize=8.5, style="italic", color="#64748B")
            y_cursor -= 0.05
            continue

        row_count = min(len(rows), 18)
        table_rows = rows[:row_count]
        tbl_h = min(0.55, max(0.08, 0.026 * row_count + 0.02))
        if y_cursor - tbl_h < 0.06:
            pdf.savefig(fig)
            fig.clf()
            fig = Figure(figsize=(11, 8.5), dpi=130)
            page_counter[0] += 1
            _draw_page_chrome(fig, title + " (cont.)", subtitle, page_counter[0], total_pages, generated_utc, neighbourhood_name)
            y_cursor = 0.86
            fig.text(0.05, y_cursor, sec_title, fontsize=10.5, fontweight="bold", color="#0E7490")
            y_cursor -= 0.016

        ax = fig.add_axes([0.05, y_cursor - tbl_h, 0.90, tbl_h])
        ax.axis("off")
        clean_rows = [[str(c)[:56] for c in r] for r in table_rows]
        tbl = ax.table(cellText=clean_rows[1:], colLabels=clean_rows[0], loc="upper center", cellLoc="left")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(7.5)
        tbl.scale(1.0, 1.18)
        for (r_idx, _c_idx), cell in tbl.get_celld().items():
            cell.set_edgecolor("#CBD5E1")
            if r_idx == 0:
                cell.set_facecolor("#0F172A")
                cell.set_text_props(color="#F8FAFC", fontweight="bold")
            else:
                cell.set_facecolor("#F8FAFC" if r_idx % 2 == 1 else "#FFFFFF")
                cell.set_text_props(color="#0F172A")

        y_cursor = y_cursor - tbl_h - 0.03
        if len(rows) > row_count:
            fig.text(0.05, y_cursor + 0.01, f"(Showing first {row_count - 1} of {len(rows) - 1} rows — export CSV for complete dataset.)", fontsize=7.5, style="italic", color="#64748B")
            y_cursor -= 0.02

    pdf.savefig(fig)


def _wrap_text(text: str, width: int = 110) -> list[str]:
    words = text.split()
    lines: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for w in words:
        if cur_len + len(w) + (1 if cur else 0) > width:
            lines.append(" ".join(cur))
            cur = [w]
            cur_len = len(w)
        else:
            cur.append(w)
            cur_len += len(w) + (1 if cur[:-1] else 0)
    if cur:
        lines.append(" ".join(cur))
    return lines or [""]


class ReportGenerator:
    """Generates all 12 Phase 7 PDF and CSV reports strictly from real SQLite/computed outputs."""

    def __init__(self, db_manager: DatabaseManager, exports_dir: Path | str = EXPORTS_DIR) -> None:
        self.db = db_manager
        self.repo = FloodGuardRepository(db_manager)
        self.exports_dir = Path(exports_dir)
        self.backup_mgr = DatabaseBackupManager(db_manager)

    def generate_report(
        self,
        report_key: str,
        neighbourhood_id: int | None,
        *,
        file_format: str = "pdf",
        output_path: Path | str | None = None,
        simulation_id: int | None = None,
        comparison_sim_ids: list[int] | None = None,
        network: RoadNetworkGraph | None = None,
        thresholds: RiskThresholds | None = None,
        road_thresholds: RoadExposureThresholds | None = None,
    ) -> ReportGenerationResult:
        """Dispatch and generate any of the 12 report types in PDF or CSV format."""
        valid_keys = {k for k, _ in REPORT_TYPES}
        if report_key not in valid_keys:
            raise ValueError(f"Unsupported report key: {report_key}")

        fmt = file_format.strip().lower()
        if fmt not in ("pdf", "csv"):
            raise ValueError("file_format must be 'pdf' or 'csv'.")

        title_lookup = dict(REPORT_TYPES)
        report_title = title_lookup[report_key]
        gen_ts = _utc_stamp()

        if output_path is None:
            self.exports_dir.mkdir(parents=True, exist_ok=True)
            ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            out = self.exports_dir / f"floodguard_{report_key}_{ts_tag}.{fmt}"
        else:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)

        nb = self.repo.get_neighbourhood_by_id(neighbourhood_id) if neighbourhood_id is not None else None
        if nb is None:
            all_nb = self.repo.list_neighbourhoods()
            nb = all_nb[0] if all_nb else None
        nid = nb.id if nb is not None else None
        nb_name = f"{nb.name}, Chennai" if nb else "No Neighbourhood Selected"

        # Delegate Phase 6 emergency-only reports directly when requested as CSV
        emergency_map = {
            "shelter_capacity": export_shelter_occupancy_report,
            "emergency_resource": export_rescue_teams_report,
            "inventory": export_inventory_report,
            "emergency_operations": export_operations_report,
        }
        if fmt == "csv" and report_key in emergency_map and nb is not None:
            emergency_map[report_key](self.db, nb, out, fmt="csv")
            return ReportGenerationResult(report_key, report_title, out, "csv", 1, gen_ts, "Generated via SQLite Emergency Exporter (contacts redacted).")

        cells = self.repo.get_grid_cells(nid) if nid is not None else []
        osm_features = self.repo.get_osm_features(nid) if nid is not None else []
        drainage = self.repo.list_drainage_features(nid) if nid is not None else []
        weather_rows = self.repo.list_weather_observations(nid, limit=30) if nid is not None else []
        runs = self.repo.list_simulation_runs(nid) if nid is not None else []

        selected_output: SimulationOutput | None = None
        if simulation_id is not None:
            selected_output = self.repo.load_simulation_output(simulation_id)
        elif runs and runs[0].id is not None:
            selected_output = self.repo.load_simulation_output(runs[0].id)

        th = thresholds or RiskThresholds()
        rth = road_thresholds or RoadExposureThresholds()

        if fmt == "csv":
            return self._write_csv_report(
                report_key, report_title, out, gen_ts,
                nb=nb, cells=cells, osm_features=osm_features, drainage=drainage,
                weather_rows=weather_rows, runs=runs, selected_output=selected_output,
                comparison_sim_ids=comparison_sim_ids, network=network, th=th, rth=rth,
            )

        return self._write_pdf_report(
            report_key, report_title, out, gen_ts,
            nb=nb, nb_name=nb_name, cells=cells, osm_features=osm_features,
            drainage=drainage, weather_rows=weather_rows, runs=runs,
            selected_output=selected_output, comparison_sim_ids=comparison_sim_ids,
            network=network, th=th, rth=rth,
        )

    # ------------------------------------------------------------------
    # CSV Implementation for All 12 Reports
    # ------------------------------------------------------------------

    def _write_csv_report(
        self,
        report_key: str,
        report_title: str,
        out: Path,
        gen_ts: str,
        *,
        nb: Neighbourhood | None,
        cells: list[GridCell],
        osm_features: list[OSMFeature],
        drainage: list[DrainageFeature],
        weather_rows: list[WeatherSnapshot],
        runs: list[Any],
        selected_output: SimulationOutput | None,
        comparison_sim_ids: list[int] | None,
        network: RoadNetworkGraph | None,
        th: RiskThresholds,
        rth: RoadExposureThresholds,
    ) -> ReportGenerationResult:
        rows: list[list[Any]] = []
        nid = nb.id if nb else None

        if report_key == "neighbourhood_profile":
            dq = self.repo.get_data_quality_summary(nid)
            rows.append(["field", "value"])
            if nb is None:
                rows.append(["status", "No neighbourhood workspace stored in SQLite"])
            else:
                rows.extend([
                    ["name", nb.name],
                    ["district", nb.district or "Not provided"],
                    ["state", nb.state or "Not provided"],
                    ["country", nb.country or "Not provided"],
                    ["center_latitude", nb.center_latitude],
                    ["center_longitude", nb.center_longitude],
                    ["grid_dimensions", f"{nb.grid_rows} x {nb.grid_cols} ({len(cells)} cells)"],
                    ["osm_features_stored", len(osm_features)],
                    ["drainage_features_stored", len(drainage)],
                    ["elevation_populated_cells", max(0, dq.total_grid_cells - dq.missing_elevation_cells)],
                    ["land_use_populated_cells", max(0, dq.total_grid_cells - dq.missing_land_use_cells)],
                    ["saved_simulations", len(runs)],
                ])

        elif report_key == "geographical_data":
            rows.append(["source_table", "id", "name_or_code", "category_or_type", "provenance_or_status", "extra"])
            for c in cells:
                el = _safe_elev(c)
                rows.append([
                    "grid_cells", c.id, c.cell_code, c.land_use,
                    c.elevation_source,
                    f"elev_m={el if el is not None else 'NULL'}; infil={c.infiltration_rate}; drain={c.drainage_capacity}",
                ])
            for d in drainage:
                rows.append([
                    "drainage_features", d.id, d.name, d.feature_type,
                    f"{d.status} ({d.source})", f"cap={d.capacity} {d.capacity_unit}",
                ])
            for f in osm_features[:200]:
                rows.append([
                    "osm_features", f.osm_id, f.name or "Unnamed", f.category,
                    f.subcategory, f"len_m={f.length_m:.1f}",
                ])

        elif report_key == "weather_data":
            rows.append(["id", "retrieved_at", "source", "temperature_c", "humidity_pct", "rainfall_mm", "precipitation_mm", "weather_description", "data_type"])
            for w in weather_rows:
                rows.append([
                    w.id, w.retrieved_at, w.source, w.temperature_c, w.humidity_pct,
                    w.rainfall_mm, w.precipitation_mm, w.weather_description, w.data_type,
                ])

        elif report_key in ("flood_simulation", "flood_risk_analysis"):
            rows.append([
                "simulation_id", "scenario_name", "cell_code", "land_use",
                "elevation_m", "elevation_source", "final_depth_cm", "max_depth_cm",
                "water_volume_m3", "infiltration_m3", "drainage_m3", "risk_category",
            ])
            if selected_output and selected_output.steps:
                last_step = selected_output.steps[-1].timestep
                d_map, v_map, _ = extract_step_cell_data(selected_output, last_step)
                cell_by_id = {c.id: c for c in cells if c.id is not None}
                for cf in selected_output.final_cells:
                    c_obj = cell_by_id.get(cf.cell_id)
                    el = _safe_elev(c_obj) if c_obj else None
                    d_m = d_map.get(cf.cell_id, cf.final_water_depth_m)
                    rows.append([
                        selected_output.run.id, selected_output.run.scenario_name, cf.cell_code, cf.land_use,
                        f"{el:.3f}" if el is not None else "Not provided",
                        cf.elevation_provenance,
                        f"{d_m * 100.0:.3f}", f"{cf.max_water_depth_m * 100.0:.3f}",
                        f"{v_map.get(cf.cell_id, cf.final_water_volume_m3):.3f}",
                        f"{cf.total_infiltration_m3:.3f}", f"{cf.total_drainage_m3:.3f}",
                        classify_flood_depth(d_m, th),
                    ])

        elif report_key == "scenario_comparison":
            comp = self._load_comparison(runs, comparison_sim_ids, cells, network, th, rth)
            rows.append([
                "run_id", "scenario_name", "rainfall_mm_hr", "duration_min", "drainage_scale",
                "max_depth_cm", "avg_depth_cm", "peak_time_min", "affected_area_m2",
                "affected_cells", "high_risk_cells", "very_high_risk_cells",
                "total_infiltration_m3", "total_drainage_m3", "exposed_high_roads", "route_passable",
            ])
            if comp is not None:
                for r in comp.rows:
                    rows.append([
                        r.run_id, r.scenario_name, r.rainfall_intensity_mm_hr, r.rainfall_duration_min,
                        r.drainage_scale, round(r.max_depth_cm, 3), round(r.avg_depth_cm, 3),
                        round(r.peak_depth_time_min, 2), round(r.affected_area_m2, 2),
                        r.affected_cells, r.high_risk_cells, r.very_high_risk_cells,
                        round(r.total_infiltration_m3, 3), round(r.total_drainage_m3, 3),
                        r.exposed_high_roads if r.exposed_high_roads is not None else "N/A",
                        r.flood_aware_route_passable if r.flood_aware_route_passable is not None else "N/A",
                    ])

        elif report_key == "saferoute_analysis":
            rows.append(["record_type", "id_or_edge", "label", "road_type_or_mode", "distance_m_or_km", "exposure_or_time", "status_or_notes"])
            if network is not None and network.edges_by_id:
                last_st = selected_output.steps[-1].timestep if selected_output and selected_output.steps else None
                exps = analyze_road_network_exposure(network, cells, selected_output, timestep=last_st, thresholds=rth)
                for eid, e in list(exps.items())[:250]:
                    edge = network.edges_by_id[eid]
                    rows.append([
                        "road_segment", eid, edge.road_name or "Unnamed", edge.road_type,
                        f"{edge.distance_m:.1f} m", e.exposure_category, f"max_depth_cm={e.max_depth_cm}",
                    ])
            if nid is not None:
                for rh in self.repo.list_route_history(nid, limit=50):
                    rows.append([
                        "route_history", rh.get("id"), f"{rh.get('origin')} -> {rh.get('destination')}",
                        f"{rh.get('travel_mode')} / {rh.get('route_type')}",
                        f"{rh.get('total_distance', 0):.2f} km",
                        f"{rh.get('estimated_time', 0):.1f} min",
                        f"sim={rh.get('simulation_id')}",
                    ])

        else:
            # Complete project CSV summary
            op_mgr = OperationManager(self.db)
            stats = op_mgr.get_dashboard_overview(nid) if nid is not None else None
            audit = self.backup_mgr.audit_database()
            rows.append(["section", "metric", "value"])
            rows.append(["Project", "Application", f"{APP_NAME} v{APP_VERSION}"])
            rows.append(["Neighbourhood", "Active", nb.name if nb else "None"])
            rows.append(["GIS", "Grid Cells", len(cells)])
            rows.append(["GIS", "OSM Features", len(osm_features)])
            rows.append(["GIS", "Drainage Features", len(drainage)])
            rows.append(["Weather", "Stored Observations", len(weather_rows)])
            rows.append(["Simulation", "Saved Runs", len(runs)])
            if selected_output and selected_output.steps:
                last_st = compute_timestep_statistics(selected_output, selected_output.steps[-1].timestep, cells, th)
                rows.append(["Simulation", "Selected Run Max Depth (cm)", round(last_st.max_depth_cm, 2)])
                rows.append(["Simulation", "Selected Run Affected Cells", last_st.affected_cells])
            if stats:
                rows.append(["Emergency", "Registered Shelters", stats.total_shelters])
                rows.append(["Emergency", "Available Shelter Capacity", stats.available_shelter_capacity])
                rows.append(["Emergency", "Available Rescue Teams", stats.available_teams])
                rows.append(["Emergency", "Available Vehicles", stats.available_vehicles])
                rows.append(["Emergency", "Low Stock Inventory Items", stats.low_stock_items])
                rows.append(["Emergency", "Registered Volunteers", stats.total_volunteers])
            rows.append(["Database", "Audit Overall OK", audit.overall_ok])

        with out.open("w", newline="", encoding="utf-8") as fh:
            fh.write(f"# {APP_NAME} — {report_title}\n")
            fh.write(f"# neighbourhood: {nb.name if nb else 'None'}\n")
            fh.write(f"# generated_at_utc: {gen_ts}\n")
            fh.write(f"# disclaimer: {DISCLAIMER_TEXT}\n")
            writer = csv.writer(fh)
            writer.writerows(rows)

        return ReportGenerationResult(report_key, report_title, out, "csv", 1, gen_ts, "CSV exported strictly from SQLite.")

    # ------------------------------------------------------------------
    # PDF Implementation for All 12 Reports
    # ------------------------------------------------------------------

    def _write_pdf_report(
        self,
        report_key: str,
        report_title: str,
        out: Path,
        gen_ts: str,
        *,
        nb: Neighbourhood | None,
        nb_name: str,
        cells: list[GridCell],
        osm_features: list[OSMFeature],
        drainage: list[DrainageFeature],
        weather_rows: list[WeatherSnapshot],
        runs: list[Any],
        selected_output: SimulationOutput | None,
        comparison_sim_ids: list[int] | None,
        network: RoadNetworkGraph | None,
        th: RiskThresholds,
        rth: RoadExposureThresholds,
    ) -> ReportGenerationResult:
        page_counter = [0]
        nid = nb.id if nb else None

        with PdfPages(out) as pdf:
            if report_key == "flood_simulation":
                total_pages = 3
                self._render_flood_simulation_pdf(
                    pdf, page_counter, total_pages, gen_ts, nb, nb_name, cells, osm_features, drainage, selected_output, th
                )
            elif report_key == "flood_risk_analysis":
                total_pages = 2
                self._render_flood_risk_pdf(pdf, page_counter, total_pages, gen_ts, nb_name, cells, selected_output, th)
            elif report_key == "scenario_comparison":
                total_pages = 2
                comp = self._load_comparison(runs, comparison_sim_ids, cells, network, th, rth)
                self._render_comparison_pdf(pdf, page_counter, total_pages, gen_ts, nb_name, cells, runs, comp)
            elif report_key == "complete_project":
                total_pages = 5
                self._render_complete_project_pdf(
                    pdf, page_counter, total_pages, gen_ts, nb, nb_name, cells, osm_features, drainage,
                    weather_rows, runs, selected_output, network, th, rth,
                )
            elif report_key in ("shelter_capacity", "emergency_resource", "inventory", "emergency_operations"):
                total_pages = 1
                self._render_emergency_pdf_section(pdf, report_key, report_title, page_counter, total_pages, gen_ts, nid, nb_name)
            elif report_key == "neighbourhood_profile":
                dq = self.repo.get_data_quality_summary(nid)
                rows = [
                    ["Attribute", "Stored SQLite Value"],
                    ["Neighbourhood Name", nb.name if nb else "Not recorded"],
                    ["District / State", f"{nb.district or 'N/A'}, {nb.state or 'N/A'}" if nb else "N/A"],
                    ["Center Coordinates", f"{nb.center_latitude:.6f}, {nb.center_longitude:.6f}" if nb else "N/A"],
                    ["Simulation Grid", f"{nb.grid_rows} x {nb.grid_cols} ({len(cells)} cells)" if nb else "0"],
                    ["OSM Features Imported", str(len(osm_features))],
                    ["Drainage Infrastructure", str(len(drainage))],
                    ["Elevation Coverage", f"{max(0, dq.total_grid_cells - dq.missing_elevation_cells)}/{dq.total_grid_cells} cells"],
                    ["Land-Use Coverage", f"{max(0, dq.total_grid_cells - dq.missing_land_use_cells)}/{dq.total_grid_cells} cells"],
                    ["Saved Simulations", str(len(runs))],
                ]
                _draw_text_and_tables(
                    pdf, title=report_title, subtitle="SQLite Neighbourhood Profile",
                    neighbourhood_name=nb_name, generated_utc=gen_ts, page_counter=page_counter,
                    total_pages=1, sections=[("Neighbourhood Summary", rows)],
                    prose_blocks=[("Disclaimer", DISCLAIMER_TEXT)],
                )
            elif report_key == "geographical_data":
                counts = self.repo.get_osm_feature_counts(nid) if nid is not None else {}
                sum_rows = [
                    ["Dataset", "Count", "Notes"],
                    ["Grid Cells", str(len(cells)), "Hydrological & elevation attributes in SQLite"],
                    ["OSM Roads", str(counts.get("road", 0)), "OpenStreetMap ODbL"],
                    ["OSM Buildings", str(counts.get("building", 0)), "OpenStreetMap ODbL"],
                    ["OSM Waterways/Waterbodies", str(counts.get("waterway", 0) + counts.get("waterbody", 0)), "OpenStreetMap ODbL"],
                    ["Drainage Features", str(len(drainage)), "User-entered / imported local features"],
                ]
                drain_rows = [["Name", "Type", "Capacity", "Status", "Source"]]
                for d in drainage[:14]:
                    drain_rows.append([d.name, d.feature_type, f"{d.capacity} {d.capacity_unit}", d.status, d.source])
                _draw_text_and_tables(
                    pdf, title=report_title, subtitle="GIS Features, Provenance & Drainage",
                    neighbourhood_name=nb_name, generated_utc=gen_ts, page_counter=page_counter,
                    total_pages=1,
                    sections=[("Geographical Inventory Summary", sum_rows), ("Drainage Features", drain_rows)],
                    prose_blocks=[("Data Provenance Notice", "Only stored SQLite records are included; missing elevations remain NULL.")],
                )
            elif report_key == "weather_data":
                w_rows = [["Retrieved (UTC)", "Source", "Temp (C)", "Humidity %", "Rain (mm)", "Precip (mm)", "Type"]]
                for w in weather_rows[:16]:
                    t_s = f"{w.temperature_c:.1f}" if w.temperature_c is not None else "N/A"
                    h_s = f"{w.humidity_pct:.0f}" if w.humidity_pct is not None else "N/A"
                    r_s = f"{w.rainfall_mm:.1f}" if w.rainfall_mm is not None else "N/A"
                    p_s = f"{w.precipitation_mm:.1f}" if w.precipitation_mm is not None else "N/A"
                    w_rows.append([w.retrieved_at, w.source, t_s, h_s, r_s, p_s, w.data_type])
                _draw_text_and_tables(
                    pdf, title=report_title, subtitle="Optional Open-Meteo Observations & Cache Status",
                    neighbourhood_name=nb_name, generated_utc=gen_ts, page_counter=page_counter,
                    total_pages=1, sections=[("Weather Observations Log", w_rows)],
                    prose_blocks=[("Weather Feed Notice", "Open-Meteo model/forecast feed is optional. Hypothetical simulation rainfall presets are configured independently.")],
                )
            elif report_key == "saferoute_analysis":
                net_rows = [["Category", "Count", "Details"]]
                if network is not None:
                    last_st = selected_output.steps[-1].timestep if selected_output and selected_output.steps else None
                    exps = analyze_road_network_exposure(network, cells, selected_output, timestep=last_st, thresholds=rth)
                    hi = sum(1 for e in exps.values() if e.exposure_category in ("High", "Very high"))
                    mod = sum(1 for e in exps.values() if e.exposure_category == "Moderate")
                    unk = sum(1 for e in exps.values() if e.exposure_category == "Unknown")
                    net_rows.extend([
                        ["Road Graph Intersections", str(len(network.nodes_by_id)), "Derived from OSM highways"],
                        ["Road Segments", str(len(network.edges_by_id)), f"Total length {sum(e.distance_m for e in network.edges_by_id.values())/1000.0:.2f} km"],
                        ["High / Very High Exposure Edges", str(hi), f"Depth > {rth.moderate_max_cm:.0f} cm"],
                        ["Moderate Exposure Edges", str(mod), f"Depth {rth.low_max_cm:.0f}-{rth.moderate_max_cm:.0f} cm"],
                        ["Unknown Exposure Edges", str(unk), "Never treated as zero-cost safe"],
                    ])
                hist_rows = [["Route", "Mode", "Type", "Distance (km)", "Time (min)"]]
                for rh in (self.repo.list_route_history(nid, limit=12) if nid is not None else []):
                    hist_rows.append([
                        f"{rh.get('origin')} -> {rh.get('destination')}",
                        str(rh.get("travel_mode")), str(rh.get("route_type")),
                        f"{float(rh.get('total_distance', 0)):.2f}", f"{float(rh.get('estimated_time', 0)):.1f}",
                    ])
                _draw_text_and_tables(
                    pdf, title=report_title, subtitle="Road Exposure & Evacuation Route History",
                    neighbourhood_name=nb_name, generated_utc=gen_ts, page_counter=page_counter,
                    total_pages=1, sections=[("Road Network Exposure Summary", net_rows), ("Saved Route Calculations", hist_rows)],
                    prose_blocks=[("SafeRoute Disclaimer", DISCLAIMER_TEXT)],
                )

        return ReportGenerationResult(report_key, report_title, out, "pdf", max(1, page_counter[0]), gen_ts, "Multi-page academic PDF report generated.")

    # ------------------------------------------------------------------
    # Section 8 Compliant Flood Simulation PDF Report
    # ------------------------------------------------------------------

    def _render_flood_simulation_pdf(
        self,
        pdf: PdfPages,
        page_counter: list[int],
        total_pages: int,
        gen_ts: str,
        nb: Neighbourhood | None,
        nb_name: str,
        cells: list[GridCell],
        osm_features: list[OSMFeature],
        drainage: list[DrainageFeature],
        output: SimulationOutput | None,
        th: RiskThresholds,
    ) -> None:
        # Page 1: Cover Page (§8 Cover Page + Sections 1 & 2)
        fig = Figure(figsize=(11, 8.5), dpi=130)
        page_counter[0] += 1
        fig.patch.set_facecolor("#0B1120")

        sim_id_str = f"#{output.run.id}" if (output and output.run.id is not None) else "Unsaved / None"
        scen_title = output.run.scenario_name if output else "No Saved Simulation Selected"

        fig.text(0.08, 0.84, APP_NAME, fontsize=28, fontweight="bold", color="#22D3EE")
        fig.text(0.08, 0.79, APP_SUBTITLE, fontsize=12, color="#CBD5E1")
        fig.text(0.08, 0.71, "FLOOD SIMULATION TECHNICAL REPORT", fontsize=18, fontweight="bold", color="#F8FAFC")
        fig.text(0.08, 0.66, f"Scenario: {scen_title}", fontsize=13, color="#14B8A6")

        ax_sep = fig.add_axes([0.08, 0.635, 0.84, 0.006])
        ax_sep.set_axis_off()
        ax_sep.axhspan(0, 1, color="#06B6D4")

        meta_lines = [
            f"Neighbourhood:        {nb_name}",
            f"Simulation ID:        {sim_id_str}",
            f"Generation Date UTC:  {gen_ts}",
            f"Application Version:  {APP_VERSION}",
            f"Model Version:        {output.run.model_version if output else 'N/A'}",
        ]
        fig.text(0.08, 0.56, "\n".join(meta_lines), fontsize=11, color="#E2E8F0", family="monospace", va="top")

        # Disclaimer box on Cover
        ax_disc = fig.add_axes([0.08, 0.14, 0.84, 0.16])
        ax_disc.set_facecolor("#451A03")
        ax_disc.set_xticks([])
        ax_disc.set_yticks([])
        for sp in ax_disc.spines.values():
            sp.set_color("#F59E0B")
            sp.set_linewidth(1.5)
        ax_disc.text(0.02, 0.50, "\n".join(_wrap_text(DISCLAIMER_TEXT, 100)), color="#FDE68A", fontsize=9.5, va="center")

        fig.text(0.92, 0.04, f"Page {page_counter[0]} of {total_pages}", color="#94A3B8", fontsize=9, ha="right")
        pdf.savefig(fig)

        # Page 2: Sections 1, 2, 3, 5, 6
        if output is None or not output.steps:
            _draw_text_and_tables(
                pdf,
                title="Flood Simulation Results & Assumptions",
                subtitle="Sections 1-6 (Empty Simulation State)",
                neighbourhood_name=nb_name,
                generated_utc=gen_ts,
                page_counter=page_counter,
                total_pages=total_pages,
                sections=[],
                prose_blocks=[
                    ("Simulation Availability", "No saved simulation run was found in SQLite for this neighbourhood. Run a simulation in Simulation Lab before generating a detailed simulation report."),
                    ("Section 6: Disclaimer", DISCLAIMER_TEXT),
                ],
            )
            return

        last_step = output.steps[-1].timestep
        stats = compute_timestep_statistics(output, last_step, cells, th)
        elev_cells = sum(1 for c in cells if _safe_elev(c) is not None)
        manual_cells = sum(1 for c in cells if c.land_use_source == "user-entered" or c.infiltration_source == "user-entered")

        sec1_rows = [
            ["Section 1: Scenario Parameter", "Value"],
            ["Scenario Name", output.run.scenario_name],
            ["Rainfall Intensity", f"{output.run.rainfall_intensity:.1f} mm/hr ({output.run.distribution_pattern})"],
            ["Duration & Time Step", f"{output.run.rainfall_duration:.0f} min total / {output.run.time_step:.1f} min step ({output.summary.total_steps} steps)"],
            ["Simulation Mode", output.run.simulation_mode],
            ["Model Version", output.run.model_version],
        ]
        sec2_rows = [
            ["Section 2: Data Source Category", "Status in SQLite"],
            ["OpenStreetMap Geographical Data", f"{len(osm_features)} features stored (© OpenStreetMap contributors)"],
            ["Elevation Source", f"{elev_cells}/{len(cells)} cells have stored elevations" if elev_cells else "Not provided — illustrative slope assumptions used" if output.summary.used_illustrative_terrain else "Not provided"],
            ["Manually Entered Cell Edits", f"{manual_cells}/{len(cells)} cells edited by user"],
            ["Drainage Infrastructure", f"{len(drainage)} drainage feature(s) in neighbourhood model"],
            ["Illustrative Assumptions", "Land-use infiltration rates (mm/hr) and road/risk thresholds are prototype defaults unless edited."],
        ]
        sec3_rows = [
            ["Section 3: Simulation Result Metric", "Simulated Value"],
            ["Maximum Simulated Water Depth", f"{stats.max_depth_cm:.2f} cm ({stats.max_depth_m:.4f} m)"],
            ["Average Simulated Water Depth", f"{stats.avg_depth_cm:.2f} cm ({stats.avg_depth_m:.4f} m)"],
            ["Total Affected Area", f"{stats.affected_area_m2:,.1f} m2 ({stats.affected_area_ha:.2f} ha)"],
            ["Affected Grid Cells (>0.1 cm)", f"{stats.affected_cells} / {stats.total_cells} ({stats.affected_grid_pct:.1f}%)"],
            ["High & Very High Risk Cells", f"High: {stats.high_risk_cells} | Very High: {stats.very_high_risk_cells}"],
            ["Cumulative Water Balance", f"Rain={stats.cumulative_rainfall_m3:,.1f} m3 | Infil={stats.cumulative_infiltration_m3:,.1f} m3 | Drain={stats.cumulative_drainage_m3:,.1f} m3 | Error={output.summary.mass_balance_error_m3:.4f} m3"],
        ]
        interp_text = (
            f"At simulation completion (t={stats.sim_time_minutes:.0f} min), maximum simulated ponding reached "
            f"{stats.max_depth_cm:.2f} cm across {stats.affected_cells} of {stats.total_cells} grid cells "
            f"({stats.affected_area_m2:,.0f} m2). {stats.high_risk_cells + stats.very_high_risk_cells} cells exceeded "
            f"{th.moderate_max_cm:.0f} cm prototype depth thresholds. Limitations: simplified cellular water balance "
            f"omits pressurized pipe hydraulics and calibrated radar rainfall."
        )
        _draw_text_and_tables(
            pdf,
            title=f"Flood Simulation Summary (Run #{output.run.id})",
            subtitle="Sections 1, 2, 3, 5 & 6 — Scenario Inputs, Provenance, Outcomes & Limitations",
            neighbourhood_name=nb_name,
            generated_utc=gen_ts,
            page_counter=page_counter,
            total_pages=total_pages,
            sections=[
                ("Section 1: Scenario Details", sec1_rows),
                ("Section 2: Data Sources", sec2_rows),
                ("Section 3: Simulation Results (Final Timestep)", sec3_rows),
            ],
            prose_blocks=[
                ("Section 5: Scenario Interpretation & Limitations", interp_text),
                ("Section 6: Disclaimer", DISCLAIMER_TEXT),
            ],
        )

        # Page 3: Section 4 — 4 Required Visualizations (Heatmap, Risk Map, Max Depth vs Time, Affected Area vs Time)
        fig3 = Figure(figsize=(11, 8.5), dpi=130)
        page_counter[0] += 1
        _draw_page_chrome(
            fig3,
            f"Section 4: Flood Simulation Visualizations (Run #{output.run.id})",
            "Flood-Depth Heatmap, Risk Map, Max Depth vs Time & Affected Area vs Time",
            page_counter[0], total_pages, gen_ts, nb_name,
        )
        fig3.subplots_adjust(left=0.07, right=0.95, top=0.84, bottom=0.09, hspace=0.38, wspace=0.28)

        d_map, _, _ = extract_step_cell_data(output, last_step)
        max_r = max((c.row_number for c in cells), default=10)
        max_c = max((c.column_number for c in cells), default=10)
        depth_grid = [[0.0 for _ in range(max_c)] for _ in range(max_r)]
        risk_grid = [[0 for _ in range(max_c)] for _ in range(max_r)]
        risk_idx_map = {cat: i for i, cat in enumerate(RISK_CATEGORIES)}
        for idx, c in enumerate(cells):
            cid = c.id if c.id is not None else (idx + 1)
            r0 = min(max_r - 1, max(0, c.row_number - 1))
            c0 = min(max_c - 1, max(0, c.column_number - 1))
            dcm = d_map.get(cid, 0.0) * 100.0
            depth_grid[r0][c0] = dcm
            risk_grid[r0][c0] = risk_idx_map.get(classify_flood_depth(d_map.get(cid, 0.0), th), 0)

        ax1 = fig3.add_subplot(2, 2, 1)
        im1 = ax1.imshow(depth_grid, cmap="YlOrRd", aspect="auto")
        ax1.set_title("Flood-Depth Heatmap (cm)", fontsize=10, fontweight="bold")
        ax1.set_xlabel("Grid Column")
        ax1.set_ylabel("Grid Row")
        fig3.colorbar(im1, ax=ax1, fraction=0.046, pad=0.04)

        ax2 = fig3.add_subplot(2, 2, 2)
        from matplotlib.colors import ListedColormap
        cmap_risk = ListedColormap([RISK_BADGE_COLORS[c] for c in RISK_CATEGORIES])
        ax2.imshow(risk_grid, cmap=cmap_risk, vmin=0, vmax=len(RISK_CATEGORIES) - 1, aspect="auto")
        ax2.set_title("Prototype Flood Risk Classification Map", fontsize=10, fontweight="bold")
        ax2.set_xlabel("Grid Column")
        ax2.set_ylabel("Grid Row")
        handles = [Patch(facecolor=RISK_BADGE_COLORS[cat], label=cat) for cat in RISK_CATEGORIES]
        ax2.legend(handles=handles, loc="upper right", fontsize=6.5, framealpha=0.88)

        times = [s.sim_time_minutes for s in output.steps]
        max_depths_cm = [s.max_water_depth_m * 100.0 for s in output.steps]
        aff_areas_m2 = [s.total_area_affected_m2 for s in output.steps]

        ax3 = fig3.add_subplot(2, 2, 3)
        ax3.plot(times, max_depths_cm, color="#0284C7", marker="o", markersize=3, linewidth=2)
        ax3.fill_between(times, max_depths_cm, color="#38BDF8", alpha=0.2)
        ax3.set_title("Maximum Simulated Depth vs Time", fontsize=10, fontweight="bold")
        ax3.set_xlabel("Simulation Time (min)")
        ax3.set_ylabel("Max Depth (cm)")
        ax3.grid(True, linestyle="--", alpha=0.4)

        ax4 = fig3.add_subplot(2, 2, 4)
        ax4.plot(times, aff_areas_m2, color="#DC2626", marker="s", markersize=3, linewidth=2)
        ax4.fill_between(times, aff_areas_m2, color="#FCA5A5", alpha=0.25)
        ax4.set_title("Affected Area vs Time", fontsize=10, fontweight="bold")
        ax4.set_xlabel("Simulation Time (min)")
        ax4.set_ylabel("Affected Area (m2)")
        ax4.grid(True, linestyle="--", alpha=0.4)

        pdf.savefig(fig3)

    def _render_flood_risk_pdf(
        self,
        pdf: PdfPages,
        page_counter: list[int],
        total_pages: int,
        gen_ts: str,
        nb_name: str,
        cells: list[GridCell],
        output: SimulationOutput | None,
        th: RiskThresholds,
    ) -> None:
        if output is None or not output.steps:
            _draw_text_and_tables(
                pdf, title="Flood-Risk Analysis Report", subtitle="No Simulation Output Available",
                neighbourhood_name=nb_name, generated_utc=gen_ts, page_counter=page_counter,
                total_pages=1, sections=[], prose_blocks=[("Empty State", "No saved simulations exist in SQLite.")],
            )
            return
        last_step = output.steps[-1].timestep
        stats = compute_timestep_statistics(output, last_step, cells, th)
        tier_rows = [["Risk Tier", "Depth Threshold (cm)", "Cell Count", "Share (%)"]]
        total_c = max(1, stats.total_cells)
        for cat in RISK_CATEGORIES:
            cnt = stats.risk_stats.category_counts.get(cat, 0)
            tier_rows.append([cat, "Configurable", str(cnt), f"{cnt / total_c * 100:.1f}%"])
        top_cells = sorted(output.final_cells, key=lambda c: c.final_water_depth_m, reverse=True)[:12]
        cell_rows = [["Cell", "Land Use", "Elev Provenance", "Final Depth (cm)", "Risk Tier"]]
        for cf in top_cells:
            cell_rows.append([cf.cell_code, cf.land_use, cf.elevation_provenance, f"{cf.final_water_depth_m*100:.2f}", classify_flood_depth(cf.final_water_depth_m, th)])
        _draw_text_and_tables(
            pdf, title=f"Flood-Risk Analysis (Run #{output.run.id})",
            subtitle=f"Scenario: {output.run.scenario_name} | Prototypical Risk Tier Breakdown",
            neighbourhood_name=nb_name, generated_utc=gen_ts, page_counter=page_counter,
            total_pages=total_pages,
            sections=[("Risk Tier Summary", tier_rows), ("Highest-Depth Grid Cells (Top 12)", cell_rows)],
            prose_blocks=[("Risk Disclaimer", PROTOTYPE_RISK_DISCLAIMER)],
        )

    def _load_comparison(
        self,
        runs: list[Any],
        comparison_sim_ids: list[int] | None,
        cells: list[GridCell],
        network: RoadNetworkGraph | None,
        th: RiskThresholds,
        rth: RoadExposureThresholds,
    ) -> ExtendedScenarioComparison | None:
        ids = list(comparison_sim_ids or [])
        if not ids and len(runs) >= 2:
            ids = [int(r.id) for r in runs[: min(4, len(runs))] if r.id is not None]
        outs: list[SimulationOutput] = []
        for sid in ids:
            loaded = self.repo.load_simulation_output(sid)
            if loaded is not None:
                outs.append(loaded)
        if len(outs) < 2:
            return None
        return compare_multiple_scenarios(outs, cells, thresholds=th, network=network, road_thresholds=rth)

    def _render_comparison_pdf(
        self,
        pdf: PdfPages,
        page_counter: list[int],
        total_pages: int,
        gen_ts: str,
        nb_name: str,
        cells: list[GridCell],
        runs: list[Any],
        comp: ExtendedScenarioComparison | None,
    ) -> None:
        if comp is None:
            _draw_text_and_tables(
                pdf, title="Scenario Comparison Report", subtitle="Requires at least 2 saved simulations",
                neighbourhood_name=nb_name, generated_utc=gen_ts, page_counter=page_counter,
                total_pages=1, sections=[], prose_blocks=[("Insufficient Runs", "Save at least two simulations to generate a comparison report.")],
            )
            return

        comp_rows = [["Scenario", "Rain mm/h", "Drain x", "Max cm", "Avg cm", "Peak t", "Affected", "High+VH Risk", "Drain m3"]]
        for r in comp.rows:
            comp_rows.append([
                r.scenario_name[:28], f"{r.rainfall_intensity_mm_hr:.0f}", f"{r.drainage_scale:.2f}x",
                f"{r.max_depth_cm:.2f}", f"{r.avg_depth_cm:.2f}", f"{r.peak_depth_time_min:.0f}m",
                f"{r.affected_cells}", f"{r.high_risk_cells + r.very_high_risk_cells}", f"{r.total_drainage_m3:,.1f}",
            ])
        delta_rows = [["Comparison vs Baseline", "Metric", "Baseline", "Target", "Delta", "% Change"]]
        for alt_lbl, dlist in comp.pairwise_deltas[:2]:
            for d in dlist[:7]:
                delta_rows.append([alt_lbl[:22], d.metric_name, str(d.baseline_value), str(d.target_value), str(d.delta_value), d.pct_change_display])
        warn_text = " | ".join(comp.compatibility_warnings) if comp.compatibility_warnings else "All compared scenarios share compatible neighbourhood grid dimensions."
        _draw_text_and_tables(
            pdf, title="Multi-Scenario Comparison Report",
            subtitle=f"Baseline: {comp.baseline_label}", neighbourhood_name=nb_name,
            generated_utc=gen_ts, page_counter=page_counter, total_pages=total_pages,
            sections=[("Scenario Summary Table", comp_rows), ("Metric Differences & % Change", delta_rows)],
            prose_blocks=[("Compatibility & Config Notes", warn_text + "\n" + "\n".join(comp.config_differences[:3]))],
        )

        # Page 2: Comparison bar chart
        fig = Figure(figsize=(11, 8.5), dpi=130)
        page_counter[0] += 1
        _draw_page_chrome(fig, "Scenario Comparison Charts", "Max Depth, Affected Cells & Water Balance Removal", page_counter[0], total_pages, gen_ts, nb_name)
        fig.subplots_adjust(left=0.08, right=0.95, top=0.82, bottom=0.14, wspace=0.30)
        names = [r.scenario_name[:16] for r in comp.rows]
        x = list(range(len(names)))

        ax1 = fig.add_subplot(1, 2, 1)
        ax1.bar(x, [r.max_depth_cm for r in comp.rows], color="#0284C7")
        ax1.set_xticks(x)
        ax1.set_xticklabels(names, rotation=20, ha="right", fontsize=8)
        ax1.set_ylabel("Max Water Depth (cm)")
        ax1.set_title("Peak Flood Depth Comparison", fontsize=10, fontweight="bold")
        ax1.grid(axis="y", linestyle="--", alpha=0.4)

        ax2 = fig.add_subplot(1, 2, 2)
        ax2.bar([i - 0.18 for i in x], [r.total_infiltration_m3 for r in comp.rows], width=0.35, label="Infiltration (m3)", color="#10B981")
        ax2.bar([i + 0.18 for i in x], [r.total_drainage_m3 for r in comp.rows], width=0.35, label="Drainage (m3)", color="#F59E0B")
        ax2.set_xticks(x)
        ax2.set_xticklabels(names, rotation=20, ha="right", fontsize=8)
        ax2.set_ylabel("Cumulative Volume (m3)")
        ax2.set_title("Infiltration vs Drainage Removal", fontsize=10, fontweight="bold")
        ax2.legend(fontsize=8)
        ax2.grid(axis="y", linestyle="--", alpha=0.4)
        pdf.savefig(fig)

    def _render_emergency_pdf_section(
        self,
        pdf: PdfPages,
        report_key: str,
        report_title: str,
        page_counter: list[int],
        total_pages: int,
        gen_ts: str,
        nid: int | None,
        nb_name: str,
    ) -> None:
        from emergency import InventoryManager, RescueTeamManager, ResourceAllocator, ShelterManager, VehicleManager, VolunteerManager

        sh_mgr = ShelterManager(self.db)
        tm_mgr = RescueTeamManager(self.db)
        vh_mgr = VehicleManager(self.db)
        vo_mgr = VolunteerManager(self.db)
        in_mgr = InventoryManager(self.db)
        op_mgr = OperationManager(self.db)
        al_mgr = ResourceAllocator(self.db)

        sections: list[tuple[str, list[list[str]]]] = []
        if nid is not None:
            if report_key == "shelter_capacity":
                rows = [["Shelter", "Occ / Total", "Avail", "Status", "Verification"]]
                for s in sh_mgr.list_shelters(nid):
                    rows.append([s.name, f"{s.occupied_capacity}/{s.total_capacity}", str(s.available_capacity), s.status, "Physically Verified" if s.is_verified else "Registered (Unverified)"])
                sections.append(("Emergency Shelters (SQLite)", rows))
            elif report_key == "emergency_resource":
                trows = [["Team", "Leader", "Members", "Availability", "Location"]]
                for t in tm_mgr.list_teams(nid):
                    trows.append([t.team_name, t.leader or "N/A", str(len(t.members)), t.availability, t.current_location])
                vrows = [["Reg#", "Type", "Capacity", "Fuel", "Status"]]
                for v in vh_mgr.list_vehicles(nid):
                    vrows.append([v.registration_number, v.vehicle_type, str(v.capacity), v.fuel_status, v.operational_status])
                volrows = [["Volunteer", "Skills", "Availability", "Contact (Redacted)"]]
                for vo in vo_mgr.list_volunteers(nid):
                    volrows.append([vo.name, vo.skills, vo.availability, "[REDACTED FOR PRIVACY]"])
                sections.extend([("Rescue Teams", trows), ("Vehicles", vrows), ("Volunteers (Privacy Redacted)", volrows)])
            elif report_key == "inventory":
                irows = [["Item", "Category", "Qty", "Min", "Status", "Verification"]]
                for it in in_mgr.list_items(nid):
                    irows.append([it.item_name, it.category, f"{it.quantity:.1f} {it.unit}", f"{it.minimum_stock:.1f}", "LOW" if it.is_low_stock else "OK", it.verification_status])
                sections.append(("Relief Inventory", irows))
            else:
                orows = [["Operation", "Type", "Priority", "Destination", "Status"]]
                for op in op_mgr.list_operations(nid):
                    orows.append([op.operation_name, op.operation_type, op.priority, op.destination, op.status])
                arows = [["Type", "Resource", "Qty", "Destination", "Status"]]
                for al in al_mgr.list_allocations(nid)[:15]:
                    arows.append([al.resource_type, al.resource_label, f"{al.quantity:.1f}", al.destination_label, al.status])
                sections.extend([("Emergency Operations", orows), ("Resource Allocations", arows)])

        _draw_text_and_tables(
            pdf, title=report_title, subtitle="SQLite-Derived Emergency Resource Record (No Invented Counts)",
            neighbourhood_name=nb_name, generated_utc=gen_ts, page_counter=page_counter,
            total_pages=total_pages, sections=sections,
            prose_blocks=[("Privacy & Prototype Notice", DISCLAIMER_TEXT)],
        )

    def _render_complete_project_pdf(
        self,
        pdf: PdfPages,
        page_counter: list[int],
        total_pages: int,
        gen_ts: str,
        nb: Neighbourhood | None,
        nb_name: str,
        cells: list[GridCell],
        osm_features: list[OSMFeature],
        drainage: list[DrainageFeature],
        weather_rows: list[WeatherSnapshot],
        runs: list[Any],
        selected_output: SimulationOutput | None,
        network: RoadNetworkGraph | None,
        th: RiskThresholds,
        rth: RoadExposureThresholds,
    ) -> None:
        # Pages 1-3: Simulation Cover, Details, Visualizations (with total_pages=5)
        self._render_flood_simulation_pdf(
            pdf, page_counter, total_pages, gen_ts, nb, nb_name, cells, osm_features, drainage, selected_output, th
        )
        # Page 4: GIS, Weather & SafeRoute overview
        nid = nb.id if nb else None
        audit = self.backup_mgr.audit_database()
        w_latest = weather_rows[0] if weather_rows else None
        if w_latest is not None:
            wt = f"{w_latest.temperature_c:.1f} C" if w_latest.temperature_c is not None else "Temp N/A"
            wr = f"{w_latest.rainfall_mm:.1f} mm" if w_latest.rainfall_mm is not None else "Rain N/A"
            w_desc = f"{wt}, {wr} ({w_latest.retrieved_at})"
        else:
            w_desc = "Not recorded in SQLite"
        sys_rows = [
            ["Subsystem", "Recorded State"],
            ["Neighbourhood", nb_name],
            ["Grid & GIS", f"{len(cells)} grid cells | {len(osm_features)} OSM features | {len(drainage)} drainage features"],
            ["Latest Weather Record", w_desc],
            ["Road Network", f"{len(network.nodes_by_id)} nodes / {len(network.edges_by_id)} edges" if network else "Not built in memory"],
            ["SQLite Integrity Audit", f"v{audit.schema_version} | FK={'ON' if audit.foreign_keys_enabled else 'OFF'} | OK={audit.overall_ok}"],
        ]
        _draw_text_and_tables(
            pdf, title="Complete Project Summary — GIS, Weather, SafeRoute & DB Audit",
            subtitle="Integrated Phase 1–7 System Overview", neighbourhood_name=nb_name,
            generated_utc=gen_ts, page_counter=page_counter, total_pages=total_pages,
            sections=[("Integrated Subsystems Overview", sys_rows)],
        )
        # Page 5: Emergency Operations & Shelters Summary
        op_mgr = OperationManager(self.db)
        st = op_mgr.get_dashboard_overview(nid) if nid is not None else None
        em_rows = [
            ["Emergency Metric (SQLite Only)", "Count"],
            ["Registered Shelters", str(st.total_shelters if st else 0)],
            ["Available / Total Capacity", f"{st.available_shelter_capacity if st else 0} / {st.total_shelter_capacity if st else 0}"],
            ["Available / Active Rescue Teams", f"{st.available_teams if st else 0} / {st.active_teams if st else 0}"],
            ["Available / Total Vehicles", f"{st.available_vehicles if st else 0} / {st.total_vehicles if st else 0}"],
            ["Low-Stock Inventory Items", str(st.low_stock_items if st else 0)],
            ["Registered Volunteers (Contacts Private)", str(st.total_volunteers if st else 0)],
            ["Active Unacknowledged Alerts", str(st.unacknowledged_alerts if st else 0)],
        ]
        _draw_text_and_tables(
            pdf, title="Complete Project Summary — Emergency Resource Status",
            subtitle="SQLite Emergency Operations & Readiness Summary", neighbourhood_name=nb_name,
            generated_utc=gen_ts, page_counter=page_counter, total_pages=total_pages,
            sections=[("Emergency Management Readiness (SQLite Derived)", em_rows)],
            prose_blocks=[("Final Disclaimer", DISCLAIMER_TEXT)],
        )
