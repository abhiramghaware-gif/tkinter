"""Drainage infrastructure capacity resolution and step removal model."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from config import DRAINAGE_STATUS_FACTORS
from core.models import DrainageFeature, GridCell
from core.simulation_config import SimulationConfig
from core.validation import ValidationError


@dataclass(slots=True)
class CellDrainageProfile:
    """Resolved drainage discharge summary for a single grid cell."""

    cell_index: int
    cell_id: int | None
    cell_code: str
    effective_discharge_m3_s: float
    feature_count: int
    unknown_capacity_count: int
    disabled_count: int
    provenance_notes: str


def _feature_to_m3_per_s(
    capacity: float | None,
    unit: str,
    cell_area_m2: float,
    feature_name: str,
) -> float:
    """Convert a drainage feature capacity into cubic metres per second (m^3/s)."""
    if capacity is None:
        return 0.0
    val = float(capacity)
    if not math.isfinite(val) or val < 0.0:
        raise ValidationError(
            f"Drainage feature '{feature_name}' has invalid capacity ({capacity}); must be finite and >= 0."
        )
    u = (unit or "L/s").strip()
    if u == "L/s":
        return val / 1000.0
    if u in ("m3/s", "m³/s"):
        return val
    if u == "mm/hr":
        return (val / 1000.0 / 3600.0) * cell_area_m2
    raise ValidationError(f"Unsupported drainage capacity unit '{unit}' on '{feature_name}'.")


def resolve_cell_drainage_profiles(
    cells: list[GridCell],
    drainage_features: list[DrainageFeature],
    config: SimulationConfig,
) -> tuple[np.ndarray, list[CellDrainageProfile], list[str]]:
    """Resolve effective drainage discharge (m^3/s) per cell and diagnostic warnings."""
    if not math.isfinite(config.drainage_capacity_scale) or config.drainage_capacity_scale < 0.0:
        raise ValidationError("Drainage capacity scale must be finite and >= 0.")

    cell_idx_by_id: dict[int, int] = {
        c.id: idx for idx, c in enumerate(cells) if c.id is not None
    }
    all_features: list[DrainageFeature] = []
    if config.include_drainage_features:
        all_features.extend(drainage_features)
    all_features.extend(config.extra_drainage_features)

    # Group drainage features by cell index
    grouped: dict[int, list[DrainageFeature]] = {idx: [] for idx in range(len(cells))}
    unassigned_count = 0

    for feat in all_features:
        target_idx: int | None = None
        if feat.grid_cell_id is not None and feat.grid_cell_id in cell_idx_by_id:
            target_idx = cell_idx_by_id[feat.grid_cell_id]
        else:
            for idx, c in enumerate(cells):
                if (
                    c.min_latitude <= feat.latitude <= c.max_latitude
                    and c.min_longitude <= feat.longitude <= c.max_longitude
                ):
                    target_idx = idx
                    break
        if target_idx is None:
            unassigned_count += 1
            continue
        grouped[target_idx].append(feat)

    max_discharge_m3_s = np.zeros(len(cells), dtype=np.float64)
    profiles: list[CellDrainageProfile] = []
    warnings: list[str] = []

    if unassigned_count > 0:
        warnings.append(
            f"{unassigned_count} drainage feature(s) lie outside the simulation grid bounds and were excluded."
        )

    total_unknown_cap = 0
    total_unknown_status = 0

    for idx, cell in enumerate(cells):
        area = cell.approx_area_sq_m()
        q_total = 0.0
        notes: list[str] = []
        unk_cap = 0
        disabled_cnt = 0

        if config.include_cell_drainage_capacity:
            c_cap = float(cell.drainage_capacity or 0.0)
            if not math.isfinite(c_cap) or c_cap < 0.0:
                raise ValidationError(
                    f"Cell {cell.cell_code} has invalid drainage_capacity ({c_cap}); must be >= 0 mm/hr."
                )
            if c_cap > 0.0:
                q_cell = (c_cap / 1000.0 / 3600.0) * area * float(config.drainage_capacity_scale)
                q_total += q_cell
                notes.append(f"cell={c_cap:.2f} mm/hr ({cell.drainage_source})")

        feats = grouped[idx]
        for feat in feats:
            if feat.id is not None and feat.id in config.disabled_drainage_ids:
                disabled_cnt += 1
                notes.append(f"{feat.name}: disabled (what-if)")
                continue

            if feat.capacity is None:
                unk_cap += 1
                total_unknown_cap += 1
                notes.append(f"{feat.name}: capacity unknown (0 assumed)")
                continue

            q_raw = _feature_to_m3_per_s(feat.capacity, feat.capacity_unit, area, feat.name)
            factor = DRAINAGE_STATUS_FACTORS.get(feat.status, 0.0)
            if feat.status == "Unknown":
                total_unknown_status += 1
            q_eff = q_raw * factor * float(config.drainage_capacity_scale)
            q_total += q_eff
            notes.append(
                f"{feat.name} ({feat.feature_type}, {feat.status}, {feat.source}): "
                f"{q_eff * 1000.0:.2f} L/s"
            )

        max_discharge_m3_s[idx] = max(0.0, q_total)
        profiles.append(
            CellDrainageProfile(
                cell_index=idx,
                cell_id=cell.id,
                cell_code=cell.cell_code,
                effective_discharge_m3_s=max(0.0, q_total),
                feature_count=len(feats),
                unknown_capacity_count=unk_cap,
                disabled_count=disabled_cnt,
                provenance_notes="; ".join(notes) if notes else "none",
            )
        )

    if total_unknown_cap > 0:
        warnings.append(
            f"{total_unknown_cap} drainage feature(s) have NULL/unknown capacity and contribute 0 m3/s "
            "(capacity is never invented)."
        )
    if total_unknown_status > 0:
        warnings.append(
            f"{total_unknown_status} drainage feature(s) have 'Unknown' operational status and were treated as inactive (0%)."
        )

    return max_discharge_m3_s, profiles, warnings


def calculate_drainage(
    available_volumes_m3: np.ndarray,
    max_discharge_m3_s: np.ndarray,
    time_step_seconds: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Remove water up to min(available_water, capacity * dt).

    Returns (drainage_loss_m3, remaining_surface_volumes_m3).
    """
    if time_step_seconds <= 0.0 or not math.isfinite(time_step_seconds):
        raise ValidationError("Time step duration (s) must be finite and > 0.")

    avail = np.maximum(0.0, np.asarray(available_volumes_m3, dtype=np.float64))
    q_m3_s = np.maximum(0.0, np.asarray(max_discharge_m3_s, dtype=np.float64))
    max_removal_m3 = q_m3_s * float(time_step_seconds)

    drainage_loss_m3 = np.minimum(avail, max_removal_m3)
    remaining_volumes_m3 = np.maximum(0.0, avail - drainage_loss_m3)
    return drainage_loss_m3, remaining_volumes_m3
