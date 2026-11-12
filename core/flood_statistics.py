"""Neighbourhood flood statistics and multi-run scenario comparison calculations."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.models import GridCell
from core.risk_classifier import (
    RiskStatistics,
    RiskThresholds,
    calculate_risk_statistics,
)
from core.simulation_engine import SimulationCellStepRecord, SimulationOutput


@dataclass(slots=True)
class TimestepFloodStats:
    """Detailed flood statistics for a simulation run at a specific timestep."""

    timestep: int
    sim_time_minutes: float
    total_cells: int
    max_depth_m: float
    max_depth_cm: float
    avg_depth_m: float
    avg_depth_cm: float
    affected_cells: int
    affected_grid_pct: float
    affected_area_m2: float
    affected_area_ha: float
    high_risk_cells: int
    very_high_risk_cells: int
    cumulative_rainfall_m3: float
    cumulative_infiltration_m3: float
    cumulative_drainage_m3: float
    remaining_volume_m3: float
    risk_stats: RiskStatistics
    is_empty: bool = False


@dataclass(slots=True)
class SimulationComparison:
    """Side-by-side comparison of two saved Phase 3 simulations at final state."""

    run_a_id: int | None
    run_b_id: int | None
    label_a: str
    label_b: str
    stats_a: TimestepFloodStats
    stats_b: TimestepFloodStats
    max_depth_delta_cm: float
    avg_depth_delta_cm: float
    affected_area_delta_m2: float
    affected_cells_delta: int
    high_risk_delta: int
    very_high_risk_delta: int
    drainage_delta_m3: float
    compatibility_warnings: list[str] = field(default_factory=list)
    are_compatible: bool = True


def extract_step_cell_data(
    output: SimulationOutput,
    timestep: int,
) -> tuple[dict[int, float], dict[int, float], float]:
    """Return (depths_m_by_cell_id, volumes_m3_by_cell_id, sim_time_minutes) for a timestep.

    If timestep <= 0, returns an empty zero-depth mapping at t = 0.0.
    """
    if not output.steps or not output.cell_steps or timestep <= 0:
        return {}, {}, 0.0

    valid_steps = sorted({s.timestep for s in output.steps})
    target_step = min(valid_steps, key=lambda t: abs(t - timestep)) if timestep not in valid_steps else timestep

    depths: dict[int, float] = {}
    volumes: dict[int, float] = {}
    sim_time = 0.0
    for cs in output.cell_steps:
        if cs.timestep == target_step:
            depths[cs.cell_id] = float(cs.water_depth_m)
            volumes[cs.cell_id] = float(cs.water_volume_m3)
            sim_time = float(cs.sim_time_minutes)
    return depths, volumes, sim_time


def extract_step_cell_records(
    output: SimulationOutput,
    timestep: int,
) -> dict[int, SimulationCellStepRecord]:
    """Return {cell_id: SimulationCellStepRecord} for a specific timestep."""
    if not output.cell_steps or timestep <= 0:
        return {}
    return {cs.cell_id: cs for cs in output.cell_steps if cs.timestep == timestep}


def compute_timestep_statistics(
    output: SimulationOutput | None,
    timestep: int,
    cells: list[GridCell],
    thresholds: RiskThresholds | None = None,
) -> TimestepFloodStats:
    """Calculate §8 neighbourhood statistics strictly from stored Phase 3 simulation results."""
    th = thresholds or RiskThresholds()
    th.validate()
    total_cells = len(cells)

    if output is None or not output.steps or total_cells == 0:
        empty_risk = calculate_risk_statistics(cells, {}, th)
        return TimestepFloodStats(
            timestep=0,
            sim_time_minutes=0.0,
            total_cells=total_cells,
            max_depth_m=0.0,
            max_depth_cm=0.0,
            avg_depth_m=0.0,
            avg_depth_cm=0.0,
            affected_cells=0,
            affected_grid_pct=0.0,
            affected_area_m2=0.0,
            affected_area_ha=0.0,
            high_risk_cells=0,
            very_high_risk_cells=0,
            cumulative_rainfall_m3=0.0,
            cumulative_infiltration_m3=0.0,
            cumulative_drainage_m3=0.0,
            remaining_volume_m3=0.0,
            risk_stats=empty_risk,
            is_empty=True,
        )

    step_objs = sorted(output.steps, key=lambda s: s.timestep)
    target = next((s for s in step_objs if s.timestep == timestep), step_objs[-1])
    depths_map, volumes_map, sim_t = extract_step_cell_data(output, target.timestep)

    depth_values = [float(depths_map.get(c.id if c.id is not None else (i + 1), 0.0)) for i, c in enumerate(cells)]
    max_d = max(depth_values) if depth_values else 0.0
    avg_d = (sum(depth_values) / len(depth_values)) if depth_values else 0.0

    wet_cutoff_m = th.wet_cutoff_cm / 100.0
    affected_cells = 0
    affected_area_m2 = 0.0
    for idx, cell in enumerate(cells):
        cid = cell.id if cell.id is not None else (idx + 1)
        if float(depths_map.get(cid, 0.0)) > wet_cutoff_m:
            affected_cells += 1
            affected_area_m2 += cell.approx_area_sq_m()

    pct = (affected_cells / total_cells) * 100.0 if total_cells > 0 else 0.0
    risk_stats = calculate_risk_statistics(cells, depths_map, th)

    cum_rain = sum(s.rainfall_input_m3 for s in step_objs if s.timestep <= target.timestep)
    cum_infil = sum(s.infiltration_loss_m3 for s in step_objs if s.timestep <= target.timestep)
    cum_drain = sum(s.drainage_loss_m3 for s in step_objs if s.timestep <= target.timestep)
    rem_vol = sum(volumes_map.values()) if volumes_map else target.total_volume_remaining_m3

    return TimestepFloodStats(
        timestep=target.timestep,
        sim_time_minutes=sim_t or target.sim_time_minutes,
        total_cells=total_cells,
        max_depth_m=max_d,
        max_depth_cm=max_d * 100.0,
        avg_depth_m=avg_d,
        avg_depth_cm=avg_d * 100.0,
        affected_cells=affected_cells,
        affected_grid_pct=pct,
        affected_area_m2=affected_area_m2,
        affected_area_ha=affected_area_m2 / 10_000.0,
        high_risk_cells=risk_stats.high_risk_cells,
        very_high_risk_cells=risk_stats.very_high_risk_cells,
        cumulative_rainfall_m3=cum_rain,
        cumulative_infiltration_m3=cum_infil,
        cumulative_drainage_m3=cum_drain,
        remaining_volume_m3=rem_vol,
        risk_stats=risk_stats,
        is_empty=False,
    )


def compare_simulations(
    out_a: SimulationOutput,
    out_b: SimulationOutput,
    cells_a: list[GridCell],
    cells_b: list[GridCell],
    thresholds: RiskThresholds | None = None,
) -> SimulationComparison:
    """Compare two Phase 3 simulation outputs at their final timesteps and verify compatibility."""
    th = thresholds or RiskThresholds()
    warnings: list[str] = []

    if out_a.run.neighbourhood_id != out_b.run.neighbourhood_id:
        warnings.append(
            f"Different neighbourhoods: Run A (#{out_a.run.neighbourhood_id}) vs "
            f"Run B (#{out_b.run.neighbourhood_id})."
        )
    if len(cells_a) != len(cells_b):
        warnings.append(
            f"Incompatible grid cell counts: {len(cells_a)} cells vs {len(cells_b)} cells."
        )
    else:
        coords_a = {(c.row_number, c.column_number) for c in cells_a}
        coords_b = {(c.row_number, c.column_number) for c in cells_b}
        if coords_a != coords_b:
            warnings.append("Grid row/column layouts differ between Run A and Run B.")

    if out_a.run.simulation_mode != out_b.run.simulation_mode:
        warnings.append(
            f"Different elevation modes: '{out_a.run.simulation_mode}' vs '{out_b.run.simulation_mode}'."
        )
    if abs(out_a.run.rainfall_duration - out_b.run.rainfall_duration) > 1e-6:
        warnings.append(
            f"Different storm durations: {out_a.run.rainfall_duration:.0f} min vs "
            f"{out_b.run.rainfall_duration:.0f} min."
        )
    if abs(out_a.run.time_step - out_b.run.time_step) > 1e-6:
        warnings.append(
            f"Different simulation time steps: {out_a.run.time_step:.1f} min vs "
            f"{out_b.run.time_step:.1f} min."
        )
    if out_a.run.model_version != out_b.run.model_version:
        warnings.append(
            f"Different model versions: {out_a.run.model_version} vs {out_b.run.model_version}."
        )

    last_step_a = out_a.steps[-1].timestep if out_a.steps else 0
    last_step_b = out_b.steps[-1].timestep if out_b.steps else 0

    stats_a = compute_timestep_statistics(out_a, last_step_a, cells_a, th)
    stats_b = compute_timestep_statistics(out_b, last_step_b, cells_b, th)

    label_a = f"Run #{out_a.run.id or 'A'}: {out_a.run.scenario_name}"
    label_b = f"Run #{out_b.run.id or 'B'}: {out_b.run.scenario_name}"

    grid_compatible = (len(cells_a) == len(cells_b)) and (
        out_a.run.neighbourhood_id == out_b.run.neighbourhood_id
    )

    return SimulationComparison(
        run_a_id=out_a.run.id,
        run_b_id=out_b.run.id,
        label_a=label_a,
        label_b=label_b,
        stats_a=stats_a,
        stats_b=stats_b,
        max_depth_delta_cm=stats_b.max_depth_cm - stats_a.max_depth_cm,
        avg_depth_delta_cm=stats_b.avg_depth_cm - stats_a.avg_depth_cm,
        affected_area_delta_m2=stats_b.affected_area_m2 - stats_a.affected_area_m2,
        affected_cells_delta=stats_b.affected_cells - stats_a.affected_cells,
        high_risk_delta=stats_b.high_risk_cells - stats_a.high_risk_cells,
        very_high_risk_delta=stats_b.very_high_risk_cells - stats_a.very_high_risk_cells,
        drainage_delta_m3=stats_b.cumulative_drainage_m3 - stats_a.cumulative_drainage_m3,
        compatibility_warnings=warnings,
        are_compatible=grid_compatible and len(warnings) == 0,
    )


__all__ = [
    "SimulationComparison",
    "TimestepFloodStats",
    "compare_simulations",
    "compute_timestep_statistics",
    "extract_step_cell_data",
    "extract_step_cell_records",
]
