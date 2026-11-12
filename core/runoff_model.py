"""Surface runoff generation diagnostic calculation."""

from __future__ import annotations

import numpy as np


def calculate_runoff(
    rainfall_volumes_m3: np.ndarray,
    infiltration_losses_m3: np.ndarray,
    surface_volumes_m3: np.ndarray,
    cell_areas_m2: np.ndarray,
) -> dict[str, np.ndarray]:
    """Compute step excess runoff volume (m^3) and equivalent depth (m).

    Note: Surface water volume balance already reflects added rainfall minus
    infiltration; this function quantifies the step excess runoff generated above
    soil infiltration without double-subtracting from surface storage.
    """
    rain = np.maximum(0.0, np.asarray(rainfall_volumes_m3, dtype=np.float64))
    infil = np.maximum(0.0, np.asarray(infiltration_losses_m3, dtype=np.float64))
    avail = np.maximum(0.0, np.asarray(surface_volumes_m3, dtype=np.float64))
    areas = np.maximum(1e-9, np.asarray(cell_areas_m2, dtype=np.float64))

    excess_runoff_m3 = np.maximum(0.0, rain - infil)
    excess_runoff_depth_m = excess_runoff_m3 / areas
    surface_depth_m = avail / areas
    return {
        "excess_runoff_m3": excess_runoff_m3,
        "excess_runoff_depth_m": excess_runoff_depth_m,
        "surface_depth_m": surface_depth_m,
    }
