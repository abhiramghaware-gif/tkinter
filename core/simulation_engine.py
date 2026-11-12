"""Core Phase 3 Flood Simulation Engine with strict SI mass conservation."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np

from config import SIMULATION_MODE_ELEVATION, SIMULATION_MODE_ILLUSTRATIVE
from core.drainage_model import (
    CellDrainageProfile,
    calculate_drainage,
    resolve_cell_drainage_profiles,
)
from core.infiltration_model import calculate_infiltration, resolve_cell_infiltration_rates
from core.models import DrainageFeature, FloodSimulationEngine, GridCell, RainfallScenarioConfig
from core.rainfall_model import (
    calculate_rainfall,
    compute_timestep_durations_seconds,
    generate_rainfall_schedule,
)
from core.runoff_model import calculate_runoff
from core.simulation_config import SimulationConfig
from core.validation import ValidationError
from core.water_flow_model import (
    build_neighbour_index,
    calculate_surface_flow,
    resolve_cell_elevations,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(slots=True)
class SimulationStepRecord:
    """Aggregate quantities recorded for a single simulation timestep."""

    timestep: int
    sim_time_minutes: float
    rainfall_intensity_mm_hr: float
    rainfall_input_m3: float
    infiltration_loss_m3: float
    drainage_loss_m3: float
    water_transferred_m3: float
    total_volume_remaining_m3: float
    max_water_depth_m: float
    avg_water_depth_m: float
    affected_cell_count: int
    total_area_affected_m2: float
    mass_balance_error_m3: float


@dataclass(slots=True)
class SimulationCellStepRecord:
    """Per-cell per-timestep record matching SQLite `simulation_results` schema."""

    timestep: int
    sim_time_minutes: float
    cell_id: int
    cell_code: str
    water_depth_m: float
    water_volume_m3: float
    rainfall_input_m3: float
    infiltration_loss_m3: float
    drainage_loss_m3: float
    flow_transferred_m3: float


@dataclass(slots=True)
class SimulationCellFinalState:
    """Per-cell summary state at end of simulation."""

    cell_id: int
    cell_code: str
    row_number: int
    column_number: int
    land_use: str
    area_m2: float
    elevation_m: float
    elevation_provenance: str
    infiltration_rate_mm_hr: float
    infiltration_provenance: str
    drainage_discharge_m3_s: float
    final_water_depth_m: float
    max_water_depth_m: float
    final_water_volume_m3: float
    total_rainfall_m3: float
    total_infiltration_m3: float
    total_drainage_m3: float


@dataclass(slots=True)
class SimulationSummary:
    """Final simulation summary metrics & strict water-balance verification."""

    max_water_depth_m: float
    avg_water_depth_m: float
    initial_water_volume_m3: float
    total_rainfall_volume_m3: float
    total_infiltration_volume_m3: float
    total_drainage_volume_m3: float
    total_transferred_volume_m3: float
    final_surface_volume_m3: float
    max_affected_cells: int
    total_affected_area_m2: float
    time_of_max_depth_minutes: float
    mass_balance_error_m3: float
    mass_balance_tolerance_m3: float
    mass_balance_passed: bool
    used_illustrative_terrain: bool
    total_steps: int


@dataclass(slots=True)
class SimulationRunRecord:
    """Persistence header matching `simulation_runs` SQLite table."""

    id: int | None
    neighbourhood_id: int
    scenario_name: str
    rainfall_intensity: float
    rainfall_duration: float
    time_step: float
    simulation_mode: str
    distribution_pattern: str
    initial_water_depth: float
    config_json: str
    start_time: str
    completion_time: str
    status: str
    model_version: str


@dataclass(slots=True)
class SimulationOutput:
    """Complete bundle returned by `run_simulation`."""

    run: SimulationRunRecord
    config: SimulationConfig
    summary: SimulationSummary
    steps: list[SimulationStepRecord]
    cell_steps: list[SimulationCellStepRecord]
    final_cells: list[SimulationCellFinalState]
    drainage_profiles: list[CellDrainageProfile]
    warnings: list[str] = field(default_factory=list)
    is_hypothetical: bool = True
    disclaimer: str = (
        "Hypothetical simulation output from an experimental prototype. "
        "Not verified real-world flood measurements or an official flood warning."
    )


def validate_scenario(
    cells: list[GridCell],
    config: SimulationConfig,
    drainage_features: list[DrainageFeature] | None = None,
) -> dict[str, Any]:
    """Validate scenario parameters, grid completeness, terrain mode, and drainage inputs.

    Raises ValidationError on invalid or unreasonable configuration.
    Returns resolved internal arrays & warnings ready for simulation execution.
    """
    if not cells:
        raise ValidationError("Cannot simulate: the active neighbourhood has 0 grid cells.")

    if not config.scenario_name or not config.scenario_name.strip():
        raise ValidationError("Scenario name is required.")

    # Bounds on rainfall & timing to catch typos / unreasonable parameters
    if not math.isfinite(config.rainfall_intensity_mm_hr) or config.rainfall_intensity_mm_hr < 0.0:
        raise ValidationError("Rainfall intensity must be finite and >= 0 mm/hr.")
    if config.rainfall_intensity_mm_hr > 500.0:
        raise ValidationError(
            "Rainfall intensity exceeds maximum supported prototype limit (500 mm/hr)."
        )

    if not math.isfinite(config.rainfall_duration_min) or config.rainfall_duration_min <= 0.0:
        raise ValidationError("Rainfall duration must be finite and > 0 minutes.")
    if config.rainfall_duration_min > 1440.0:
        raise ValidationError(
            "Rainfall duration exceeds maximum supported limit (1440 minutes / 24 hours)."
        )

    if not math.isfinite(config.time_step_min) or config.time_step_min <= 0.0:
        raise ValidationError("Simulation time step must be finite and > 0 minutes.")
    if config.time_step_min > config.rainfall_duration_min:
        raise ValidationError("Simulation time step cannot exceed total rainfall duration.")

    if not math.isfinite(config.initial_water_depth_m) or config.initial_water_depth_m < 0.0:
        raise ValidationError("Initial water depth must be finite and >= 0 m.")
    if config.initial_water_depth_m > 10.0:
        raise ValidationError("Initial water depth exceeds reasonable urban prototype limit (10 m).")

    if not math.isfinite(config.mass_balance_tolerance_m3) or config.mass_balance_tolerance_m3 <= 0.0:
        raise ValidationError("Mass-balance tolerance must be > 0 m^3.")

    if config.simulation_mode not in (SIMULATION_MODE_ELEVATION, SIMULATION_MODE_ILLUSTRATIVE):
        raise ValidationError("Invalid simulation mode.")

    # Validate areas and cell IDs
    areas = np.zeros(len(cells), dtype=np.float64)
    seen_coords: set[tuple[int, int]] = set()
    for idx, cell in enumerate(cells):
        pos = (cell.row_number, cell.column_number)
        if pos in seen_coords:
            raise ValidationError(f"Duplicate grid cell coordinate detected at {pos}.")
        seen_coords.add(pos)
        area = float(cell.approx_area_sq_m())
        if not math.isfinite(area) or area <= 0.0:
            raise ValidationError(f"Grid cell {cell.cell_code} has invalid area ({area}).")
        areas[idx] = area

    # Validate category infiltration parameters
    for cat_name, rate in config.category_infiltration_rates_mm_hr.items():
        if not math.isfinite(rate) or rate < 0.0:
            raise ValidationError(
                f"Infiltration rate for '{cat_name}' must be finite and >= 0 mm/hr."
            )

    # Validate rainfall schedule
    schedule_mm_hr = generate_rainfall_schedule(
        intensity_mm_hr=config.rainfall_intensity_mm_hr,
        duration_minutes=config.rainfall_duration_min,
        time_step_minutes=config.time_step_min,
        distribution=config.distribution_pattern,
        custom_intensities_mm_hr=config.custom_intensities_mm_hr,
        scale_factor=config.rainfall_scale_factor,
    )
    step_durations_sec = compute_timestep_durations_seconds(
        config.rainfall_duration_min,
        config.time_step_min,
    )
    if len(schedule_mm_hr) != len(step_durations_sec):
        # Ensure exact alignment if rounding occurred
        step_durations_sec = step_durations_sec[: len(schedule_mm_hr)]

    # Validate & resolve elevation, infiltration, drainage, neighbours
    elevations_m, elev_prov, used_illustrative, elev_warnings = resolve_cell_elevations(cells, config)
    infil_rates_mm_hr, infil_prov = resolve_cell_infiltration_rates(cells, config)
    max_discharge_m3_s, drainage_profiles, drain_warnings = resolve_cell_drainage_profiles(
        cells, drainage_features or [], config
    )
    neighbours = build_neighbour_index(cells)

    return {
        "areas_m2": areas,
        "elevations_m": elevations_m,
        "elevation_provenance": elev_prov,
        "used_illustrative_terrain": used_illustrative,
        "infil_rates_mm_hr": infil_rates_mm_hr,
        "infiltration_provenance": infil_prov,
        "max_discharge_m3_s": max_discharge_m3_s,
        "drainage_profiles": drainage_profiles,
        "neighbours": neighbours,
        "schedule_mm_hr": schedule_mm_hr,
        "step_durations_sec": step_durations_sec,
        "warnings": elev_warnings + drain_warnings,
    }


def update_water_levels(volumes_m3: np.ndarray, cell_areas_m2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Clamp non-negative volumes and compute per-cell water depths (m)."""
    safe_vols = np.maximum(0.0, np.asarray(volumes_m3, dtype=np.float64))
    safe_areas = np.asarray(cell_areas_m2, dtype=np.float64)
    depths_m = safe_vols / safe_areas
    return safe_vols, depths_m


