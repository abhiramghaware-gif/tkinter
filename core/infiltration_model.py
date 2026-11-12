"""Soil infiltration loss model with editable illustrative land-use defaults."""

from __future__ import annotations

import numpy as np

from config import DEFAULT_INFILTRATION_RATES_MM_HR, LAND_USE_TO_INFILTRATION_CATEGORY
from core.models import GridCell
from core.simulation_config import SimulationConfig
from core.validation import ValidationError


def resolve_cell_infiltration_rates(
    cells: list[GridCell],
    config: SimulationConfig,
) -> tuple[np.ndarray, list[str]]:
    """Resolve per-cell infiltration rate (mm/hr) and explicit provenance labels.

    Priority order (never mutating saved cells):
      1. In-memory What-If override (`config.cell_infiltration_overrides_mm_hr`)
      2. Explicit cell infiltration rate (`cell.infiltration_rate` when source != 'missing')
      3. Editable category assumption (`config.category_infiltration_rates_mm_hr`)
    """
    rates = np.zeros(len(cells), dtype=np.float64)
    provenance: list[str] = []

    for idx, cell in enumerate(cells):
        cid = cell.id if cell.id is not None else idx
        if cell.id is not None and cell.id in config.cell_infiltration_overrides_mm_hr:
            val = float(config.cell_infiltration_overrides_mm_hr[cell.id])
            src = "what-if-override (illustrative)"
        elif (
            config.use_cell_infiltration_if_present
            and cell.infiltration_source != "missing"
            and cell.infiltration_rate >= 0.0
        ):
            val = float(cell.infiltration_rate)
            src = f"cell-parameter ({cell.infiltration_source})"
        else:
            cat_key = LAND_USE_TO_INFILTRATION_CATEGORY.get(cell.land_use, "Residential")
            val = float(
                config.category_infiltration_rates_mm_hr.get(
                    cat_key,
                    DEFAULT_INFILTRATION_RATES_MM_HR.get(cat_key, 5.0),
                )
            )
            src = f"illustrative-assumption ({cat_key})"

        if not np.isfinite(val) or val < 0.0:
            raise ValidationError(
                f"Infiltration rate for cell {cell.cell_code} (id={cid}) must be finite and >= 0 mm/hr."
            )
        rates[idx] = val
        provenance.append(src)

    return rates, provenance


def calculate_infiltration(
    available_volumes_m3: np.ndarray,
    cell_areas_m2: np.ndarray,
    infiltration_rates_mm_hr: np.ndarray,
    time_step_seconds: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Calculate actual infiltration loss (m^3) bounded by both capacity and available water.

    Returns (infiltration_loss_m3, remaining_surface_volumes_m3).
    Never produces negative water volume or negative infiltration.
    """
    if time_step_seconds <= 0.0 or not np.isfinite(time_step_seconds):
        raise ValidationError("Time step duration (s) must be finite and > 0.")

    avail = np.maximum(0.0, np.asarray(available_volumes_m3, dtype=np.float64))
    areas = np.asarray(cell_areas_m2, dtype=np.float64)
    rates = np.asarray(infiltration_rates_mm_hr, dtype=np.float64)
    if np.any(rates < 0.0) or not np.all(np.isfinite(rates)):
        raise ValidationError("Infiltration rates must be finite and >= 0 mm/hr.")

    dt_hours = float(time_step_seconds) / 3600.0
    potential_depth_m = (rates * dt_hours) / 1000.0
    potential_volume_m3 = np.maximum(0.0, potential_depth_m * areas)

    infiltration_loss_m3 = np.minimum(avail, potential_volume_m3)
    remaining_volumes_m3 = np.maximum(0.0, avail - infiltration_loss_m3)
    return infiltration_loss_m3, remaining_volumes_m3
