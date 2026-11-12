"""Layer 1 OpenStreetMap & Drainage geographical renderer and coordinate projection."""

from __future__ import annotations

import math
from typing import Iterable

import tkinter as tk

from config import MAP_COLORS, OSM_ATTRIBUTION
from core.models import DrainageFeature, METRES_PER_DEG_LAT, Neighbourhood, OSMFeature
from services.osm_service import classify_road_category


class GeoViewport:
    """Projects geographic (lat, lon) coordinates to Tkinter Canvas (x, y) pixels."""

    def __init__(
        self,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        width: int = 800,
        height: int = 600,
        padding: int = 28,
    ) -> None:
        self.min_lat = min_lat
        self.max_lat = max_lat
        self.min_lon = min_lon
        self.max_lon = max_lon
        self.width = max(100, width)
        self.height = max(100, height)
        self.padding = padding
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0

        self.center_lat = (min_lat + max_lat) / 2.0
        self.center_lon = (min_lon + max_lon) / 2.0
        self.cos_lat = max(0.05, math.cos(math.radians(self.center_lat)))

    def set_bounds(self, min_lat: float, max_lat: float, min_lon: float, max_lon: float) -> None:
        self.min_lat = min_lat
        self.max_lat = max_lat
        self.min_lon = min_lon
        self.max_lon = max_lon
        self.center_lat = (min_lat + max_lat) / 2.0
        self.center_lon = (min_lon + max_lon) / 2.0
        self.cos_lat = max(0.05, math.cos(math.radians(self.center_lat)))

    def resize(self, width: int, height: int) -> None:
        self.width = max(100, width)
        self.height = max(100, height)

    def reset_view(self) -> None:
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0

    def _base_pixels_per_deg_lat(self) -> float:
        lon_span = max(1e-6, (self.max_lon - self.min_lon) * self.cos_lat)
        lat_span = max(1e-6, self.max_lat - self.min_lat)
        avail_w = max(20.0, self.width - 2.0 * self.padding)
        avail_h = max(20.0, self.height - 2.0 * self.padding)
        return min(avail_w / lon_span, avail_h / lat_span)

    @property
    def pixels_per_deg_lat(self) -> float:
        return self._base_pixels_per_deg_lat() * self.zoom

    def geo_to_screen(self, lat: float, lon: float) -> tuple[float, float]:
        scale = self.pixels_per_deg_lat
        x = (self.width / 2.0) + self.pan_x + (lon - self.center_lon) * self.cos_lat * scale
        y = (self.height / 2.0) + self.pan_y - (lat - self.center_lat) * scale
        return x, y

    def screen_to_geo(self, x: float, y: float) -> tuple[float, float]:
        scale = self.pixels_per_deg_lat
        if scale <= 0:
            return self.center_lat, self.center_lon
        lon = self.center_lon + (x - (self.width / 2.0) - self.pan_x) / (self.cos_lat * scale)
        lat = self.center_lat - (y - (self.height / 2.0) - self.pan_y) / scale
        return lat, lon

    def zoom_at(self, factor: float, pivot_x: float, pivot_y: float) -> None:
        new_zoom = max(0.4, min(30.0, self.zoom * factor))
        if abs(new_zoom - self.zoom) < 1e-6:
            return
        lat_at_cursor, lon_at_cursor = self.screen_to_geo(pivot_x, pivot_y)
        self.zoom = new_zoom
        new_x, new_y = self.geo_to_screen(lat_at_cursor, lon_at_cursor)
        self.pan_x += pivot_x - new_x
        self.pan_y += pivot_y - new_y

    def pan_by(self, dx: float, dy: float) -> None:
        self.pan_x += dx
        self.pan_y += dy

    def metres_per_pixel(self) -> float:
        scale = self.pixels_per_deg_lat
        if scale <= 0:
            return 1.0
        return METRES_PER_DEG_LAT / scale