def calculate_simulation_metrics(
    initial_volume_m3: float,
    final_volumes_m3: np.ndarray,
    cell_areas_m2: np.ndarray,
    steps: list[SimulationStepRecord],
    total_rainfall_m3: float,
    total_infiltration_m3: float,
    total_drainage_m3: float,
    total_transferred_m3: float,
    max_depth_overall_m: float,
    time_of_max_depth_min: float,
    max_affected_cells: int,
    max_affected_area_m2: float,
    tolerance_m3: float,
    used_illustrative_terrain: bool,
) -> SimulationSummary:
    """Compute final summary metrics and verify strict global mass conservation."""
    final_vol = float(np.sum(final_volumes_m3))
    depths = final_volumes_m3 / cell_areas_m2
    avg_depth = float(np.mean(depths)) if len(depths) > 0 else 0.0

    # Global mass conservation:
    # Initial + Rainfall == Final + Infiltration + Drainage (internal transfers cancel identically)
    lhs_in = float(initial_volume_m3) + float(total_rainfall_m3)
    rhs_out = final_vol + float(total_infiltration_m3) + float(total_drainage_m3)
    mass_error = abs(lhs_in - rhs_out)

    return SimulationSummary(
        max_water_depth_m=float(max_depth_overall_m),
        avg_water_depth_m=avg_depth,
        initial_water_volume_m3=float(initial_volume_m3),
        total_rainfall_volume_m3=float(total_rainfall_m3),
        total_infiltration_volume_m3=float(total_infiltration_m3),
        total_drainage_volume_m3=float(total_drainage_m3),
        total_transferred_volume_m3=float(total_transferred_m3),
        final_surface_volume_m3=final_vol,
        max_affected_cells=int(max_affected_cells),
        total_affected_area_m2=float(max_affected_area_m2),
        time_of_max_depth_minutes=float(time_of_max_depth_min),
        mass_balance_error_m3=mass_error,
        mass_balance_tolerance_m3=float(tolerance_m3),
        mass_balance_passed=bool(mass_error <= float(tolerance_m3)),
        used_illustrative_terrain=used_illustrative_terrain,
        total_steps=len(steps),
    )


