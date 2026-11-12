"""Configurable travel-time estimation for evacuation modes (prototype speed assumptions)."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

from config import DEFAULT_SPEED_ASSUMPTIONS_KMH, TRAVEL_MODES
from core.validation import ValidationError


@dataclass(slots=True)
class TravelSpeedConfig:
    """Assumed travel speeds (km/hr) by road type — NOT live traffic data."""

    mode: str = TRAVEL_MODES[1]  # "Two-wheeler/Car" default
    speeds_by_mode: dict[str, dict[str, float]] = field(
        default_factory=lambda: copy.deepcopy(DEFAULT_SPEED_ASSUMPTIONS_KMH)
    )

    def validate(self) -> None:
        if self.mode not in TRAVEL_MODES:
            raise ValidationError(f"Unsupported travel mode '{self.mode}'.")
        mode_map = self.speeds_by_mode.get(self.mode, {})
        for rtype, spd in mode_map.items():
            if not math.isfinite(spd) or spd < 0.0:
                raise ValidationError(f"Speed for {self.mode} / {rtype} must be >= 0 km/hr.")
        if not any(v > 0.0 for v in mode_map.values()):
            raise ValidationError(f"At least one road type must have speed > 0 km/hr for {self.mode}.")

    def speed_kmh_for(self, road_type: str) -> float:
        mode_map = self.speeds_by_mode.get(self.mode, {})
        if road_type in mode_map:
            return float(mode_map[road_type])
        # Fallback within mode without inventing zero on normal streets
        if self.mode == "Walking":
            return float(mode_map.get("Residential", 4.5))
        return float(mode_map.get("Residential", 20.0))


def estimate_segment_time_minutes(
    distance_m: float,
    road_type: str,
    speed_config: TravelSpeedConfig,
) -> float | None:
    """Return estimated traversal time in minutes, or None if mode forbids that road type."""
    spd = speed_config.speed_kmh_for(road_type)
    if spd <= 0.0:
        return None
    dist_km = max(0.0, float(distance_m)) / 1000.0
    return (dist_km / spd) * 60.0


def estimate_route_travel_time_minutes(
    distances_and_types: list[tuple[float, str]],
    speed_config: TravelSpeedConfig,
) -> float:
    """Sum assumed travel time estimates across all segments in a route."""
    speed_config.validate()
    total_min = 0.0
    for dist_m, rtype in distances_and_types:
        seg_t = estimate_segment_time_minutes(dist_m, rtype, speed_config)
        if seg_t is None:
            # Should not happen unless an excluded road type was explicitly forced; use conservative fallback
            fallback_spd = 4.5 if speed_config.mode == "Walking" else 10.0
            seg_t = ((max(0.0, float(dist_m)) / 1000.0) / fallback_spd) * 60.0
        total_min += seg_t
    return total_min


def format_travel_time(minutes: float) -> str:
    """Format estimated travel duration with prototype assumption label."""
    if not math.isfinite(minutes) or minutes < 0.0:
        return "Unavailable"
    if minutes < 1.0:
        secs = max(1, round(minutes * 60.0))
        return f"{secs} sec (Assumed est.)"
    if minutes >= 60.0:
        hrs = int(minutes // 60)
        rem = minutes - hrs * 60
        return f"{hrs}h {rem:.0f}m (Assumed est.)"
    return f"{minutes:.1f} min (Assumed est.)"


__all__ = [
    "TravelSpeedConfig",
    "estimate_route_travel_time_minutes",
    "estimate_segment_time_minutes",
    "format_travel_time",
]
