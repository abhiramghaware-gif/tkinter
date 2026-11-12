"""Workspace, simulation grid generation, cell editing, and export logic."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import DEFAULT_GRID_COLS, DEFAULT_GRID_ROWS, EXPORTS_DIR
from core.geo_utils import compute_feature_grid_links
from core.models import GridCell, Neighbourhood, OSMFeature, approximate_cell_metrics_m
from core.validation import (
    ValidationError,
    validate_bounding_box,
    validate_elevation,
    validate_elevation_source,
    validate_grid_dimensions,
    validate_land_use,
    validate_latitude,
    validate_longitude,
    validate_non_negative_rate,
    validate_workspace_name,
)
from database.repository import FloodGuardRepository


def build_grid_cells(
    neighbourhood_id: int,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    rows: int = DEFAULT_GRID_ROWS,
    cols: int = DEFAULT_GRID_COLS,
) -> list[GridCell]:
    """Generate rows x cols GridCell objects partitioning the bounding box.

    Row 0 corresponds to the northernmost strip (top of map) down to row (rows - 1)
    at the southern boundary; Column 0 corresponds to the westernmost strip (left)
    to column (cols - 1) at the eastern boundary.
    """
    south, north, west, east = validate_bounding_box(min_lat, max_lat, min_lon, max_lon)
    r_count, c_count = validate_grid_dimensions(rows, cols)

    lat_step = (north - south) / r_count
    lon_step = (east - west) / c_count

    cells: list[GridCell] = []
    for r in range(r_count):
        cell_max_lat = north - r * lat_step
        cell_min_lat = south if r == r_count - 1 else north - (r + 1) * lat_step
        for c in range(c_count):
            cell_min_lon = west + c * lon_step
            cell_max_lon = east if c == c_count - 1 else west + (c + 1) * lon_step
            w_m, h_m, area_m2 = approximate_cell_metrics_m(
                cell_min_lat, cell_max_lat, cell_min_lon, cell_max_lon
            )
            cells.append(
                GridCell(
                    id=None,
                    neighbourhood_id=neighbourhood_id,
                    row_number=r,
                    column_number=c,
                    min_latitude=cell_min_lat,
                    max_latitude=cell_max_lat,
                    min_longitude=cell_min_lon,
                    max_longitude=cell_max_lon,
                    elevation_m=None,
                    elevation_source=None,
                    land_use="Unknown",
                    land_use_source="missing",
                    infiltration_rate=0.0,
                    infiltration_source="missing",
                    drainage_capacity=0.0,
                    drainage_source="missing",
                    approx_width_m=w_m,
                    approx_height_m=h_m,
                    approx_area_m2=area_m2,
                    notes="",
                )
            )
    return cells


class WorkspaceManager:
    """High-level coordinator for neighbourhood workspaces and editable simulation grids."""

    def __init__(self, repo: FloodGuardRepository) -> None:
        self.repo = repo

    def create_or_get_workspace(
        self,
        name: str,
        center_latitude: float,
        center_longitude: float,
        min_latitude: float,
        max_latitude: float,
        min_longitude: float,
        max_longitude: float,
        district: str = "",
        state: str = "",
        country: str = "",
        grid_rows: int = DEFAULT_GRID_ROWS,
        grid_cols: int = DEFAULT_GRID_COLS,
    ) -> tuple[Neighbourhood, bool]:
        """Create a workspace with its grid cells, or return existing workspace without duplicating.

        Returns (neighbourhood, created_new).
        """
        clean_name = validate_workspace_name(name)
        existing = self.repo.get_neighbourhood_by_name(clean_name)
        if existing is not None:
            return existing, False

        c_lat = validate_latitude(center_latitude, "Center latitude")
        c_lon = validate_longitude(center_longitude, "Center longitude")
        south, north, west, east = validate_bounding_box(
            min_latitude, max_latitude, min_longitude, max_longitude
        )
        rows, cols = validate_grid_dimensions(grid_rows, grid_cols)

        neighbourhood = Neighbourhood(
            id=None,
            name=clean_name,
            district=district.strip(),
            state=state.strip(),
            country=country.strip(),
            center_latitude=c_lat,
            center_longitude=c_lon,
            min_latitude=south,
            max_latitude=north,
            min_longitude=west,
            max_longitude=east,
            grid_rows=rows,
            grid_cols=cols,
        )
        cells = build_grid_cells(0, south, north, west, east, rows=rows, cols=cols)
        created = self.repo.create_neighbourhood_with_cells(neighbourhood, cells)
        self.repo.set_setting("active_neighbourhood_id", str(created.id))
        return created, True

    def regenerate_workspace_grid(
        self,
        neighbourhood: Neighbourhood,
        min_latitude: float,
        max_latitude: float,
        min_longitude: float,
        max_longitude: float,
        grid_rows: int,
        grid_cols: int,
        center_latitude: float | None = None,
        center_longitude: float | None = None,
        district: str | None = None,
        state: str | None = None,
        country: str | None = None,
        preserve_existing: bool = True,
    ) -> Neighbourhood:
        """Update workspace bounding box and/or grid dimensions and regenerate cells.

        When preserve_existing=True, attributes from previous cells whose bounds contain
        the new cell's center are carried over rather than silently discarded.
        """
        if neighbourhood.id is None:
            raise ValidationError("Neighbourhood has not been saved yet.")

        south, north, west, east = validate_bounding_box(
            min_latitude, max_latitude, min_longitude, max_longitude
        )
        rows, cols = validate_grid_dimensions(grid_rows, grid_cols)
        c_lat = (
            validate_latitude(center_latitude, "Center latitude")
            if center_latitude is not None
            else (south + north) / 2.0
        )
        c_lon = (
            validate_longitude(center_longitude, "Center longitude")
            if center_longitude is not None
            else (west + east) / 2.0
        )

        old_cells = self.repo.get_grid_cells(neighbourhood.id) if preserve_existing else []
        new_cells = build_grid_cells(
            neighbourhood.id, south, north, west, east, rows=rows, cols=cols
        )

        if old_cells:
            for ncell in new_cells:
                cx = ncell.center_longitude
                cy = ncell.center_latitude
                match = self.find_cell_for_point(old_cells, cy, cx)
                if match is not None and match.is_configured:
                    ncell.elevation_m = match.elevation_m
                    ncell.elevation_source = match.elevation_source
                    ncell.min_elevation_m = match.min_elevation_m
                    ncell.max_elevation_m = match.max_elevation_m
                    ncell.mean_elevation_m = match.mean_elevation_m
                    ncell.land_use = match.land_use
                    ncell.land_use_source = match.land_use_source
                    ncell.infiltration_rate = match.infiltration_rate
                    ncell.infiltration_source = match.infiltration_source
                    ncell.drainage_capacity = match.drainage_capacity
                    ncell.drainage_source = match.drainage_source
                    ncell.notes = match.notes

        updated = self.repo.update_neighbourhood_bbox_and_grid(
            neighbourhood_id=neighbourhood.id,
            center_lat=c_lat,
            center_lon=c_lon,
            min_lat=south,
            max_lat=north,
            min_lon=west,
            max_lon=east,
            grid_rows=rows,
            grid_cols=cols,
            new_cells=new_cells,
            district=district,
            state=state,
            country=country,
        )
        self.rebuild_feature_grid_links(updated.id)
        return updated

    def validate_and_save_cell(
        self,
        cell: GridCell,
        elevation_input: Any,
        elevation_source_input: Any,
        land_use_input: Any,
        infiltration_input: Any,
        drainage_input: Any,
        notes_input: str,
    ) -> GridCell:
        """Validate edited cell attributes and persist to SQLite with provenance."""
        elev = validate_elevation(elevation_input)
        elev_src = validate_elevation_source(elevation_source_input, elev)
        land_use = validate_land_use(land_use_input)
        infil = validate_non_negative_rate(infiltration_input, "Soil infiltration rate (mm/hr)")
        drain = validate_non_negative_rate(drainage_input, "Drainage capacity (mm/hr)")
        notes = (notes_input or "").strip()

        cell.elevation_m = elev
        cell.elevation_source = elev_src
        if elev is not None and cell.mean_elevation_m is None:
            cell.mean_elevation_m = elev
        elif elev is None:
            cell.min_elevation_m = None
            cell.max_elevation_m = None
            cell.mean_elevation_m = None

        cell.land_use = land_use
        cell.land_use_source = "missing" if land_use == "Unknown" else "user-entered"
        cell.infiltration_rate = infil
        cell.infiltration_source = "user-entered" if infil > 0.0 else "missing"
        cell.drainage_capacity = drain
        cell.drainage_source = "user-entered" if drain > 0.0 else "missing"
        cell.notes = notes
        return self.repo.update_grid_cell(cell)

    @staticmethod
    def find_cell_for_point(cells: list[GridCell], lat: float, lon: float) -> GridCell | None:
        """Return the GridCell containing (lat, lon), or None if outside grid bounds."""
        for cell in cells:
            if (
                cell.min_latitude <= lat <= cell.max_latitude
                and cell.min_longitude <= lon <= cell.max_longitude
            ):
                return cell
        return None

    def rebuild_feature_grid_links(self, neighbourhood_id: int | None) -> int:
        """Recompute normalized feature-to-grid intersections in SQLite."""
        if neighbourhood_id is None:
            return 0
        cells = self.repo.get_grid_cells(neighbourhood_id)
        osm_feats = self.repo.get_osm_features(neighbourhood_id)
        drain_feats = self.repo.list_drainage_features(neighbourhood_id)
        links = compute_feature_grid_links(cells, osm_feats, drain_feats)
        return self.repo.replace_grid_feature_links(neighbourhood_id, links)

    def suggest_land_use_from_features(
        self,
        neighbourhood_id: int,
        overwrite_user_verified: bool = False,
    ) -> int:
        """Infer tentative cell land-use categories from intersecting mapped features.

        Only applies when clear feature rules match and always tags results as 'inferred'
        (never marked as verified or user-entered).
        """
        cells = self.repo.get_grid_cells(neighbourhood_id)
        osm_feats = self.repo.get_osm_features(neighbourhood_id)
        links = self.repo.get_links_for_neighbourhood(neighbourhood_id)
        if not links and osm_feats:
            self.rebuild_feature_grid_links(neighbourhood_id)
            links = self.repo.get_links_for_neighbourhood(neighbourhood_id)

        feat_by_id: dict[int, OSMFeature] = {f.id: f for f in osm_feats if f.id is not None}
        feats_per_cell: dict[int, list[OSMFeature]] = {}
        for lk in links:
            if lk.osm_feature_id is not None and lk.osm_feature_id in feat_by_id:
                feats_per_cell.setdefault(lk.grid_cell_id, []).append(feat_by_id[lk.osm_feature_id])

        updates: list[tuple[int, str, str]] = []
        for cell in cells:
            if cell.id is None:
                continue
            if not overwrite_user_verified and cell.land_use_source == "user-entered":
                continue

            intersecting = feats_per_cell.get(cell.id, [])
            if not intersecting:
                continue

            cats = [f.category for f in intersecting]
            b_cats = {f.building_category for f in intersecting if f.category == "building"}

            suggested: str | None = None
            if "waterway" in cats and cats.count("waterway") >= max(1, len(cats) // 2) and "building" not in cats:
                suggested = "Water Body"
            elif "green_area" in cats and "building" not in cats and "road" not in cats:
                suggested = "Green Area"
            elif "building" in cats:
                if "Commercial" in b_cats and "Residential" in b_cats:
                    suggested = "Mixed Use"
                elif "Industrial" in b_cats and "Residential" not in b_cats:
                    suggested = "Industrial"
                elif "Commercial" in b_cats and "Residential" not in b_cats:
                    suggested = "Commercial"
                else:
                    suggested = "Residential"
            elif "road" in cats and "green_area" not in cats:
                suggested = "Road"

            if suggested is not None and (suggested != cell.land_use or cell.land_use_source != "inferred"):
                updates.append((cell.id, suggested, "inferred"))

        return self.repo.update_cells_land_use_batch(updates, neighbourhood_id)

    def validate_and_bulk_save_cells(
        self,
        cells: list[GridCell],
        elevation_input: Any,
        elevation_source_input: Any,
        land_use_input: Any,
        infiltration_input: Any,
        drainage_input: Any,
        notes_input: str,
    ) -> int:
        """Validate attributes and apply to multiple selected cells atomically."""
        if not cells:
            raise ValidationError("No grid cells selected.")
        elev = validate_elevation(elevation_input)
        elev_src = validate_elevation_source(elevation_source_input, elev)
        land_use = validate_land_use(land_use_input)
        infil = validate_non_negative_rate(infiltration_input, "Soil infiltration rate (mm/hr)")
        drain = validate_non_negative_rate(drainage_input, "Drainage capacity (mm/hr)")
        notes = (notes_input or "").strip()

        nid = cells[0].neighbourhood_id
        ids = [c.id for c in cells if c.id is not None]
        return self.repo.bulk_update_grid_cells(
            cell_ids=ids,
            neighbourhood_id=nid,
            elevation_m=elev,
            elevation_source=elev_src,
            land_use=land_use,
            infiltration_rate=infil,
            drainage_capacity=drain,
            notes=notes,
        )

    def export_grid_geojson(
        self,
        neighbourhood: Neighbourhood,
        cells: list[GridCell],
        export_dir: Path | str = EXPORTS_DIR,
    ) -> Path:
        """Export simulation grid and attributes as a GeoJSON FeatureCollection."""
        out_dir = Path(export_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in neighbourhood.name).strip("_")
        out_path = out_dir / f"{safe_name}_grid_{stamp}.geojson"

        features = []
        for cell in cells:
            w_m, h_m = cell.approx_dimensions_m()
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "cell_id": cell.id,
                        "cell_code": cell.cell_code,
                        "row_number": cell.row_number,
                        "column_number": cell.column_number,
                        "center_latitude": cell.center_latitude,
                        "center_longitude": cell.center_longitude,
                        "approx_width_m": round(w_m, 2),
                        "approx_height_m": round(h_m, 2),
                        "elevation_m": cell.elevation_m,
                        "elevation_source": cell.elevation_source,
                        "land_use": cell.land_use,
                        "infiltration_rate_mm_hr": cell.infiltration_rate,
                        "drainage_capacity_mm_hr": cell.drainage_capacity,
                        "notes": cell.notes,
                        "updated_at": cell.updated_at,
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [cell.min_longitude, cell.min_latitude],
                                [cell.max_longitude, cell.min_latitude],
                                [cell.max_longitude, cell.max_latitude],
                                [cell.min_longitude, cell.max_latitude],
                                [cell.min_longitude, cell.min_latitude],
                            ]
                        ],
                    },
                }
            )

        payload = {
            "type": "FeatureCollection",
            "metadata": {
                "application": "CHENNAI FLOODGUARD (Phase 1 Prototype)",
                "neighbourhood": neighbourhood.name,
                "grid_dimensions": f"{neighbourhood.grid_rows}x{neighbourhood.grid_cols}",
                "exported_at_utc": stamp,
                "disclaimer": "Experimental educational data; elevation/rates are user-entered unless sourced.",
            },
            "features": features,
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out_path

    def export_grid_csv(
        self,
        neighbourhood: Neighbourhood,
        cells: list[GridCell],
        export_dir: Path | str = EXPORTS_DIR,
    ) -> Path:
        """Export simulation grid cells to CSV."""
        out_dir = Path(export_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in neighbourhood.name).strip("_")
        out_path = out_dir / f"{safe_name}_grid_{stamp}.csv"

        fieldnames = [
            "cell_id",
            "cell_code",
            "row_number",
            "column_number",
            "min_latitude",
            "max_latitude",
            "min_longitude",
            "max_longitude",
            "center_latitude",
            "center_longitude",
            "approx_width_m",
            "approx_height_m",
            "elevation_m",
            "elevation_source",
            "land_use",
            "infiltration_rate_mm_hr",
            "drainage_capacity_mm_hr",
            "notes",
            "updated_at",
        ]
        with out_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for cell in cells:
                w_m, h_m = cell.approx_dimensions_m()
                writer.writerow(
                    {
                        "cell_id": cell.id,
                        "cell_code": cell.cell_code,
                        "row_number": cell.row_number,
                        "column_number": cell.column_number,
                        "min_latitude": round(cell.min_latitude, 7),
                        "max_latitude": round(cell.max_latitude, 7),
                        "min_longitude": round(cell.min_longitude, 7),
                        "max_longitude": round(cell.max_longitude, 7),
                        "center_latitude": round(cell.center_latitude, 7),
                        "center_longitude": round(cell.center_longitude, 7),
                        "approx_width_m": round(w_m, 2),
                        "approx_height_m": round(h_m, 2),
                        "elevation_m": cell.elevation_m if cell.elevation_m is not None else "",
                        "elevation_source": cell.elevation_source or "",
                        "land_use": cell.land_use,
                        "infiltration_rate_mm_hr": cell.infiltration_rate,
                        "drainage_capacity_mm_hr": cell.drainage_capacity,
                        "notes": cell.notes,
                        "updated_at": cell.updated_at,
                    }
                )
        return out_path

