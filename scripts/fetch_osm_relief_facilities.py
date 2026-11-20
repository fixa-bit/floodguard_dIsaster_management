"""Download relief facilities for Pakistan from OpenStreetMap (free, ODbL) for GIS Operations.

Hospitals, clinics, police, fire and rescue stations, and schools / colleges (the buildings
used as relief camps in Pakistan's floods), as points. Community-mapped: coverage varies by
district and nothing here is verified by an authority, which the app says wherever it shows them.

    python scripts/fetch_osm_relief_facilities.py            # writes the file below
    python scripts/fetch_osm_relief_facilities.py --dry-run  # counts only
    python scripts/fetch_osm_relief_facilities.py --only rescue  # refetch one category

Output: app/gis/data/pakistan_osm_relief_facilities.json
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Free public Overpass servers, tried in turn (the main one is often at capacity).
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
OUTPUT_PATH = Path("app/gis/data/pakistan_osm_relief_facilities.json")
USER_AGENT = "floodguard-relief-facilities/1.0"

# category -> Overpass filters (each run over nodes, ways and relations inside Pakistan)
CATEGORIES: dict[str, list[str]] = {
    "hospital": ['["amenity"="hospital"]', '["healthcare"="hospital"]'],
    "clinic": ['["amenity"="clinic"]', '["healthcare"="clinic"]', '["amenity"="doctors"]'],
    "rescue": ['["amenity"="fire_station"]', '["emergency"="ambulance_station"]'],
    "police": ['["amenity"="police"]'],
    "school": ['["amenity"~"^(school|college|university)$"]'],
    "assembly": ['["emergency"="assembly_point"]', '["social_facility"="shelter"]'],
}
# Ranked: a place tagged as two kinds keeps the first it matches here.
PRIORITY = ["hospital", "clinic", "rescue", "police", "assembly", "school"]
KEEP_TAGS = ("name", "name:en", "operator", "beds", "capacity", "phone", "contact:phone", "addr:city", "addr:district", "emergency")


def query(category: str) -> str:
    parts = "".join(f"nwr{f}(area.pk);" for f in CATEGORIES[category])
    return f'[out:json][timeout:180];area["ISO3166-1"="PK"][admin_level=2]->.pk;({parts});out center tags;'


def fetch(category: str) -> list[dict]:
    body = urllib.parse.urlencode({"data": query(category)}).encode()
    attempts = 3 * len(OVERPASS_URLS)
    for attempt in range(attempts):
        url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
        try:
            request = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=200) as response:
                payload = json.load(response)
            # A busy server can answer 200 with no elements and a "runtime error" remark: not an empty result.
            if "remark" in payload and "error" in payload["remark"].lower():
                raise RuntimeError(payload["remark"])
            return payload["elements"]
        except Exception as error:  # a busy server: try the next one, waiting longer each round
            if attempt == attempts - 1:
                raise
            print(f"  {category}: {url.split('/')[2]} failed ({str(error)[:80]}); trying the next server", flush=True)
            time.sleep(5 + 10 * (attempt // len(OVERPASS_URLS)))
    return []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print counts only")
    parser.add_argument("--only", nargs="+", choices=PRIORITY, help="fetch just these categories again, keeping the rest of the file")
    args = parser.parse_args()

    found: dict[str, dict] = {}
    if args.only and OUTPUT_PATH.exists():
        kept = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))["facilities"]
        found = {f["id"]: f for f in kept if f["category"] not in args.only}
    for category in [c for c in PRIORITY if not args.only or c in args.only]:
        elements = fetch(category)
        print(f"{category}: {len(elements)}", flush=True)
        for element in elements:
            key = f"{element['type'][0]}{element['id']}"
            if key in found:
                continue
            lat = element.get("lat", element.get("center", {}).get("lat"))
            lon = element.get("lon", element.get("center", {}).get("lon"))
            if lat is None or lon is None:
                continue
            tags = element.get("tags", {})
            found[key] = {"id": key, "category": category, "lat": round(lat, 6), "lon": round(lon, 6),
                          "name": tags.get("name:en") or tags.get("name") or "",
                          "tags": {k: tags[k] for k in KEEP_TAGS if k in tags and k not in ("name", "name:en")}}
        time.sleep(5)

    counts = {c: sum(1 for f in found.values() if f["category"] == c) for c in PRIORITY}
    print("kept:", counts, "total", len(found))
    if args.dry_run:
        return
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({
        "source": "OpenStreetMap contributors (ODbL), via the Overpass API",
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Community-mapped facilities; coverage varies by district and nothing is verified by an authority.",
        "counts": counts,
        "facilities": sorted(found.values(), key=lambda f: f["id"]),
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
