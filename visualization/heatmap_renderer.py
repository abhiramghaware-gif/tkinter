"""Flood-depth heatmap canvas renderer for Phase 4 visualization."""

from __future__ import annotations

import tkinter as tk
from typing import Iterable

from config import MAP_COLORS
from core.models import GridCell
from core.risk_classifier import (
    HeatmapColorScale,
    RiskThresholds,
    color_for_flood_depth,
)
from visualization.map_renderer import GeoViewport


class HeatmapRenderer:
    """Renders simulated flood-depth colours over the active neighbourhood grid."""

    def render(
        self,
        canvas: tk.Canvas,
        viewport: GeoViewport,
        cells: Iterable[GridCell],
        depths_by_cell_id: dict[int, float],
        thresholds: RiskThresholds | None = None,
        color_scale: HeatmapColorScale | None = None,
        selected_cell_id: int | None = None,
        show_heatmap: bool = True,
        show_grid_lines: bool = True,
        show_labels: bool = True,
        translucent: bool = True,
    ) -> None:
        canvas.delete("layer_flood_heatmap")
        cell_list = list(cells)
        if not cell_list or (not show_heatmap and not show_grid_lines):
            return

        th = thresholds or RiskThresholds()
        cs = color_scale or HeatmapColorScale()
        selected_cell: tuple[int, GridCell] | None = None

        for idx, cell in enumerate(cell_list):
            cid = cell.id if cell.id is not None else (idx + 1)
            if selected_cell_id is not None and cid == selected_cell_id:
                selected_cell = (cid, cell)
                continue
            self._draw_cell(
                canvas=canvas,
                viewport=viewport,
                cell=cell,
                depth_m=float(depths_by_cell_id.get(cid, 0.0)),
                thresholds=th,
                color_scale=cs,
                is_selected=False,
                show_heatmap=show_heatmap,
                show_grid_lines=show_grid_lines,
                show_labels=show_labels,
                translucent=translucent,
            )

        if selected_cell is not None:
            cid, cell = selected_cell
            self._draw_cell(
                canvas=canvas,
                viewport=viewport,
                cell=cell,
                depth_m=float(depths_by_cell_id.get(cid, 0.0)),
                thresholds=th,
                color_scale=cs,
                is_selected=True,
                show_heatmap=show_heatmap,
                show_grid_lines=show_grid_lines,
                show_labels=show_labels,
                translucent=translucent,
            )

    def _draw_cell(
        self,
        canvas: tk.Canvas,
        viewport: GeoViewport,
        cell: GridCell,
        depth_m: float,
        thresholds: RiskThresholds,
        color_scale: HeatmapColorScale,
        is_selected: bool,
        show_heatmap: bool,
        show_grid_lines: bool,
        show_labels: bool,
        translucent: bool,
    ) -> None:
        x0, y0 = viewport.geo_to_screen(cell.max_latitude, cell.min_longitude)
        x1, y1 = viewport.geo_to_screen(cell.min_latitude, cell.max_longitude)
        cell_w = abs(x1 - x0)
        cell_h = abs(y1 - y0)

        color_hex, _ = color_for_flood_depth(depth_m, thresholds, color_scale)
        depth_cm = max(0.0, depth_m * 100.0)
        is_wet = depth_cm > thresholds.wet_cutoff_cm

        fill_kwargs: dict = {"fill": ""}
        if show_heatmap:
            if translucent:
                fill_kwargs = {
                    "fill": color_hex,
                    "stipple": "gray50" if is_wet else "gray12",
                }
            else:
                fill_kwargs = {"fill": color_hex}

        if is_selected:
            outline = MAP_COLORS["grid_selected"]
            width = 2.6
        elif show_grid_lines:
            outline = "#475569" if not is_wet else "#E2E8F0"
            width = 1.0
        else:
            outline = ""
            width = 0

        tags = ("layer_flood_heatmap", f"fcell_{cell.row_number}_{cell.column_number}")
        canvas.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            outline=outline,
            width=width,
            tags=tags,
            **fill_kwargs,
        )

        if show_labels and cell_w >= 38 and cell_h >= 26:
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            label_text = f"{cell.cell_code}\n{depth_cm:.1f}cm" if is_wet else cell.cell_code
            text_color = "#FFFFFF" if (is_selected or is_wet) else "#94A3B8"
            canvas.create_text(
                cx,
                cy,
                text=label_text,
                fill=text_color,
                font=("Segoe UI", 7, "bold" if (is_selected or is_wet) else "normal"),
                justify="center",
                tags=tags,
            )

    @staticmethod
    def render_timestamp_hud(
        canvas: tk.Canvas,
        scenario_name: str,
        timestep: int,
        total_steps: int,
        sim_time_minutes: float,
        is_empty: bool = False,
    ) -> None:
        canvas.delete("layer_flood_hud")
        text = (
            "No simulation selected — Run a scenario in Simulation Lab"
            if is_empty
            else f"[SIMULATED] {scenario_name}  |  Step {timestep}/{total_steps}  •  t = {sim_time_minutes:.1f} min"
        )
        pad_x = 12
        box_w = min(max(260, len(text) * 6 + 24), 620)
        canvas.create_rectangle(
            12,
            10,
            12 + box_w,
            34,
            fill="#0B1120",
            outline="#06B6D4",
            width=1,
            tags=("layer_flood_hud",),
        )
        canvas.create_text(
            12 + pad_x,
            22,
            text=text,
            anchor="w",
            fill="#E2E8F0",
            font=("Segoe UI", 8, "bold"),
            tags=("layer_flood_hud",),
        )
