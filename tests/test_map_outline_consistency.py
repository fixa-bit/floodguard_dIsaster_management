import hashlib
import json
from pathlib import Path

import pytest
from shapely import make_valid
from shapely.geometry import box, shape
from shapely.ops import unary_union

DATA = Path(__file__).parents[1] / "frontend/src/data/pakistan"


@pytest.mark.parametrize("source_name,outline_name", [
    ("pakistan_districts.geojson", "district_operational_outline.geojson"),
    ("kashmir_districts.geojson", "district_kashmir_outline.geojson"),
])
def test_outline_is_exact_union_of_its_districts(source_name, outline_name):
    source = json.loads((DATA / source_name).read_text())
    outline = json.loads((DATA / outline_name).read_text())
    assert outline["metadata"]["source_sha256"] == hashlib.sha256((DATA / source_name).read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    for region in outline["features"]:
        districts = [make_valid(shape(feature["geometry"])) for feature in source["features"]
                     if feature["properties"].get("district") and feature["properties"]["province"] == region["properties"]["name"]]
        union = unary_union(districts)
        geometry = shape(region["geometry"])
        assert geometry.is_valid
        assert region["properties"]["district_count"] == len(districts)
        assert union.symmetric_difference(geometry).area < 1e-12
        assert union.boundary.equals(geometry.boundary)


def test_kathua_white_edge_matches_district_edge():
    districts = json.loads((DATA / "kashmir_districts.geojson").read_text())["features"]
    kathua = shape(next(feature for feature in districts if feature["properties"]["district"] == "Kathua")["geometry"])
    old = shape(json.loads((DATA / "jammu_kashmir_context.geojson").read_text())["features"][0]["geometry"])
    new = shape(json.loads((DATA / "district_kashmir_outline.geojson").read_text())["features"][0]["geometry"])
    # The south/east frontier is the location shown in the reported screenshot.
    frontier = box(75.5, 32.2, 76.1, 32.9)
    district_edge = kathua.boundary.intersection(new.boundary).intersection(frontier)
    assert district_edge.length > 0.1
    assert district_edge.difference(new.boundary.buffer(1e-10)).length < 1e-10
    assert old.boundary.intersection(frontier).difference(new.boundary.buffer(1e-6)).length > 0.01
