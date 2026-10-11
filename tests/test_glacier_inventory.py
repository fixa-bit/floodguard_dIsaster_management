import json
from pathlib import Path

import pytest
from shapely.geometry import Point, box, shape
from shapely.ops import unary_union
from shapely.prepared import prep

DATA = Path(__file__).parents[1] / "frontend/src/data/pakistan"


@pytest.fixture(scope="module")
def inventory():
    return json.loads((DATA / "glaciers.geojson").read_text(encoding="utf-8"))


def test_glacier_inventory_is_complete_for_its_declared_extract(inventory):
    features = inventory["features"]
    metadata = inventory["metadata"]
    assert len(features) == metadata["feature_count"]
    assert len({feature["id"] for feature in features}) == len(features)
    assert len(features) > 1000
    assert "snapshot" in metadata["note"]
    for feature in features:
        properties = feature["properties"]
        assert properties["area_km2"] >= metadata["minimum_area_km2"]
        assert feature["id"].startswith("RGI2000-v7.0-G-")
        assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
        assert -180 <= properties["longitude"] <= 180
        assert -90 <= properties["latitude"] <= 90
        assert shape(feature["geometry"]).intersects(box(*metadata["extent"]).buffer(0.0005))


def test_external_glaciers_are_highlighted_by_drainage_not_country(inventory):
    pakistan = prep(unary_union([shape(feature["geometry"]) for feature in
                                 json.loads((DATA / "pakistan_admin1.geojson").read_text(encoding="utf-8"))["features"]]))
    basin = shape(json.loads((DATA / "glacier_indus_basin.geojson").read_text(encoding="utf-8"))["features"][0]["geometry"])
    # Allow only the declared display simplification tolerance at watershed edges.
    basin_margin = prep(basin.buffer(0.006))
    external = []
    neighbors = []
    for feature in inventory["features"]:
        properties = feature["properties"]
        point = Point(properties["longitude"], properties["latitude"])
        assert properties["outside_pakistan_boundary"] == (not pakistan.covers(point))
        if properties["highlight"] == "external_contributor":
            external.append(feature)
            assert properties["connection"] == "pakistan_contributor"
            assert properties["outside_pakistan_boundary"]
            assert basin_margin.covers(point)
            assert properties["main_basin_id"] == inventory["metadata"]["main_basin_id"]
        elif properties["connection"] == "other_basin":
            neighbors.append(feature)
            assert properties["main_basin_id"] is None
    assert len(external) == inventory["metadata"]["counts"]["external_contributors"] > 0
    assert len(neighbors) == inventory["metadata"]["counts"]["other_basin"] > 0
    assert basin.covers(Point(78.72, 31.8)), "Sutlej headwaters outside Pakistan must be included"
    assert not basin.covers(Point(79.1, 30.8)), "Neighboring Ganges headwaters must not be treated as Pakistan contributors"
