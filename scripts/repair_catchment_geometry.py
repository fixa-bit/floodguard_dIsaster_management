"""SUPERSEDED (2026-11-26) by scripts/rebuild_catchments_from_hydrobasins.py, which rebuilds the catchments from
the original HydroBASINS polygons so neighbours share exact edges. Running this on the rebuilt file is not
needed; on the service geometry it makes polygons valid but keeps the slivers and overlaps between neighbours
(up to ~400 m) and can move a boundary by kilometres where it fills nested shells.

Repair the HydroBASINS catchment file after frontend/scripts/fetch-catchments.mjs downloads it.

The service's simplified geometry has rings that cross themselves and polygons drawn inside other
polygons of the same basin (both invalid GeoJSON; the map fills such overlaps twice), plus slivers
left by simplification (sub-basin 3005 was a 0.1 km2 triangle). This makes each basin valid and
drops basins smaller than 1 km2.

    python scripts/repair_catchment_geometry.py
"""
import json
import math
from datetime import date
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

PATH = Path(__file__).resolve().parents[1] / "frontend" / "src" / "data" / "pakistan" / "catchment_areas.geojson"
MIN_KM2 = 1


def km2(geometry) -> float:
    return geometry.area * 111.32 ** 2 * math.cos(math.radians(geometry.centroid.y))


def polygonal(geometry):
    parts = [part for part in getattr(geometry, "geoms", [geometry]) if isinstance(part, (Polygon, MultiPolygon))]
    flat = [polygon for part in parts for polygon in getattr(part, "geoms", [part])]
    return flat[0] if len(flat) == 1 else MultiPolygon(flat)


def repair(geometry):
    # Each polygon is fixed on its own and the basin is their union, so a polygon drawn inside another
    # stays filled (as the map showed it) instead of becoming a hole, which would open gaps between basins.
    pieces = [polygonal(make_valid(part)) for part in getattr(geometry, "geoms", [geometry])]
    return polygonal(unary_union(pieces))


def rounded(value):
    if isinstance(value, float):
        return round(value, 5)
    if isinstance(value, (list, tuple)):
        return [rounded(item) for item in value]
    return value


def main() -> None:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    kept, repaired, dropped = [], [], []
    for feature in data["features"]:
        geometry = shape(feature["geometry"])
        if km2(geometry) < MIN_KM2:
            dropped.append(feature["properties"]["basin_id"])
            continue
        if not geometry.is_valid:
            geometry = repair(geometry)
            assert geometry.is_valid
            feature["geometry"] = {"type": geometry.geom_type, "coordinates": rounded(mapping(geometry)["coordinates"])}
            feature["bbox"] = [round(value, 5) for value in geometry.bounds]
            repaired.append(feature["properties"]["basin_id"])
        kept.append(feature)
    data["features"] = kept
    if repaired or dropped:
        data["metadata"]["geometry_repair"] = {"date": date.today().isoformat(), "made_valid": repaired,
                                               "dropped_under_1_km2": dropped, "script": "scripts/repair_catchment_geometry.py"}
    PATH.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(kept)} catchments; made valid: {repaired or 'none'}; dropped: {dropped or 'none'}")


if __name__ == "__main__":
    main()
