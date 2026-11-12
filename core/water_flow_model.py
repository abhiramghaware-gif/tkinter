"""Surface water head comparison and mass-conserving cell-to-cell flow routing."""

from __future__ import annotations

import math

import numpy as np

from config import SIMULATION_MODE_ELEVATION, SIMULATION_MODE_ILLUSTRATIVE
from core.models import GridCell
from core.simulation_config import SimulationConfig
from core.validation import ValidationError


def resolve_cell_elevations(
    cells: list[GridCell],
    config: SimulationConfig,
) -> tuple[np.ndarray, list[str], bool, list[str]]:
    """Resolve cell ground elevations (m) according to selected simulation mode.

    Returns (elevations_m, provenance_per_cell, used_illustrative_terrain, warnings).
    In 'elevation_based' mode, raises ValidationError if any cell lacks elevation.
    In 'illustrative_assumed' mode, uses verified elevation where present and fills
    missing cells with a configurable synthetic terrain plane, flagged clearly.
    """
    if config.simulation_mode not in (SIMULATION_MODE_ELEVATION, SIMULATION_MODE_ILLUSTRATIVE):
        raise ValidationError(f"Unknown simulation mode: '{config.simulation_mode}'.")

    elevations = np.zeros(len(cells), dtype=np.float64)
    provenance: list[str] = []
    warnings: list[str] = []
    missing_codes: list[str] = []
    assumed_count = 0

    max_row = max((c.row_number for c in cells), default=0)
    max_col = max((c.column_number for c in cells), default=0)

    for idx, cell in enumerate(cells):
        raw_elev = cell.mean_elevation_m if cell.mean_elevation_m is not None else cell.elevation_m
        if raw_elev is not None and math.isfinite(float(raw_elev)):
            elevations[idx] = float(raw_elev)
            provenance.append(cell.elevation_source or "stored")
        else:
            missing_codes.append(cell.cell_code)
            if config.simulation_mode == SIMULATION_MODE_ILLUSTRATIVE:
                r_frac = (cell.row_number / max_row) if max_row > 0 else 0.0
                c_frac = (cell.column_number / max_col) if max_col > 0 else 0.0
                # Gentle synthetic slope toward SE (for illustrative testing only)
                assumed = (
                    float(config.illustrative_base_elevation_m)
                    + (1.0 - r_frac) * float(config.illustrative_north_south_slope_m)
                    + (1.0 - c_frac) * float(config.illustrative_west_east_slope_m)
                )
                elevations[idx] = assumed
                provenance.append("illustrative-assumed (non-verified)")
                assumed_count += 1

    if missing_codes and config.simulation_mode == SIMULATION_MODE_ELEVATION:
        preview = ", ".join(missing_codes[:8])
        more = f" (+{len(missing_codes) - 8} more)" if len(missing_codes) > 8 else ""
        raise ValidationError(
            f"Elevation-based simulation cannot run: {len(missing_codes)}/{len(cells)} grid cell(s) "
            f"have NULL/missing elevation ({preview}{more}). "
            "Import a GeoTIFF DEM in Elevation Manager, enter elevations manually, or switch "
            "to 'Illustrative Assumed Terrain' mode."
        )

    used_illustrative = assumed_count > 0 or config.simulation_mode == SIMULATION_MODE_ILLUSTRATIVE
    if assumed_count > 0:
        warnings.append(
            f"ILLUSTRATIVE TERRAIN MODE: {assumed_count}/{len(cells)} grid cell(s) lack verified elevation "
            "and use non-verified illustrative terrain assumptions. Do not treat as true Potheri topography."
        )
    elif config.simulation_mode == SIMULATION_MODE_ILLUSTRATIVE:
        warnings.append(
            "Simulation executed under Illustrative Mode tag using stored cell elevations."
        )

    return elevations, provenance, used_illustrative, warnings