def run_simulation(
    cells: list[GridCell],
    config: SimulationConfig,
    drainage_features: list[DrainageFeature] | None = None,
    neighbourhood_id: int | None = None,
    progress_callback: Callable[[int, int, SimulationStepRecord], None] | None = None,
    pause_event: threading.Event | None = None,
    cancel_event: threading.Event | None = None,
) -> SimulationOutput:
    """Execute full Phase 3 flood water-balance simulation without modifying DB inputs."""
    resolved = validate_scenario(cells, config, drainage_features)

    areas: np.ndarray = resolved["areas_m2"]
    elevations: np.ndarray = resolved["elevations_m"]
    elev_prov: list[str] = resolved["elevation_provenance"]
    used_illustrative: bool = resolved["used_illustrative_terrain"]
    infil_rates: np.ndarray = resolved["infil_rates_mm_hr"]
    infil_prov: list[str] = resolved["infiltration_provenance"]
    max_discharge: np.ndarray = resolved["max_discharge_m3_s"]
    drainage_profiles: list[CellDrainageProfile] = resolved["drainage_profiles"]
    neighbours: list[list[int]] = resolved["neighbours"]
    schedule_mm_hr: list[float] = resolved["schedule_mm_hr"]
    step_durations_sec: list[float] = resolved["step_durations_sec"]
    warnings: list[str] = list(resolved["warnings"])

    n_cells = len(cells)
    nb_id = neighbourhood_id if neighbourhood_id is not None else cells[0].neighbourhood_id
    start_iso = _utc_now_iso()

    # Initial water depth per cell (supports uniform or per-cell What-If overrides)
    init_depths = np.full(n_cells, float(config.initial_water_depth_m), dtype=np.float64)
    for idx, cell in enumerate(cells):
        if cell.id is not None and cell.id in config.cell_initial_depths_m:
            d_val = float(config.cell_initial_depths_m[cell.id])
            if not math.isfinite(d_val) or d_val < 0.0:
                raise ValidationError(f"Invalid initial depth for cell {cell.cell_code}.")
            init_depths[idx] = d_val

    vols = init_depths * areas
    initial_volume_m3 = float(np.sum(vols))

    cum_rain = 0.0
    cum_infil = 0.0
    cum_drain = 0.0
    cum_transfer = 0.0
    sim_time_min = 0.0

    cell_cum_rain = np.zeros(n_cells, dtype=np.float64)
    cell_cum_infil = np.zeros(n_cells, dtype=np.float64)
    cell_cum_drain = np.zeros(n_cells, dtype=np.float64)
    cell_max_depth = init_depths.copy()

    max_depth_overall = float(np.max(init_depths)) if n_cells else 0.0
    time_of_max_depth = 0.0
    init_wet = init_depths > config.wet_depth_threshold_m
    max_affected_cells = int(np.sum(init_wet))
    max_affected_area = float(np.sum(areas[init_wet]))

    steps: list[SimulationStepRecord] = []
    cell_steps: list[SimulationCellStepRecord] = []
    total_steps = len(schedule_mm_hr)

    for step_idx, (intensity_mm_hr, dt_sec) in enumerate(zip(schedule_mm_hr, step_durations_sec), start=1):
        while pause_event is not None and pause_event.is_set():
            if cancel_event is not None and cancel_event.is_set():
                raise ValidationError("Simulation cancelled while paused.")
            time.sleep(0.05)
        if cancel_event is not None and cancel_event.is_set():
            raise ValidationError("Simulation cancelled by user.")

        sim_time_min += dt_sec / 60.0

        # 1. Rainfall input
        _, rain_vols = calculate_rainfall(areas, intensity_mm_hr, dt_sec)
        vols = vols + rain_vols

        # 2. Soil infiltration loss
        infil_vols, vols = calculate_infiltration(vols, areas, infil_rates, dt_sec)

        # 3. Runoff excess diagnostic (does not double-subtract from storage)
        _runoff_diag = calculate_runoff(rain_vols, infil_vols, vols, areas)

        # 4. Drainage infrastructure removal
        drain_vols, vols = calculate_drainage(vols, max_discharge, dt_sec)

        # 5. Surface water flow between neighbouring cells (mass-conserving)
        vols, step_transfer_m3, cell_outflow_m3 = calculate_surface_flow(
            volumes_m3=vols,
            cell_areas_m2=areas,
            elevations_m=elevations,
            neighbours=neighbours,
            time_step_seconds=dt_sec,
            mobility=config.surface_flow_mobility,
        )

        # 6. Update levels & mass balance check
        vols, depths = update_water_levels(vols, areas)

        step_rain = float(np.sum(rain_vols))
        step_infil = float(np.sum(infil_vols))
        step_drain = float(np.sum(drain_vols))
        cum_rain += step_rain
        cum_infil += step_infil
        cum_drain += step_drain
        cum_transfer += step_transfer_m3

        cell_cum_rain += rain_vols
        cell_cum_infil += infil_vols
        cell_cum_drain += drain_vols
        cell_max_depth = np.maximum(cell_max_depth, depths)

        step_max_depth = float(np.max(depths)) if n_cells else 0.0
        step_avg_depth = float(np.mean(depths)) if n_cells else 0.0
        wet_mask = depths > config.wet_depth_threshold_m
        wet_count = int(np.sum(wet_mask))
        wet_area = float(np.sum(areas[wet_mask]))
        rem_vol = float(np.sum(vols))

        if step_max_depth > max_depth_overall:
            max_depth_overall = step_max_depth
            time_of_max_depth = sim_time_min
        if wet_count > max_affected_cells:
            max_affected_cells = wet_count
        if wet_area > max_affected_area:
            max_affected_area = wet_area

        step_mass_err = abs((initial_volume_m3 + cum_rain) - (rem_vol + cum_infil + cum_drain))

        step_rec = SimulationStepRecord(
            timestep=step_idx,
            sim_time_minutes=sim_time_min,
            rainfall_intensity_mm_hr=float(intensity_mm_hr),
            rainfall_input_m3=step_rain,
            infiltration_loss_m3=step_infil,
            drainage_loss_m3=step_drain,
            water_transferred_m3=step_transfer_m3,
            total_volume_remaining_m3=rem_vol,
            max_water_depth_m=step_max_depth,
            avg_water_depth_m=step_avg_depth,
            affected_cell_count=wet_count,
            total_area_affected_m2=wet_area,
            mass_balance_error_m3=step_mass_err,
        )
        steps.append(step_rec)

        for idx, cell in enumerate(cells):
            cid = cell.id if cell.id is not None else (idx + 1)
            cell_steps.append(
                SimulationCellStepRecord(
                    timestep=step_idx,
                    sim_time_minutes=sim_time_min,
                    cell_id=cid,
                    cell_code=cell.cell_code,
                    water_depth_m=float(depths[idx]),
                    water_volume_m3=float(vols[idx]),
                    rainfall_input_m3=float(rain_vols[idx]),
                    infiltration_loss_m3=float(infil_vols[idx]),
                    drainage_loss_m3=float(drain_vols[idx]),
                    flow_transferred_m3=float(cell_outflow_m3[idx]),
                )
            )

        if progress_callback is not None:
            progress_callback(step_idx, total_steps, step_rec)

    summary = calculate_simulation_metrics(
        initial_volume_m3=initial_volume_m3,
        final_volumes_m3=vols,
        cell_areas_m2=areas,
        steps=steps,
        total_rainfall_m3=cum_rain,
        total_infiltration_m3=cum_infil,
        total_drainage_m3=cum_drain,
        total_transferred_m3=cum_transfer,
        max_depth_overall_m=max_depth_overall,
        time_of_max_depth_min=time_of_max_depth,
        max_affected_cells=max_affected_cells,
        max_affected_area_m2=max_affected_area,
        tolerance_m3=config.mass_balance_tolerance_m3,
        used_illustrative_terrain=used_illustrative,
    )

    if not summary.mass_balance_passed:
        warnings.append(
            f"MASS BALANCE WARNING: Water-balance residual {summary.mass_balance_error_m3:.6e} m3 "
            f"exceeded tolerance {summary.mass_balance_tolerance_m3:.6e} m3."
        )

    final_depths = vols / areas
    final_cells: list[SimulationCellFinalState] = []
    for idx, cell in enumerate(cells):
        cid = cell.id if cell.id is not None else (idx + 1)
        final_cells.append(
            SimulationCellFinalState(
                cell_id=cid,
                cell_code=cell.cell_code,
                row_number=cell.row_number,
                column_number=cell.column_number,
                land_use=cell.land_use,
                area_m2=float(areas[idx]),
                elevation_m=float(elevations[idx]),
                elevation_provenance=elev_prov[idx],
                infiltration_rate_mm_hr=float(infil_rates[idx]),
                infiltration_provenance=infil_prov[idx],
                drainage_discharge_m3_s=float(max_discharge[idx]),
                final_water_depth_m=float(final_depths[idx]),
                max_water_depth_m=float(cell_max_depth[idx]),
                final_water_volume_m3=float(vols[idx]),
                total_rainfall_m3=float(cell_cum_rain[idx]),
                total_infiltration_m3=float(cell_cum_infil[idx]),
                total_drainage_m3=float(cell_cum_drain[idx]),
            )
        )

    end_iso = _utc_now_iso()
    run_rec = SimulationRunRecord(
        id=None,
        neighbourhood_id=nb_id,
        scenario_name=config.scenario_name.strip(),
        rainfall_intensity=float(config.rainfall_intensity_mm_hr),
        rainfall_duration=float(config.rainfall_duration_min),
        time_step=float(config.time_step_min),
        simulation_mode=config.simulation_mode,
        distribution_pattern=config.distribution_pattern,
        initial_water_depth=float(config.initial_water_depth_m),
        config_json=config.to_json(),
        start_time=start_iso,
        completion_time=end_iso,
        status="completed" if summary.mass_balance_passed else "completed_with_warning",
        model_version=config.model_version,
    )

    return SimulationOutput(
        run=run_rec,
        config=config.clone(),
        summary=summary,
        steps=steps,
        cell_steps=cell_steps,
        final_cells=final_cells,
        drainage_profiles=drainage_profiles,
        warnings=warnings,
    )


