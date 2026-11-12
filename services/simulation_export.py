"""Phase 4 simulation output export service (CSV, GeoJSON, PDF Summary, PNG Charts)."""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# pyrefly: ignore[missing-import]
from matplotlib.backends.backend_pdf import PdfPages
# pyrefly: ignore[missing-import]
from matplotlib.figure import Figure

from config import APP_NAME, RISK_CATEGORIES
from core.flood_statistics import compute_timestep_statistics, extract_step_cell_data
from core.models import GridCell, Neighbourhood
from core.risk_classifier import (
    PROTOTYPE_RISK_DISCLAIMER,
    RiskThresholds,
    classify_flood_depth,
)
from core.simulation_engine import SimulationOutput
from core.validation import ValidationError


ASSUMPTIONS_AND_LIMITATIONS = (
    "Simplified cellular hydraulic-head water-balance prototype. Outputs depend on terrain mode "
    "(verified DEM vs illustrative slope), editable illustrative land-use infiltration assumptions, "
    "and user-entered drainage capacity. NOT an official flood-warning system or real-world observation."
)


def _export_metadata(
    neighbourhood: Neighbourhood,
    output: SimulationOutput,
    timestep: int,
) -> dict[str, Any]:
    return {
        "project_name": APP_NAME,
        "neighbourhood": neighbourhood.name,
        "simulation_id": output.run.id,
        "scenario_name": output.run.scenario_name,
        "simulation_date": output.run.completion_time or output.run.start_time,
        "exported_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "model_version": output.run.model_version,
        "simulation_mode": output.run.simulation_mode,
        "timestep": timestep,
        "data_source": (
            "Phase 3 Water-Balance Model + OpenStreetMap + "
            + (
                "Illustrative Assumed Terrain (Non-verified)"
                if output.summary.used_illustrative_terrain
                else "Stored Grid Elevations"
            )
        ),
        "assumptions_and_limitations": ASSUMPTIONS_AND_LIMITATIONS,
    }


def _validated_cell_elevation(cell: GridCell) -> tuple[float | None, str]:
    """Return real stored elevation or None (never export invented elevations)."""
    if cell.mean_elevation_m is not None and math.isfinite(cell.mean_elevation_m):
        return float(cell.mean_elevation_m), cell.elevation_source or "stored"
    if cell.elevation_m is not None and math.isfinite(cell.elevation_m):
        return float(cell.elevation_m), cell.elevation_source or "stored"
    return None, "Unset (NULL)"


def export_flood_depth_grid_csv(
    neighbourhood: Neighbourhood,
    output: SimulationOutput,
    cells: list[GridCell],
    timestep: int,
    output_path: Path | str,
    thresholds: RiskThresholds | None = None,
) -> Path:
    """Export per-cell simulated flood depth (cm & m), volume, and coordinates as CSV."""
    if not output.steps:
        raise ValidationError("Cannot export CSV: simulation contains no timestep results.")
    th = thresholds or RiskThresholds()
    th.validate()
    depths_map, vols_map, sim_time = extract_step_cell_data(output, timestep)
    meta = _export_metadata(neighbourhood, output, timestep)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        for k, v in meta.items():
            fh.write(f"# {k}: {v}\n")
        writer = csv.writer(fh)
        writer.writerow(
            [
                "cell_id",
                "cell_code",
                "row",
                "col",
                "center_lat",
                "center_lon",
                "ground_elevation_m",
                "elevation_source",
                "land_use",
                "sim_time_min",
                "water_depth_m",
                "water_depth_cm",
                "water_volume_m3",
                "risk_category",
            ]
        )
        for idx, cell in enumerate(cells):
            cid = cell.id if cell.id is not None else (idx + 1)
            d_m = float(depths_map.get(cid, 0.0))
            v_m3 = float(vols_map.get(cid, 0.0))
            elev, elev_src = _validated_cell_elevation(cell)
            risk_cat = classify_flood_depth(d_m, th)
            writer.writerow(
                [
                    cid,
                    cell.cell_code,
                    cell.row_number,
                    cell.column_number,
                    f"{cell.center_latitude:.6f}",
                    f"{cell.center_longitude:.6f}",
                    f"{elev:.3f}" if elev is not None else "",
                    elev_src,
                    cell.land_use,
                    f"{sim_time:.2f}",
                    f"{d_m:.6f}",
                    f"{d_m * 100.0:.3f}",
                    f"{v_m3:.3f}",
                    risk_cat,
                ]
            )
    return path


