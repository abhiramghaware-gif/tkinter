"""Multi-scenario comparison analytics, configuration diffs, & SafeRoute availability."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from core.flood_statistics import compute_timestep_statistics
from core.models import GridCell
from core.risk_classifier import RiskThresholds
from core.simulation_engine import SimulationOutput
from routing.flood_exposure import RoadExposureThresholds, analyze_road_network_exposure
from routing.road_network import RoadNetworkGraph
from routing.route_planner import RouteCostWeights, calculate_evacuation_routes


@dataclass(slots=True)
class MultiScenarioRow:
    """Comprehensive metric & SafeRoute summary for one simulated scenario."""

    run_id: int | None
    label: str
    scenario_name: str
    rainfall_intensity_mm_hr: float
    rainfall_duration_min: float
    time_step_min: float
    simulation_mode: str
    drainage_scale: float
    disabled_drainage_count: int
    extra_drainage_count: int
    infiltration_mean_rate: float
    max_depth_cm: float
    avg_depth_cm: float
    peak_depth_time_min: float
    affected_area_m2: float
    affected_cells: int
    high_risk_cells: int
    very_high_risk_cells: int
    total_infiltration_m3: float
    total_drainage_m3: float
    exposed_high_roads: int | None = None
    exposed_moderate_roads: int | None = None
    shortest_route_passable: bool | None = None
    flood_aware_route_passable: bool | None = None
    route_distance_km: float | None = None
    is_hypothetical_infra: bool = False


@dataclass(slots=True)
class MetricDeltaRow:
    """Comparison row between a baseline scenario and a target scenario."""

    metric_name: str
    unit: str
    baseline_value: float | str
    target_value: float | str
    delta_value: float | str
    pct_change_display: str
    pct_change_numeric: float | None = None


@dataclass(slots=True)
class ExtendedScenarioComparison:
    """Comparison results across 2+ simulation outputs including deltas, config diffs & warnings."""

    baseline_label: str
    rows: list[MultiScenarioRow]
    pairwise_deltas: list[tuple[str, list[MetricDeltaRow]]]
    config_differences: list[str]
    compatibility_warnings: list[str]
    are_compatible: bool
    route_probe_note: str = ""


def compute_meaningful_pct_change(baseline: float, target: float) -> tuple[float | None, str]:
    """Compute percentage change cleanly without divide-by-zero or misleading infinities."""
    if not (math.isfinite(baseline) and math.isfinite(target)):
        return None, "N/A"
    if abs(baseline) < 1e-9:
        if abs(target) < 1e-9:
            return 0.0, "0.0%"
        return None, "N/A (baseline=0)"
    pct = ((target - baseline) / abs(baseline)) * 100.0
    sign = "+" if pct > 0 else ""
    return pct, f"{sign}{pct:.1f}%"


def _build_scenario_row(
    out: SimulationOutput,
    cells: list[GridCell],
    thresholds: RiskThresholds,
    *,
    network: RoadNetworkGraph | None = None,
    origin_node_id: int | None = None,
    dest_node_id: int | None = None,
    closed_edge_ids: set[int] | None = None,
    road_thresholds: RoadExposureThresholds | None = None,
) -> MultiScenarioRow:
    last_step = out.steps[-1].timestep if out.steps else 0
    stats = compute_timestep_statistics(out, last_step, cells, thresholds)
    cfg = out.config

    # Exact peak depth occurrence across all steps
    peak_d = -1.0
    peak_t = float(out.summary.time_of_max_depth_minutes)
    max_ever_d = 0.0
    for s in out.steps:
        if s.max_water_depth_m > max_ever_d:
            max_ever_d = s.max_water_depth_m
        if s.max_water_depth_m > peak_d:
            peak_d = s.max_water_depth_m
            peak_t = s.sim_time_minutes

    infil_vals = list(cfg.category_infiltration_rates_mm_hr.values())
    mean_infil = (sum(infil_vals) / len(infil_vals)) if infil_vals else 0.0

    exposed_high: int | None = None
    exposed_mod: int | None = None
    short_ok: bool | None = None
    fa_ok: bool | None = None
    route_km: float | None = None

    if network is not None and network.edges_by_id:
        exposures = analyze_road_network_exposure(
            network,
            cells,
            out,
            timestep=last_step if last_step > 0 else None,
            thresholds=road_thresholds,
        )
        exposed_high = sum(1 for e in exposures.values() if e.exposure_category in ("High", "Very high"))
        exposed_mod = sum(1 for e in exposures.values() if e.exposure_category == "Moderate")
        if origin_node_id is not None and dest_node_id is not None:
            statuses = {eid: ("Closed" if eid in (closed_edge_ids or set()) else "Normal") for eid in network.edges_by_id}
            res = calculate_evacuation_routes(
                network,
                origin_node_id,
                dest_node_id,
                "Origin",
                "Destination",
                exposures,
                statuses,
                weights=RouteCostWeights(avoid_high_exposure=False),
                simulation_id=out.run.id,
                timestep=last_step,
            )
            short_ok = res.shortest is not None
            fa_ok = res.flood_aware is not None
            if res.flood_aware is not None:
                route_km = res.flood_aware.total_distance_km
            elif res.shortest is not None:
                route_km = res.shortest.total_distance_km

    label = f"#{out.run.id}: {out.run.scenario_name}" if out.run.id is not None else out.run.scenario_name
    return MultiScenarioRow(
        run_id=out.run.id,
        label=label,
        scenario_name=out.run.scenario_name,
        rainfall_intensity_mm_hr=float(out.run.rainfall_intensity),
        rainfall_duration_min=float(out.run.rainfall_duration),
        time_step_min=float(out.run.time_step),
        simulation_mode=out.run.simulation_mode,
        drainage_scale=float(cfg.drainage_capacity_scale),
        disabled_drainage_count=len(cfg.disabled_drainage_ids),
        extra_drainage_count=len(cfg.extra_drainage_features),
        infiltration_mean_rate=mean_infil,
        max_depth_cm=max(stats.max_depth_cm, max_ever_d * 100.0),
        avg_depth_cm=stats.avg_depth_cm,
        peak_depth_time_min=peak_t,
        affected_area_m2=stats.affected_area_m2,
        affected_cells=stats.affected_cells,
        high_risk_cells=stats.high_risk_cells,
        very_high_risk_cells=stats.very_high_risk_cells,
        total_infiltration_m3=stats.cumulative_infiltration_m3,
        total_drainage_m3=stats.cumulative_drainage_m3,
        exposed_high_roads=exposed_high,
        exposed_moderate_roads=exposed_mod,
        shortest_route_passable=short_ok,
        flood_aware_route_passable=fa_ok,
        route_distance_km=route_km,
        is_hypothetical_infra=bool(cfg.extra_drainage_features),
    )


def compare_multiple_scenarios(
    outputs: list[SimulationOutput],
    cells: list[GridCell],
    *,
    thresholds: RiskThresholds | None = None,
    network: RoadNetworkGraph | None = None,
    origin_node_id: int | None = None,
    dest_node_id: int | None = None,
    closed_edge_ids_per_run: dict[int, set[int]] | None = None,
    road_thresholds: RoadExposureThresholds | None = None,
) -> ExtendedScenarioComparison:
    """Compare 2 or more simulations across flood depth, risk, water balance, config, and SafeRoute."""
    if len(outputs) < 2:
        raise ValueError("Select at least two simulation scenarios to compare.")

    th = thresholds or RiskThresholds()
    warnings: list[str] = []
    base = outputs[0]

    for other in outputs[1:]:
        if other.run.neighbourhood_id != base.run.neighbourhood_id:
            warnings.append(
                f"Incompatible neighbourhoods: '{base.run.scenario_name}' (nb#{base.run.neighbourhood_id}) vs "
                f"'{other.run.scenario_name}' (nb#{other.run.neighbourhood_id})."
            )
        if other.run.simulation_mode != base.run.simulation_mode:
            warnings.append(
                f"Elevation mode mismatch: '{base.run.scenario_name}' ({base.run.simulation_mode}) vs "
                f"'{other.run.scenario_name}' ({other.run.simulation_mode})."
            )
        if abs(other.run.rainfall_duration - base.run.rainfall_duration) > 1e-6:
            warnings.append(
                f"Duration difference: {base.run.rainfall_duration:.0f} min vs {other.run.rainfall_duration:.0f} min."
            )
        if base.final_cells and other.final_cells and len(base.final_cells) != len(other.final_cells):
            warnings.append(
                f"Incompatible grid sizes: {len(base.final_cells)} cells vs {len(other.final_cells)} cells."
            )

    rows: list[MultiScenarioRow] = []
    for idx, out in enumerate(outputs):
        closed_ids = (closed_edge_ids_per_run or {}).get(idx, set())
        rows.append(
            _build_scenario_row(
                out,
                cells,
                th,
                network=network,
                origin_node_id=origin_node_id,
                dest_node_id=dest_node_id,
                closed_edge_ids=closed_ids,
                road_thresholds=road_thresholds,
            )
        )

    base_row = rows[0]
    pairwise: list[tuple[str, list[MetricDeltaRow]]] = []
    for alt in rows[1:]:
        specs: list[tuple[str, str, float, float]] = [
            ("Max Simulated Depth", "cm", base_row.max_depth_cm, alt.max_depth_cm),
            ("Avg Simulated Depth", "cm", base_row.avg_depth_cm, alt.avg_depth_cm),
            ("Peak Depth Time", "min", base_row.peak_depth_time_min, alt.peak_depth_time_min),
            ("Affected Area", "m2", base_row.affected_area_m2, alt.affected_area_m2),
            ("Affected Grid Cells", "cells", float(base_row.affected_cells), float(alt.affected_cells)),
            ("High-Risk Cells", "cells", float(base_row.high_risk_cells), float(alt.high_risk_cells)),
            ("Very-High-Risk Cells", "cells", float(base_row.very_high_risk_cells), float(alt.very_high_risk_cells)),
            ("Total Infiltration", "m3", base_row.total_infiltration_m3, alt.total_infiltration_m3),
            ("Total Drainage Removal", "m3", base_row.total_drainage_m3, alt.total_drainage_m3),
        ]
        if base_row.exposed_high_roads is not None and alt.exposed_high_roads is not None:
            specs.append(
                ("High/V.High Exposed Roads", "edges", float(base_row.exposed_high_roads), float(alt.exposed_high_roads))
            )
        if base_row.route_distance_km is not None and alt.route_distance_km is not None:
            specs.append(
                ("Evacuation Route Distance", "km", base_row.route_distance_km, alt.route_distance_km)
            )
        delta_rows: list[MetricDeltaRow] = []
        for mname, unit, bv, tv in specs:
            pct_num, pct_txt = compute_meaningful_pct_change(bv, tv)
            delta_rows.append(
                MetricDeltaRow(
                    metric_name=mname,
                    unit=unit,
                    baseline_value=round(bv, 2),
                    target_value=round(tv, 2),
                    delta_value=round(tv - bv, 2),
                    pct_change_display=pct_txt,
                    pct_change_numeric=pct_num,
                )
            )
        if base_row.flood_aware_route_passable is not None and alt.flood_aware_route_passable is not None:
            delta_rows.append(
                MetricDeltaRow(
                    metric_name="Flood-Aware Route Passable",
                    unit="status",
                    baseline_value="Yes" if base_row.flood_aware_route_passable else "Blocked",
                    target_value="Yes" if alt.flood_aware_route_passable else "Blocked",
                    delta_value="Changed" if base_row.flood_aware_route_passable != alt.flood_aware_route_passable else "Same",
                    pct_change_display="N/A (boolean)",
                )
            )
        pairwise.append((alt.label, delta_rows))

    # Summarize configuration differences vs Baseline
    cfg_diffs: list[str] = []
    for alt in rows[1:]:
        diffs: list[str] = []
        if abs(alt.rainfall_intensity_mm_hr - base_row.rainfall_intensity_mm_hr) > 1e-6:
            diffs.append(f"Rainfall: {base_row.rainfall_intensity_mm_hr:.0f} -> {alt.rainfall_intensity_mm_hr:.0f} mm/hr")
        if abs(alt.drainage_scale - base_row.drainage_scale) > 1e-6:
            diffs.append(f"Drainage scale: {base_row.drainage_scale:.2f}x -> {alt.drainage_scale:.2f}x")
        if alt.disabled_drainage_count != base_row.disabled_drainage_count:
            diffs.append(f"Disabled drains: {base_row.disabled_drainage_count} -> {alt.disabled_drainage_count}")
        if alt.extra_drainage_count != base_row.extra_drainage_count:
            diffs.append(f"Hypothetical drains: {base_row.extra_drainage_count} -> {alt.extra_drainage_count}")
        if abs(alt.infiltration_mean_rate - base_row.infiltration_mean_rate) > 1e-3:
            diffs.append(f"Mean infiltration rate: {base_row.infiltration_mean_rate:.1f} -> {alt.infiltration_mean_rate:.1f} mm/hr")
        if not diffs:
            diffs.append("Same storm/hydrology parameters (check road closures or initial conditions).")
        cfg_diffs.append(f"{alt.label} vs {base_row.label}: " + "; ".join(diffs))

    route_note = ""
    if network is None or not network.edges_by_id:
        route_note = "Road exposure & SafeRoute comparison omitted (no OSM road network loaded)."
    elif origin_node_id is None or dest_node_id is None:
        route_note = "Road flood-exposure counted across full network; route distance omitted (no endpoint pair)."
    else:
        route_note = f"Evaluated SafeRoute between Node #{origin_node_id} and Node #{dest_node_id}."

    return ExtendedScenarioComparison(
        baseline_label=base_row.label,
        rows=rows,
        pairwise_deltas=pairwise,
        config_differences=cfg_diffs,
        compatibility_warnings=warnings,
        are_compatible=(len(warnings) == 0),
        route_probe_note=route_note,
    )
