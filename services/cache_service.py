"""Local JSON file caching service for offline-first operation."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import CACHE_DIR

logger = logging.getLogger(__name__)


def format_age_seconds(age_seconds: float) -> str:
    """Format elapsed seconds into a concise human-readable age string."""
    secs = max(0, int(age_seconds))
    if secs < 60:
        return f"{secs}s ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min{'s' if mins != 1 else ''} ago"
    hours = mins // 60
    rem_mins = mins % 60
    if hours < 24:
        return f"{hours}h {rem_mins}m ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


class CacheService:
    """Thread-safe local JSON file cache keyed by namespace and hashed key."""

    def __init__(self, cache_dir: Path | str = CACHE_DIR) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _entry_path(self, namespace: str, key: str) -> Path:
        safe_ns = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in namespace)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        ns_dir = self.cache_dir / safe_ns
        ns_dir.mkdir(parents=True, exist_ok=True)
        return ns_dir / f"{digest}.json"

    def set(self, namespace: str, key: str, payload: Any, source: str = "") -> Path:
        """Persist payload to local JSON cache with UTC timestamp."""
        path = self._entry_path(namespace, key)
        envelope = {
            "cached_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "source": source,
            "key": key,
            "payload": payload,
        }
        path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        return path

    def get(
        self,
        namespace: str,
        key: str,
        max_age_seconds: float | None = None,
    ) -> tuple[Any, str, float] | None:
        """Return (payload, cached_at_iso, age_seconds) if present and within max_age_seconds."""
        path = self._entry_path(namespace, key)
        if not path.exists():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            cached_at_str = envelope.get("cached_at", "")
            cached_dt = datetime.fromisoformat(cached_at_str)
            if cached_dt.tzinfo is None:
                cached_dt = cached_dt.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (datetime.now(timezone.utc) - cached_dt).total_seconds())
            if max_age_seconds is not None and age_seconds > max_age_seconds:
                return None
            return envelope.get("payload"), cached_at_str, age_seconds
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read cache entry %s: %s", path, exc)
            return None

    def clear(self, namespace: str | None = None) -> int:
        """Delete cached JSON files (optionally restricted to one namespace)."""
        removed = 0
        target_dir = self.cache_dir / namespace if namespace else self.cache_dir
        if not target_dir.exists():
            return 0
        for item in target_dir.rglob("*.json"):
            try:
                item.unlink()
                removed += 1
            except OSError:
                pass
        return removed