class CellularFloodSimulationEngine(FloodSimulationEngine):
    """Concrete implementation of the Phase 1/2 `FloodSimulationEngine` interface."""

    def run_simulation(
        self,
        cells: list[GridCell],
        scenario: RainfallScenarioConfig,
    ) -> dict[str, Any]:
        duration_min = max(1.0, float(scenario.duration_hours) * 60.0)
        intensity_mm_hr = float(scenario.total_rainfall_mm) / max(1e-6, float(scenario.duration_hours))
        pattern = "constant" if scenario.distribution_pattern == "uniform" else scenario.distribution_pattern
        cfg = SimulationConfig(
            scenario_name=scenario.scenario_name,
            rainfall_intensity_mm_hr=intensity_mm_hr,
            rainfall_duration_min=duration_min,
            time_step_min=float(scenario.time_step_minutes),
            distribution_pattern=pattern,
            simulation_mode=SIMULATION_MODE_ILLUSTRATIVE,
        )
        out = run_simulation(cells, cfg)
        return {
            "summary": out.summary,
            "steps": out.steps,
            "final_cells": out.final_cells,
            "warnings": out.warnings,
        }


__all__ = [
    "CellularFloodSimulationEngine",
    "SimulationCellFinalState",
    "SimulationCellStepRecord",
    "SimulationOutput",
    "SimulationRunRecord",
    "SimulationStepRecord",
    "SimulationSummary",
    "calculate_drainage",
    "calculate_infiltration",
    "calculate_rainfall",
    "calculate_runoff",
    "calculate_simulation_metrics",
    "calculate_surface_flow",
    "run_simulation",
    "update_water_levels",
    "validate_scenario",
]
