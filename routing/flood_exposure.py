"""Road-segment flood exposure analysis linked to Phase 3 results and Phase 4 risk tiers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from config import DEFAULT_ROAD_EXPOSURE_THRESHOLDS_CM, SIMULATION_MODE_ELEVATION
from core.flood_statistics import extract_step_cell_data
from core.models import GridCell
from core.simulation_engine import SimulationOutput
from core.validation import ValidationError
from routing.road_network import RoadNetworkGraph


@dataclass(slots=True)
class RoadExposureThresholds:
    """Configurable illustrative depth thresholds (cm) for road exposure categories."""

    low_max_cm: float = DEFAULT_ROAD_EXPOSURE_THRESHOLDS_CM["low_max_cm"]          # >0 to 10 cm
    moderate_max_cm: float = DEFAULT_ROAD_EXPOSURE_THRESHOLDS_CM["moderate_max_cm"]  # >10 to 30 cm
    high_max_cm: float = DEFAULT_ROAD_EXPOSURE_THRESHOLDS_CM["high_max_cm"]        # >30 to 60 cm
    wet_cutoff_cm: float = 0.01  # 0.1 mm threshold

    def validate(self) -> None:
        vals = (self.wet_cutoff_cm, self.low_max_cm, self.moderate_max_cm, self.high_max_cm)
        if not all(math.isfinite(v) for v in vals):
            raise ValidationError("Road exposure thresholds must be finite numbers.")
        if self.wet_cutoff_cm < 0.0:
            raise ValidationError("Wet cutoff depth must be >= 0 cm.")
        if not (0.0 < self.low_max_cm <= self.moderate_max_cm <= self.high_max_cm):
            raise ValidationError(
                "Road exposure thresholds must satisfy: 0 < Low Max <= Moderate Max <= High Max (cm)."
            )


@dataclass(slots=True)
class RoadFloodExposure:
    """Simulated flood exposure snapshot for one road edge at a simulation timestep."""

    road_edge_id: int
    intersecting_cell_ids: list[int]
    max_depth_m: float | None
    avg_depth_m: float | None
    max_depth_cm: float | None
    avg_depth_cm: float | None
    exposure_category: str  # No surface flooding | Low | Moderate | High | Very high | Unknown
    simulation_id: int | None
    timestep: int | None
    sim_time_minutes: float | None
    status_source: str  # simulation-derived | unknown
    reason: str = ""
    uses_illustrative_terrain: bool = False


def classify_road_exposure_depth(
    depth_m: float | None,
    thresholds: RoadExposureThresholds | None = None,
) -> str:
    """Classify simulated water depth (m) along a road into illustrative exposure tiers."""
    if depth_m is None or not math.isfinite(depth_m):
        return "Unknown"
    th = thresholds or RoadExposureThresholds()
    th.validate()
    depth_cm = max(0.0, float(depth_m)) * 100.0
    if depth_cm <= th.wet_cutoff_cm:
        return "No surface flooding"
    if depth_cm <= th.low_max_cm:
        return "Low"
    if depth_cm <= th.moderate_max_cm:
        return "Moderate"
    if depth_cm <= th.high_max_cm:
        return "High"
    return "Very high"


def _cell_has_stored_elevation(cell: GridCell | None) -> bool:
    if cell is None:
        return False
    return (cell.mean_elevation_m is not None and math.isfinite(cell.mean_elevation_m)) or (
        cell.elevation_m is not None and math.isfinite(cell.elevation_m)
    )


def analyze_road_network_exposure(
    network: RoadNetworkGraph,
    cells: Iterable[GridCell],
    output: SimulationOutput | None,
    timestep: int | None = None,
    thresholds: RoadExposureThresholds | None = None,
    require_verified_elevation: bool = False,
) -> dict[int, RoadFloodExposure]:
    """Evaluate every road edge against intersecting Phase 3 simulation cells.

    Unknown rules (never treat unknown as safe):
    - No simulation output / empty steps -> all edges Unknown.
    - Edge has no intersecting grid cells -> Unknown.
    - Intersecting cells lack stored simulation depth coverage -> Unknown.
    - Intersecting cells lack stored elevation AND (`require_verified_elevation=True`
      or simulation predicts 0 cm on unverified terrain) -> Unknown rather than safe.
    """
    th = thresholds or RoadExposureThresholds()
    th.validate()

    cell_by_id: dict[int, GridCell] = {}
    for idx, cell in enumerate(cells):
        cid = cell.id if cell.id is not None else (idx + 1)
        cell_by_id[cid] = cell

    results: dict[int, RoadFloodExposure] = {}

    if output is None or not output.steps or not output.cell_steps:
        for edge_id, edge in network.edges_by_id.items():
            edge.max_depth_m = None
            edge.avg_depth_m = None
            edge.exposure_category = "Unknown"
            results[edge_id] = RoadFloodExposure(
                road_edge_id=edge_id,
                intersecting_cell_ids=list(edge.grid_cell_ids),
                max_depth_m=None,
                avg_depth_m=None,
                max_depth_cm=None,
                avg_depth_cm=None,
                exposure_category="Unknown",
                simulation_id=output.run.id if output else None,
                timestep=None,
                sim_time_minutes=None,
                status_source="unknown",
                reason="No simulation selected or simulation has no timestep results.",
                uses_illustrative_terrain=False,
            )
        return results

    sorted_steps = sorted(output.steps, key=lambda s: s.timestep)
    target_step = timestep if timestep is not None else sorted_steps[-1].timestep
    depths_by_cell, _, sim_time = extract_step_cell_data(output, target_step)
    used_illustrative = bool(output.summary.used_illustrative_terrain) or (
        output.run.simulation_mode != SIMULATION_MODE_ELEVATION
    )

    for edge_id, edge in network.edges_by_id.items():
        cids = list(edge.grid_cell_ids)
        if not cids:
            edge.max_depth_m = None
            edge.avg_depth_m = None
            edge.exposure_category = "Unknown"
            results[edge_id] = RoadFloodExposure(
                road_edge_id=edge_id,
                intersecting_cell_ids=[],
                max_depth_m=None,
                avg_depth_m=None,
                max_depth_cm=None,
                avg_depth_cm=None,
                exposure_category="Unknown",
                simulation_id=output.run.id,
                timestep=target_step,
                sim_time_minutes=sim_time,
                status_source="unknown",
                reason="Road segment lies outside simulation grid cell coverage.",
                uses_illustrative_terrain=used_illustrative,
            )
            continue

        covered_depths = [depths_by_cell[cid] for cid in cids if cid in depths_by_cell]
        if len(covered_depths) < len(cids):
            edge.max_depth_m = max(covered_depths) if covered_depths else None
            edge.avg_depth_m = (sum(covered_depths) / len(covered_depths)) if covered_depths else None
            edge.exposure_category = "Unknown"
            results[edge_id] = RoadFloodExposure(
                road_edge_id=edge_id,
                intersecting_cell_ids=cids,
                max_depth_m=edge.max_depth_m,
                avg_depth_m=edge.avg_depth_m,
                max_depth_cm=(edge.max_depth_m * 100.0) if edge.max_depth_m is not None else None,
                avg_depth_cm=(edge.avg_depth_m * 100.0) if edge.avg_depth_m is not None else None,
                exposure_category="Unknown",
                simulation_id=output.run.id,
                timestep=target_step,
                sim_time_minutes=sim_time,
                status_source="unknown",
                reason="Missing simulation depth coverage for one or more intersecting grid cells.",
                uses_illustrative_terrain=used_illustrative,
            )
            continue

        max_d = max(covered_depths)
        avg_d = sum(covered_depths) / len(covered_depths)
        all_cells_have_elev = all(_cell_has_stored_elevation(cell_by_id.get(cid)) for cid in cids)

        if require_verified_elevation and not all_cells_have_elev:
            edge.max_depth_m = max_d
            edge.avg_depth_m = avg_d
            edge.exposure_category = "Unknown"
            results[edge_id] = RoadFloodExposure(
                road_edge_id=edge_id,
                intersecting_cell_ids=cids,
                max_depth_m=max_d,
                avg_depth_m=avg_d,
                max_depth_cm=max_d * 100.0,
                avg_depth_cm=avg_d * 100.0,
                exposure_category="Unknown",
                simulation_id=output.run.id,
                timestep=target_step,
                sim_time_minutes=sim_time,
                status_source="unknown",
                reason="Missing verified ground elevation on intersecting cell(s); marked Unknown.",
                uses_illustrative_terrain=used_illustrative,
            )
            continue

        raw_cat = classify_road_exposure_depth(max_d, th)
        # Never declare dry ("No surface flooding" / zero) as confirmed safe if underlying cell elevation is missing
        if raw_cat == "No surface flooding" and not all_cells_have_elev:
            final_cat = "Unknown"
            src = "unknown"
            reason = (
                "Simulated 0 cm under illustrative terrain with missing verified cell elevation; "
                "marked Unknown rather than safe."
            )
        else:
            final_cat = raw_cat
            src = "simulation-derived"
            reason = (
                "Derived from Illustrative Assumed Terrain simulation (non-verified)."
                if used_illustrative
                else "Derived from elevation-based simulation output."
            )

        edge.max_depth_m = max_d
        edge.avg_depth_m = avg_d
        edge.exposure_category = final_cat
        results[edge_id] = RoadFloodExposure(
            road_edge_id=edge_id,
            intersecting_cell_ids=cids,
            max_depth_m=max_d,
            avg_depth_m=avg_d,
            max_depth_cm=max_d * 100.0,
            avg_depth_cm=avg_d * 100.0,
            exposure_category=final_cat,
            simulation_id=output.run.id,
            timestep=target_step,
            sim_time_minutes=sim_time,
            status_source=src,
            reason=reason,
            uses_illustrative_terrain=used_illustrative,
        )

    return results


__all__ = [
    "RoadExposureThresholds",
    "RoadFloodExposure",
    "analyze_road_network_exposure",
    "classify_road_exposure_depth",
]
