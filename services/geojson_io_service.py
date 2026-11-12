"""GeoJSON and CSV import/export service for neighbourhood features, grid, and drainage."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.geo_utils import calculate_geometry_length_m
from core.models import DrainageFeature, GridCell, Neighbourhood, OSMFeature
from core.validation import ValidationError, validate_geojson_geometry
from services.osm_service import classify_building_category, classify_road_category


class GeoDataIOError(RuntimeError):
    """Raised when GeoJSON/CSV validation, import, or export fails."""


class GeoJSONIOService:
    """Handles validated GeoJSON import/export and CSV exports with provenance."""

    @staticmethod
    def export_neighbourhood_geojson(
        neighbourhood: Neighbourhood,
        osm_features: list[OSMFeature],
        drainage_features: list[DrainageFeature],
        out_path: Path | str,
    ) -> Path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        features_out: list[dict[str, Any]] = []

        for feat in osm_features:
            features_out.append(
                {
                    "type": "Feature",
                    "properties": {
                        "feature_group": "osm_feature",
                        "db_id": feat.id,
                        "osm_id": feat.osm_id,
                        "element_type": feat.element_type,
                        "category": feat.category,
                        "subcategory": feat.subcategory,
                        "road_category": feat.road_category,
                        "building_category": feat.building_category,
                        "name": feat.name,
                        "length_m": round(feat.length_m, 2),
                        "source": feat.source,
                        "imported_at": feat.imported_at,
                        "is_user_edited": feat.is_user_edited,
                        "user_notes": feat.user_notes,
                    },
                    "geometry": feat.geometry,
                }
            )

        for dr in drainage_features:
            features_out.append(
                {
                    "type": "Feature",
                    "properties": {
                        "feature_group": "drainage_feature",
                        "db_id": dr.id,
                        "name": dr.name,
                        "feature_type": dr.feature_type,
                        "grid_cell_id": dr.grid_cell_id,
                        "capacity": dr.capacity,
                        "capacity_unit": dr.capacity_unit,
                        "status": dr.status,
                        "source": dr.source,
                        "notes": dr.notes,
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [dr.longitude, dr.latitude],
                    },
                }
            )

        payload = {
            "type": "FeatureCollection",
            "metadata": {
                "application": "CHENNAI FLOODGUARD (Phase 2)",
                "neighbourhood": neighbourhood.name,
                "exported_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            },
            "features": features_out,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def export_grid_csv(
        neighbourhood: Neighbourhood,
        cells: list[GridCell],
        out_path: Path | str,
    ) -> Path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "neighbourhood",
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
            "approx_area_m2",
            "elevation_m",
            "min_elevation_m",
            "max_elevation_m",
            "mean_elevation_m",
            "elevation_source",
            "land_use",
            "land_use_source",
            "infiltration_rate_mm_hr",
            "infiltration_source",
            "drainage_capacity_mm_hr",
            "drainage_source",
            "notes",
            "updated_at",
        ]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for c in cells:
                w_m, h_m = c.approx_dimensions_m()
                area_m2 = c.approx_area_sq_m()
                writer.writerow(
                    {
                        "neighbourhood": neighbourhood.name,
                        "cell_id": c.id,
                        "cell_code": c.cell_code,
                        "row_number": c.row_number,
                        "column_number": c.column_number,
                        "min_latitude": round(c.min_latitude, 7),
                        "max_latitude": round(c.max_latitude, 7),
                        "min_longitude": round(c.min_longitude, 7),
                        "max_longitude": round(c.max_longitude, 7),
                        "center_latitude": round(c.center_latitude, 7),
                        "center_longitude": round(c.center_longitude, 7),
                        "approx_width_m": round(w_m, 2),
                        "approx_height_m": round(h_m, 2),
                        "approx_area_m2": round(area_m2, 2),
                        "elevation_m": "" if c.elevation_m is None else c.elevation_m,
                        "min_elevation_m": "" if c.min_elevation_m is None else c.min_elevation_m,
                        "max_elevation_m": "" if c.max_elevation_m is None else c.max_elevation_m,
                        "mean_elevation_m": "" if c.mean_elevation_m is None else c.mean_elevation_m,
                        "elevation_source": c.elevation_source or "missing",
                        "land_use": c.land_use,
                        "land_use_source": c.land_use_source,
                        "infiltration_rate_mm_hr": c.infiltration_rate,
                        "infiltration_source": c.infiltration_source,
                        "drainage_capacity_mm_hr": c.drainage_capacity,
                        "drainage_source": c.drainage_source,
                        "notes": c.notes,
                        "updated_at": c.updated_at,
                    }
                )
        return path

    @staticmethod
    def export_drainage_csv(
        neighbourhood: Neighbourhood,
        drainage_features: list[DrainageFeature],
        out_path: Path | str,
    ) -> Path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "id",
            "neighbourhood",
            "grid_cell_id",
            "name",
            "feature_type",
            "latitude",
            "longitude",
            "capacity",
            "capacity_unit",
            "status",
            "source",
            "notes",
            "updated_at",
        ]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for dr in drainage_features:
                writer.writerow(
                    {
                        "id": dr.id,
                        "neighbourhood": neighbourhood.name,
                        "grid_cell_id": dr.grid_cell_id if dr.grid_cell_id is not None else "",
                        "name": dr.name,
                        "feature_type": dr.feature_type,
                        "latitude": round(dr.latitude, 7),
                        "longitude": round(dr.longitude, 7),
                        "capacity": "" if dr.capacity is None else dr.capacity,
                        "capacity_unit": dr.capacity_unit,
                        "status": dr.status,
                        "source": dr.source,
                        "notes": dr.notes,
                        "updated_at": dr.updated_at,
                    }
                )
        return path

    @staticmethod
    def import_geojson_features(
        file_path: Path | str,
        neighbourhood_id: int,
    ) -> list[OSMFeature]:
        """Validate and parse a GeoJSON file into OSMFeature records."""
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise GeoDataIOError(f"GeoJSON file not found: {path}")

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GeoDataIOError(f"Invalid JSON in '{path.name}': {exc}") from exc

        if not isinstance(raw, dict):
            raise GeoDataIOError("GeoJSON root must be a JSON object.")

        if raw.get("type") == "FeatureCollection":
            raw_features = raw.get("features")
            if not isinstance(raw_features, list):
                raise GeoDataIOError("GeoJSON FeatureCollection missing 'features' list.")
        elif raw.get("type") == "Feature":
            raw_features = [raw]
        else:
            raise GeoDataIOError("Unsupported GeoJSON type (expected FeatureCollection or Feature).")

        stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        parsed: list[OSMFeature] = []
        errors: list[str] = []

        for idx, item in enumerate(raw_features):
            if not isinstance(item, dict) or item.get("type") != "Feature":
                errors.append(f"Feature #{idx + 1}: invalid Feature object")
                continue
            geom = item.get("geometry")
            try:
                validate_geojson_geometry(geom)
            except ValidationError as exc:
                errors.append(f"Feature #{idx + 1}: {exc}")
                continue

            props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
            cat = str(props.get("category") or "").strip().lower()
            if cat not in ("road", "building", "waterway", "green_area", "other"):
                if "highway" in props:
                    cat = "road"
                elif "building" in props:
                    cat = "building"
                elif "waterway" in props or props.get("natural") == "water":
                    cat = "waterway"
                elif props.get("leisure") in ("park", "garden") or props.get("natural") == "wetland":
                    cat = "green_area"
                else:
                    gtype = geom.get("type", "")
                    cat = "road" if "Line" in gtype else ("building" if "Polygon" in gtype else "other")

            sub = str(props.get("subcategory") or props.get("highway") or props.get("building") or cat)
            name = str(props.get("name") or "").strip()
            src = str(props.get("source") or f"User-imported GeoJSON ({path.name})").strip()

            # Stable negative deterministic ID if no osm_id provided so we don't collide with real OSM IDs
            raw_id = props.get("osm_id")
            if raw_id is not None:
                try:
                    feat_id = int(raw_id)
                except (TypeError, ValueError):
                    feat_id = -abs(int(hashlib.sha256(f"{path.name}:{idx}".encode()).hexdigest()[:12], 16))
            else:
                feat_id = -abs(int(hashlib.sha256(f"{path.name}:{idx}:{json.dumps(geom)}".encode()).hexdigest()[:12], 16))

            length_m = calculate_geometry_length_m(geom) if cat in ("road", "waterway") else 0.0
            road_cat = str(props.get("road_category") or (classify_road_category(sub, props) if cat == "road" else ""))
            bldg_cat = str(props.get("building_category") or (classify_building_category(sub, props) if cat == "building" else ""))

            parsed.append(
                OSMFeature(
                    id=None,
                    neighbourhood_id=neighbourhood_id,
                    osm_id=feat_id,
                    element_type="geojson",
                    category=cat,
                    subcategory=sub,
                    name=name,
                    geometry=geom,
                    tags={str(k): str(v) for k, v in props.items()},
                    source=src,
                    imported_at=stamp,
                    length_m=length_m,
                    road_category=road_cat,
                    building_category=bldg_cat,
                )
            )

        if not parsed:
            detail = "; ".join(errors[:3]) if errors else "No valid features found."
            raise GeoDataIOError(f"Could not import GeoJSON '{path.name}': {detail}")

        return parsed
