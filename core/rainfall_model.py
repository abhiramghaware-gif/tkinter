"""Rainfall temporal distribution and SI volume calculation module."""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from core.validation import ValidationError


def generate_rainfall_schedule(
    intensity_mm_hr: float,
    duration_minutes: float,
    time_step_minutes: float,
    distribution: str = "constant",
    custom_intensities_mm_hr: Sequence[float] | None = None,
    scale_factor: float = 1.0,
) -> list[float]:
    """Generate per-timestep rainfall intensities (mm/hr) over the configured duration.

    For 'increasing' and 'decreasing', weights ramp smoothly and normalize so the
    time-averaged intensity equals ``intensity_mm_hr * scale_factor``.
    For 'custom', explicit values in mm/hr are interpolated/repeated to match step count
    and multiplied by ``scale_factor``.
    """
    if not math.isfinite(intensity_mm_hr) or intensity_mm_hr < 0.0:
        raise ValidationError("Rainfall intensity must be finite and >= 0 mm/hr.")
    if not math.isfinite(duration_minutes) or duration_minutes <= 0.0:
        raise ValidationError("Rainfall duration must be finite and > 0 minutes.")
    if not math.isfinite(time_step_minutes) or time_step_minutes <= 0.0:
        raise ValidationError("Simulation time step must be finite and > 0 minutes.")
    if not math.isfinite(scale_factor) or scale_factor < 0.0:
        raise ValidationError("Rainfall scale factor must be finite and >= 0.")

    num_steps = max(1, int(math.ceil((duration_minutes - 1e-9) / time_step_minutes)))
    dist = (distribution or "constant").strip().lower()
    base = float(intensity_mm_hr) * float(scale_factor)

    if dist == "constant":
        return [base] * num_steps

    if dist == "increasing":
        if num_steps == 1:
            return [base]
        weights = [0.25 + (1.5 * idx / (num_steps - 1)) for idx in range(num_steps)]
        mean_w = sum(weights) / len(weights)
        return [base * (w / mean_w) for w in weights]

    if dist == "decreasing":
        if num_steps == 1:
            return [base]
        weights = [1.75 - (1.5 * idx / (num_steps - 1)) for idx in range(num_steps)]
        mean_w = sum(weights) / len(weights)
        return [base * (w / mean_w) for w in weights]

    if dist == "custom":
        if not custom_intensities_mm_hr:
            raise ValidationError(
                "Custom rainfall distribution requires at least one comma-separated intensity value (mm/hr)."
            )
        vals = [float(v) for v in custom_intensities_mm_hr]
        for v in vals:
            if not math.isfinite(v) or v < 0.0:
                raise ValidationError("Custom rainfall values must be finite and >= 0 mm/hr.")
        if len(vals) == num_steps:
            return [v * scale_factor for v in vals]
        # Resample piecewise linearly across the number of steps
        src_x = np.linspace(0.0, 1.0, num=len(vals)) if len(vals) > 1 else np.array([0.0])
        dst_x = np.linspace(0.0, 1.0, num=num_steps) if num_steps > 1 else np.array([0.0])
        sampled = np.interp(dst_x, src_x, np.asarray(vals, dtype=float))
        return [float(v) * scale_factor for v in sampled]

    raise ValidationError(
        f"Unsupported rainfall distribution '{distribution}'. "
        "Choose constant, increasing, decreasing, or custom."
    )


def compute_timestep_durations_seconds(
    duration_minutes: float,
    time_step_minutes: float,
) -> list[float]:
    """Return exact duration (seconds) for each simulation step summing to duration_minutes * 60."""
    total_sec = float(duration_minutes) * 60.0
    dt_sec = float(time_step_minutes) * 60.0
    durations: list[float] = []
    remaining = total_sec
    while remaining > 1e-9:
        step = min(dt_sec, remaining)
        durations.append(step)
        remaining -= step
    return durations


def calculate_rainfall(
    cell_areas_m2: np.ndarray,
    intensity_mm_hr: float,
    time_step_seconds: float,
) -> tuple[float, np.ndarray]:
    """Convert rainfall intensity (mm/hr) over time_step_seconds into SI depth (m) and volume (m^3).

    Formula:
        Rainfall depth (m) = Rainfall intensity (mm/hr) * time (hr) / 1000
        Rainfall volume (m^3) = Rainfall depth (m) * Cell area (m^2)
    """
    if not math.isfinite(intensity_mm_hr) or intensity_mm_hr < 0.0:
        raise ValidationError("Rainfall intensity must be finite and >= 0 mm/hr.")
    if not math.isfinite(time_step_seconds) or time_step_seconds <= 0.0:
        raise ValidationError("Time step duration (s) must be finite and > 0.")

    time_hours = float(time_step_seconds) / 3600.0
    rainfall_depth_m = float(intensity_mm_hr) * time_hours / 1000.0
    volumes_m3 = np.asarray(cell_areas_m2, dtype=np.float64) * rainfall_depth_m
    return rainfall_depth_m, volumes_m3