class MapRenderer:
    """Draws Layer 1 OSM features (roads, buildings, water, green, wetlands) & drainage."""

    def render(
        self,
        canvas: tk.Canvas,
        viewport: GeoViewport,
        neighbourhood: Neighbourhood | None,
        features: Iterable[OSMFeature],
        drainage_features: Iterable[DrainageFeature] = (),
        show_osm: bool = True,
        show_roads: bool = True,
        show_buildings: bool = True,
        show_water: bool = True,
        show_green: bool = True,
        show_wetlands: bool = True,
        show_drainage: bool = True,
        selected_osm_id: int | None = None,
        selected_drainage_id: int | None = None,
        draw_hud: bool = True,
    ) -> None:
        canvas.delete("layer_osm")
        canvas.delete("layer_drainage")
        canvas.delete("layer_hud")

        if neighbourhood is None:
            return

        x0, y0 = viewport.geo_to_screen(neighbourhood.max_latitude, neighbourhood.min_longitude)
        x1, y1 = viewport.geo_to_screen(neighbourhood.min_latitude, neighbourhood.max_longitude)
        canvas.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            outline="#1E3A5F",
            width=1.5,
            dash=(4, 4),
            tags=("layer_osm", "osm_bbox"),
        )

        if show_osm:
            grouped: dict[str, list[OSMFeature]] = {
                "wetland": [],
                "green_area": [],
                "other": [],
                "waterway": [],
                "building": [],
                "road": [],
            }
            for feat in features:
                if feat.category == "green_area" and feat.subcategory == "wetland":
                    grouped["wetland"].append(feat)
                else:
                    grouped.get(feat.category, grouped["other"]).append(feat)

            if show_wetlands:
                for feat in grouped["wetland"]:
                    is_sel = selected_osm_id is not None and feat.id == selected_osm_id
                    self._draw_feature(
                        canvas,
                        viewport,
                        feat,
                        fill=MAP_COLORS["wetland_fill"],
                        outline=MAP_COLORS["feature_selected"] if is_sel else MAP_COLORS["wetland_outline"],
                        line_color=MAP_COLORS["feature_selected"] if is_sel else MAP_COLORS["wetland_outline"],
                        width=2.4 if is_sel else 1.2,
                    )

            if show_green:
                for feat in grouped["green_area"]:
                    is_sel = selected_osm_id is not None and feat.id == selected_osm_id
                    self._draw_feature(
                        canvas,
                        viewport,
                        feat,
                        fill=MAP_COLORS["green_fill"],
                        outline=MAP_COLORS["feature_selected"] if is_sel else MAP_COLORS["green_outline"],
                        line_color=MAP_COLORS["feature_selected"] if is_sel else MAP_COLORS["green_outline"],
                        width=2.4 if is_sel else 1.0,
                    )

            for feat in grouped["other"]:
                is_sel = selected_osm_id is not None and feat.id == selected_osm_id
                self._draw_feature(
                    canvas,
                    viewport,
                    feat,
                    fill=MAP_COLORS["other_fill"],
                    outline=MAP_COLORS["feature_selected"] if is_sel else MAP_COLORS["other_outline"],
                    line_color=MAP_COLORS["feature_selected"] if is_sel else MAP_COLORS["other_outline"],
                    width=2.4 if is_sel else 1.0,
                )

            if show_water:
                for feat in grouped["waterway"]:
                    is_sel = selected_osm_id is not None and feat.id == selected_osm_id
                    w = 3.2 if is_sel else (2.6 if feat.subcategory in ("river", "canal") else 1.8)
                    self._draw_feature(
                        canvas,
                        viewport,
                        feat,
                        fill=MAP_COLORS["water_fill"],
                        outline=MAP_COLORS["feature_selected"] if is_sel else MAP_COLORS["water_outline"],
                        line_color=MAP_COLORS["feature_selected"] if is_sel else MAP_COLORS["waterway_line"],
                        width=w,
                    )

            if show_buildings:
                for feat in grouped["building"]:
                    is_sel = selected_osm_id is not None and feat.id == selected_osm_id
                    self._draw_feature(
                        canvas,
                        viewport,
                        feat,
                        fill=MAP_COLORS["building_fill"],
                        outline=MAP_COLORS["feature_selected"] if is_sel else MAP_COLORS["building_outline"],
                        line_color=MAP_COLORS["feature_selected"] if is_sel else MAP_COLORS["building_outline"],
                        width=2.4 if is_sel else 1.0,
                    )

            if show_roads:
                zoom_boost = min(1.8, max(0.8, viewport.zoom * 0.65))
                for feat in grouped["road"]:
                    is_sel = selected_osm_id is not None and feat.id == selected_osm_id
                    road_cls = feat.road_category or classify_road_category(feat.subcategory, feat.tags)
                    color, base_w, dash = self._road_style(road_cls)
                    if is_sel:
                        color = MAP_COLORS["feature_selected"]
                        base_w += 1.6
                    w = max(0.8, min(5.0, base_w * zoom_boost))
                    self._draw_feature(
                        canvas,
                        viewport,
                        feat,
                        fill="",
                        outline="",
                        line_color=color,
                        width=w,
                        dash=dash,
                    )

        if show_drainage:
            self._render_drainage(canvas, viewport, drainage_features, selected_drainage_id)

        if draw_hud:
            self._draw_scale_and_attribution(canvas, viewport)

    @staticmethod
    def _road_style(road_cls: str) -> tuple[str, float, tuple[int, ...] | None]:
        if road_cls == "Motorway / Major":
            return MAP_COLORS["road_motorway"], 3.2, None
        if road_cls == "Primary":
            return MAP_COLORS["road_primary"], 2.6, None
        if road_cls == "Secondary":
            return MAP_COLORS["road_secondary"], 2.0, None
        if road_cls == "Tertiary":
            return MAP_COLORS["road_tertiary"], 1.6, None
        if road_cls == "Residential":
            return MAP_COLORS["road_residential"], 1.3, None
        if road_cls == "Service":
            return MAP_COLORS["road_service"], 1.0, (4, 2)
        if road_cls == "Footpath":
            return MAP_COLORS["road_footpath"], 0.9, (2, 3)
        return MAP_COLORS["road_residential"], 1.2, None

    def _render_drainage(
        self,
        canvas: tk.Canvas,
        viewport: GeoViewport,
        drainage_features: Iterable[DrainageFeature],
        selected_drainage_id: int | None,
    ) -> None:
        status_colors = {
            "Operational": MAP_COLORS["drainage_operational"],
            "Partially blocked": MAP_COLORS["drainage_partial"],
            "Blocked": MAP_COLORS["drainage_blocked"],
            "Unknown": MAP_COLORS["drainage_unknown"],
        }
        code_map = {
            "Stormwater drain": "D",
            "Drain inlet": "I",
            "Drain outlet": "O",
            "Drainage channel": "Ch",
            "Culvert": "Cu",
            "Pumping station": "P",
        }
        for dr in drainage_features:
            x, y = viewport.geo_to_screen(dr.latitude, dr.longitude)
            is_sel = selected_drainage_id is not None and dr.id == selected_drainage_id
            fill = status_colors.get(dr.status, MAP_COLORS["drainage_unknown"])
            outline = MAP_COLORS["feature_selected"] if is_sel else "#0B1120"
            r = 8 if is_sel else 6
            canvas.create_oval(
                x - r,
                y - r,
                x + r,
                y + r,
                fill=fill,
                outline=outline,
                width=2.2 if is_sel else 1.4,
                tags=("layer_drainage", f"drain_{dr.id}"),
            )
            badge = code_map.get(dr.feature_type, "D")
            canvas.create_text(
                x,
                y,
                text=badge,
                fill="#0B1120",
                font=("Segoe UI", 7, "bold"),
                tags=("layer_drainage", f"drain_{dr.id}"),
            )

    def _draw_feature(
        self,
        canvas: tk.Canvas,
        viewport: GeoViewport,
        feat: OSMFeature,
        fill: str,
        outline: str,
        line_color: str,
        width: float,
        dash: tuple[int, ...] | None = None,
    ) -> None:
        geom = feat.geometry
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if not coords:
            return

        tag = ("layer_osm", f"osm_{feat.category}")
        line_kw: dict = {
            "fill": line_color,
            "width": width,
            "capstyle": tk.ROUND,
            "joinstyle": tk.ROUND,
            "tags": tag,
        }
        if dash:
            line_kw["dash"] = dash

        if gtype == "LineString":
            pts = self._project_ring(viewport, coords)
            if len(pts) >= 4:
                canvas.create_line(*pts, **line_kw)
        elif gtype == "MultiLineString":
            for line in coords:
                pts = self._project_ring(viewport, line)
                if len(pts) >= 4:
                    canvas.create_line(*pts, **line_kw)
        elif gtype == "Polygon":
            outer = coords[0]
            pts = self._project_ring(viewport, outer)
            if len(pts) >= 6:
                canvas.create_polygon(*pts, fill=fill, outline=outline, width=width, tags=tag)
        elif gtype == "MultiPolygon":
            for poly in coords:
                if poly:
                    pts = self._project_ring(viewport, poly[0])
                    if len(pts) >= 6:
                        canvas.create_polygon(*pts, fill=fill, outline=outline, width=width, tags=tag)
        elif gtype == "Point":
            x, y = viewport.geo_to_screen(coords[1], coords[0])
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=line_color, outline="", tags=tag)

    @staticmethod
    def hit_test_feature(
        osm_features: Iterable[OSMFeature],
        drainage_features: Iterable[DrainageFeature],
        viewport: GeoViewport,
        screen_x: float,
        screen_y: float,
        tolerance_px: float = 9.0,
    ) -> tuple[str, OSMFeature | DrainageFeature] | None:
        """Return ('drainage', obj) or ('osm', obj) closest to clicked screen coordinates."""
        best_drain: tuple[float, DrainageFeature] | None = None
        for dr in drainage_features:
            dx, dy = viewport.geo_to_screen(dr.latitude, dr.longitude)
            dist = math.hypot(screen_x - dx, screen_y - dy)
            if dist <= tolerance_px + 3.0 and (best_drain is None or dist < best_drain[0]):
                best_drain = (dist, dr)
        if best_drain is not None:
            return "drainage", best_drain[1]

        best_osm: tuple[float, OSMFeature] | None = None
        for feat in osm_features:
            dist = MapRenderer._feature_screen_distance(feat.geometry, viewport, screen_x, screen_y)
            if dist is not None and dist <= tolerance_px:
                if best_osm is None or dist < best_osm[0]:
                    best_osm = (dist, feat)
        if best_osm is not None:
            return "osm", best_osm[1]
        return None

    @staticmethod
    def _feature_screen_distance(
        geom: dict,
        viewport: GeoViewport,
        px: float,
        py: float,
    ) -> float | None:
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if not coords:
            return None

        if gtype == "Point":
            x, y = viewport.geo_to_screen(coords[1], coords[0])
            return math.hypot(px - x, py - y)
        if gtype == "LineString":
            return MapRenderer._min_dist_polyline(coords, viewport, px, py)
        if gtype == "MultiLineString":
            dists = [MapRenderer._min_dist_polyline(line, viewport, px, py) for line in coords]
            valid = [d for d in dists if d is not None]
            return min(valid) if valid else None
        if gtype == "Polygon":
            ring = coords[0]
            if MapRenderer._point_in_ring(ring, viewport, px, py):
                return 0.0
            return MapRenderer._min_dist_polyline(ring, viewport, px, py)
        if gtype == "MultiPolygon":
            for poly in coords:
                if poly and MapRenderer._point_in_ring(poly[0], viewport, px, py):
                    return 0.0
            dists = [
                MapRenderer._min_dist_polyline(poly[0], viewport, px, py)
                for poly in coords
                if poly
            ]
            valid = [d for d in dists if d is not None]
            return min(valid) if valid else None
        return None

    @staticmethod
    def _min_dist_polyline(coords: list, viewport: GeoViewport, px: float, py: float) -> float | None:
        if len(coords) < 2:
            return None
        best = float("inf")
        pts = [viewport.geo_to_screen(c[1], c[0]) for c in coords]
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            dx, dy = x2 - x1, y2 - y1
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq <= 1e-9:
                d = math.hypot(px - x1, py - y1)
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len_sq))
                proj_x = x1 + t * dx
                proj_y = y1 + t * dy
                d = math.hypot(px - proj_x, py - proj_y)
            if d < best:
                best = d
        return best

    @staticmethod
    def _point_in_ring(ring: list, viewport: GeoViewport, px: float, py: float) -> bool:
        pts = [viewport.geo_to_screen(c[1], c[0]) for c in ring]
        inside = False
        n = len(pts)
        j = n - 1
        for i in range(n):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-9) + xi):
                inside = not inside
            j = i
        return inside

    @staticmethod
    def _project_ring(viewport: GeoViewport, lonlat_list: list) -> list[float]:
        flat: list[float] = []
        for pair in lonlat_list:
            x, y = viewport.geo_to_screen(pair[1], pair[0])
            flat.extend((x, y))
        return flat

    @staticmethod
    def _draw_scale_and_attribution(canvas: tk.Canvas, viewport: GeoViewport) -> None:
        w = viewport.width
        h = viewport.height
        mpp = viewport.metres_per_pixel()

        target_m = mpp * 110.0
        nice_steps = [25, 50, 100, 200, 250, 500, 1000, 2000, 5000]
        bar_m = min(nice_steps, key=lambda s: abs(s - target_m))
        bar_px = max(30.0, min(180.0, bar_m / max(1e-6, mpp)))
        label = f"{bar_m} m" if bar_m < 1000 else f"{bar_m / 1000:.1f} km"

        x_start = 16
        y_base = h - 18
        canvas.create_rectangle(
            x_start - 6,
            y_base - 22,
            x_start + bar_px + 12,
            y_base + 8,
            fill="#0B1120",
            outline="#334155",
            tags=("layer_hud",),
        )
        canvas.create_line(
            x_start,
            y_base,
            x_start + bar_px,
            y_base,
            fill=MAP_COLORS["scale_bar"],
            width=2.0,
            tags=("layer_hud",),
        )
        canvas.create_line(x_start, y_base - 4, x_start, y_base + 4, fill=MAP_COLORS["scale_bar"], width=2.0, tags=("layer_hud",))
        canvas.create_line(x_start + bar_px, y_base - 4, x_start + bar_px, y_base + 4, fill=MAP_COLORS["scale_bar"], width=2.0, tags=("layer_hud",))
        canvas.create_text(
            x_start + bar_px / 2.0,
            y_base - 11,
            text=f"Scale ~{label}",
            fill="#E2E8F0",
            font=("Segoe UI", 8, "bold"),
            tags=("layer_hud",),
        )

        attr_w = 215
        canvas.create_rectangle(
            w - attr_w - 10,
            h - 26,
            w - 8,
            h - 6,
            fill="#0B1120",
            outline="#334155",
            tags=("layer_hud",),
        )
        canvas.create_text(
            w - 14,
            h - 16,
            text=OSM_ATTRIBUTION,
            anchor="e",
            fill="#94A3B8",
            font=("Segoe UI", 8),
            tags=("layer_hud",),
        )
