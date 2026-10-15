"""Build read-only, portable what-if map assets from existing local GIS inputs.

No downloads, raster changes, database writes, or operational flood analyses.
Run with --population-raster PATH pointing to the WorldPop 2025 PAK count raster.
The 2 km display-grid intersection is an approximation, not a hydraulic model.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds, transform as window_transform
from shapely import make_valid, set_precision, transform as transform_geometry
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
AREAS = {"jhang": "Jhang", "multan": "Multan", "lahore": "Lahore", "rawalpindi": "Rawalpindi",
         "charsadda": "Charsadda", "sukkur": "Sukkur", "dadu": "Dadu", "badin": "Badin"}
WIDTHS = [0, 250, 500, 1000, 2000, 4000]
GRID_M = 2000
TO_AREA = Transformer.from_crs(4326, 6933, always_xy=True).transform
FROM_AREA = Transformer.from_crs(6933, 4326, always_xy=True).transform


def transform(project, geometry):
    return transform_geometry(geometry, project, interleaved=False)


def signature(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"file": path.name, "sha256": digest.hexdigest()}


def geographic(geometry):
    # Coordinate precision (~1 m) is already finer than the source display grid.
    # Topology-aware snapping prevents rounded district-edge slivers from becoming
    # self-intersecting polygons. Independent decimal rounding is insufficient.
    snapped = make_valid(set_precision(transform(FROM_AREA, geometry), grid_size=.00001, mode="pointwise"))
    return mapping(snapped)


def population_grid(dataset, district):
    """Sum unmodified native pixel counts by center into 2 km equal-area cells.

    Stream small row windows. No national raster read or resampling of counts.
    AOI membership uses native pixel centers, including at the district boundary.
    """
    raw = from_bounds(*district.bounds, transform=dataset.transform)
    col0, row0 = max(0, int(np.floor(raw.col_off))), max(0, int(np.floor(raw.row_off)))
    col1 = min(dataset.width, int(np.ceil(raw.col_off + raw.width)))
    row1 = min(dataset.height, int(np.ceil(raw.row_off + raw.height)))
    projected = transform(TO_AREA, district)
    west, south, east, north = projected.bounds
    grid_x, grid_y = int(west // GRID_M), int(south // GRID_M)
    cols, rows = int(east // GRID_M) - grid_x + 1, int(north // GRID_M) - grid_y + 1
    counts, known_area = np.zeros(rows * cols), np.zeros(rows * cols)
    valid_pixels = 0
    for start in range(row0, row1, 192):
        window = Window(col0, start, col1 - col0, min(192, row1 - start))
        data = dataset.read(1, window=window, masked=True)
        inside = geometry_mask([mapping(district)], out_shape=data.shape,
                               transform=window_transform(window, dataset.transform), invert=True)
        valid = inside & ~np.ma.getmaskarray(data) & np.isfinite(data.data) & (data.data >= 0)
        rr, cc = np.nonzero(valid)
        if not len(rr):
            continue
        lat = dataset.transform.f + (start + rr + .5) * dataset.transform.e
        lon = dataset.transform.c + (col0 + cc + .5) * dataset.transform.a
        x, y = TO_AREA(lon, lat)
        ids = (np.floor(y / GRID_M).astype(int) - grid_y) * cols + np.floor(x / GRID_M).astype(int) - grid_x
        counts += np.bincount(ids, weights=data.data[rr, cc].astype(float), minlength=len(counts))
        left, bottom = TO_AREA(lon - dataset.res[0] / 2, lat - dataset.res[1] / 2)
        right, top = TO_AREA(lon + dataset.res[0] / 2, lat + dataset.res[1] / 2)
        known_area += np.bincount(ids, weights=(right - left) * (top - bottom), minlength=len(counts))
        valid_pixels += len(rr)
    cells = []
    for index in np.flatnonzero(known_area):
        x, y = (grid_x + index % cols) * GRID_M, (grid_y + index // cols) * GRID_M
        geometry = box(x, y, x + GRID_M, y + GRID_M).intersection(projected)
        if geometry.is_empty or not geometry.area:
            continue
        cells.append((int(index), geometry, float(counts[index]), min(float(known_area[index]), geometry.area)))
    return projected, cells, valid_pixels


def build_region(dataset, area_id, feature, rivers):
    district = shape(feature["geometry"])
    boundary, cells, valid_pixels = population_grid(dataset, district)
    # Metric distances use the local UTM zone; areas/intersection fractions use EPSG:6933.
    zone = int((district.centroid.x + 180) // 6) + 1
    to_local = Transformer.from_crs(4326, 32600 + zone, always_xy=True).transform
    local_to_area = Transformer.from_crs(32600 + zone, 6933, always_xy=True).transform
    local_boundary = transform(to_local, district)
    relevant = [river for river in rivers if transform(to_local, shape(river["geometry"])).intersects(local_boundary.buffer(WIDTHS[-1]))]
    lines = unary_union([transform(to_local, shape(river["geometry"])) for river in relevant])
    footprints = [box(0, 0, 0, 0)]
    for width in WIDTHS[1:]:
        footprints.append(transform(local_to_area, lines.buffer(width, quad_segs=6)).intersection(boundary))
    supported = bool(relevant) and not footprints[-1].is_empty
    features, totals, covered = [], [0.0] * len(WIDTHS), [0.0] * len(WIDTHS)
    for index, geometry, count, known_area in cells:
        fractions = [0.0] + [min(1, geometry.intersection(water).area / geometry.area) if supported else 0.0 for water in footprints[1:]]
        exposed = [round(count * fraction, 4) for fraction in fractions]
        for level, fraction in enumerate(fractions):
            totals[level] += exposed[level]
            covered[level] += known_area * fraction
        features.append({"type": "Feature", "id": index, "geometry": geographic(geometry), "properties": {
            "id": index, "population_2025": round(count, 4), "density_km2": round(count / (geometry.area / 1e6), 2),
            "known_area_km2": round(known_area / 1e6, 5), "area_km2": round(geometry.area / 1e6, 5),
            "exposed_by_level": exposed}})
    levels, rings = [], []
    for level, footprint in enumerate(footprints):
        area = footprint.area
        levels.append({"level": level, "example_buffer_m": WIDTHS[level], "flood_area_km2": round(area / 1e6, 4) if supported else None,
                       "exposed_population": round(totals[level], 4) if supported else None,
                       "known_raster_area_fraction": round(min(1, covered[level] / area), 4) if supported and area else None})
        if level and supported:
            ring = footprint.difference(footprints[level - 1]).simplify(12, preserve_topology=True).intersection(boundary)
            if not ring.is_empty:
                rings.append({"type": "Feature", "properties": {"min_level": level, "is_hypothetical": True}, "geometry": geographic(ring)})
    # Core mathematical invariants, checked before an asset can be written.
    total = sum(item[2] for item in cells)
    assert total >= totals[-1] >= 0
    assert all(totals[i] <= totals[i + 1] + .01 for i in range(5))
    assert all(footprints[i].difference(footprints[i + 1]).area < 1 for i in range(5))
    assert all(levels[i]["flood_area_km2"] <= levels[i + 1]["flood_area_km2"] for i in range(5)) if supported else True
    return {"id": area_id, "name": AREAS[area_id], "bounds": list(district.bounds), "supported": supported,
            "rivers": [river["properties"]["name"] for river in relevant], "known_population_2025": round(total, 4),
            "valid_native_pixels": valid_pixels, "levels": levels,
            "population": {"type": "FeatureCollection", "features": features},
            "water": {"type": "FeatureCollection", "features": rings},
            "river_lines": {"type": "FeatureCollection", "features": [{**river, "geometry": geographic(transform(TO_AREA, shape(river["geometry"])).intersection(boundary))} for river in relevant]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population-raster", required=True, type=Path)
    args = parser.parse_args()
    district_path = ROOT / "frontend/src/data/pakistan/pakistan_districts.geojson"
    river_path = ROOT / "app/gis/data/pakistan_osm_waterways.geojson"
    districts = json.loads(district_path.read_text(encoding="utf-8-sig"))["features"]
    rivers = json.loads(river_path.read_text(encoding="utf-8-sig"))["features"]
    output = ROOT / "frontend/src/data/outlook-exposure"
    output.mkdir(exist_ok=True, parents=True)
    metadata = {"version": "river-corridor-what-if-v1", "population_year": 2025, "grid_m": GRID_M,
                "widths_m": WIDTHS, "population_source": "WorldPop R2025A v1, Pakistan 2025 constrained 100 m people-per-pixel",
                "source_url": "https://doi.org/10.5258/SOTON/WP00839", "license": "CC BY 4.0",
                "inputs": [signature(args.population_raster), signature(district_path), signature(river_path)],
                "method": "Native pixel-center district mask; sum counts to 2 km equal-area display cells. Exposure = count x footprint/cell area. Uniform population within each clipped cell. NoData excluded. Population fixed at 2025.",
                "flood_method": "Arbitrary nested UTM river buffers, clipped to display districts. Levels 0-5 are ordinal, not water heights, discharge, official categories, or predicted inundation. No DEM, levees, drainage, or hydraulic routing.",
                "regions": []}
    with rasterio.open(args.population_raster) as dataset:
        if str(dataset.crs) != "EPSG:4326" or "2025" not in dataset.tags().get("TIFFTAG_IMAGEDESCRIPTION", ""):
            raise ValueError("Expected the identified WorldPop 2025 EPSG:4326 count raster")
        for area_id, name in AREAS.items():
            feature = next(item for item in districts if item["properties"].get("district") == name)
            data = build_region(dataset, area_id, feature, rivers)
            target = output / f"{area_id}.geojson"
            target.write_text(json.dumps(data, separators=(",", ":"), allow_nan=False), encoding="utf-8")
            metadata["regions"].append({key: data[key] for key in ["id", "name", "supported", "known_population_2025", "valid_native_pixels"]})
            print(f"{name}: {len(data['population']['features'])} cells; known pop {data['known_population_2025']:,.0f}; river spread {'available' if data['supported'] else 'unavailable'}", flush=True)
    (output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
