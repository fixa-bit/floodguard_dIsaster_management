"""Last successful provider response, kept on disk so it survives backend restarts.

Live providers save each good result here and read it back when the upstream
service fails, so the dashboard keeps showing the last known values instead of
an error. Entries older than ``last_good_max_age_hours`` are not served.
"""
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]


def _path(name: str) -> Path | None:
    configured = get_settings().last_good_cache_dir.strip()
    if not configured:
        return None
    directory = Path(configured)
    directory = directory if directory.is_absolute() else REPO_ROOT / directory
    return directory / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.json"


def save(name: str, payload: Any) -> None:
    path = _path(name)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"saved_at": time.time(), "payload": payload}, default=str), encoding="utf-8")
        temporary.replace(path)
    except (OSError, TypeError, ValueError):
        logger.warning("Could not store last good response %s", name, exc_info=True)


def load(name: str) -> tuple[float, Any] | None:
    """Return (saved_at epoch seconds, payload), or None when nothing recent enough is stored."""
    path = _path(name)
    if path is None or not path.exists():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        saved_at = float(stored["saved_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if time.time() - saved_at > get_settings().last_good_max_age_hours * 3600:
        return None
    return saved_at, stored["payload"]
