"""Build a clipped Kashmir district display subset from geoBoundaries ADM2.

The source represents 2021 districts; this is geography, not live risk coverage.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from shapely import make_valid
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "frontend/src/data/pakistan"
SOURCE = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/9469f09/releaseData/gbOpen/IND/ADM2/geoBoundaries-IND-ADM2_simplified.geojson"


def main():
    context = json.loads((DATA / "jammu_kashmir_context.geojson").read_text())
    extent = unary_union([make_valid(shape(feature["geometry"])) for feature in context["features"]])
    response = httpx.get(SOURCE, timeout=180, follow_redirects=True)
    response.raise_for_status()
    features = []
    for feature in response.json()["features"]:
        geometry = make_valid(shape(feature["geometry"]))
        if not extent.covers(geometry.representative_point()):
            continue
        clipped = make_valid(geometry.intersection(extent))
        if clipped.geom_type not in ("Polygon", "MultiPolygon"):
            polygons = [part for part in clipped.geoms if part.geom_type in ("Polygon", "MultiPolygon")]
            clipped = unary_union(polygons)
        if clipped.is_empty or clipped.area / geometry.area < 0.5:
            continue
        properties = feature["properties"]
        features.append({"type": "Feature", "geometry": mapping(clipped), "properties": {
            "id": f"kashmir_{properties['shapeID']}", "district": properties["shapeName"],
            "province": "Jammu & Kashmir context", "boundary_type": "district_context",
            "source": "geoBoundaries IND ADM2 / Pathways Data / LG Directory",
            "source_url": SOURCE, "boundary_year": 2021,
        }})
    names = {feature["properties"]["district"].lower() for feature in features}
    if not {"srinagar", "jammu", "anantnag", "baramula", "kargil"}.issubset(names):
        raise ValueError(f"Incomplete Kashmir district subset: {sorted(names)}")
    output = {"type": "FeatureCollection", "metadata": {
        "source": "geoBoundaries IND-ADM2-76128533", "source_url": SOURCE,
        "license": "Open Data Commons Open Database License 1.0", "boundary_year": 2021,
        "retrieved": datetime.now(timezone.utc).date().isoformat(),
        "note": "District display clipped to the existing disputed-territory context. Does not assign sovereignty or extend risk-model coverage.",
    }, "features": features}
    (DATA / "kashmir_districts.geojson").write_text(json.dumps(output, separators=(",", ":")) + "\n")
    print(f"Saved {len(features)} district polygons: {', '.join(sorted(names))}")


if __name__ == "__main__":
    main()
