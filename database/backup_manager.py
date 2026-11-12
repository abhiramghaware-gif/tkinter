"""SQLite database verification, audit, online backup, validation, and safe restore."""

from __future__ import annotations

import gc
import hashlib
import json
import logging
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import BACKUPS_DIR, SCHEMA_VERSION
from database.db import DatabaseManager

logger = logging.getLogger(__name__)

CORE_REQUIRED_TABLES = (
    "neighbourhoods",
    "grid_cells",
    "osm_features",
    "simulation_runs",
    "app_settings",
)

ALL_EXPECTED_TABLES = (
    "schema_migrations",
    "neighbourhoods",
    "grid_cells",
    "osm_features",
    "drainage_features",
    "grid_feature_links",
    "elevation_sources",
    "land_use_history",
    "weather_observations",
    "app_settings",
    "simulation_runs",
    "simulation_results",
    "simulation_metrics",
    "road_network_nodes",
    "road_network_edges",
    "road_conditions",
    "route_history",
    "shelters",
    "rescue_teams",
    "vehicles",
    "emergency_operations",
    "volunteers",
    "inventory_items",
    "inventory_transactions",
    "resource_allocations",
    "emergency_alerts",
)


@dataclass(slots=True)
class DatabaseAuditReport:
    """Structured SQLite integrity, foreign-key, duplicate, and index audit."""

    db_path: str
    schema_version: int
    foreign_keys_enabled: bool
    integrity_ok: bool
    integrity_messages: list[str]
    foreign_key_violations: list[str]
    duplicate_issues: list[str]
    missing_value_issues: list[str]
    missing_tables: list[str]
    index_count: int
    table_row_counts: dict[str, int]
    checked_at_utc: str
    overall_ok: bool


