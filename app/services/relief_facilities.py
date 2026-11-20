"""Relief facilities near a point, from the OpenStreetMap extract in app/gis/data.

The extract is made by scripts/fetch_osm_relief_facilities.py (free, ODbL). It is community-mapped:
coverage varies by district and nothing in it is verified by an authority, so every answer carries
the source and that note.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parents[1] / "gis" / "data" / "pakistan_osm_relief_facilities.json"

CATEGORY_LABELS = {
    "hospital": "Hospitals",
    "clinic": "Clinics & health centres",
    "rescue": "Rescue & fire stations",
    "police": "Police",
    "school": "Schools & colleges (possible relief camps)",
    "assembly": "Assembly points & shelters",
}


_cache: tuple[tuple[str, float], dict[str, Any]] | None = None


def _load() -> dict[str, Any] | None:
    """The extract, read again whenever the file changes (e.g. after the fetch script runs)."""
    global _cache
    if not DATA_PATH.exists():
        return None
    key = (str(DATA_PATH), DATA_PATH.stat().st_mtime)
    if _cache is None or _cache[0] != key:
        _cache = (key, json.loads(DATA_PATH.read_text(encoding="utf-8")))
    return _cache[1]


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = math.pi / 180
    h = math.sin((lat2 - lat1) * r / 2) ** 2 + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin((lon2 - lon1) * r / 2) ** 2
    return 12742 * math.asin(math.sqrt(min(1.0, h)))


def nearby(latitude: float, longitude: float, radius_km: float, per_category: int = 8, map_limit: int = 800) -> dict[str, Any]:
    """Facilities within `radius_km`: per category, the count and the nearest few; plus up to
    `map_limit` points (nearest first) for the map. Each category also names its nearest
    facility even when it lies outside the radius, so a gap is visible rather than silent."""
    data = _load()
    if data is None:
        return {"available": False, "radius_km": radius_km, "categories": [], "features": [],
                "note": "The relief facility extract is missing: run scripts/fetch_osm_relief_facilities.py."}
    # A cheap box first: one degree of latitude is ~111 km.
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.2, math.cos(math.radians(latitude))))
    inside: list[dict[str, Any]] = []
    nearest_any: dict[str, tuple[float, dict[str, Any]]] = {}
    for facility in data["facilities"]:
        lat, lon = facility["lat"], facility["lon"]
        close = abs(lat - latitude) <= dlat and abs(lon - longitude) <= dlon
        best = nearest_any.get(facility["category"])
        if not close and best is not None and abs(lat - latitude) * 111 > best[0]:
            continue
        km = distance_km(latitude, longitude, lat, lon)
        if best is None or km < best[0]:
            nearest_any[facility["category"]] = (km, facility)
        if close and km <= radius_km:
            inside.append({**facility, "distance_km": round(km, 2)})
    inside.sort(key=lambda f: f["distance_km"])
    categories = []
    for category, label in CATEGORY_LABELS.items():
        within = [f for f in inside if f["category"] == category]
        nearest = nearest_any.get(category)
        categories.append({
            "category": category, "label": label, "count": len(within), "items": within[:per_category],
            "nearest_outside": None if within or nearest is None else {**nearest[1], "distance_km": round(nearest[0], 1)},
        })
    return {"available": True, "source": data["source"], "retrieved_at": data["retrieved_at"], "note": data["note"],
            "radius_km": radius_km, "total": len(inside), "categories": categories, "features": inside[:map_limit]}
