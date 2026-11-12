"""What-If Scenario Manager: non-destructive scenario cloning, edits, and 6 experiments."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Callable

from config import SIMULATION_MODE_ELEVATION, SIMULATION_MODE_ILLUSTRATIVE
from core.models import DrainageFeature, GridCell, Neighbourhood
from core.simulation_config import SimulationConfig
from core.simulation_engine import SimulationOutput, SimulationRunRecord, run_simulation
from core.validation import ValidationError


@dataclass(slots=True)
class ScenarioVariant:
    """Self-contained non-destructive scenario definition (never alters baseline GIS/runs)."""

    name: str
    config: SimulationConfig
    description: str = ""
    experiment_key: str = "custom"
    is_hypothetical: bool = False
    is_stress_test: bool = False
    closed_edge_ids: set[int] = field(default_factory=set)
    reopened_edge_ids: set[int] = field(default_factory=set)
    baseline_run_id: int | None = None
    notes: str = ""


@dataclass(slots=True)
class ExperimentExecutionResult:
    """Output bundle returned after executing a custom scenario or ready-made experiment."""

    experiment_key: str
    experiment_title: str
    variants: list[ScenarioVariant]
    outputs: list[SimulationOutput]
    notes: str = ""


def clone_config_from_run(
    run_record: SimulationRunRecord | None = None,
    *,
    scenario_name: str | None = None,
    has_elevations: bool = True,
) -> SimulationConfig:
    """Clone a saved simulation configuration (or sensible baseline) without mutating source."""
    if run_record is not None:
        raw_cfg = json.loads(run_record.config_json or "{}") if run_record.config_json else {}
        if "scenario_name" not in raw_cfg:
            raw_cfg["scenario_name"] = run_record.scenario_name
        if "rainfall_intensity_mm_hr" not in raw_cfg:
            raw_cfg["rainfall_intensity_mm_hr"] = run_record.rainfall_intensity
        if "rainfall_duration_min" not in raw_cfg:
            raw_cfg["rainfall_duration_min"] = run_record.rainfall_duration
        if "time_step_min" not in raw_cfg:
            raw_cfg["time_step_min"] = run_record.time_step
        if "simulation_mode" not in raw_cfg:
            raw_cfg["simulation_mode"] = run_record.simulation_mode
        if "distribution_pattern" not in raw_cfg:
            raw_cfg["distribution_pattern"] = run_record.distribution_pattern
        if "initial_water_depth_m" not in raw_cfg:
            raw_cfg["initial_water_depth_m"] = run_record.initial_water_depth
        cfg = SimulationConfig.from_dict(raw_cfg).clone()
    else:
        cfg = SimulationConfig(
            scenario_name="Baseline Moderate Storm",
            rainfall_intensity_mm_hr=30.0,
            rainfall_duration_min=60.0,
            time_step_min=5.0,
            simulation_mode=SIMULATION_MODE_ELEVATION if has_elevations else SIMULATION_MODE_ILLUSTRATIVE,
        )
    if scenario_name:
        cfg.scenario_name = scenario_name.strip()
    return cfg


def _pick_representative_cell(cells: list[GridCell]) -> GridCell | None:
    if not cells:
        return None
    # Prefer lowest stored elevation or center cell for hypothetical drainage placement
    with_elev = [c for c in cells if (c.mean_elevation_m or c.elevation_m) is not None]
    if with_elev:
        return min(with_elev, key=lambda c: float(c.mean_elevation_m if c.mean_elevation_m is not None else c.elevation_m))  # type: ignore[arg-type]
    mid_idx = len(cells) // 2
    return cells[mid_idx]


class ScenarioManager:
    """Builds, validates, executes, and persists non-destructive What-If scenarios."""

    def create_modified_variant(
        self,
        base_config: SimulationConfig,
        *,
        name: str,
        description: str = "",
        experiment_key: str = "custom",
        baseline_run_id: int | None = None,
        rainfall_intensity_mm_hr: float | None = None,
        rainfall_duration_min: float | None = None,
        distribution_pattern: str | None = None,
        time_step_min: float | None = None,
        initial_water_depth_m: float | None = None,
        disabled_drainage_ids: set[int] | None = None,
        drainage_capacity_scale: float | None = None,
        extra_drainage_features: list[DrainageFeature] | None = None,
        infiltration_scale: float = 1.0,
        cell_land_use_infiltration_mm_hr: dict[int, float] | None = None,
        closed_edge_ids: set[int] | None = None,
        reopened_edge_ids: set[int] | None = None,
        is_hypothetical: bool = False,
        is_stress_test: bool = False,
        notes: str = "",
    ) -> ScenarioVariant:
        """Create a cloned ScenarioVariant applying requested parameter overrides."""
        cfg = base_config.clone()
        cfg.scenario_name = name.strip() or "What-If Scenario"

        if rainfall_intensity_mm_hr is not None:
            if rainfall_intensity_mm_hr < 0 or rainfall_intensity_mm_hr > 500:
                raise ValidationError("What-If rainfall intensity must be between 0 and 500 mm/hr.")
            cfg.rainfall_intensity_mm_hr = float(rainfall_intensity_mm_hr)
        if rainfall_duration_min is not None:
            if rainfall_duration_min <= 0 or rainfall_duration_min > 1440:
                raise ValidationError("What-If duration must be between 1 and 1440 minutes.")
            cfg.rainfall_duration_min = float(rainfall_duration_min)
        if distribution_pattern is not None:
            cfg.distribution_pattern = distribution_pattern
        if time_step_min is not None:
            if time_step_min <= 0 or time_step_min > cfg.rainfall_duration_min:
                raise ValidationError("What-If time step must be > 0 and <= duration.")
            cfg.time_step_min = float(time_step_min)
        if initial_water_depth_m is not None:
            if initial_water_depth_m < 0 or initial_water_depth_m > 10.0:
                raise ValidationError("Initial water depth must be between 0 and 10 m.")
            cfg.initial_water_depth_m = float(initial_water_depth_m)

        if disabled_drainage_ids is not None:
            cfg.disabled_drainage_ids = set(int(d) for d in disabled_drainage_ids)
        if drainage_capacity_scale is not None:
            if drainage_capacity_scale < 0 or drainage_capacity_scale > 10.0:
                raise ValidationError("Drainage capacity multiplier must be between 0.0 and 10.0.")
            cfg.drainage_capacity_scale = float(drainage_capacity_scale)
        if extra_drainage_features:
            for df in extra_drainage_features:
                copy_df = copy.deepcopy(df)
                copy_df.source = "what-if-hypothetical"
                cfg.extra_drainage_features.append(copy_df)
            is_hypothetical = True

        if infiltration_scale != 1.0:
            if infiltration_scale < 0 or infiltration_scale > 5.0:
                raise ValidationError("Infiltration scale multiplier must be between 0.0 and 5.0.")
            cfg.use_cell_infiltration_if_present = False
            cfg.category_infiltration_rates_mm_hr = {
                cat: round(max(0.0, float(rate) * float(infiltration_scale)), 4)
                for cat, rate in cfg.category_infiltration_rates_mm_hr.items()
            }
        if cell_land_use_infiltration_mm_hr:
            for cid, rate in cell_land_use_infiltration_mm_hr.items():
                if float(rate) < 0:
                    raise ValidationError("Cell infiltration override cannot be negative.")
                cfg.cell_infiltration_overrides_mm_hr[int(cid)] = float(rate)

        return ScenarioVariant(
            name=cfg.scenario_name,
            config=cfg,
            description=description,
            experiment_key=experiment_key,
            is_hypothetical=is_hypothetical,
            is_stress_test=is_stress_test,
            closed_edge_ids=set(int(e) for e in (closed_edge_ids or set())),
            reopened_edge_ids=set(int(e) for e in (reopened_edge_ids or set())),
            baseline_run_id=baseline_run_id,
            notes=notes,
        )

    def build_experiment_variants(
        self,
        experiment_key: str,
        base_config: SimulationConfig,
        cells: list[GridCell],
        drainage_features: list[DrainageFeature],
        *,
        selected_drainage_ids: list[int] | None = None,
        selected_road_edge_ids: list[int] | None = None,
        baseline_run_id: int | None = None,
    ) -> tuple[str, list[ScenarioVariant]]:
        """Build the 6 required ready-made What-If experiments cleanly without altering DB state."""
        # Experiment 1: Heavy rainfall (30 vs 60 vs 100 mm/hr)
        if experiment_key == "exp1_heavy_rainfall":
            variants = [
                self.create_modified_variant(
                    base_config,
                    name=f"[Exp 1] {int(r)} mm/hr Storm",
                    description=f"Hypothetical {int(r)} mm/hr rainfall with identical baseline drainage & infiltration.",
                    experiment_key=experiment_key,
                    baseline_run_id=baseline_run_id,
                    rainfall_intensity_mm_hr=float(r),
                    is_hypothetical=True,
                )
                for r in (30.0, 60.0, 100.0)
            ]
            return "Experiment 1: Heavy Rainfall (30 vs 60 vs 100 mm/hr)", variants

        # Experiment 2: Drainage failure (Normal vs 1 disabled vs multiple disabled)
        if experiment_key == "exp2_drainage_failure":
            op_drains = [d for d in drainage_features if d.id is not None and d.status != "Blocked"]
            if not op_drains and drainage_features:
                op_drains = [d for d in drainage_features if d.id is not None]

            picked = [int(i) for i in (selected_drainage_ids or [])]
            if not picked and op_drains:
                picked = [int(d.id) for d in op_drains[: min(3, len(op_drains))] if d.id is not None]

            one_disabled = {picked[0]} if picked else set()
            multi_disabled = set(picked) if len(picked) >= 2 else set(picked)

            v_norm = self.create_modified_variant(
                base_config,
                name="[Exp 2] Normal Drainage",
                description="Baseline drainage features enabled.",
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                disabled_drainage_ids=set(),
                drainage_capacity_scale=1.0,
            )
            v_one = self.create_modified_variant(
                base_config,
                name=f"[Exp 2] 1 Drain Failed ({len(one_disabled)} disabled)",
                description=f"Selected drainage feature(s) disabled: {sorted(one_disabled) or 'N/A (scaled capacity 0.7x)'}.",
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                disabled_drainage_ids=one_disabled,
                drainage_capacity_scale=1.0 if one_disabled else 0.7,
                is_hypothetical=True,
            )
            v_multi = self.create_modified_variant(
                base_config,
                name=f"[Exp 2] Multi-Drain Failure ({len(multi_disabled)} disabled)",
                description=(
                    f"Multiple drainage features disabled: {sorted(multi_disabled)}."
                    if multi_disabled
                    else "Severe drainage failure fallback (cell & drain capacity scaled 0.25x)."
                ),
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                disabled_drainage_ids=multi_disabled,
                drainage_capacity_scale=1.0 if len(multi_disabled) >= 2 else 0.25,
                is_hypothetical=True,
            )
            return "Experiment 2: Drainage Failure Analysis", [v_norm, v_one, v_multi]

        # Experiment 3: Improved drainage (Existing vs +50% capacity vs Hypothetical Channel)
        if experiment_key == "exp3_improved_drainage":
            nid = cells[0].neighbourhood_id if cells else 0
            target_cell = _pick_representative_cell(cells)
            hyp_drain = DrainageFeature(
                id=None,
                neighbourhood_id=nid,
                grid_cell_id=target_cell.id if target_cell else None,
                name="Hypothetical Relief Channel (What-If)",
                feature_type="Drainage channel",
                latitude=target_cell.center_latitude if target_cell else 0.0,
                longitude=target_cell.center_longitude if target_cell else 0.0,
                capacity=450.0,
                capacity_unit="L/s",
                status="Operational",
                source="what-if-hypothetical",
                notes="HYPOTHETICAL INFRASTRUCTURE: Proposed stormwater channel tested in What-If Lab.",
            )
            v_exist = self.create_modified_variant(
                base_config,
                name="[Exp 3] Existing Drainage",
                description="Current stored drainage network and cell drainage rates.",
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                drainage_capacity_scale=1.0,
            )
            v_inc = self.create_modified_variant(
                base_config,
                name="[Exp 3] Upgraded Drainage (+50%)",
                description="Hypothetical 1.5x increase in drainage discharge capacity.",
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                drainage_capacity_scale=1.5,
                is_hypothetical=True,
            )
            v_hyp = self.create_modified_variant(
                base_config,
                name="[Exp 3] Hypothetical Relief Channel (450 L/s)",
                description=f"Adds hypothetical non-verified relief channel at cell {target_cell.cell_code if target_cell else 'center'}.",
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                drainage_capacity_scale=1.25,
                extra_drainage_features=[hyp_drain],
                is_hypothetical=True,
                notes="Hypothetical infrastructure — NOT present on the real neighbourhood map.",
            )
            return "Experiment 3: Improved Drainage & Hypothetical Channel", [v_exist, v_inc, v_hyp]

        # Experiment 4: Land-use / infiltration changes
        if experiment_key == "exp4_land_use":
            v_base = self.create_modified_variant(
                base_config,
                name="[Exp 4] Baseline Infiltration",
                description="Existing land-use infiltration assumptions.",
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                infiltration_scale=1.0,
            )
            v_low = self.create_modified_variant(
                base_config,
                name="[Exp 4] Lower Infiltration (-40% Paved)",
                description="Simulates higher impervious paving (0.6x infiltration capacity).",
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                infiltration_scale=0.60,
                is_hypothetical=True,
            )
            v_high = self.create_modified_variant(
                base_config,
                name="[Exp 4] Higher Infiltration (+40% Pervious)",
                description="Simulates permeable green/sponge improvements (1.4x infiltration capacity).",
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                infiltration_scale=1.40,
                is_hypothetical=True,
            )
            return "Experiment 4: Land-Use & Infiltration Changes", [v_base, v_low, v_high]

        # Experiment 5: Road closure & SafeRoute availability
        if experiment_key == "exp5_road_closure":
            picked_edges = set(int(e) for e in (selected_road_edge_ids or []))
            v_open = self.create_modified_variant(
                base_config,
                name="[Exp 5] Normal Road Network",
                description="Flood simulation with normal open road network for baseline SafeRoute comparison.",
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                closed_edge_ids=set(),
            )
            v_closed = self.create_modified_variant(
                base_config,
                name=f"[Exp 5] Road Closures Applied ({len(picked_edges)} closed)",
                description=f"Closes {len(picked_edges)} road segment(s) during SafeRoute alternative evacuation calculation.",
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                closed_edge_ids=picked_edges,
                is_hypothetical=True,
            )
            return "Experiment 5: Road Closure & Alternative SafeRoute", [v_open, v_closed]

        # Experiment 6: Combined extreme scenario (stress-test)
        if experiment_key == "exp6_combined_extreme":
            v_base = self.create_modified_variant(
                base_config,
                name="[Exp 6] Baseline Reference",
                description="Baseline configuration before extreme stress-test multipliers.",
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
            )
            v_extreme = self.create_modified_variant(
                base_config,
                name="[Exp 6] Hypothetical Stress-Test (100mm/h, Low Drain & Infil)",
                description=(
                    "HYPOTHETICAL STRESS-TEST SCENARIO: 100 mm/hr rainfall + 50% drainage capacity + "
                    "40% reduced soil infiltration."
                ),
                experiment_key=experiment_key,
                baseline_run_id=baseline_run_id,
                rainfall_intensity_mm_hr=max(100.0, base_config.rainfall_intensity_mm_hr),
                drainage_capacity_scale=0.50,
                infiltration_scale=0.60,
                is_hypothetical=True,
                is_stress_test=True,
                notes="Hypothetical stress-test scenario — NOT an official weather prediction.",
            )
            return "Experiment 6: Combined Extreme Stress-Test Scenario", [v_base, v_extreme]

        raise ValidationError(f"Unknown What-If experiment key: {experiment_key}")

    def run_variant(
        self,
        neighbourhood: Neighbourhood,
        cells: list[GridCell],
        drainage_features: list[DrainageFeature],
        variant: ScenarioVariant,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> SimulationOutput:
        """Execute a single ScenarioVariant non-destructively."""
        return run_simulation(
            cells=cells,
            config=variant.config,
            drainage_features=drainage_features,
            neighbourhood_id=neighbourhood.id,
            progress_callback=(
                (lambda step, total, _rec: on_progress(step, total, variant.name))
                if on_progress
                else None
            ),
        )

    def run_experiment_batch(
        self,
        neighbourhood: Neighbourhood,
        cells: list[GridCell],
        drainage_features: list[DrainageFeature],
        experiment_key: str,
        title: str,
        variants: list[ScenarioVariant],
    ) -> ExperimentExecutionResult:
        """Run all variants in an experiment cleanly."""
        outputs: list[SimulationOutput] = []
        for variant in variants:
            out = self.run_variant(neighbourhood, cells, drainage_features, variant)
            outputs.append(out)
        return ExperimentExecutionResult(
            experiment_key=experiment_key,
            experiment_title=title,
            variants=variants,
            outputs=outputs,
        )
