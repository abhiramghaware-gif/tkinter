"""Phase 5 Canvas renderer for SafeRoute evacuation paths, road conditions & markers."""

from __future__ import annotations

import math
import tkinter as tk
from typing import Any, Iterable

from config import MAP_COLORS, ROUTE_COLORS
from routing.flood_exposure import RoadFloodExposure
from routing.road_network import RoadEdge, RoadNetworkGraph, RoadNode
from routing.route_comparison import RouteMetrics
from visualization.map_renderer import GeoViewport, MapRenderer


class RouteRenderer:
    """Draws road condition overlays, directional evacuation routes, and markers."""

    def render_road_conditions(
        self,
        canvas: tk.Canvas,
        viewport: GeoViewport,
        network: RoadNetworkGraph,
        exposures: dict[int, RoadFloodExposure],
        manual_statuses: dict[int, str],
        show_unknown_roads: bool = True,
        show_closed_roads: bool = True,
        selected_edge_id: int | None = None,
    ) -> None:
        canvas.delete("layer_route_conditions")

        for eid, edge in network.edges_by_id.items():
            coords = (edge.geometry or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            m_status = manual_statuses.get(eid, edge.manual_status or "Normal")
            exp = exposures.get(eid)
            exp_cat = exp.exposure_category if exp is not None else edge.exposure_category

            is_closed = m_status in ("Closed", "Blocked")
            is_inspection = m_status == "Under inspection"
            is_unknown = exp_cat == "Unknown"

            pts = MapRenderer._project_ring(viewport, coords)
            if len(pts) < 4:
                continue

            if eid == selected_edge_id:
                canvas.create_line(
                    *pts,
                    fill="#F472B6",
                    width=6.0,
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND,
                    tags=("layer_route_conditions",),
                )

            if is_closed and show_closed_roads:
                canvas.create_line(
                    *pts,
                    fill=ROUTE_COLORS["closed"],
                    width=3.6,
                    dash=(6, 4),
                    capstyle=tk.ROUND,
                    tags=("layer_route_conditions",),
                )
            elif is_inspection and show_closed_roads:
                canvas.create_line(
                    *pts,
                    fill="#FBBF24",
                    width=3.0,
                    dash=(4, 4),
                    capstyle=tk.ROUND,
                    tags=("layer_route_conditions",),
                )
            elif is_unknown and show_unknown_roads:
                canvas.create_line(
                    *pts,
                    fill=ROUTE_COLORS["unknown"],
                    width=1.8,
                    dash=(2, 3),
                    capstyle=tk.ROUND,
                    tags=("layer_route_conditions",),
                )

    def render_routes(
        self,
        canvas: tk.Canvas,
        viewport: GeoViewport,
        network: RoadNetworkGraph,
        routes: Iterable[RouteMetrics],
        origin_node: RoadNode | None = None,
        dest_node: RoadNode | None = None,
        show_labels: bool = True,
    ) -> None:
        canvas.delete("layer_routes")
        route_list = list(routes)

        # Draw order: Alternative (orange bottom), Shortest (blue middle), Flood-aware (green top)
        order_rank = {"Alternative": 0, "Shortest": 1, "Flood-aware": 2}
        route_list.sort(key=lambda r: order_rank.get(r.route_type, 1))

        style_map = {
            "Alternative": (ROUTE_COLORS["alternative"], 6.0, (8, 5), (-3, 3)),
            "Shortest": (ROUTE_COLORS["shortest"], 4.8, None, (2, -2)),
            "Flood-aware": (ROUTE_COLORS["flood_aware"], 3.4, None, (0, 0)),
        }

        labeled_names: set[str] = set()

        for route in route_list:
            if len(route.coordinates) < 2:
                continue
            color, width, dash, offset_xy = style_map.get(
                route.route_type,
                ("#38BDF8", 4.0, None, (0, 0)),
            )
            pts = MapRenderer._project_ring(viewport, route.coordinates)
            if len(pts) < 4:
                continue

            ox, oy = offset_xy
            shifted = [
                (pts[i] + ox) if i % 2 == 0 else (pts[i] + oy)
                for i in range(len(pts))
            ]

            # Subtle dark casing for crisp separation over any heatmap colour
            canvas.create_line(
                *shifted,
                fill="#020617",
                width=width + 2.4,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                tags=("layer_routes",),
            )
            kwargs = {
                "fill": color,
                "width": width,
                "capstyle": tk.ROUND,
                "joinstyle": tk.ROUND,
                "tags": ("layer_routes",),
            }
            if dash:
                kwargs["dash"] = dash
            canvas.create_line(*shifted, **kwargs)

            # Draw directional arrow markers along route every ~85 px
            self._draw_direction_arrows(canvas, shifted, color)

            if show_labels:
                for eid in route.edge_ids:
                    edge = network.edges_by_id.get(eid)
                    if edge is None:
                        continue
                    rname = edge.road_name.strip()
                    if not rname or rname.startswith("Unnamed") or rname in labeled_names:
                        continue
                    coords = (edge.geometry or {}).get("coordinates") or []
                    if not coords:
                        continue
                    mid = coords[len(coords) // 2]
                    mx, my = viewport.geo_to_screen(float(mid[1]), float(mid[0]))
                    if 40 <= mx <= viewport.width - 40 and 30 <= my <= viewport.height - 30:
                        labeled_names.add(rname)
                        canvas.create_rectangle(
                            mx - len(rname) * 3 - 4,
                            my - 14,
                            mx + len(rname) * 3 + 4,
                            my - 2,
                            fill="#0F172A",
                            outline=color,
                            width=1,
                            tags=("layer_routes",),
                        )
                        canvas.create_text(
                            mx,
                            my - 8,
                            text=rname,
                            fill="#F8FAFC",
                            font=("Segoe UI", 7, "bold"),
                            tags=("layer_routes",),
                        )

        # Start & Destination Markers on top
        if origin_node is not None:
            x, y = viewport.geo_to_screen(origin_node.latitude, origin_node.longitude)
            self._draw_pin(canvas, x, y, fill="#22C55E", badge="A", caption="ORIGIN")
        if dest_node is not None:
            x, y = viewport.geo_to_screen(dest_node.latitude, dest_node.longitude)
            self._draw_pin(canvas, x, y, fill="#06B6D4", badge="B", caption="DEST")

    def render_shelters(
        self,
        canvas: tk.Canvas,
        viewport: GeoViewport,
        shelters: Iterable[Any],
        selected_shelter_id: int | None = None,
    ) -> None:
        """Render registered shelter locations with clear Verified vs Unverified markers (never contact PII)."""
        canvas.delete("layer_reg_shelters")
        for s in shelters:
            lat = float(getattr(s, "latitude", 0.0))
            lon = float(getattr(s, "longitude", 0.0))
            sid = getattr(s, "id", None)
            status = str(getattr(s, "status", "Active"))
            is_verified = bool(getattr(s, "is_verified", False))
            name = str(getattr(s, "name", "") or "Shelter")
            avail = int(getattr(s, "available_capacity", 0))
            tot = int(getattr(s, "total_capacity", 0))

            x, y = viewport.geo_to_screen(lat, lon)
            if x < -40 or y < -40 or x > viewport.width + 40 or y > viewport.height + 40:
                continue

            if status in ("Inactive", "Closed"):
                fill = "#64748B"
                badge = "X"
            elif status == "Full" or (tot > 0 and avail <= 0):
                fill = "#EF4444"
                badge = "F"
            elif is_verified:
                fill = "#14B8A6"
                badge = "S"
            else:
                fill = "#F59E0B"
                badge = "S?"

            if sid is not None and sid == selected_shelter_id:
                canvas.create_oval(
                    x - 13, y - 13, x + 13, y + 13,
                    fill="",
                    outline="#22D3EE",
                    width=2.2,
                    tags=("layer_reg_shelters",),
                )

            r = 8
            canvas.create_polygon(
                x, y - r, x + r, y, x, y + r, x - r, y,
                fill=fill,
                outline="#0F172A",
                width=1.8,
                tags=("layer_reg_shelters",),
            )
            canvas.create_text(
                x, y,
                text=badge,
                fill="#020617",
                font=("Segoe UI", 7, "bold"),
                tags=("layer_reg_shelters",),
            )
            short_name = name if len(name) <= 20 else f"{name[:18]}.."
            label_txt = f"{short_name} ({avail}/{tot})"
            canvas.create_rectangle(
                x - len(label_txt) * 3 - 4,
                y + 10,
                x + len(label_txt) * 3 + 4,
                y + 22,
                fill="#0F172A",
                outline=fill,
                width=1,
                tags=("layer_reg_shelters",),
            )
            canvas.create_text(
                x,
                y + 16,
                text=label_txt,
                fill="#F8FAFC",
                font=("Segoe UI", 7, "bold"),
                tags=("layer_reg_shelters",),
            )

    @staticmethod
    def _draw_direction_arrows(
        canvas: tk.Canvas,
        shifted: list[float],
        color: str,
    ) -> None:
        accum = 0.0
        for i in range(0, len(shifted) - 2, 2):
            x1, y1 = shifted[i], shifted[i + 1]
            x2, y2 = shifted[i + 2], shifted[i + 3]
            seg_len = math.hypot(x2 - x1, y2 - y1)
            accum += seg_len
            if accum >= 75.0 and seg_len >= 12.0:
                accum = 0.0
                mx = (x1 + x2) / 2.0
                my = (y1 + y2) / 2.0
                ux = (x2 - x1) / seg_len
                uy = (y2 - y1) / seg_len
                canvas.create_line(
                    mx - ux * 6,
                    my - uy * 6,
                    mx + ux * 6,
                    my + uy * 6,
                    fill="#F8FAFC",
                    width=2.2,
                    arrow=tk.LAST,
                    arrowshape=(7, 8, 3),
                    tags=("layer_routes",),
                )

    @staticmethod
    def _draw_pin(
        canvas: tk.Canvas,
        x: float,
        y: float,
        fill: str,
        badge: str,
        caption: str,
    ) -> None:
        r = 9
        canvas.create_oval(
            x - r, y - r, x + r, y + r,
            fill=fill,
            outline="#020617",
            width=2,
            tags=("layer_routes",),
        )
        canvas.create_text(
            x, y,
            text=badge,
            fill="#020617",
            font=("Segoe UI", 8, "bold"),
            tags=("layer_routes",),
        )
        canvas.create_rectangle(
            x - 24, y - 24, x + 24, y - 12,
            fill="#0F172A",
            outline=fill,
            width=1,
            tags=("layer_routes",),
        )
        canvas.create_text(
            x, y - 18,
            text=caption,
            fill="#F8FAFC",
            font=("Segoe UI", 7, "bold"),
            tags=("layer_routes",),
        )


__all__ = ["RouteRenderer"]
