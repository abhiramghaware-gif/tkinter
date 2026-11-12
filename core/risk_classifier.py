"""Configurable prototype flood-depth risk classification and heatmap colour mapping."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from config import (
    DEFAULT_HEATMAP_COLORS,
    DEFAULT_RISK_THRESHOLDS_CM,
    RISK_CATEGORIES,
    WET_CELL_DEPTH_THRESHOLD_M,
)
from core.models import GridCell
from core.validation import ValidationError


PROTOTYPE_RISK_DISCLAIMER = (
    "Illustrative prototype thresholds only — NOT official flood safety standards. "
    "'No surface flooding' indicates 0 cm simulated model accumulation and must never "
    "be interpreted as guaranteed real-world safety."
)


@dataclass(slots=True)
class RiskThresholds:
    """Editable illustrative flood-depth thresholds in centimetres (cm)."""

    low_max_cm: float = DEFAULT_RISK_THRESHOLDS_CM["low_max_cm"]
    moderate_max_cm: float = DEFAULT_RISK_THRESHOLDS_CM["moderate_max_cm"]
    high_max_cm: float = DEFAULT_RISK_THRESHOLDS_CM["high_max_cm"]
    critical_min_cm: float = DEFAULT_RISK_THRESHOLDS_CM["critical_min_cm"]
    wet_cutoff_cm: float = WET_CELL_DEPTH_THRESHOLD_M * 100.0  # 0.01 cm (0.1 mm)

    def validate(self) -> None:
        vals = (
            self.wet_cutoff_cm,
            self.low_max_cm,
            self.moderate_max_cm,
            self.high_max_cm,
            self.critical_min_cm,
        )
        if not all(math.isfinite(v) for v in vals):
            raise ValidationError("Risk classification thresholds must be finite numbers.")
        if self.wet_cutoff_cm < 0.0:
            raise ValidationError("Wet cutoff depth must be >= 0 cm.")
        if not (
            0.0 < self.low_max_cm <= self.moderate_max_cm <= self.high_max_cm <= self.critical_min_cm
        ):
            raise ValidationError(
                "Thresholds must satisfy: 0 < Low Max <= Moderate Max <= High Max <= Critical Min (cm)."
            )


@dataclass(slots=True)
class HeatmapColorScale:
    """Configurable 6-tier heatmap colour palette."""

    no_water: str = DEFAULT_HEATMAP_COLORS["no_water"]
    low: str = DEFAULT_HEATMAP_COLORS["low"]
    moderate: str = DEFAULT_HEATMAP_COLORS["moderate"]
    high: str = DEFAULT_HEATMAP_COLORS["high"]
    very_high: str = DEFAULT_HEATMAP_COLORS["very_high"]
    critical: str = DEFAULT_HEATMAP_COLORS["critical"]


@dataclass(slots=True)
class CellRiskClassification:
    """Simulated risk assessment result for a single grid cell."""

    cell_id: int | None
    cell_code: str
    depth_m: float
    depth_cm: float
    risk_category: str
    area_m2: float
    is_model_assumption: bool = True
    note: str = PROTOTYPE_RISK_DISCLAIMER


@dataclass(slots=True)
class RiskStatistics:
    """Aggregated neighbourhood risk breakdown at a simulation timestep."""

    total_cells: int = 0
    total_area_m2: float = 0.0
    category_counts: dict[str, int] = field(
        default_factory=lambda: {cat: 0 for cat in RISK_CATEGORIES}
    )
    category_areas_m2: dict[str, float] = field(
        default_factory=lambda: {cat: 0.0 for cat in RISK_CATEGORIES}
    )
    high_risk_cells: int = 0
    very_high_risk_cells: int = 0
    disclaimer: str = PROTOTYPE_RISK_DISCLAIMER


def classify_flood_depth(
    depth_m: float,
    thresholds: RiskThresholds | None = None,
) -> str:
    """Classify simulated water depth (m) into one of the 5 prototype risk categories.

    Thresholds (default illustrative prototype values in cm):
      - <= wet_cutoff (0 cm): No surface flooding
      - > 0 to 10 cm: Low
      - > 10 to 30 cm: Moderate
      - > 30 to 60 cm: High
      - > 60 cm: Very High
    """
    th = thresholds or RiskThresholds()
    th.validate()

    if not math.isfinite(depth_m):
        raise ValidationError("Simulated water depth must be finite.")
    safe_depth_m = max(0.0, float(depth_m))
    depth_cm = safe_depth_m * 100.0

    if depth_cm <= th.wet_cutoff_cm:
        return "No surface flooding"
    if depth_cm <= th.low_max_cm:
        return "Low"
    if depth_cm <= th.moderate_max_cm:
        return "Moderate"
    if depth_cm <= th.high_max_cm:
        return "High"
    return "Very High"


def color_for_flood_depth(
    depth_m: float,
    thresholds: RiskThresholds | None = None,
    color_scale: HeatmapColorScale | None = None,
) -> tuple[str, str]:
    """Return (hex_color, tier_label) for a simulated water depth (m)."""
    th = thresholds or RiskThresholds()
    th.validate()
    cs = color_scale or HeatmapColorScale()

    safe_depth_m = max(0.0, float(depth_m))
    depth_cm = safe_depth_m * 100.0

    if depth_cm <= th.wet_cutoff_cm:
        return cs.no_water, "No water (0 cm)"
    if depth_cm <= th.low_max_cm:
        return cs.low, f"Low (>0–{th.low_max_cm:.0f} cm)"
    if depth_cm <= th.moderate_max_cm:
        return cs.moderate, f"Moderate ({th.low_max_cm:.0f}–{th.moderate_max_cm:.0f} cm)"
    if depth_cm <= th.high_max_cm:
        return cs.high, f"High ({th.moderate_max_cm:.0f}–{th.high_max_cm:.0f} cm)"
    if depth_cm < th.critical_min_cm:
        return cs.very_high, f"Very High ({th.high_max_cm:.0f}–{th.critical_min_cm:.0f} cm)"
    return cs.critical, f"Critical (≥{th.critical_min_cm:.0f} cm)"


def classify_grid_cell(
    cell: GridCell,
    depth_m: float,
    thresholds: RiskThresholds | None = None,
) -> CellRiskClassification:
    """Classify a single GridCell using its simulated depth (m)."""
    safe_depth_m = max(0.0, float(depth_m))
    category = classify_flood_depth(safe_depth_m, thresholds)
    return CellRiskClassification(
        cell_id=cell.id,
        cell_code=cell.cell_code,
        depth_m=safe_depth_m,
        depth_cm=safe_depth_m * 100.0,
        risk_category=category,
        area_m2=cell.approx_area_sq_m(),
    )


def calculate_neighbourhood_risk(
    cells: list[GridCell],
    depths_by_cell_id: dict[int, float],
    thresholds: RiskThresholds | None = None,
) -> dict[int, CellRiskClassification]:
    """Classify every grid cell in a neighbourhood at a given timestep."""
    th = thresholds or RiskThresholds()
    th.validate()
    classified: dict[int, CellRiskClassification] = {}
    for idx, cell in enumerate(cells):
        cid = cell.id if cell.id is not None else (idx + 1)
        depth_m = float(depths_by_cell_id.get(cid, 0.0))
        classified[cid] = classify_grid_cell(cell, depth_m, th)
    return classified


def calculate_risk_statistics(
    cells: list[GridCell],
    depths_by_cell_id: dict[int, float],
    thresholds: RiskThresholds | None = None,
) -> RiskStatistics:
    """Compute counts and affected area for each risk category across the grid."""
    classified = calculate_neighbourhood_risk(cells, depths_by_cell_id, thresholds)
    stats = RiskStatistics(total_cells=len(cells))
    for item in classified.values():
        stats.total_area_m2 += item.area_m2
        stats.category_counts[item.risk_category] = (
            stats.category_counts.get(item.risk_category, 0) + 1
        )
        stats.category_areas_m2[item.risk_category] = (
            stats.category_areas_m2.get(item.risk_category, 0.0) + item.area_m2
        )
    stats.high_risk_cells = stats.category_counts.get("High", 0)
    stats.very_high_risk_cells = stats.category_counts.get("Very High", 0)
    return stats


__all__ = [
    "CellRiskClassification",
    "HeatmapColorScale",
    "PROTOTYPE_RISK_DISCLAIMER",
    "RiskStatistics",
    "RiskThresholds",
    "calculate_neighbourhood_risk",
    "calculate_risk_statistics",
    "classify_flood_depth",
    "classify_grid_cell",
    "color_for_flood_depth",
]
