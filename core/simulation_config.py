"""Simulation configuration, hypothetical scenario presets, and parameter models."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from config import (
    DEFAULT_INFILTRATION_RATES_MM_HR,
    DEFAULT_MASS_BALANCE_TOLERANCE_M3,
    MODEL_VERSION,
    RAINFALL_DISTRIBUTIONS,
    RAINFALL_PRESETS,
    SIMULATION_MODE_ELEVATION,
    SIMULATION_MODE_ILLUSTRATIVE,
    WET_CELL_DEPTH_THRESHOLD_M,
)
from core.models import DrainageFeature


@dataclass(slots=True)
class SimulationConfig:
    """Complete, self-contained, reproducible flood simulation configuration."""

    scenario_name: str = "Hypothetical Moderate Storm"
    rainfall_intensity_mm_hr: float = 30.0
    rainfall_duration_min: float = 60.0
    time_step_min: float = 5.0
    distribution_pattern: str = "constant"
    custom_intensities_mm_hr: list[float] = field(default_factory=list)
    initial_water_depth_m: float = 0.0

    # Terrain mode: 'elevation_based' or 'illustrative_assumed'
    simulation_mode: str = SIMULATION_MODE_ELEVATION

    # Illustrative terrain fallback settings (used ONLY in illustrative_assumed mode)
    illustrative_base_elevation_m: float = 15.0
    illustrative_north_south_slope_m: float = 2.0
    illustrative_west_east_slope_m: float = 1.0

    # Editable hydrological infiltration parameters (mm/hr) — labelled illustrative unless verified
    category_infiltration_rates_mm_hr: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_INFILTRATION_RATES_MM_HR)
    )
    use_cell_infiltration_if_present: bool = True

    # Surface flow routing conductance/mobility factor (0.05..0.50)
    surface_flow_mobility: float = 0.35

    # Drainage & What-If non-destructive overrides (never mutate DB)
    include_drainage_features: bool = True
    include_cell_drainage_capacity: bool = True
    rainfall_scale_factor: float = 1.0
    drainage_capacity_scale: float = 1.0
    disabled_drainage_ids: set[int] = field(default_factory=set)
    cell_infiltration_overrides_mm_hr: dict[int, float] = field(default_factory=dict)
    cell_initial_depths_m: dict[int, float] = field(default_factory=dict)
    extra_drainage_features: list[DrainageFeature] = field(default_factory=list)

    # Verification & numerical tolerances
    mass_balance_tolerance_m3: float = DEFAULT_MASS_BALANCE_TOLERANCE_M3
    wet_depth_threshold_m: float = WET_CELL_DEPTH_THRESHOLD_M
    model_version: str = MODEL_VERSION

    @property
    def num_steps(self) -> int:
        if self.time_step_min <= 0 or self.rainfall_duration_min <= 0:
            return 0
        return max(1, int(round(self.rainfall_duration_min / self.time_step_min)))

    def clone(self) -> SimulationConfig:
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_name": self.scenario_name,
            "rainfall_intensity_mm_hr": float(self.rainfall_intensity_mm_hr),
            "rainfall_duration_min": float(self.rainfall_duration_min),
            "time_step_min": float(self.time_step_min),
            "distribution_pattern": self.distribution_pattern,
            "custom_intensities_mm_hr": [float(v) for v in self.custom_intensities_mm_hr],
            "initial_water_depth_m": float(self.initial_water_depth_m),
            "simulation_mode": self.simulation_mode,
            "illustrative_base_elevation_m": float(self.illustrative_base_elevation_m),
            "illustrative_north_south_slope_m": float(self.illustrative_north_south_slope_m),
            "illustrative_west_east_slope_m": float(self.illustrative_west_east_slope_m),
            "category_infiltration_rates_mm_hr": {
                str(k): float(v) for k, v in self.category_infiltration_rates_mm_hr.items()
            },
            "use_cell_infiltration_if_present": bool(self.use_cell_infiltration_if_present),
            "surface_flow_mobility": float(self.surface_flow_mobility),
            "include_drainage_features": bool(self.include_drainage_features),
            "include_cell_drainage_capacity": bool(self.include_cell_drainage_capacity),
            "rainfall_scale_factor": float(self.rainfall_scale_factor),
            "drainage_capacity_scale": float(self.drainage_capacity_scale),
            "disabled_drainage_ids": sorted(int(i) for i in self.disabled_drainage_ids),
            "cell_infiltration_overrides_mm_hr": {
                str(k): float(v) for k, v in self.cell_infiltration_overrides_mm_hr.items()
            },
            "cell_initial_depths_m": {
                str(k): float(v) for k, v in self.cell_initial_depths_m.items()
            },
            "extra_drainage_features": [
                {
                    "id": df.id,
                    "neighbourhood_id": df.neighbourhood_id,
                    "grid_cell_id": df.grid_cell_id,
                    "name": df.name,
                    "feature_type": df.feature_type,
                    "latitude": df.latitude,
                    "longitude": df.longitude,
                    "capacity": df.capacity,
                    "capacity_unit": df.capacity_unit,
                    "status": df.status,
                    "source": df.source,
                    "notes": df.notes,
                }
                for df in self.extra_drainage_features
            ],
            "mass_balance_tolerance_m3": float(self.mass_balance_tolerance_m3),
            "wet_depth_threshold_m": float(self.wet_depth_threshold_m),
            "model_version": self.model_version,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SimulationConfig:
        extras: list[DrainageFeature] = []
        for raw_df in data.get("extra_drainage_features") or []:
            if not isinstance(raw_df, dict):
                continue
            extras.append(
                DrainageFeature(
                    id=raw_df.get("id"),
                    neighbourhood_id=int(raw_df.get("neighbourhood_id", 0)),
                    grid_cell_id=raw_df.get("grid_cell_id"),
                    name=str(raw_df.get("name", "Hypothetical Drain")),
                    feature_type=str(raw_df.get("feature_type", "Drainage channel")),
                    latitude=float(raw_df.get("latitude", 0.0)),
                    longitude=float(raw_df.get("longitude", 0.0)),
                    capacity=float(raw_df["capacity"]) if raw_df.get("capacity") is not None else None,
                    capacity_unit=str(raw_df.get("capacity_unit", "L/s")),
                    status=str(raw_df.get("status", "Operational")),
                    source=str(raw_df.get("source", "what-if-hypothetical")),
                    notes=str(raw_df.get("notes", "")),
                )
            )
        rates = dict(DEFAULT_INFILTRATION_RATES_MM_HR)
        for k, v in (data.get("category_infiltration_rates_mm_hr") or {}).items():
            rates[str(k)] = float(v)
        return cls(
            scenario_name=str(data.get("scenario_name", "Saved Scenario")),
            rainfall_intensity_mm_hr=float(data.get("rainfall_intensity_mm_hr", 30.0)),
            rainfall_duration_min=float(data.get("rainfall_duration_min", 60.0)),
            time_step_min=float(data.get("time_step_min", 5.0)),
            distribution_pattern=str(data.get("distribution_pattern", "constant")),
            custom_intensities_mm_hr=[float(v) for v in (data.get("custom_intensities_mm_hr") or [])],
            initial_water_depth_m=float(data.get("initial_water_depth_m", 0.0)),
            simulation_mode=str(data.get("simulation_mode", SIMULATION_MODE_ELEVATION)),
            illustrative_base_elevation_m=float(data.get("illustrative_base_elevation_m", 15.0)),
            illustrative_north_south_slope_m=float(data.get("illustrative_north_south_slope_m", 2.0)),
            illustrative_west_east_slope_m=float(data.get("illustrative_west_east_slope_m", 1.0)),
            category_infiltration_rates_mm_hr=rates,
            use_cell_infiltration_if_present=bool(data.get("use_cell_infiltration_if_present", True)),
            surface_flow_mobility=float(data.get("surface_flow_mobility", 0.35)),
            include_drainage_features=bool(data.get("include_drainage_features", True)),
            include_cell_drainage_capacity=bool(data.get("include_cell_drainage_capacity", True)),
            rainfall_scale_factor=float(data.get("rainfall_scale_factor", 1.0)),
            drainage_capacity_scale=float(data.get("drainage_capacity_scale", 1.0)),
            disabled_drainage_ids={int(i) for i in (data.get("disabled_drainage_ids") or [])},
            cell_infiltration_overrides_mm_hr={
                int(k): float(v)
                for k, v in (data.get("cell_infiltration_overrides_mm_hr") or {}).items()
            },
            cell_initial_depths_m={
                int(k): float(v)
                for k, v in (data.get("cell_initial_depths_m") or {}).items()
            },
            extra_drainage_features=extras,
            mass_balance_tolerance_m3=float(
                data.get("mass_balance_tolerance_m3", DEFAULT_MASS_BALANCE_TOLERANCE_M3)
            ),
            wet_depth_threshold_m=float(
                data.get("wet_depth_threshold_m", WET_CELL_DEPTH_THRESHOLD_M)
            ),
            model_version=str(data.get("model_version", MODEL_VERSION)),
        )


def create_preset_config(
    preset_label: str,
    duration_min: float = 60.0,
    time_step_min: float = 5.0,
    simulation_mode: str = SIMULATION_MODE_ILLUSTRATIVE,
) -> SimulationConfig:
    """Create a clearly labelled hypothetical rainfall scenario from a preset label."""
    intensity = RAINFALL_PRESETS.get(preset_label)
    if intensity is None:
        intensity = 30.0
    clean_name = f"[Hypothetical] {preset_label}"
    return SimulationConfig(
        scenario_name=clean_name,
        rainfall_intensity_mm_hr=float(intensity),
        rainfall_duration_min=float(duration_min),
        time_step_min=float(time_step_min),
        distribution_pattern="constant",
        simulation_mode=simulation_mode,
    )


__all__ = [
    "RAINFALL_DISTRIBUTIONS",
    "RAINFALL_PRESETS",
    "SIMULATION_MODE_ELEVATION",
    "SIMULATION_MODE_ILLUSTRATIVE",
    "SimulationConfig",
    "create_preset_config",
]
