"""Repository layer encapsulating all SQL queries for CHENNAI FLOODGUARD."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any, Iterable

from core.models import (
    DashboardSummary,
    DataQualitySummary,
    DrainageFeature,
    ElevationSourceRecord,
    GridCell,
    GridFeatureLink,
    HourlyForecastPoint,
    LandUseHistoryEntry,
    Neighbourhood,
    OSMFeature,
    WeatherSnapshot,
)
from core.simulation_config import SimulationConfig
from core.simulation_engine import (
    SimulationCellFinalState,
    SimulationCellStepRecord,
    SimulationOutput,
    SimulationRunRecord,
    SimulationStepRecord,
    SimulationSummary,
)
from core.validation import validate_geojson_geometry
from database.db import DatabaseManager, utc_now_iso

if TYPE_CHECKING:
    from routing.flood_exposure import RoadFloodExposure
    from routing.road_network import RoadNetworkGraph
    from routing.route_comparison import RouteMetrics
    from routing.route_planner import RoadConditionRecord

logger = logging.getLogger(__name__)


class FloodGuardRepository:
    """Provides parameterized CRUD operations without exposing SQL to the GUI."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db = db_manager

    # -------------------------------------------------------------------------
    # Neighbourhoods
    # -------------------------------------------------------------------------

    def get_neighbourhood_by_id(self, neighbourhood_id: int) -> Neighbourhood | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM neighbourhoods WHERE id = ?",
                (neighbourhood_id,),
            ).fetchone()
            return self._row_to_neighbourhood(row) if row else None

    def get_neighbourhood_by_name(self, name: str) -> Neighbourhood | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM neighbourhoods WHERE LOWER(name) = LOWER(?)",
                (name.strip(),),
            ).fetchone()
            return self._row_to_neighbourhood(row) if row else None

    def list_neighbourhoods(self) -> list[Neighbourhood]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM neighbourhoods ORDER BY updated_at DESC, name ASC"
            ).fetchall()
            return [self._row_to_neighbourhood(r) for r in rows]

    def create_neighbourhood_with_cells(
        self,
        neighbourhood: Neighbourhood,
        cells: list[GridCell],
    ) -> Neighbourhood:
        """Create a neighbourhood and its grid cells atomically, or return existing if duplicate."""
        existing = self.get_neighbourhood_by_name(neighbourhood.name)
        if existing is not None:
            return existing

        now = utc_now_iso()
        with self.db.transaction() as conn:
            dup = conn.execute(
                "SELECT * FROM neighbourhoods WHERE LOWER(name) = LOWER(?)",
                (neighbourhood.name.strip(),),
            ).fetchone()
            if dup is not None:
                return self._row_to_neighbourhood(dup)

            cur = conn.execute(
                """
                INSERT INTO neighbourhoods (
                    name, district, state, country,
                    center_latitude, center_longitude,
                    min_latitude, max_latitude, min_longitude, max_longitude,
                    grid_rows, grid_cols, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    neighbourhood.name.strip(),
                    neighbourhood.district.strip(),
                    neighbourhood.state.strip(),
                    neighbourhood.country.strip(),
                    neighbourhood.center_latitude,
                    neighbourhood.center_longitude,
                    neighbourhood.min_latitude,
                    neighbourhood.max_latitude,
                    neighbourhood.min_longitude,
                    neighbourhood.max_longitude,
                    neighbourhood.grid_rows,
                    neighbourhood.grid_cols,
                    now,
                    now,
                ),
            )
            nid = int(cur.lastrowid)
            self._insert_grid_cells_conn(conn, nid, cells, now)

        created = self.get_neighbourhood_by_id(nid)
        assert created is not None
        return created

    def update_neighbourhood_bbox_and_grid(
        self,
        neighbourhood_id: int,
        center_lat: float,
        center_lon: float,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        grid_rows: int,
        grid_cols: int,
        new_cells: list[GridCell],
        district: str | None = None,
        state: str | None = None,
        country: str | None = None,
    ) -> Neighbourhood:
        """Update neighbourhood bounds/dimensions and replace its grid cells atomically."""
        now = utc_now_iso()
        with self.db.transaction() as conn:
            current = conn.execute(
                "SELECT district, state, country FROM neighbourhoods WHERE id = ?",
                (neighbourhood_id,),
            ).fetchone()
            if current is None:
                raise ValueError(f"Neighbourhood {neighbourhood_id} not found.")

            conn.execute(
                """
                UPDATE neighbourhoods
                SET district = ?, state = ?, country = ?,
                    center_latitude = ?, center_longitude = ?,
                    min_latitude = ?, max_latitude = ?, min_longitude = ?, max_longitude = ?,
                    grid_rows = ?, grid_cols = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    district if district is not None else current["district"],
                    state if state is not None else current["state"],
                    country if country is not None else current["country"],
                    center_lat,
                    center_lon,
                    min_lat,
                    max_lat,
                    min_lon,
                    max_lon,
                    grid_rows,
                    grid_cols,
                    now,
                    neighbourhood_id,
                ),
            )
            conn.execute("DELETE FROM grid_cells WHERE neighbourhood_id = ?", (neighbourhood_id,))
            self._insert_grid_cells_conn(conn, neighbourhood_id, new_cells, now)
        updated = self.get_neighbourhood_by_id(neighbourhood_id)
        assert updated is not None
        return updated

    @staticmethod
    def _insert_grid_cells_conn(
        conn: sqlite3.Connection,
        neighbourhood_id: int,
        cells: list[GridCell],
        timestamp: str,
    ) -> None:
        conn.executemany(
            """
            INSERT INTO grid_cells (
                neighbourhood_id, row_number, column_number,
                min_latitude, max_latitude, min_longitude, max_longitude,
                center_latitude, center_longitude,
                approx_width_m, approx_height_m, approx_area_m2,
                elevation_m, elevation_source,
                min_elevation_m, max_elevation_m, mean_elevation_m,
                land_use, land_use_source,
                infiltration_rate, infiltration_source,
                drainage_capacity, drainage_source,
                notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    neighbourhood_id,
                    c.row_number,
                    c.column_number,
                    c.min_latitude,
                    c.max_latitude,
                    c.min_longitude,
                    c.max_longitude,
                    c.center_latitude,
                    c.center_longitude,
                    c.approx_dimensions_m()[0],
                    c.approx_dimensions_m()[1],
                    c.approx_area_sq_m(),
                    c.elevation_m,
                    c.elevation_source,
                    c.min_elevation_m,
                    c.max_elevation_m,
                    c.mean_elevation_m,
                    c.land_use,
                    c.land_use_source,
                    c.infiltration_rate,
                    c.infiltration_source,
                    c.drainage_capacity,
                    c.drainage_source,
                    c.notes,
                    timestamp,
                )
                for c in cells
            ],
        )

    # -------------------------------------------------------------------------
    # Grid Cells & Land-Use History
    # -------------------------------------------------------------------------

    def get_grid_cells(self, neighbourhood_id: int) -> list[GridCell]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM grid_cells
                WHERE neighbourhood_id = ?
                ORDER BY row_number ASC, column_number ASC
                """,
                (neighbourhood_id,),
            ).fetchall()
            return [self._row_to_grid_cell(r) for r in rows]

    def get_grid_cell(self, cell_id: int) -> GridCell | None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM grid_cells WHERE id = ?", (cell_id,)).fetchone()
            return self._row_to_grid_cell(row) if row else None

    def update_grid_cell(self, cell: GridCell) -> GridCell:
        if cell.id is None:
            raise ValueError("Cannot update GridCell without an ID.")
        now = utc_now_iso()
        with self.db.transaction() as conn:
            prev = conn.execute(
                "SELECT land_use FROM grid_cells WHERE id = ?",
                (cell.id,),
            ).fetchone()
            if prev is not None and prev["land_use"] != cell.land_use:
                conn.execute(
                    """
                    INSERT INTO land_use_history (
                        grid_cell_id, previous_category, new_category, source, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (cell.id, prev["land_use"], cell.land_use, cell.land_use_source, now),
                )

            conn.execute(
                """
                UPDATE grid_cells
                SET elevation_m = ?,
                    elevation_source = ?,
                    min_elevation_m = ?,
                    max_elevation_m = ?,
                    mean_elevation_m = ?,
                    land_use = ?,
                    land_use_source = ?,
                    infiltration_rate = ?,
                    infiltration_source = ?,
                    drainage_capacity = ?,
                    drainage_source = ?,
                    notes = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    cell.elevation_m,
                    cell.elevation_source,
                    cell.min_elevation_m,
                    cell.max_elevation_m,
                    cell.mean_elevation_m,
                    cell.land_use,
                    cell.land_use_source,
                    cell.infiltration_rate,
                    cell.infiltration_source,
                    cell.drainage_capacity,
                    cell.drainage_source,
                    cell.notes,
                    now,
                    cell.id,
                ),
            )
            conn.execute(
                "UPDATE neighbourhoods SET updated_at = ? WHERE id = ?",
                (now, cell.neighbourhood_id),
            )
        refreshed = self.get_grid_cell(cell.id)
        assert refreshed is not None
        return refreshed

    def bulk_update_grid_cells(
        self,
        cell_ids: Iterable[int],
        neighbourhood_id: int,
        elevation_m: float | None,
        elevation_source: str | None,
        land_use: str,
        infiltration_rate: float,
        drainage_capacity: float,
        notes: str,
        land_use_source: str = "user-entered",
        infiltration_source: str | None = None,
        drainage_source: str | None = None,
    ) -> int:
        ids = list(cell_ids)
        if not ids:
            return 0
        now = utc_now_iso()
        lu_src = "missing" if land_use == "Unknown" else land_use_source
        inf_src = infiltration_source or ("user-entered" if infiltration_rate > 0.0 else "missing")
        dr_src = drainage_source or ("user-entered" if drainage_capacity > 0.0 else "missing")

        with self.db.transaction() as conn:
            for cid in ids:
                prev = conn.execute(
                    "SELECT land_use FROM grid_cells WHERE id = ? AND neighbourhood_id = ?",
                    (cid, neighbourhood_id),
                ).fetchone()
                if prev is not None and prev["land_use"] != land_use:
                    conn.execute(
                        """
                        INSERT INTO land_use_history (
                            grid_cell_id, previous_category, new_category, source, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (cid, prev["land_use"], land_use, lu_src, now),
                    )
            conn.executemany(
                """
                UPDATE grid_cells
                SET elevation_m = ?,
                    elevation_source = ?,
                    mean_elevation_m = ?,
                    land_use = ?,
                    land_use_source = ?,
                    infiltration_rate = ?,
                    infiltration_source = ?,
                    drainage_capacity = ?,
                    drainage_source = ?,
                    notes = ?,
                    updated_at = ?
                WHERE id = ? AND neighbourhood_id = ?
                """,
                [
                    (
                        elevation_m,
                        elevation_source,
                        elevation_m,
                        land_use,
                        lu_src,
                        infiltration_rate,
                        inf_src,
                        drainage_capacity,
                        dr_src,
                        notes,
                        now,
                        cid,
                        neighbourhood_id,
                    )
                    for cid in ids
                ],
            )
            conn.execute(
                "UPDATE neighbourhoods SET updated_at = ? WHERE id = ?",
                (now, neighbourhood_id),
            )
        return len(ids)

    def update_cells_land_use_batch(
        self,
        updates: list[tuple[int, str, str]],
        neighbourhood_id: int,
    ) -> int:
        """Batch update (cell_id, new_land_use, source) and log land_use_history."""
        if not updates:
            return 0
        now = utc_now_iso()
        with self.db.transaction() as conn:
            for cid, new_lu, src in updates:
                prev = conn.execute(
                    "SELECT land_use FROM grid_cells WHERE id = ? AND neighbourhood_id = ?",
                    (cid, neighbourhood_id),
                ).fetchone()
                if prev is None:
                    continue
                if prev["land_use"] != new_lu:
                    conn.execute(
                        """
                        INSERT INTO land_use_history (
                            grid_cell_id, previous_category, new_category, source, updated_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (cid, prev["land_use"], new_lu, src, now),
                    )
                conn.execute(
                    """
                    UPDATE grid_cells
                    SET land_use = ?, land_use_source = ?, updated_at = ?
                    WHERE id = ? AND neighbourhood_id = ?
                    """,
                    (new_lu, src, now, cid, neighbourhood_id),
                )
            conn.execute(
                "UPDATE neighbourhoods SET updated_at = ? WHERE id = ?",
                (now, neighbourhood_id),
            )
        return len(updates)

    def update_cells_elevation_batch(
        self,
        updates: list[tuple[int, float | None, float | None, float | None, float | None, str | None]],
        neighbourhood_id: int,
    ) -> int:
        """Batch update (cell_id, center_elev, min_elev, max_elev, mean_elev, source)."""
        if not updates:
            return 0
        now = utc_now_iso()
        with self.db.transaction() as conn:
            conn.executemany(
                """
                UPDATE grid_cells
                SET elevation_m = ?,
                    min_elevation_m = ?,
                    max_elevation_m = ?,
                    mean_elevation_m = ?,
                    elevation_source = ?,
                    updated_at = ?
                WHERE id = ? AND neighbourhood_id = ?
                """,
                [
                    (c_el, min_el, max_el, mean_el, src, now, cid, neighbourhood_id)
                    for cid, c_el, min_el, max_el, mean_el, src in updates
                ],
            )
            conn.execute(
                "UPDATE neighbourhoods SET updated_at = ? WHERE id = ?",
                (now, neighbourhood_id),
            )
        return len(updates)

    def get_land_use_history(self, neighbourhood_id: int, limit: int = 100) -> list[tuple[str, LandUseHistoryEntry]]:
        """Return (cell_code, LandUseHistoryEntry) ordered newest first."""
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT h.*, g.row_number, g.column_number
                FROM land_use_history h
                JOIN grid_cells g ON g.id = h.grid_cell_id
                WHERE g.neighbourhood_id = ?
                ORDER BY h.updated_at DESC, h.id DESC
                LIMIT ?
                """,
                (neighbourhood_id, limit),
            ).fetchall()
            out: list[tuple[str, LandUseHistoryEntry]] = []
            for r in rows:
                code = f"R{r['row_number'] + 1}C{r['column_number'] + 1}"
                out.append(
                    (
                        code,
                        LandUseHistoryEntry(
                            id=r["id"],
                            grid_cell_id=r["grid_cell_id"],
                            previous_category=r["previous_category"],
                            new_category=r["new_category"],
                            source=r["source"],
                            updated_at=r["updated_at"],
                        ),
                    )
                )
            return out

    # -------------------------------------------------------------------------
    # OSM Features
    # -------------------------------------------------------------------------

    def replace_osm_features(self, neighbourhood_id: int, features: list[OSMFeature]) -> int:
        """Replace imported OSM features for a neighbourhood inside a single transaction."""
        now = utc_now_iso()
        validated_rows = self._prepare_osm_rows(neighbourhood_id, features, now)

        with self.db.transaction() as conn:
            conn.execute("DELETE FROM osm_features WHERE neighbourhood_id = ?", (neighbourhood_id,))
            conn.executemany(
                """
                INSERT INTO osm_features (
                    neighbourhood_id, osm_id, element_type, category,
                    subcategory, name, geometry_json, tags_json, source, imported_at,
                    length_m, road_category, building_category, user_notes, is_user_edited
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                validated_rows,
            )
            conn.execute(
                "UPDATE neighbourhoods SET updated_at = ? WHERE id = ?",
                (now, neighbourhood_id),
            )
        return len(validated_rows)

    def upsert_osm_features(self, neighbourhood_id: int, features: list[OSMFeature]) -> int:
        """Insert or update features (used for GeoJSON import without deleting existing OSM data)."""
        now = utc_now_iso()
        validated_rows = self._prepare_osm_rows(neighbourhood_id, features, now)
        with self.db.transaction() as conn:
            conn.executemany(
                """
                INSERT INTO osm_features (
                    neighbourhood_id, osm_id, element_type, category,
                    subcategory, name, geometry_json, tags_json, source, imported_at,
                    length_m, road_category, building_category, user_notes, is_user_edited
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(neighbourhood_id, element_type, osm_id) DO UPDATE SET
                    category = excluded.category,
                    subcategory = excluded.subcategory,
                    name = excluded.name,
                    geometry_json = excluded.geometry_json,
                    tags_json = excluded.tags_json,
                    source = excluded.source,
                    imported_at = excluded.imported_at,
                    length_m = excluded.length_m,
                    road_category = excluded.road_category,
                    building_category = excluded.building_category
                """,
                validated_rows,
            )
            conn.execute(
                "UPDATE neighbourhoods SET updated_at = ? WHERE id = ?",
                (now, neighbourhood_id),
            )
        return len(validated_rows)

    @staticmethod
    def _prepare_osm_rows(
        neighbourhood_id: int,
        features: list[OSMFeature],
        now: str,
    ) -> list[tuple]:
        validated_rows: list[tuple] = []
        seen_keys: set[tuple[str, int]] = set()
        for feat in features:
            key = (feat.element_type, feat.osm_id)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            validate_geojson_geometry(feat.geometry)
            validated_rows.append(
                (
                    neighbourhood_id,
                    feat.osm_id,
                    feat.element_type,
                    feat.category,
                    feat.subcategory,
                    feat.name,
                    json.dumps(feat.geometry, separators=(",", ":")),
                    json.dumps(feat.tags, separators=(",", ":")),
                    feat.source or "OpenStreetMap",
                    feat.imported_at or now,
                    float(feat.length_m or 0.0),
                    feat.road_category or "",
                    feat.building_category or "",
                    feat.user_notes or "",
                    1 if feat.is_user_edited else 0,
                )
            )
        return validated_rows

    def update_osm_feature_attributes(
        self,
        feature_id: int,
        name: str,
        road_category: str = "",
        building_category: str = "",
        user_notes: str = "",
    ) -> OSMFeature | None:
        """Allow offline editing of road/building/waterbody metadata."""
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE osm_features
                SET name = ?,
                    road_category = ?,
                    building_category = ?,
                    user_notes = ?,
                    is_user_edited = 1
                WHERE id = ?
                """,
                (name.strip(), road_category.strip(), building_category.strip(), user_notes.strip(), feature_id),
            )
            row = conn.execute("SELECT * FROM osm_features WHERE id = ?", (feature_id,)).fetchone()
            return self._row_to_osm_feature(row) if row else None

    def get_osm_features(self, neighbourhood_id: int) -> list[OSMFeature]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM osm_features WHERE neighbourhood_id = ? ORDER BY category, id",
                (neighbourhood_id,),
            ).fetchall()
            features: list[OSMFeature] = []
            for row in rows:
                feat = self._row_to_osm_feature(row)
                if feat is not None:
                    features.append(feat)
            return features

    def get_osm_feature_counts(self, neighbourhood_id: int) -> dict[str, int]:
        counts = {"road": 0, "building": 0, "waterway": 0, "green_area": 0, "other": 0}
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT category, COUNT(*) AS cnt
                FROM osm_features
                WHERE neighbourhood_id = ?
                GROUP BY category
                """,
                (neighbourhood_id,),
            ).fetchall()
            for r in rows:
                cat = r["category"]
                if cat in counts:
                    counts[cat] = int(r["cnt"])
                else:
                    counts["other"] += int(r["cnt"])
        return counts

    def get_last_osm_import_time(self, neighbourhood_id: int) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT MAX(imported_at) AS last_import FROM osm_features WHERE neighbourhood_id = ?",
                (neighbourhood_id,),
            ).fetchone()
            return row["last_import"] if row and row["last_import"] else None

    # -------------------------------------------------------------------------
    # Drainage Infrastructure CRUD
    # -------------------------------------------------------------------------

    def create_drainage_feature(self, feature: DrainageFeature) -> DrainageFeature:
        now = utc_now_iso()
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO drainage_features (
                    neighbourhood_id, grid_cell_id, name, feature_type,
                    latitude, longitude, capacity, capacity_unit,
                    status, source, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feature.neighbourhood_id,
                    feature.grid_cell_id,
                    feature.name.strip(),
                    feature.feature_type,
                    feature.latitude,
                    feature.longitude,
                    feature.capacity,
                    feature.capacity_unit,
                    feature.status,
                    feature.source or "user-entered",
                    feature.notes.strip(),
                    now,
                    now,
                ),
            )
            did = int(cur.lastrowid)
            conn.execute(
                "UPDATE neighbourhoods SET updated_at = ? WHERE id = ?",
                (now, feature.neighbourhood_id),
            )
        created = self.get_drainage_feature(did)
        assert created is not None
        return created

    def update_drainage_feature(self, feature: DrainageFeature) -> DrainageFeature:
        if feature.id is None:
            raise ValueError("Cannot update DrainageFeature without an ID.")
        now = utc_now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE drainage_features
                SET grid_cell_id = ?,
                    name = ?,
                    feature_type = ?,
                    latitude = ?,
                    longitude = ?,
                    capacity = ?,
                    capacity_unit = ?,
                    status = ?,
                    source = ?,
                    notes = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    feature.grid_cell_id,
                    feature.name.strip(),
                    feature.feature_type,
                    feature.latitude,
                    feature.longitude,
                    feature.capacity,
                    feature.capacity_unit,
                    feature.status,
                    feature.source or "user-entered",
                    feature.notes.strip(),
                    now,
                    feature.id,
                ),
            )
            conn.execute(
                "UPDATE neighbourhoods SET updated_at = ? WHERE id = ?",
                (now, feature.neighbourhood_id),
            )
        refreshed = self.get_drainage_feature(feature.id)
        assert refreshed is not None
        return refreshed

    def delete_drainage_feature(self, drainage_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM drainage_features WHERE id = ?", (drainage_id,))

    def get_drainage_feature(self, drainage_id: int) -> DrainageFeature | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM drainage_features WHERE id = ?",
                (drainage_id,),
            ).fetchone()
            return self._row_to_drainage(row) if row else None

    def list_drainage_features(self, neighbourhood_id: int) -> list[DrainageFeature]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM drainage_features WHERE neighbourhood_id = ? ORDER BY id DESC",
                (neighbourhood_id,),
            ).fetchall()
            return [self._row_to_drainage(r) for r in rows]

    # -------------------------------------------------------------------------
    # Feature-to-Grid Spatial Links
    # -------------------------------------------------------------------------

    def replace_grid_feature_links(
        self,
        neighbourhood_id: int,
        links: list[GridFeatureLink],
    ) -> int:
        now = utc_now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                DELETE FROM grid_feature_links
                WHERE grid_cell_id IN (
                    SELECT id FROM grid_cells WHERE neighbourhood_id = ?
                )
                """,
                (neighbourhood_id,),
            )
            conn.executemany(
                """
                INSERT INTO grid_feature_links (
                    grid_cell_id, osm_feature_id, drainage_feature_id, relationship_type, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        lk.grid_cell_id,
                        lk.osm_feature_id,
                        lk.drainage_feature_id,
                        lk.relationship_type,
                        now,
                    )
                    for lk in links
                ],
            )
        return len(links)

    def get_links_for_neighbourhood(self, neighbourhood_id: int) -> list[GridFeatureLink]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT l.*
                FROM grid_feature_links l
                JOIN grid_cells g ON g.id = l.grid_cell_id
                WHERE g.neighbourhood_id = ?
                """,
                (neighbourhood_id,),
            ).fetchall()
            return [
                GridFeatureLink(
                    id=r["id"],
                    grid_cell_id=r["grid_cell_id"],
                    osm_feature_id=r["osm_feature_id"],
                    drainage_feature_id=r["drainage_feature_id"],
                    relationship_type=r["relationship_type"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    def get_cells_for_osm_feature(self, osm_feature_id: int) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT g.row_number, g.column_number
                FROM grid_feature_links l
                JOIN grid_cells g ON g.id = l.grid_cell_id
                WHERE l.osm_feature_id = ?
                ORDER BY g.row_number, g.column_number
                """,
                (osm_feature_id,),
            ).fetchall()
            return [f"R{r['row_number'] + 1}C{r['column_number'] + 1}" for r in rows]

    # -------------------------------------------------------------------------
    # Elevation Sources
    # -------------------------------------------------------------------------

    def save_elevation_source(self, record: ElevationSourceRecord) -> ElevationSourceRecord:
        now = record.imported_at or utc_now_iso()
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO elevation_sources (
                    neighbourhood_id, source_name, file_name,
                    coordinate_reference_system, imported_at, source_description
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.neighbourhood_id,
                    record.source_name,
                    record.file_name,
                    record.coordinate_reference_system,
                    now,
                    record.source_description,
                ),
            )
            record.id = int(cur.lastrowid)
        return record

    def list_elevation_sources(self, neighbourhood_id: int) -> list[ElevationSourceRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM elevation_sources WHERE neighbourhood_id = ? ORDER BY imported_at DESC",
                (neighbourhood_id,),
            ).fetchall()
            return [
                ElevationSourceRecord(
                    id=r["id"],
                    neighbourhood_id=r["neighbourhood_id"],
                    source_name=r["source_name"],
                    file_name=r["file_name"],
                    coordinate_reference_system=r["coordinate_reference_system"],
                    imported_at=r["imported_at"],
                    source_description=r["source_description"],
                )
                for r in rows
            ]

    # -------------------------------------------------------------------------
    # Weather Observations
    # -------------------------------------------------------------------------

    def save_weather_observation(self, snapshot: WeatherSnapshot) -> WeatherSnapshot:
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO weather_observations (
                    neighbourhood_id, temperature, humidity, precipitation,
                    rainfall, weather_code, data_type, source,
                    observed_at, retrieved_at, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.neighbourhood_id,
                    snapshot.temperature_c,
                    snapshot.humidity_pct,
                    snapshot.precipitation_mm,
                    snapshot.rainfall_mm,
                    snapshot.weather_code,
                    snapshot.data_type,
                    snapshot.source,
                    snapshot.observed_at,
                    snapshot.retrieved_at,
                    snapshot.raw_json,
                ),
            )
            snapshot.id = int(cur.lastrowid)
        return snapshot

    def get_latest_weather_observation(self, neighbourhood_id: int) -> WeatherSnapshot | None:
        with self.db.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM weather_observations
                WHERE neighbourhood_id = ?
                ORDER BY retrieved_at DESC, id DESC
                LIMIT 1
                """,
                (neighbourhood_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_weather_snapshot(row)

    def list_weather_observations(self, neighbourhood_id: int, limit: int = 50) -> list[WeatherSnapshot]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM weather_observations
                WHERE neighbourhood_id = ?
                ORDER BY retrieved_at DESC, id DESC
                LIMIT ?
                """,
                (neighbourhood_id, max(1, int(limit))),
            ).fetchall()
            return [self._row_to_weather_snapshot(r) for r in rows]

    # -------------------------------------------------------------------------
    # Settings, Dashboard & Data Quality Summary
    # -------------------------------------------------------------------------

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = ?",
                (key,),
            ).fetchone()
            return row["setting_value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO app_settings (setting_key, setting_value)
                VALUES (?, ?)
                ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value
                """,
                (key, value),
            )

    def get_dashboard_summary(self, neighbourhood_id: int | None) -> DashboardSummary:
        if neighbourhood_id is None:
            return DashboardSummary(neighbourhood=None)
        neighbourhood = self.get_neighbourhood_by_id(neighbourhood_id)
        if neighbourhood is None:
            return DashboardSummary(neighbourhood=None)

        counts = self.get_osm_feature_counts(neighbourhood_id)
        cells = self.get_grid_cells(neighbourhood_id)
        configured = sum(1 for c in cells if c.is_configured)
        last_map = self.get_last_osm_import_time(neighbourhood_id)
        weather = self.get_latest_weather_observation(neighbourhood_id)

        return DashboardSummary(
            neighbourhood=neighbourhood,
            road_count=counts["road"],
            building_count=counts["building"],
            waterway_count=counts["waterway"],
            green_area_count=counts["green_area"],
            other_feature_count=counts["other"],
            total_grid_cells=len(cells),
            configured_grid_cells=configured,
            last_map_update=last_map,
            weather=weather,
        )

    def get_data_quality_summary(self, neighbourhood_id: int | None) -> DataQualitySummary:
        if neighbourhood_id is None:
            return DataQualitySummary()

        counts = self.get_osm_feature_counts(neighbourhood_id)
        cells = self.get_grid_cells(neighbourhood_id)
        osm_feats = self.get_osm_features(neighbourhood_id)
        drainage = self.list_drainage_features(neighbourhood_id)
        links = self.get_links_for_neighbourhood(neighbourhood_id)

        missing_elev = sum(1 for c in cells if c.elevation_m is None and c.mean_elevation_m is None)
        missing_lu = sum(1 for c in cells if c.land_use == "Unknown")
        missing_inf = sum(
            1 for c in cells if c.infiltration_source == "missing" and c.infiltration_rate <= 0.0
        )
        missing_dr = sum(
            1 for c in cells if c.drainage_source == "missing" and c.drainage_capacity <= 0.0
        )

        imported_elev = sum(
            1
            for c in cells
            if (c.elevation_m is not None or c.mean_elevation_m is not None)
            and (c.elevation_source or "").startswith("Imported Raster")
        )
        user_elev = sum(
            1
            for c in cells
            if (c.elevation_m is not None or c.mean_elevation_m is not None)
            and not (c.elevation_source or "").startswith("Imported Raster")
        )

        inferred_lu = sum(1 for c in cells if c.land_use_source == "inferred")
        user_lu = sum(1 for c in cells if c.land_use_source == "user-entered")

        user_edited_osm = sum(1 for f in osm_feats if f.is_user_edited)
        imported_osm = len(osm_feats) - user_edited_osm

        return DataQualitySummary(
            road_count=counts["road"],
            building_count=counts["building"],
            water_feature_count=counts["waterway"],
            green_area_count=counts["green_area"],
            drainage_count=len(drainage),
            total_grid_cells=len(cells),
            missing_elevation_cells=missing_elev,
            missing_land_use_cells=missing_lu,
            missing_infiltration_cells=missing_inf,
            missing_drainage_cells=missing_dr,
            imported_elevation_cells=imported_elev,
            user_elevation_cells=user_elev,
            imported_osm_count=imported_osm,
            user_edited_osm_count=user_edited_osm,
            inferred_land_use_cells=inferred_lu,
            user_land_use_cells=user_lu,
            user_drainage_count=len(drainage),
            grid_links_count=len(links),
        )

    # -------------------------------------------------------------------------
    # Phase 3: Simulation Runs, Step Results & Metrics
    # -------------------------------------------------------------------------

    def save_simulation_output(self, output: SimulationOutput) -> int:
        """Persist a simulation run, per-step cell results, and summary metrics in one transaction."""
        run = output.run
        summary = output.summary
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO simulation_runs (
                    neighbourhood_id, scenario_name, rainfall_intensity, rainfall_duration,
                    time_step, simulation_mode, distribution_pattern, initial_water_depth,
                    config_json, start_time, completion_time, status, model_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.neighbourhood_id,
                    run.scenario_name,
                    run.rainfall_intensity,
                    run.rainfall_duration,
                    run.time_step,
                    run.simulation_mode,
                    run.distribution_pattern,
                    run.initial_water_depth,
                    run.config_json,
                    run.start_time,
                    run.completion_time,
                    run.status,
                    run.model_version,
                ),
            )
            sim_id = int(cur.lastrowid)
            run.id = sim_id

            conn.executemany(
                """
                INSERT INTO simulation_results (
                    simulation_id, timestep, sim_time_minutes, cell_id,
                    water_depth, water_volume, rainfall_input,
                    infiltration_loss, drainage_loss, flow_transferred
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        sim_id,
                        cr.timestep,
                        cr.sim_time_minutes,
                        cr.cell_id,
                        cr.water_depth_m,
                        cr.water_volume_m3,
                        cr.rainfall_input_m3,
                        cr.infiltration_loss_m3,
                        cr.drainage_loss_m3,
                        cr.flow_transferred_m3,
                    )
                    for cr in output.cell_steps
                ],
            )

            metric_rows = [
                ("max_water_depth", summary.max_water_depth_m, "m"),
                ("avg_water_depth", summary.avg_water_depth_m, "m"),
                ("initial_water_volume", summary.initial_water_volume_m3, "m3"),
                ("total_rainfall_volume", summary.total_rainfall_volume_m3, "m3"),
                ("total_infiltration_volume", summary.total_infiltration_volume_m3, "m3"),
                ("total_drainage_volume", summary.total_drainage_volume_m3, "m3"),
                ("total_transferred_volume", summary.total_transferred_volume_m3, "m3"),
                ("final_surface_volume", summary.final_surface_volume_m3, "m3"),
                ("max_affected_cells", float(summary.max_affected_cells), "cells"),
                ("total_affected_area", summary.total_affected_area_m2, "m2"),
                ("time_of_max_depth", summary.time_of_max_depth_minutes, "min"),
                ("mass_balance_error", summary.mass_balance_error_m3, "m3"),
                ("mass_balance_tolerance", summary.mass_balance_tolerance_m3, "m3"),
                ("mass_balance_passed", 1.0 if summary.mass_balance_passed else 0.0, "bool"),
                ("used_illustrative_terrain", 1.0 if summary.used_illustrative_terrain else 0.0, "bool"),
                ("total_steps", float(summary.total_steps), "steps"),
            ]
            conn.executemany(
                """
                INSERT INTO simulation_metrics (simulation_id, metric_name, metric_value, unit)
                VALUES (?, ?, ?, ?)
                """,
                [(sim_id, name, float(val), unit) for name, val, unit in metric_rows],
            )
        return sim_id

    def list_simulation_runs(self, neighbourhood_id: int) -> list[SimulationRunRecord]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM simulation_runs
                WHERE neighbourhood_id = ?
                ORDER BY id DESC
                """,
                (neighbourhood_id,),
            ).fetchall()
            return [self._row_to_simulation_run(r) for r in rows]

    def get_simulation_run(self, simulation_id: int) -> SimulationRunRecord | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM simulation_runs WHERE id = ?",
                (simulation_id,),
            ).fetchone()
            return self._row_to_simulation_run(row) if row else None

    def delete_simulation_run(self, simulation_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM simulation_runs WHERE id = ?", (simulation_id,))

    def load_simulation_output(self, simulation_id: int) -> SimulationOutput | None:
        """Reconstruct a saved simulation output bundle from SQLite."""
        run = self.get_simulation_run(simulation_id)
        if run is None:
            return None

        try:
            cfg_dict = json.loads(run.config_json or "{}")
            config = SimulationConfig.from_dict(cfg_dict)
        except (json.JSONDecodeError, TypeError, ValueError):
            config = SimulationConfig(
                scenario_name=run.scenario_name,
                rainfall_intensity_mm_hr=run.rainfall_intensity,
                rainfall_duration_min=run.rainfall_duration,
                time_step_min=run.time_step,
                simulation_mode=run.simulation_mode,
                distribution_pattern=run.distribution_pattern,
                initial_water_depth_m=run.initial_water_depth,
                model_version=run.model_version,
            )

        cells = self.get_grid_cells(run.neighbourhood_id)
        cell_map = {c.id: c for c in cells if c.id is not None}

        with self.db.connect() as conn:
            metric_rows = conn.execute(
                "SELECT metric_name, metric_value FROM simulation_metrics WHERE simulation_id = ?",
                (simulation_id,),
            ).fetchall()
            metrics_map = {str(r["metric_name"]): float(r["metric_value"]) for r in metric_rows}

            res_rows = conn.execute(
                """
                SELECT * FROM simulation_results
                WHERE simulation_id = ?
                ORDER BY timestep ASC, cell_id ASC
                """,
                (simulation_id,),
            ).fetchall()

        cell_steps: list[SimulationCellStepRecord] = []
        steps_grouped: dict[int, list[sqlite3.Row]] = {}
        for r in res_rows:
            cid = int(r["cell_id"])
            c_obj = cell_map.get(cid)
            c_code = c_obj.cell_code if c_obj else f"C{cid}"
            ts = int(r["timestep"])
            steps_grouped.setdefault(ts, []).append(r)
            cell_steps.append(
                SimulationCellStepRecord(
                    timestep=ts,
                    sim_time_minutes=float(r["sim_time_minutes"]),
                    cell_id=cid,
                    cell_code=c_code,
                    water_depth_m=float(r["water_depth"]),
                    water_volume_m3=float(r["water_volume"]),
                    rainfall_input_m3=float(r["rainfall_input"]),
                    infiltration_loss_m3=float(r["infiltration_loss"]),
                    drainage_loss_m3=float(r["drainage_loss"]),
                    flow_transferred_m3=float(r["flow_transferred"]),
                )
            )

        from core.rainfall_model import generate_rainfall_schedule

        try:
            sched = generate_rainfall_schedule(
                config.rainfall_intensity_mm_hr,
                config.rainfall_duration_min,
                config.time_step_min,
                config.distribution_pattern,
                config.custom_intensities_mm_hr,
                config.rainfall_scale_factor,
            )
        except Exception:
            sched = [run.rainfall_intensity] * max(1, len(steps_grouped))

        init_vol = metrics_map.get("initial_water_volume", 0.0)
        cum_rain = 0.0
        cum_infil = 0.0
        cum_drain = 0.0
        steps: list[SimulationStepRecord] = []
        cell_totals_rain: dict[int, float] = {}
        cell_totals_infil: dict[int, float] = {}
        cell_totals_drain: dict[int, float] = {}
        cell_max_d: dict[int, float] = {}
        last_rows: dict[int, sqlite3.Row] = {}

        for ts in sorted(steps_grouped.keys()):
            group = steps_grouped[ts]
            s_rain = sum(float(r["rainfall_input"]) for r in group)
            s_infil = sum(float(r["infiltration_loss"]) for r in group)
            s_drain = sum(float(r["drainage_loss"]) for r in group)
            s_trans = sum(float(r["flow_transferred"]) for r in group)
            s_rem = sum(float(r["water_volume"]) for r in group)
            depths = [float(r["water_depth"]) for r in group]
            s_max_d = max(depths) if depths else 0.0
            s_avg_d = sum(depths) / len(depths) if depths else 0.0

            wet_rows = [r for r in group if float(r["water_depth"]) > config.wet_depth_threshold_m]
            wet_area = sum(
                cell_map[int(r["cell_id"])].approx_area_sq_m()
                for r in wet_rows
                if int(r["cell_id"]) in cell_map
            )
            cum_rain += s_rain
            cum_infil += s_infil
            cum_drain += s_drain
            err = abs((init_vol + cum_rain) - (s_rem + cum_infil + cum_drain))
            sim_t = float(group[0]["sim_time_minutes"]) if group else ts * run.time_step
            inten = sched[ts - 1] if 0 <= (ts - 1) < len(sched) else run.rainfall_intensity

            steps.append(
                SimulationStepRecord(
                    timestep=ts,
                    sim_time_minutes=sim_t,
                    rainfall_intensity_mm_hr=float(inten),
                    rainfall_input_m3=s_rain,
                    infiltration_loss_m3=s_infil,
                    drainage_loss_m3=s_drain,
                    water_transferred_m3=s_trans,
                    total_volume_remaining_m3=s_rem,
                    max_water_depth_m=s_max_d,
                    avg_water_depth_m=s_avg_d,
                    affected_cell_count=len(wet_rows),
                    total_area_affected_m2=wet_area,
                    mass_balance_error_m3=err,
                )
            )

            for r in group:
                cid = int(r["cell_id"])
                cell_totals_rain[cid] = cell_totals_rain.get(cid, 0.0) + float(r["rainfall_input"])
                cell_totals_infil[cid] = cell_totals_infil.get(cid, 0.0) + float(r["infiltration_loss"])
                cell_totals_drain[cid] = cell_totals_drain.get(cid, 0.0) + float(r["drainage_loss"])
                cell_max_d[cid] = max(cell_max_d.get(cid, 0.0), float(r["water_depth"]))
                last_rows[cid] = r

        from core.infiltration_model import resolve_cell_infiltration_rates
        from core.water_flow_model import resolve_cell_elevations

        try:
            elevs, elev_prov, used_ill_elev, _ = resolve_cell_elevations(cells, config)
        except Exception:
            elevs = [0.0] * len(cells)
            elev_prov = ["unavailable"] * len(cells)
            used_ill_elev = metrics_map.get("used_illustrative_terrain", 0.0) >= 0.5

        infil_rates, infil_prov = resolve_cell_infiltration_rates(cells, config)
        final_cells: list[SimulationCellFinalState] = []
        for idx, c in enumerate(cells):
            if c.id is None:
                continue
            lr = last_rows.get(c.id)
            final_cells.append(
                SimulationCellFinalState(
                    cell_id=c.id,
                    cell_code=c.cell_code,
                    row_number=c.row_number,
                    column_number=c.column_number,
                    land_use=c.land_use,
                    area_m2=c.approx_area_sq_m(),
                    elevation_m=float(elevs[idx]),
                    elevation_provenance=elev_prov[idx],
                    infiltration_rate_mm_hr=float(infil_rates[idx]),
                    infiltration_provenance=infil_prov[idx],
                    drainage_discharge_m3_s=0.0,
                    final_water_depth_m=float(lr["water_depth"]) if lr is not None else 0.0,
                    max_water_depth_m=cell_max_d.get(c.id, 0.0),
                    final_water_volume_m3=float(lr["water_volume"]) if lr is not None else 0.0,
                    total_rainfall_m3=cell_totals_rain.get(c.id, 0.0),
                    total_infiltration_m3=cell_totals_infil.get(c.id, 0.0),
                    total_drainage_m3=cell_totals_drain.get(c.id, 0.0),
                )
            )

        summary = SimulationSummary(
            max_water_depth_m=metrics_map.get("max_water_depth", 0.0),
            avg_water_depth_m=metrics_map.get("avg_water_depth", 0.0),
            initial_water_volume_m3=metrics_map.get("initial_water_volume", 0.0),
            total_rainfall_volume_m3=metrics_map.get("total_rainfall_volume", 0.0),
            total_infiltration_volume_m3=metrics_map.get("total_infiltration_volume", 0.0),
            total_drainage_volume_m3=metrics_map.get("total_drainage_volume", 0.0),
            total_transferred_volume_m3=metrics_map.get("total_transferred_volume", 0.0),
            final_surface_volume_m3=metrics_map.get("final_surface_volume", 0.0),
            max_affected_cells=int(metrics_map.get("max_affected_cells", 0.0)),
            total_affected_area_m2=metrics_map.get("total_affected_area", 0.0),
            time_of_max_depth_minutes=metrics_map.get("time_of_max_depth", 0.0),
            mass_balance_error_m3=metrics_map.get("mass_balance_error", 0.0),
            mass_balance_tolerance_m3=metrics_map.get("mass_balance_tolerance", config.mass_balance_tolerance_m3),
            mass_balance_passed=metrics_map.get("mass_balance_passed", 1.0) >= 0.5,
            used_illustrative_terrain=used_ill_elev,
            total_steps=int(metrics_map.get("total_steps", float(len(steps)))),
        )

        warnings: list[str] = ["Loaded from saved SQLite simulation run."]
        if summary.used_illustrative_terrain:
            warnings.append("Run used Illustrative Assumed Terrain (non-verified).")

        return SimulationOutput(
            run=run,
            config=config,
            summary=summary,
            steps=steps,
            cell_steps=cell_steps,
            final_cells=final_cells,
            drainage_profiles=[],
            warnings=warnings,
        )

    @staticmethod
    def _row_to_simulation_run(row: sqlite3.Row) -> SimulationRunRecord:
        return SimulationRunRecord(
            id=int(row["id"]),
            neighbourhood_id=int(row["neighbourhood_id"]),
            scenario_name=str(row["scenario_name"]),
            rainfall_intensity=float(row["rainfall_intensity"]),
            rainfall_duration=float(row["rainfall_duration"]),
            time_step=float(row["time_step"]),
            simulation_mode=str(row["simulation_mode"]),
            distribution_pattern=str(row["distribution_pattern"]),
            initial_water_depth=float(row["initial_water_depth"]),
            config_json=str(row["config_json"]),
            start_time=str(row["start_time"]),
            completion_time=str(row["completion_time"]),
            status=str(row["status"]),
            model_version=str(row["model_version"]),
        )

    # -------------------------------------------------------------------------
    # Row Mappers
    # -------------------------------------------------------------------------

    @staticmethod
    def _row_to_neighbourhood(row: sqlite3.Row) -> Neighbourhood:
        return Neighbourhood(
            id=row["id"],
            name=row["name"],
            district=row["district"],
            state=row["state"],
            country=row["country"],
            center_latitude=row["center_latitude"],
            center_longitude=row["center_longitude"],
            min_latitude=row["min_latitude"],
            max_latitude=row["max_latitude"],
            min_longitude=row["min_longitude"],
            max_longitude=row["max_longitude"],
            grid_rows=row["grid_rows"],
            grid_cols=row["grid_cols"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_grid_cell(row: sqlite3.Row) -> GridCell:
        keys = row.keys()
        return GridCell(
            id=row["id"],
            neighbourhood_id=row["neighbourhood_id"],
            row_number=row["row_number"],
            column_number=row["column_number"],
            min_latitude=row["min_latitude"],
            max_latitude=row["max_latitude"],
            min_longitude=row["min_longitude"],
            max_longitude=row["max_longitude"],
            elevation_m=row["elevation_m"],
            elevation_source=row["elevation_source"],
            min_elevation_m=row["min_elevation_m"] if "min_elevation_m" in keys else None,
            max_elevation_m=row["max_elevation_m"] if "max_elevation_m" in keys else None,
            mean_elevation_m=row["mean_elevation_m"] if "mean_elevation_m" in keys else None,
            land_use=row["land_use"],
            land_use_source=row["land_use_source"] if "land_use_source" in keys else "missing",
            infiltration_rate=row["infiltration_rate"],
            infiltration_source=row["infiltration_source"] if "infiltration_source" in keys else "missing",
            drainage_capacity=row["drainage_capacity"],
            drainage_source=row["drainage_source"] if "drainage_source" in keys else "missing",
            approx_width_m=row["approx_width_m"] if "approx_width_m" in keys else None,
            approx_height_m=row["approx_height_m"] if "approx_height_m" in keys else None,
            approx_area_m2=row["approx_area_m2"] if "approx_area_m2" in keys else None,
            notes=row["notes"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_osm_feature(row: sqlite3.Row) -> OSMFeature | None:
        try:
            geometry = json.loads(row["geometry_json"])
            tags = json.loads(row["tags_json"] or "{}")
        except json.JSONDecodeError:
            logger.warning("Skipping corrupt geometry JSON in osm_features id=%s", row["id"])
            return None
        keys = row.keys()
        return OSMFeature(
            id=row["id"],
            neighbourhood_id=row["neighbourhood_id"],
            osm_id=row["osm_id"],
            element_type=row["element_type"],
            category=row["category"],
            subcategory=row["subcategory"],
            name=row["name"],
            geometry=geometry,
            tags=tags,
            source=row["source"],
            imported_at=row["imported_at"],
            length_m=float(row["length_m"] or 0.0) if "length_m" in keys else 0.0,
            road_category=row["road_category"] if "road_category" in keys else "",
            building_category=row["building_category"] if "building_category" in keys else "",
            user_notes=row["user_notes"] if "user_notes" in keys else "",
            is_user_edited=bool(row["is_user_edited"]) if "is_user_edited" in keys else False,
        )

    @staticmethod
    def _row_to_drainage(row: sqlite3.Row) -> DrainageFeature:
        return DrainageFeature(
            id=row["id"],
            neighbourhood_id=row["neighbourhood_id"],
            grid_cell_id=row["grid_cell_id"],
            name=row["name"],
            feature_type=row["feature_type"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            capacity=row["capacity"],
            capacity_unit=row["capacity_unit"],
            status=row["status"],
            source=row["source"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_weather_snapshot(row: sqlite3.Row) -> WeatherSnapshot:
        from services.weather_service import decode_wmo_weather_code, extract_hourly_from_raw

        raw_json = row["raw_json"] or "{}"
        hourly: list[HourlyForecastPoint] = []
        try:
            parsed = json.loads(raw_json)
            hourly = extract_hourly_from_raw(parsed)
        except json.JSONDecodeError:
            pass

        wcode = row["weather_code"]
        return WeatherSnapshot(
            id=row["id"],
            neighbourhood_id=row["neighbourhood_id"],
            temperature_c=row["temperature"],
            humidity_pct=row["humidity"],
            precipitation_mm=row["precipitation"],
            rainfall_mm=row["rainfall"],
            weather_code=wcode,
            weather_description=decode_wmo_weather_code(wcode),
            data_type=row["data_type"],
            source=row["source"],
            observed_at=row["observed_at"] or "",
            retrieved_at=row["retrieved_at"],
            hourly_forecast=hourly,
            raw_json=raw_json,
        )

    # -------------------------------------------------------------------------
    # Phase 5: SafeRoute Road Network, Conditions & Route History
    # -------------------------------------------------------------------------

    def sync_road_network(self, network: RoadNetworkGraph) -> None:
        """Persist or reuse SQLite node/edge IDs for a neighbourhood's road network."""
        nid = network.neighbourhood_id
        if nid <= 0 or network.node_count == 0:
            return

        with self.db.connect() as conn:
            existing_edges = conn.execute(
                "SELECT id, edge_key, start_node_id, end_node_id FROM road_network_edges WHERE neighbourhood_id = ? ORDER BY id",
                (nid,),
            ).fetchall()
            existing_nodes = conn.execute(
                "SELECT id, latitude, longitude FROM road_network_nodes WHERE neighbourhood_id = ? ORDER BY id",
                (nid,),
            ).fetchall()

        current_keys = [e.edge_key for e in network.edges_by_id.values()]
        existing_keys = [str(r["edge_key"]) for r in existing_edges]

        if (
            existing_edges
            and len(existing_edges) == len(current_keys)
            and set(existing_keys) == set(current_keys)
            and len(existing_nodes) == network.node_count
        ):
            # Existing persisted graph matches current OSM topology — map memory IDs to DB IDs cleanly
            db_node_by_coord = {
                (round(float(r["latitude"]), 6), round(float(r["longitude"]), 6)): int(r["id"])
                for r in existing_nodes
            }
            node_id_map: dict[int, int] = {}
            for mem_nid, node in network.nodes_by_id.items():
                key = (round(node.latitude, 6), round(node.longitude, 6))
                if key in db_node_by_coord:
                    node_id_map[mem_nid] = db_node_by_coord[key]
            edge_id_map = {str(r["edge_key"]): int(r["id"]) for r in existing_edges}
            if len(node_id_map) == network.node_count:
                network.reindex_with_db_ids(node_id_map, edge_id_map)
                return

        # Rebuild persisted road_network_nodes & road_network_edges atomically
        node_id_map = {}
        edge_id_map = {}
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM road_conditions WHERE neighbourhood_id = ?", (nid,))
            conn.execute("DELETE FROM road_network_edges WHERE neighbourhood_id = ?", (nid,))
            conn.execute("DELETE FROM road_network_nodes WHERE neighbourhood_id = ?", (nid,))

            for mem_nid, node in sorted(network.nodes_by_id.items()):
                cur = conn.execute(
                    """
                    INSERT INTO road_network_nodes (
                        neighbourhood_id, osm_id, latitude, longitude, label, source
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (nid, node.osm_id, node.latitude, node.longitude, node.label, node.source),
                )
                node_id_map[mem_nid] = int(cur.lastrowid)

            for _, edge in sorted(network.edges_by_id.items()):
                s_id = node_id_map[edge.start_node_id]
                e_id = node_id_map[edge.end_node_id]
                cur = conn.execute(
                    """
                    INSERT INTO road_network_edges (
                        neighbourhood_id, osm_feature_id, edge_key, start_node_id, end_node_id,
                        road_name, road_type, distance_m, geometry, grid_cell_ids_json, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        nid,
                        edge.osm_feature_id,
                        edge.edge_key,
                        s_id,
                        e_id,
                        edge.road_name,
                        edge.road_type,
                        float(edge.distance_m),
                        json.dumps(edge.geometry, separators=(",", ":")),
                        json.dumps(edge.grid_cell_ids, separators=(",", ":")),
                        edge.source,
                    ),
                )
                edge_id_map[edge.edge_key] = int(cur.lastrowid)

        network.reindex_with_db_ids(node_id_map, edge_id_map)

    def get_road_conditions(self, neighbourhood_id: int) -> dict[int, RoadConditionRecord]:
        from routing.route_planner import RoadConditionRecord

        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM road_conditions WHERE neighbourhood_id = ?",
                (neighbourhood_id,),
            ).fetchall()
            out: dict[int, RoadConditionRecord] = {}
            for r in rows:
                eid = int(r["road_edge_id"])
                out[eid] = RoadConditionRecord(
                    road_edge_id=eid,
                    status=str(r["status"]),
                    exposure_category=str(r["exposure_category"]),
                    maximum_water_depth=r["maximum_water_depth"],
                    simulation_id=r["simulation_id"],
                    time_step=r["time_step"],
                    status_source=str(r["status_source"]),
                    notes=str(r["notes"]),
                    updated_at=str(r["updated_at"]),
                )
            return out

    def upsert_road_condition(
        self,
        neighbourhood_id: int,
        road_edge_id: int,
        status: str,
        exposure_category: str = "Unknown",
        maximum_water_depth: float | None = None,
        simulation_id: int | None = None,
        time_step: int | None = None,
        status_source: str = "user-entered",
        notes: str = "",
    ) -> None:
        now = utc_now_iso()
        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO road_conditions (
                    neighbourhood_id, road_edge_id, status, exposure_category,
                    maximum_water_depth, simulation_id, time_step, status_source, notes, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(road_edge_id) DO UPDATE SET
                    status = excluded.status,
                    exposure_category = excluded.exposure_category,
                    maximum_water_depth = excluded.maximum_water_depth,
                    simulation_id = excluded.simulation_id,
                    time_step = excluded.time_step,
                    status_source = excluded.status_source,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (
                    neighbourhood_id,
                    road_edge_id,
                    status,
                    exposure_category,
                    maximum_water_depth,
                    simulation_id,
                    time_step,
                    status_source,
                    notes.strip(),
                    now,
                ),
            )

    def sync_simulation_road_conditions(
        self,
        neighbourhood_id: int,
        exposures: dict[int, RoadFloodExposure],
        existing_conditions: dict[int, RoadConditionRecord],
    ) -> dict[int, RoadConditionRecord]:
        """Update simulated exposure snapshots in SQLite while preserving user-entered closures."""
        from routing.route_planner import RoadConditionRecord

        now = utc_now_iso()
        rows_to_upsert: list[tuple[Any, ...]] = []
        merged: dict[int, RoadConditionRecord] = {}

        for edge_id, exp in exposures.items():
            prev = existing_conditions.get(edge_id)
            if prev is not None and prev.status_source == "user-entered" and prev.status != "Normal":
                status = prev.status
                src = "user-entered"
                notes = prev.notes
            else:
                status = "Normal"
                src = exp.status_source
                notes = prev.notes if prev else ""

            rows_to_upsert.append(
                (
                    neighbourhood_id,
                    edge_id,
                    status,
                    exp.exposure_category,
                    exp.max_depth_m,
                    exp.simulation_id,
                    exp.timestep,
                    src,
                    notes,
                    now,
                )
            )
            merged[edge_id] = RoadConditionRecord(
                road_edge_id=edge_id,
                status=status,
                exposure_category=exp.exposure_category,
                maximum_water_depth=exp.max_depth_m,
                simulation_id=exp.simulation_id,
                time_step=exp.timestep,
                status_source=src,
                notes=notes,
                updated_at=now,
            )

        if rows_to_upsert:
            with self.db.transaction() as conn:
                conn.executemany(
                    """
                    INSERT INTO road_conditions (
                        neighbourhood_id, road_edge_id, status, exposure_category,
                        maximum_water_depth, simulation_id, time_step, status_source, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(road_edge_id) DO UPDATE SET
                        status = excluded.status,
                        exposure_category = excluded.exposure_category,
                        maximum_water_depth = excluded.maximum_water_depth,
                        simulation_id = excluded.simulation_id,
                        time_step = excluded.time_step,
                        status_source = excluded.status_source,
                        updated_at = excluded.updated_at
                    """,
                    rows_to_upsert,
                )
        return merged

    def save_route_history(
        self,
        neighbourhood_id: int,
        route: RouteMetrics,
        simulation_id: int | None = None,
        time_step: int | None = None,
    ) -> int:
        now = utc_now_iso()
        with self.db.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO route_history (
                    neighbourhood_id, origin, destination, origin_node_id, dest_node_id,
                    travel_mode, route_type, total_distance, estimated_time,
                    simulation_id, time_step, summary_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    neighbourhood_id,
                    route.origin_label,
                    route.destination_label,
                    route.origin_node_id,
                    route.dest_node_id,
                    route.travel_mode,
                    route.route_type,
                    float(route.total_distance_m),
                    float(route.estimated_time_minutes),
                    simulation_id,
                    time_step,
                    json.dumps(route.to_summary_dict(), separators=(",", ":")),
                    now,
                ),
            )
            return int(cur.lastrowid)

    def list_route_history(self, neighbourhood_id: int, limit: int = 80) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM route_history
                WHERE neighbourhood_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (neighbourhood_id, limit),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                summary: dict[str, Any] = {}
                try:
                    summary = json.loads(r["summary_json"] or "{}")
                except json.JSONDecodeError:
                    pass
                out.append(
                    {
                        "id": int(r["id"]),
                        "neighbourhood_id": int(r["neighbourhood_id"]),
                        "origin": str(r["origin"]),
                        "destination": str(r["destination"]),
                        "origin_node_id": r["origin_node_id"],
                        "dest_node_id": r["dest_node_id"],
                        "travel_mode": str(r["travel_mode"]),
                        "route_type": str(r["route_type"]),
                        "total_distance_m": float(r["total_distance"]),
                        "estimated_time_min": float(r["estimated_time"]),
                        "simulation_id": r["simulation_id"],
                        "time_step": r["time_step"],
                        "summary": summary,
                        "created_at": str(r["created_at"]),
                    }
                )
            return out

    def delete_route_history(self, route_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM route_history WHERE id = ?", (route_id,))