@dataclass(slots=True)
class BackupValidationResult:
    """Validation summary for a candidate SQLite backup file."""

    backup_path: str
    is_valid: bool
    message: str
    schema_version: int = 0
    file_size_bytes: int = 0
    sha256: str = ""
    table_counts: dict[str, int] = field(default_factory=dict)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class DatabaseBackupManager:
    """Provides SQLite structural audits, online backups, backup validation, and safe restores."""

    def __init__(self, db_manager: DatabaseManager, backup_dir: Path | str = BACKUPS_DIR) -> None:
        self.db = db_manager
        self.backup_dir = Path(backup_dir)

    def audit_database(self) -> DatabaseAuditReport:
        """Run a thorough integrity, foreign-key, duplicate, missing-value, and index audit."""
        now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with closing(self.db.connect()) as conn:
            fk_row = conn.execute("PRAGMA foreign_keys;").fetchone()
            fk_enabled = bool(fk_row[0]) if fk_row else False
            version = int(conn.execute("PRAGMA user_version;").fetchone()[0])

            ic_rows = conn.execute("PRAGMA integrity_check;").fetchall()
            ic_msgs = [str(r[0]) for r in ic_rows]
            integrity_ok = ic_msgs == ["ok"]

            fk_rows = conn.execute("PRAGMA foreign_key_check;").fetchall()
            fk_violations = [
                f"table={r['table']}, rowid={r['rowid']}, parent={r['parent']}, fkid={r['fkid']}"
                for r in fk_rows
            ]

            existing_tables = {
                str(r["name"])
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            missing_tables = [t for t in ALL_EXPECTED_TABLES if t not in existing_tables]

            index_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
                ).fetchone()[0]
            )

            table_counts: dict[str, int] = {}
            for t in ALL_EXPECTED_TABLES:
                if t in existing_tables:
                    table_counts[t] = int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])

            dup_issues: list[str] = []
            dup_cells = conn.execute(
                """
                SELECT neighbourhood_id, row_number, column_number, COUNT(*) AS cnt
                FROM grid_cells
                GROUP BY neighbourhood_id, row_number, column_number
                HAVING cnt > 1
                """
            ).fetchall()
            for r in dup_cells:
                dup_issues.append(
                    f"Duplicate grid cell ({r['row_number']}, {r['column_number']}) in neighbourhood {r['neighbourhood_id']}"
                )

            if "shelters" in existing_tables:
                bad_caps = conn.execute(
                    "SELECT id, name, occupied_capacity, total_capacity FROM shelters "
                    "WHERE occupied_capacity < 0 OR total_capacity < 0 OR occupied_capacity > total_capacity"
                ).fetchall()
                for r in bad_caps:
                    dup_issues.append(
                        f"Invalid shelter capacity #{r['id']} ({r['name']}): {r['occupied_capacity']}/{r['total_capacity']}"
                    )

            if "inventory_items" in existing_tables:
                neg_inv = conn.execute(
                    "SELECT id, item_name, quantity FROM inventory_items WHERE quantity < 0"
                ).fetchall()
                for r in neg_inv:
                    dup_issues.append(f"Negative inventory quantity #{r['id']} ({r['item_name']}): {r['quantity']}")

            missing_vals: list[str] = []
            bad_nb = conn.execute(
                "SELECT id FROM neighbourhoods WHERE TRIM(COALESCE(name, '')) = ''"
            ).fetchall()
            if bad_nb:
                missing_vals.append(f"{len(bad_nb)} neighbourhood row(s) missing required name")

            overall_ok = (
                integrity_ok
                and not fk_violations
                and not dup_issues
                and not missing_vals
                and not missing_tables
                and fk_enabled
                and version == SCHEMA_VERSION
            )

            return DatabaseAuditReport(
                db_path=str(self.db.db_path),
                schema_version=version,
                foreign_keys_enabled=fk_enabled,
                integrity_ok=integrity_ok,
                integrity_messages=ic_msgs,
                foreign_key_violations=fk_violations,
                duplicate_issues=dup_issues,
                missing_value_issues=missing_vals,
                missing_tables=missing_tables,
                index_count=index_count,
                table_row_counts=table_counts,
                checked_at_utc=now_utc,
                overall_ok=overall_ok,
            )

    def create_backup(
        self,
        destination_path: Path | str | None = None,
        label: str = "manual",
    ) -> tuple[Path, BackupValidationResult]:
        """Create a consistent online SQLite backup + SHA-256 metadata sidecar."""
        if not self.db.db_path.exists():
            self.db.initialize()

        if destination_path is None:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safe_lbl = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in label).strip("_") or "backup"
            dest = self.backup_dir / f"floodguard_{safe_lbl}_{ts}.db"
        else:
            dest = Path(destination_path)
            dest.parent.mkdir(parents=True, exist_ok=True)

        # Avoid same-path overwrite
        if dest.resolve() == self.db.db_path.resolve():
            raise ValueError("Backup destination cannot be the active database path.")

        with closing(self.db.connect()) as src_conn:
            with closing(sqlite3.connect(str(dest))) as dst_conn:
                src_conn.backup(dst_conn)

        val = self.validate_backup(dest)
        if not val.is_valid:
            raise RuntimeError(f"Backup validation failed immediately after creation: {val.message}")

        meta_path = dest.with_suffix(dest.suffix + ".meta.json")
        meta = {
            "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "label": label,
            "source_db": str(self.db.db_path),
            "schema_version": val.schema_version,
            "file_size_bytes": val.file_size_bytes,
            "sha256": val.sha256,
            "table_counts": val.table_counts,
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        logger.info("Created verified SQLite backup at %s (%d bytes)", dest, val.file_size_bytes)
        return dest, val

    def validate_backup(self, backup_path: Path | str) -> BackupValidationResult:
        """Validate that a candidate file is a readable, uncorrupted CHENNAI FLOODGUARD SQLite DB."""
        path = Path(backup_path)
        if not path.exists() or not path.is_file():
            return BackupValidationResult(str(path), False, "Backup file does not exist.")
        size = path.stat().st_size
        if size < 1024:
            return BackupValidationResult(str(path), False, "File is too small to be a valid SQLite database.", file_size_bytes=size)

        with path.open("rb") as fh:
            header = fh.read(16)
        if not header.startswith(b"SQLite format 3\x00"):
            return BackupValidationResult(str(path), False, "File does not have a valid SQLite 3 header.", file_size_bytes=size)

        sha = _sha256_file(path)
        meta_path = path.with_suffix(path.suffix + ".meta.json")
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                expected_sha = str(meta.get("sha256") or "")
                if expected_sha and expected_sha != sha:
                    return BackupValidationResult(
                        str(path),
                        False,
                        "Checksum mismatch against backup metadata (.meta.json). Backup may be corrupted.",
                        file_size_bytes=size,
                        sha256=sha,
                    )
            except Exception as exc:
                logger.warning("Ignoring unreadable backup metadata %s: %s", meta_path, exc)

        try:
            conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                ic = [str(r[0]) for r in conn.execute("PRAGMA integrity_check;").fetchall()]
                if ic != ["ok"]:
                    return BackupValidationResult(
                        str(path), False, f"SQLite integrity check failed: {'; '.join(ic)}", file_size_bytes=size, sha256=sha
                    )
                version = int(conn.execute("PRAGMA user_version;").fetchone()[0])
                tables = {
                    str(r[0])
                    for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                }
                missing_core = [t for t in CORE_REQUIRED_TABLES if t not in tables]
                if missing_core:
                    return BackupValidationResult(
                        str(path),
                        False,
                        f"Missing required FloodGuard tables: {', '.join(missing_core)}",
                        schema_version=version,
                        file_size_bytes=size,
                        sha256=sha,
                    )
                fk_errs = conn.execute("PRAGMA foreign_key_check;").fetchall()
                if fk_errs:
                    return BackupValidationResult(
                        str(path),
                        False,
                        f"Backup has {len(fk_errs)} foreign-key constraint violation(s).",
                        schema_version=version,
                        file_size_bytes=size,
                        sha256=sha,
                    )
                counts: dict[str, int] = {}
                for t in ("neighbourhoods", "grid_cells", "osm_features", "simulation_runs", "shelters", "inventory_items"):
                    if t in tables:
                        counts[t] = int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
                return BackupValidationResult(
                    str(path),
                    True,
                    f"Valid FloodGuard backup (schema v{version}, {counts.get('neighbourhoods', 0)} neighbourhood(s), {counts.get('simulation_runs', 0)} simulation(s)).",
                    schema_version=version,
                    file_size_bytes=size,
                    sha256=sha,
                    table_counts=counts,
                )
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return BackupValidationResult(str(path), False, f"SQLite error reading backup: {exc}", file_size_bytes=size, sha256=sha)

    def restore_backup(
        self,
        backup_path: Path | str,
        user_confirmed: bool = False,
        safety_backup_dir: Path | str | None = None,
    ) -> tuple[Path | None, BackupValidationResult]:
        """Validate backup, require explicit confirmation, create pre-restore safety snapshot, and restore."""
        if not user_confirmed:
            raise PermissionError("Database restore aborted: explicit user confirmation is required.")

        candidate = Path(backup_path)
        validation = self.validate_backup(candidate)
        if not validation.is_valid:
            raise ValueError(f"Cannot restore invalid backup: {validation.message}")

        safety_path: Path | None = None
        if self.db.db_path.exists():
            sdir = Path(safety_backup_dir) if safety_backup_dir else self.backup_dir
            sdir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safety_target = sdir / f"pre_restore_safety_{ts}.db"
            safety_path, _ = self.create_backup(safety_target, label="pre_restore_safety")

        # Restore into active DB atomically using temp-file replace or online SQLite backup fallback on Windows
        self.db.db_path.parent.mkdir(parents=True, exist_ok=True)
        gc.collect()
        temp_restore = self.db.db_path.with_suffix(".restore.tmp")
        if temp_restore.exists():
            temp_restore.unlink()
        shutil.copy2(candidate, temp_restore)
        try:
            temp_restore.replace(self.db.db_path)
        except PermissionError:
            if temp_restore.exists():
                temp_restore.unlink()
            with closing(sqlite3.connect(f"file:{candidate.as_posix()}?mode=ro", uri=True)) as src_conn:
                with closing(sqlite3.connect(str(self.db.db_path))) as dst_conn:
                    src_conn.backup(dst_conn)

        # Ensure schema is migrated safely if backup was from an earlier schema version
        self.db.initialize()
        post_check = self.audit_database()
        if not post_check.overall_ok:
            logger.warning("Post-restore audit reported notes: fk=%s ic=%s", post_check.foreign_key_violations, post_check.integrity_messages)
        logger.info("Database restored cleanly from %s (pre-restore safety backup: %s)", candidate, safety_path)
        return safety_path, validation

    def list_backups(self) -> list[Path]:
        if not self.backup_dir.exists():
            return []
        return sorted(self.backup_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
