"""Derive display outlines from the exact district polygons used by the map.

No snapping, buffering, or guessed district assignments are applied.
These are consistent display boundaries, not newly certified authority data.
"""
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from shapely import make_valid
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "frontend/src/data/pakistan"


def build_outline(source_name, output_name):
    source_path = DATA / source_name
    source = json.loads(source_path.read_text())
    groups = defaultdict(list)
    for feature in source["features"]:
        if not feature["properties"].get("district"):
            continue
        groups[feature["properties"]["province"]].append(make_valid(shape(feature["geometry"])))
    features = []
    for name, polygons in sorted(groups.items()):
        geometry = unary_union(polygons)
        if geometry.geom_type not in ("Polygon", "MultiPolygon") or not geometry.is_valid:
            raise ValueError(f"Invalid outline for {name}")
        features.append({"type": "Feature", "properties": {
            "name": name, "district_count": len(polygons), "boundary_type": "district_derived_display_outline",
            "source_file": source_name,
        }, "geometry": mapping(geometry)})
    output = {"type": "FeatureCollection", "metadata": {
        "name": "District-derived display outline", "method": "Exact union of named district polygons by region; no snapping or buffering",
        "source_file": source_name, "source_sha256": hashlib.sha256(source_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
        "hash_line_endings": "LF",
        "source_metadata": source.get("metadata", {}),
        "note": "Display consistency only; not a newly certified NDMA boundary. Retains source coverage and vintage.",
    }, "features": features}
    (DATA / output_name).write_text(json.dumps(output, separators=(",", ":")) + "\n")
    print(f"{output_name}: {len(features)} regions from {sum(len(polygons) for polygons in groups.values())} named districts")


def main():
    build_outline("pakistan_districts.geojson", "district_operational_outline.geojson")
    build_outline("kashmir_districts.geojson", "district_kashmir_outline.geojson")


if __name__ == "__main__":
    main()
