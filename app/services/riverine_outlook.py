"""Serve the saved riverine outlook snapshot for one station.

Snapshots are built offline by ``models/riverine_outlook/build_*.py`` from the
trained flood_model riverine models. Only Marala has trained models so far;
any other station returns the same shape with ``available: false``.
"""
from __future__ import annotations

import copy
import json
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = {"MARALA": ROOT / "models" / "riverine_outlook" / "artifacts" / "marala_outlook.json"}
STALE_AFTER_DAYS = 45


@lru_cache(maxsize=4)
def _read(path: str, mtime_ns: int) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def get_riverine_outlook(station_id: str, today: date | None = None) -> dict:
    station_id = station_id.upper()
    path = SNAPSHOTS.get(station_id)
    if path is None or not path.is_file():
        return {
            "station": {"id": station_id},
            "available": False,
            "reason": "No riverine outlook models have been trained for this station yet. Marala (Chenab) is the only station with trained models.",
        }
    payload = copy.deepcopy(_read(str(path), path.stat().st_mtime_ns))
    issue = date.fromisoformat(payload["seasonal"]["issue_date"])
    age = ((today or datetime.now(timezone.utc).date()) - issue).days
    payload.update(available=True, issue_age_days=age, stale=age > STALE_AFTER_DAYS)
    return payload
