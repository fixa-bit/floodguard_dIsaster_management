"""Validate the shipped what-if assets without needing the external raster."""
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely import transform as transform_geometry
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "frontend/src/data/outlook-exposure"
to_area = Transformer.from_crs(4326, 6933, always_xy=True).transform


def transform(project, geometry):
    return transform_geometry(geometry, project, interleaved=False)

metadata = json.loads((ASSETS / "metadata.json").read_text())
assert metadata["population_year"] == 2025
assert metadata["widths_m"] == [0, 250, 500, 1000, 2000, 4000]
assert len(metadata["regions"]) == 8
districts = json.loads((ROOT / "frontend/src/data/pakistan/pakistan_districts.geojson").read_text(encoding="utf-8-sig"))
for path in [ROOT / "frontend/src/data/pakistan/pakistan_districts.geojson", ROOT / "app/gis/data/pakistan_osm_waterways.geojson"]:
    expected = next(item for item in metadata["inputs"] if item["file"] == path.name)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"], "Source geometry changed; regenerate assets"

for region in metadata["regions"]:
    data = json.loads((ASSETS / f"{region['id']}.geojson").read_text())
    cells = data["population"]["features"]
    assert cells and data["valid_native_pixels"] > 0
    assert abs(sum(cell["properties"]["population_2025"] for cell in cells) - data["known_population_2025"]) < .1
    for cell in cells:
        p = cell["properties"]
        assert math.isfinite(p["population_2025"]) and p["population_2025"] >= 0
        assert shape(cell["geometry"]).is_valid
        assert len(p["exposed_by_level"]) == 6 and p["exposed_by_level"][0] == 0
        assert all(0 <= value <= p["population_2025"] + .001 for value in p["exposed_by_level"])
        assert all(a <= b for a, b in zip(p["exposed_by_level"], p["exposed_by_level"][1:]))
    if not data["supported"]:
        assert data["id"] == "badin"
        assert not data["water"]["features"]
        assert all(level["exposed_population"] is None and level["flood_area_km2"] is None for level in data["levels"])
        continue
    assert data["levels"][0]["exposed_population"] == data["levels"][0]["flood_area_km2"] == 0
    assert len(data["water"]["features"]) == 5
    boundary = transform(to_area, shape(next(item for item in districts["features"] if item["properties"].get("district") == data["name"])["geometry"]))
    for level in data["levels"]:
        assert 0 <= level["exposed_population"] <= data["known_population_2025"]
        computed = sum(cell["properties"]["exposed_by_level"][level["level"]] for cell in cells)
        assert abs(computed - level["exposed_population"]) < .01
        if not level["level"]:
            continue
        water = unary_union([transform(to_area, shape(item["geometry"])) for item in data["water"]["features"] if item["properties"]["min_level"] <= level["level"]])
        assert water.is_valid
        # Display simplification (12 m) and 5-decimal lon/lat rounding are not the analytical footprint.
        assert water.difference(boundary.buffer(2)).area < 1
        assert abs(water.area / 1e6 - level["flood_area_km2"]) < max(1, .025 * level["flood_area_km2"])
        assert 0 <= level["known_raster_area_fraction"] <= 1
    assert all(a["exposed_population"] <= b["exposed_population"] and a["flood_area_km2"] <= b["flood_area_km2"] for a, b in zip(data["levels"], data["levels"][1:]))

print("PASS: 8 real population assets; source hashes; finite counts; conservation; nested/nondecreasing level exposure; zero-level behavior; clipped valid map geometry; honest missing river coverage.")
