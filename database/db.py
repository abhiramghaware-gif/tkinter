"""SQLite database initialization, non-destructive migrations, and transactions."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from config import DB_PATH, SCHEMA_PATH, SCHEMA_VERSION
from core.models import approximate_cell_metrics_m

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class DatabaseManager:
    """Manages SQLite database lifecycle, foreign keys, migrations, and transactions."""

    def __init__(self, db_path: Path | str = DB_PATH, schema_path: Path | str = SCHEMA_PATH) -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path(schema_path)

    def initialize(self) -> None:
        """Ensure parent directory exists, create database if missing, and apply safe migrations."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        schema_sql = self.schema_path.read_text(encoding="utf-8")

        with self.connect() as conn:
            # First detect whether this is an existing v1 DB before running v2 indexes
            current_version = self._get_user_version(conn)
            has_grid_cells = self._table_exists(conn, "grid_cells")

            if has_grid_cells and current_version < 2:
                self._migrate_v1_to_v2(conn)
            if has_grid_cells and current_version < 3:
                self._migrate_v2_to_v3(conn)
            if has_grid_cells and current_version < 4:
                self._migrate_v3_to_v4(conn)
            if has_grid_cells and current_version < 5:
                self._migrate_v4_to_v5(conn)

            conn.executescript(schema_sql)

            # Re-check in case DB was freshly created at version 0
            current_version = self._get_user_version(conn)
            if current_version < 1:
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (1, utc_now_iso()),
                )
            if current_version < SCHEMA_VERSION:
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, utc_now_iso()),
                )
                conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
            conn.commit()
        logger.info("Database initialized at %s (schema v%d)", self.db_path, SCHEMA_VERSION)

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        """Safely extend Phase 1 tables in-place without dropping or deleting user data."""
        logger.info("Running non-destructive database migration from v1 to v2...")
        grid_cols = self._get_columns(conn, "grid_cells")
        grid_additions = [
            ("center_latitude", "REAL"),
            ("center_longitude", "REAL"),
            ("approx_width_m", "REAL"),
            ("approx_height_m", "REAL"),
            ("approx_area_m2", "REAL"),
            ("min_elevation_m", "REAL"),
            ("max_elevation_m", "REAL"),
            ("mean_elevation_m", "REAL"),
            ("land_use_source", "TEXT NOT NULL DEFAULT 'missing'"),
            ("infiltration_source", "TEXT NOT NULL DEFAULT 'missing'"),
            ("drainage_source", "TEXT NOT NULL DEFAULT 'missing'"),
        ]
        for col_name, col_def in grid_additions:
            if col_name not in grid_cols:
                conn.execute(f"ALTER TABLE grid_cells ADD COLUMN {col_name} {col_def}")

        osm_cols = self._get_columns(conn, "osm_features")
        osm_additions = [
            ("length_m", "REAL NOT NULL DEFAULT 0.0"),
            ("road_category", "TEXT NOT NULL DEFAULT ''"),
            ("building_category", "TEXT NOT NULL DEFAULT ''"),
            ("user_notes", "TEXT NOT NULL DEFAULT ''"),
            ("is_user_edited", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for col_name, col_def in osm_additions:
            if col_name not in osm_cols:
                conn.execute(f"ALTER TABLE osm_features ADD COLUMN {col_name} {col_def}")

        # Backfill derived geographic metrics and provenance for preserved Phase 1 cells
        rows = conn.execute(
            """
            SELECT id, min_latitude, max_latitude, min_longitude, max_longitude,
                   land_use, infiltration_rate, drainage_capacity
            FROM grid_cells
            """
        ).fetchall()
        for row in rows:
            w_m, h_m, area_m2 = approximate_cell_metrics_m(
                row["min_latitude"],
                row["max_latitude"],
                row["min_longitude"],
                row["max_longitude"],
            )
            c_lat = (row["min_latitude"] + row["max_latitude"]) / 2.0
            c_lon = (row["min_longitude"] + row["max_longitude"]) / 2.0
            lu_src = "user-entered" if row["land_use"] and row["land_use"] != "Unknown" else "missing"
            inf_src = "user-entered" if (row["infiltration_rate"] or 0.0) > 0.0 else "missing"
            dr_src = "user-entered" if (row["drainage_capacity"] or 0.0) > 0.0 else "missing"
            conn.execute(
                """
                UPDATE grid_cells
                SET center_latitude = COALESCE(center_latitude, ?),
                    center_longitude = COALESCE(center_longitude, ?),
                    approx_width_m = COALESCE(approx_width_m, ?),
                    approx_height_m = COALESCE(approx_height_m, ?),
                    approx_area_m2 = COALESCE(approx_area_m2, ?),
                    land_use_source = CASE WHEN land_use_source = 'missing' THEN ? ELSE land_use_source END,
                    infiltration_source = CASE WHEN infiltration_source = 'missing' THEN ? ELSE infiltration_source END,
                    drainage_source = CASE WHEN drainage_source = 'missing' THEN ? ELSE drainage_source END
                WHERE id = ?
                """,
                (c_lat, c_lon, w_m, h_m, area_m2, lu_src, inf_src, dr_src, row["id"]),
            )
        conn.commit()
        logger.info("Migration v1 -> v2 completed (%d grid cell(s) preserved).", len(rows))

    def _migrate_v2_to_v3(self, conn: sqlite3.Connection) -> None:
        """Non-destructive migration to v3 ensuring simulation tables preserve Phase 1/2 records."""
        logger.info("Running non-destructive database migration to v3 (simulation tables)...")
        if self._table_exists(conn, "simulation_runs"):
            run_cols = self._get_columns(conn, "simulation_runs")
            if "distribution_pattern" not in run_cols:
                conn.execute(
                    "ALTER TABLE simulation_runs ADD COLUMN distribution_pattern TEXT NOT NULL DEFAULT 'constant'"
                )
            if "initial_water_depth" not in run_cols:
                conn.execute(
                    "ALTER TABLE simulation_runs ADD COLUMN initial_water_depth REAL NOT NULL DEFAULT 0.0"
                )
            if "config_json" not in run_cols:
                conn.execute(
                    "ALTER TABLE simulation_runs ADD COLUMN config_json TEXT NOT NULL DEFAULT '{}'"
                )
        conn.commit()
        logger.info("Migration to v3 completed cleanly.")

    def _migrate_v3_to_v4(self, conn: sqlite3.Connection) -> None:
        """Non-destructive migration to v4 adding SafeRoute road network and history tables."""
        logger.info("Running non-destructive database migration to v4 (SafeRoute tables)...")
        conn.commit()
        logger.info("Migration to v4 prepared (schema script will ensure new tables).")

    def _migrate_v4_to_v5(self, conn: sqlite3.Connection) -> None:
        """Non-destructive migration to v5 adding Phase 6 emergency management tables."""
        logger.info("Running non-destructive database migration to v5 (Emergency Management tables)...")
        conn.commit()
        logger.info("Migration to v5 prepared (schema script will ensure new tables).")

    def connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with foreign keys and Row factory enabled."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection wrapped in an explicit transaction (commit or rollback)."""
        conn = self.connect()
        try:
            conn.execute("BEGIN;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def verify_integrity(self) -> tuple[bool, str]:
        """Check database connectivity, foreign keys, and schema version."""
        try:
            if not self.db_path.exists():
                self.initialize()
            with self.connect() as conn:
                fk_row = conn.execute("PRAGMA foreign_keys;").fetchone()
                fk_enabled = bool(fk_row[0]) if fk_row else False
                version = self._get_user_version(conn)
                return True, f"SQLite OK (v{version}, FK={'ON' if fk_enabled else 'OFF'})"
        except sqlite3.Error as exc:
            logger.exception("Database integrity check failed")
            return False, f"Database Error: {exc}"

    @staticmethod
    def _get_user_version(conn: sqlite3.Connection) -> int:
        row = conn.execute("PRAGMA user_version;").fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _get_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(r["name"]) for r in rows}