def export_risk_classification_csv(
    neighbourhood: Neighbourhood,
    output: SimulationOutput,
    cells: list[GridCell],
    timestep: int,
    output_path: Path | str,
    thresholds: RiskThresholds | None = None,
) -> Path:
    """Export per-cell prototype risk classification and threshold metadata as CSV."""
    if not output.steps:
        raise ValidationError("Cannot export Risk CSV: simulation contains no timestep results.")
    th = thresholds or RiskThresholds()
    th.validate()
    depths_map, _, sim_time = extract_step_cell_data(output, timestep)
    meta = _export_metadata(neighbourhood, output, timestep)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        for k, v in meta.items():
            fh.write(f"# {k}: {v}\n")
        fh.write(f"# risk_disclaimer: {PROTOTYPE_RISK_DISCLAIMER}\n")
        fh.write(
            f"# thresholds_cm: low<={th.low_max_cm}, moderate<={th.moderate_max_cm}, high<={th.high_max_cm}\n"
        )
        writer = csv.writer(fh)
        writer.writerow(
            [
                "cell_id",
                "cell_code",
                "center_lat",
                "center_lon",
                "area_m2",
                "sim_time_min",
                "water_depth_cm",
                "risk_category",
                "disclaimer",
            ]
        )
        for idx, cell in enumerate(cells):
            cid = cell.id if cell.id is not None else (idx + 1)
            d_m = float(depths_map.get(cid, 0.0))
            writer.writerow(
                [
                    cid,
                    cell.cell_code,
                    f"{cell.center_latitude:.6f}",
                    f"{cell.center_longitude:.6f}",
                    f"{cell.approx_area_sq_m():.2f}",
                    f"{sim_time:.2f}",
                    f"{d_m * 100.0:.3f}",
                    classify_flood_depth(d_m, th),
                    "Model estimate only; not official safety classification",
                ]
            )
    return path