def build_neighbour_index(cells: list[GridCell]) -> list[list[int]]:
    """Build 4-connected (N/S/E/W) neighbour index lists respecting grid boundaries."""
    pos_to_idx: dict[tuple[int, int], int] = {
        (c.row_number, c.column_number): idx for idx, c in enumerate(cells)
    }
    neighbours: list[list[int]] = []
    for c in cells:
        adj: list[int] = []
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            n_idx = pos_to_idx.get((c.row_number + dr, c.column_number + dc))
            if n_idx is not None:
                adj.append(n_idx)
        neighbours.append(adj)
    return neighbours


def calculate_surface_flow(
    volumes_m3: np.ndarray,
    cell_areas_m2: np.ndarray,
    elevations_m: np.ndarray,
    neighbours: list[list[int]],
    time_step_seconds: float,
    mobility: float = 0.35,
) -> tuple[np.ndarray, float, np.ndarray]:
    """Route surface water from higher water-surface elevation to lower neighbours.

    Water surface elevation:
        H_i = E_i + (V_i / A_i)

    Properties enforced strictly:
      - Transfers only occur when H_i > H_j (higher head to lower head).
      - No double-counting across shared interfaces.
      - Outflow from any cell i never exceeds available volume V_i.
      - Grid boundaries are closed (no water disappears outside grid).
      - Internal mass balance sum(V_out) == sum(V_in) is exact.
    """
    if time_step_seconds <= 0.0 or not math.isfinite(time_step_seconds):
        raise ValidationError("Time step duration (s) must be finite and > 0.")
    if not (0.0 <= mobility <= 1.0) or not math.isfinite(mobility):
        raise ValidationError("Surface flow mobility must be within [0.0, 1.0].")

    vols = np.maximum(0.0, np.asarray(volumes_m3, dtype=np.float64)).copy()
    areas = np.asarray(cell_areas_m2, dtype=np.float64)
    elevs = np.asarray(elevations_m, dtype=np.float64)
    n_cells = len(vols)

    if mobility == 0.0 or n_cells <= 1:
        return vols, 0.0, np.zeros(n_cells, dtype=np.float64)

    # Sub-step to avoid hydraulic head overshoot across long user time steps
    n_sub = max(1, min(30, int(math.ceil(float(time_step_seconds) / 30.0))))
    dt_sub = float(time_step_seconds) / n_sub
    alpha = min(0.45, float(mobility) * (dt_sub / 30.0))

    total_transferred_m3 = 0.0
    per_cell_outflow_m3 = np.zeros(n_cells, dtype=np.float64)

    for _ in range(n_sub):
        heads = elevs + (vols / areas)
        inflows = np.zeros(n_cells, dtype=np.float64)
        outflows = np.zeros(n_cells, dtype=np.float64)

        for i in range(n_cells):
            v_i = float(vols[i])
            if v_i <= 0.0:
                continue
            h_i = float(heads[i])
            lower_nbrs: list[tuple[int, float]] = []
            for j in neighbours[i]:
                dh = h_i - float(heads[j])
                if dh > 1e-12:
                    lower_nbrs.append((j, dh))
            if not lower_nbrs:
                continue

            # Distribute outflow proportionally to positive head differences, capped to avoid
            # draining below local equilibrium or exceeding available water in cell i.
            denom = 1.0 + len(lower_nbrs)
            desired = [alpha * float(areas[i]) * (dh / denom) for _, dh in lower_nbrs]
            desired_sum = sum(desired)
            if desired_sum <= 0.0:
                continue

            scale = min(1.0, v_i / desired_sum)
            for (j, _), raw_flux in zip(lower_nbrs, desired):
                flux = raw_flux * scale
                if flux > 0.0:
                    outflows[i] += flux
                    inflows[j] += flux
                    per_cell_outflow_m3[i] += flux
                    total_transferred_m3 += flux

        vols = np.maximum(0.0, vols - outflows + inflows)

    return vols, total_transferred_m3, per_cell_outflow_m3
