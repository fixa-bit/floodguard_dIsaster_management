"""Regenerate rainfall coverage: pip install pyshp shapely; run from repo root."""
import io
import json
import zipfile
from pathlib import Path

import httpx
import shapefile
from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://data.hydrosheds.org/file/hydrobasins/standard/hybas_as_lev03_v1c.zip"


def main():
    response = httpx.get(SOURCE, timeout=120, follow_redirects=True)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        files = {Path(name).suffix: name for name in archive.namelist()}
        reader = shapefile.Reader(shp=io.BytesIO(archive.read(files[".shp"])),
                                  shx=io.BytesIO(archive.read(files[".shx"])),
                                  dbf=io.BytesIO(archive.read(files[".dbf"])))
        outlets = [Point(68.3, 25.4), Point(78.72, 31.8), Point(79.7, 32.5), Point(76, 32.5), Point(77, 33)]
        geometries = [geometry for record in reader.iterShapeRecords()
                      if any((geometry := shape(record.shape.__geo_interface__)).covers(point) for point in outlets)]
    for name in ("pakistan_admin1", "jammu_kashmir_context", "catchment_areas"):
        data = json.loads((ROOT / f"frontend/src/data/pakistan/{name}.geojson").read_text(encoding="utf-8"))
        geometries.extend(shape(feature["geometry"]) for feature in data["features"])
    coverage = unary_union([geometry.buffer(0) for geometry in geometries]).simplify(0.01, preserve_topology=True)
    for longitude, latitude in ((74.8, 34.08), (77.58, 34.15), (69.17, 34.55), (77.19, 32.24), (78.72, 31.8)):
        assert coverage.covers(Point(longitude, latitude)), (longitude, latitude)
    assert not coverage.covers(Point(77.23, 28.61)), "Unrelated Delhi basin must remain outside coverage"
    collection = {"type": "FeatureCollection", "bbox": list(coverage.bounds),
                  "metadata": {"source": "HydroBASINS / HydroSHEDS", "source_url": SOURCE,
                               "note": "Pakistan operational areas, Kashmir context, full Indus basin and transboundary sub-basins intersecting Pakistan. Hydrological monitoring coverage, not a political boundary or station-specific flood attribution."},
                  "features": [{"type": "Feature", "properties": {"name": "Pakistan and upstream rainfall coverage"},
                                "geometry": mapping(coverage)}]}
    target = ROOT / "app/gis/data/rainfall_coverage.geojson"
    target.write_text(json.dumps(collection, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Generated {target}: {coverage.bounds}")


if __name__ == "__main__":
    main()