def export_simulation_geojson(
    neighbourhood: Neighbourhood,
    output: SimulationOutput,
    cells: list[GridCell],
    timestep: int,
    output_path: Path | str,
    thresholds: RiskThresholds | None = None,
) -> Path:
    """Export simulated grid cell polygons and attributes as GeoJSON (valid coords only)."""
    if not output.steps:
        raise ValidationError("Cannot export GeoJSON: simulation contains no timestep results.")
    th = thresholds or RiskThresholds()
    th.validate()
    depths_map, vols_map, sim_time = extract_step_cell_data(output, timestep)
    meta = _export_metadata(neighbourhood, output, timestep)

    features: list[dict[str, Any]] = []
    for idx, cell in enumerate(cells):
        coords_ok = all(
            math.isfinite(v)
            for v in (cell.min_latitude, cell.max_latitude, cell.min_longitude, cell.max_longitude)
        )
        if not coords_ok or not (-90.0 <= cell.min_latitude < cell.max_latitude <= 90.0):
            raise ValidationError(
                f"Grid cell {cell.cell_code} lacks valid geographic coordinates; refusing to invent GeoJSON."
            )
        cid = cell.id if cell.id is not None else (idx + 1)
        d_m = float(depths_map.get(cid, 0.0))
        v_m3 = float(vols_map.get(cid, 0.0))
        elev, elev_src = _validated_cell_elevation(cell)
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [cell.min_longitude, cell.min_latitude],
                            [cell.max_longitude, cell.min_latitude],
                            [cell.max_longitude, cell.max_latitude],
                            [cell.min_longitude, cell.max_latitude],
                            [cell.min_longitude, cell.min_latitude],
                        ]
                    ],
                },
                "properties": {
                    "cell_id": cid,
                    "cell_code": cell.cell_code,
                    "row": cell.row_number,
                    "col": cell.column_number,
                    "ground_elevation_m": elev,
                    "elevation_source": elev_src,
                    "land_use": cell.land_use,
                    "sim_time_min": sim_time,
                    "water_depth_m": round(d_m, 6),
                    "water_depth_cm": round(d_m * 100.0, 3),
                    "water_volume_m3": round(v_m3, 3),
                    "risk_category": classify_flood_depth(d_m, th),
                },
            }
        )

    payload = {
        "type": "FeatureCollection",
        "metadata": meta,
        "features": features,
    }
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def export_charts_png(figure: Figure, output_path: Path | str, dpi: int = 160) -> Path:
    """Export a Matplotlib simulation chart Figure to PNG."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=dpi, facecolor=figure.get_facecolor(), bbox_inches="tight")
    return path


def export_simulation_summary_pdf(
    neighbourhood: Neighbourhood,
    output: SimulationOutput,
    cells: list[GridCell],
    timestep: int,
    output_path: Path | str,
    thresholds: RiskThresholds | None = None,
) -> Path:
    """Generate a multi-page PDF simulation report using Matplotlib PdfPages."""
    if not output.steps:
        raise ValidationError("Cannot export PDF: simulation contains no timestep results.")
    th = thresholds or RiskThresholds()
    th.validate()
    stats = compute_timestep_statistics(output, timestep, cells, th)
    meta = _export_metadata(neighbourhood, output, stats.timestep)

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with PdfPages(path) as pdf:
        # Page 1: Metadata, Disclaimer, KPI Summary & Risk Breakdown
        fig1 = Figure(figsize=(8.27, 11.69), dpi=120, facecolor="white")
        ax1 = fig1.add_axes([0.07, 0.05, 0.86, 0.90])
        ax1.axis("off")

        y = 0.98
        ax1.text(0.0, y, f"{APP_NAME} — Phase 4 Flood Simulation Report", fontsize=15, fontweight="bold", color="#0F172A")
        y -= 0.032
        ax1.text(0.0, y, f"Neighbourhood: {meta['neighbourhood']}  |  Run #{meta['simulation_id'] or 'mem'}: {meta['scenario_name']}", fontsize=10, color="#334155")
        y -= 0.024
        ax1.text(0.0, y, f"Date: {meta['simulation_date']}  |  Model: {meta['model_version']}  |  Mode: {meta['simulation_mode']}", fontsize=9, color="#475569")
        y -= 0.024
        ax1.text(0.0, y, f"Data Source: {meta['data_source']}", fontsize=8.5, color="#475569")
        y -= 0.045

        ax1.text(
            0.0,
            y,
            f"PROTOTYPE NOTICE & LIMITATIONS: {ASSUMPTIONS_AND_LIMITATIONS}",
            fontsize=8.2,
            color="#92400E",
            bbox={"boxstyle": "round,pad=0.5", "facecolor": "#FEF3C7", "edgecolor": "#F59E0B"},
            wrap=True,
        )
        y -= 0.085

        ax1.text(0.0, y, f"Summary Statistics at Step {stats.timestep} (t = {stats.sim_time_minutes:.1f} min)", fontsize=12, fontweight="bold", color="#0F172A")
        y -= 0.028
        summary_lines = [
            f"• Maximum Simulated Water Depth: {stats.max_depth_cm:.2f} cm ({stats.max_depth_m:.4f} m)",
            f"• Average Simulated Water Depth: {stats.avg_depth_cm:.2f} cm ({stats.avg_depth_m:.4f} m)",
            f"• Affected Grid Cells: {stats.affected_cells} / {stats.total_cells} ({stats.affected_grid_pct:.1f}%)",
            f"• Estimated Affected Area: {stats.affected_area_ha:.2f} ha ({stats.affected_area_m2:,.0f} m²)",
            f"• High-Risk Cells: {stats.high_risk_cells}  |  Very-High-Risk Cells: {stats.very_high_risk_cells}",
            f"• Cumulative Rainfall Input: {stats.cumulative_rainfall_m3:,.1f} m³",
            f"• Cumulative Infiltration Loss: {stats.cumulative_infiltration_m3:,.1f} m³",
            f"• Cumulative Drainage Removal: {stats.cumulative_drainage_m3:,.1f} m³",
            f"• Remaining Surface Water Volume: {stats.remaining_volume_m3:,.1f} m³",
            f"• Global Mass Balance Error: {output.summary.mass_balance_error_m3:.3e} m³ ({'PASS' if output.summary.mass_balance_passed else 'FAIL'})",
        ]
        for line in summary_lines:
            ax1.text(0.02, y, line, fontsize=9.5, color="#1E293B")
            y -= 0.026

        y -= 0.02
        ax1.text(0.0, y, "Illustrative Risk Category Breakdown", fontsize=12, fontweight="bold", color="#0F172A")
        y -= 0.025
        for cat in RISK_CATEGORIES:
            cnt = stats.risk_stats.category_counts.get(cat, 0)
            area_ha = stats.risk_stats.category_areas_m2.get(cat, 0.0) / 10_000.0
            ax1.text(0.02, y, f"• {cat}: {cnt} cell(s)  ({area_ha:.2f} ha)", fontsize=9.5, color="#1E293B")
            y -= 0.025

        pdf.savefig(fig1)

        # Page 2: Actual Simulation Time-Series Charts
        fig2 = Figure(figsize=(8.27, 11.69), dpi=120, facecolor="white")
        times = [s.sim_time_minutes for s in output.steps]
        ax_d = fig2.add_subplot(3, 1, 1)
        ax_d.plot(times, [s.max_water_depth_m * 100.0 for s in output.steps], color="#0284C7", lw=2, label="Max Depth (cm)")
        ax_d.set_title("Maximum Simulated Water Depth vs Time", fontsize=10, fontweight="bold")
        ax_d.set_ylabel("Depth (cm)")
        ax_d.grid(True, alpha=0.3)
        ax_d.legend(fontsize=8)

        ax_a = fig2.add_subplot(3, 1, 2)
        ax_a.plot(times, [s.total_area_affected_m2 / 10_000.0 for s in output.steps], color="#F97316", lw=2, label="Affected Area (ha)")
        ax_a.set_title("Affected Area vs Time", fontsize=10, fontweight="bold")
        ax_a.set_ylabel("Area (ha)")
        ax_a.grid(True, alpha=0.3)
        ax_a.legend(fontsize=8)

        ax_v = fig2.add_subplot(3, 1, 3)
        ax_v.plot(times, [s.rainfall_input_m3 for s in output.steps], color="#0EA5E9", lw=1.6, label="Rainfall (m³)")
        ax_v.plot(times, [s.infiltration_loss_m3 for s in output.steps], color="#10B981", lw=1.6, label="Infiltration (m³)")
        ax_v.plot(times, [s.drainage_loss_m3 for s in output.steps], color="#F59E0B", lw=1.6, label="Drainage (m³)")
        ax_v.set_title("Step Water Balance Fluxes vs Time", fontsize=10, fontweight="bold")
        ax_v.set_xlabel("Simulation Time (minutes)")
        ax_v.set_ylabel("Volume (m³)")
        ax_v.grid(True, alpha=0.3)
        ax_v.legend(fontsize=8)

        fig2.tight_layout(pad=2.0)
        pdf.savefig(fig2)

    return path


__all__ = [
    "ASSUMPTIONS_AND_LIMITATIONS",
    "export_charts_png",
    "export_flood_depth_grid_csv",
    "export_risk_classification_csv",
    "export_simulation_geojson",
    "export_simulation_summary_pdf",
]
