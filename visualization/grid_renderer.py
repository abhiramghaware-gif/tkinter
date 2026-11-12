"""Layer 2 simulation grid overlay renderer and cell hit-testing."""

from __future__ import annotations

import tkinter as tk
from typing import Iterable

from config import LAND_USE_TINT_COLORS, MAP_COLORS
from core.models import GridCell
from visualization.map_renderer import GeoViewport


class GridRenderer:
    """Draws the editable simulation grid over the geographical map canvas."""

    def render(
        self,
        canvas: tk.Canvas,
        viewport: GeoViewport,
        cells: Iterable[GridCell],
        selected_cell_ids: set[int] | None = None,
        show_grid: bool = True,
        show_land_use_tint: bool = True,
        show_labels: bool = True,
    ) -> None:
        canvas.delete("layer_grid")
        if not show_grid:
            return

        selected = selected_cell_ids or set()
        cell_list = list(cells)
        if not cell_list:
            return

        # Draw regular cells first, then selected cells on top so cyan highlight borders are crisp
        selected_cells: list[GridCell] = []

        for cell in cell_list:
            if cell.id is not None and cell.id in selected:
                selected_cells.append(cell)
                continue
            self._draw_cell(
                canvas=canvas,
                viewport=viewport,
                cell=cell,
                is_selected=False,
                show_land_use_tint=show_land_use_tint,
                show_labels=show_labels,
            )

        for cell in selected_cells:
            self._draw_cell(
                canvas=canvas,
                viewport=viewport,
                cell=cell,
                is_selected=True,
                show_land_use_tint=show_land_use_tint,
                show_labels=show_labels,
            )

    def _draw_cell(
        self,
        canvas: tk.Canvas,
        viewport: GeoViewport,
        cell: GridCell,
        is_selected: bool,
        show_land_use_tint: bool,
        show_labels: bool,
    ) -> None:
        x0, y0 = viewport.geo_to_screen(cell.max_latitude, cell.min_longitude)
        x1, y1 = viewport.geo_to_screen(cell.min_latitude, cell.max_longitude)
        cell_w = abs(x1 - x0)
        cell_h = abs(y1 - y0)

        tint_color = LAND_USE_TINT_COLORS.get(cell.land_use, "") if show_land_use_tint else ""
        fill_kwargs: dict = {}
        if is_selected:
            fill_kwargs = {"fill": MAP_COLORS["grid_selected"], "stipple": "gray25"}
        elif tint_color:
            fill_kwargs = {"fill": tint_color, "stipple": "gray12"}
        else:
            fill_kwargs = {"fill": ""}

        if is_selected:
            outline = MAP_COLORS["grid_selected"]
            width = 2.4
        elif cell.is_configured:
            outline = MAP_COLORS["grid_configured"]
            width = 1.2
        else:
            outline = MAP_COLORS["grid_line"]
            width = 1.0

        tags = ("layer_grid", f"cell_{cell.row_number}_{cell.column_number}")
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

        # Draw cell label if cell has enough screen space
        if show_labels and cell_w >= 34 and cell_h >= 22:
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            label_color = "#F8FAFC" if is_selected else ("#99F6E4" if cell.is_configured else "#64748B")
            canvas.create_text(
                cx,
                cy,
                text=cell.cell_code,
                fill=label_color,
                font=("Segoe UI", 8, "bold" if is_selected else "normal"),
                tags=tags,
            )

    @staticmethod
    def hit_test(
        cells: Iterable[GridCell],
        viewport: GeoViewport,
        screen_x: float,
        screen_y: float,
    ) -> GridCell | None:
        """Return the GridCell containing the clicked canvas pixel, or None."""
        lat, lon = viewport.screen_to_geo(screen_x, screen_y)
        for cell in cells:
            if (
                cell.min_latitude <= lat <= cell.max_latitude
                and cell.min_longitude <= lon <= cell.max_longitude
            ):
                return cell
        return None

