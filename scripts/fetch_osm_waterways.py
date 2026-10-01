from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


BASE_URL = "https://waterwaymap.org"
OUTPUT_PATH = Path("app/gis/data/pakistan_osm_waterways.geojson")

RIVERS = [
    {
        "name": "Indus River",
        "path": "/river/دریائے سندھ 000058647075/geometry.geojson",
        "description": "Indus River alignment derived from WaterwayMap/OpenStreetMap geometry.",
    },
    {
        "name": "Sutlej River",
        "path": "/river/ਸਤਲੁਜ ਦਰਿਆ / دریاۓ ستلج 000299642953/geometry.geojson",
        "description": "Sutlej River alignment derived from WaterwayMap/OpenStreetMap geometry.",
    },
    {
        "name": "Chenab River",
        "path": "/river/Chenab River 000078506695/geometry.geojson",
        "description": "Chenab River alignment derived from WaterwayMap/OpenStreetMap geometry.",
    },
    {
        "name": "Jhelum River",
        "path": "/river/دریائے جہلم 000080311524/geometry.geojson",
        "description": "Jhelum River alignment derived from WaterwayMap/OpenStreetMap geometry.",
    },
    {
        "name": "Ravi River",
        "path": "/river/دریائے راوی 000100195961/geometry.geojson",
        "description": "Ravi River alignment derived from WaterwayMap/OpenStreetMap geometry.",
    },
    {
        "name": "Kabul River",
        "path": "/river/کابل سيند 000025960736/geometry.geojson",
        "description": "Kabul River alignment derived from WaterwayMap/OpenStreetMap geometry.",
    },
]


def _url(path: str) -> str:
    return f"{BASE_URL}{urllib.parse.quote(path, safe='/:')}"


def _fetch_json(path: str) -> dict[str, Any]:
    request = urllib.request.Request(
        _url(path),
        headers={"User-Agent": "FloodGuardAI/0.1 Pakistan water intelligence geometry builder"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def _feature(river: dict[str, str], geometry: dict[str, Any]) -> dict[str, Any]:
    river_id = river["name"].lower().replace(" river", "").replace(" ", "_")
    return {
        "type": "Feature",
        "id": f"osm_river_{river_id}",
        "geometry": geometry,
        "properties": {
            "name": river["name"],
            "water_system": "Indus Basin",
            "feature_kind": "river",
            "data_class": "gis_feature",
            "data_status": "GIS reference feature",
            "telemetry_status": "not_station",
            "geometry_source": "WaterwayMap/OpenStreetMap",
            "geometry_quality": "derived",
            "source": _url(river["path"]),
            "description": f"{river['description']} It does not imply continuous telemetry along the line.",
        },
    }


def main() -> None:
    features = []
    for river in RIVERS:
        geometry = _fetch_json(river["path"])
        if geometry.get("type") not in {"LineString", "MultiLineString"}:
            raise SystemExit(f"Unexpected geometry type for {river['name']}: {geometry.get('type')}")
        features.append(_feature(river, geometry))

    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "source": "WaterwayMap.org river pages, derived from OpenStreetMap",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "geometry_quality": "derived",
            "license_note": "Contains OpenStreetMap data under ODbL; WaterwayMap pages are CC-BY-SA 4.0.",
            "rivers": [river["name"] for river in RIVERS],
        },
        "features": features,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(collection, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(features)} OSM-derived river features to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
