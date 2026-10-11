"""Build glacier display data from RGI 7 and the full HydroBASINS Indus network.

Run with the project virtualenv (httpx, pyshp and shapely).
"""
import io
import json
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
import shapefile
from shapely import force_2d, make_valid
from shapely.geometry import Point, mapping, shape
from shapely.ops import unary_union
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "frontend/src/data/pakistan"
BASIN_URL = "https://data.hydrosheds.org/file/hydrobasins/standard/hybas_as_lev03_v1c.zip"
GLACIER_URL = "https://www.glims.org/geoserver/GLIMS/ows"
REGIONS = ("13_central_asia", "14_south_asia_west", "15_south_asia_east")
EXTENT = [65, 28, 84, 39]
MINIMUM_AREA = 1
PAGE_SIZE = 500
CACHE = Path(tempfile.gettempdir()) / "floodguard-rgi7"


def indus_basin():
    response = httpx.get(BASIN_URL, timeout=120, follow_redirects=True)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        files = {Path(name).suffix: name for name in archive.namelist()}
        reader = shapefile.Reader(**{extension[1:]: io.BytesIO(archive.read(files[extension]))
                                    for extension in (".shp", ".shx", ".dbf")})
        records = [(record.record.as_dict(), make_valid(shape(record.shape.__geo_interface__)))
                   for record in reader.iterShapeRecords()]
    main_ids = {record["MAIN_BAS"] for record, geometry in records if geometry.covers(Point(68.85, 27.69))}
    if len(main_ids) != 1:
        raise ValueError("Sukkur must identify one connected Indus main basin")
    main_id = main_ids.pop()
    basin = unary_union([geometry for record, geometry in records if record["MAIN_BAS"] == main_id])
    if not basin.covers(Point(78.72, 31.8)):
        raise ValueError("Indus extract must include transboundary Sutlej headwaters")
    return basin, int(main_id)


def glacier_page(region, offset):
    cache_file = CACHE / f"{region}_area{MINIMUM_AREA}_{offset}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    params = {
        "service": "WFS", "version": "1.0.0", "request": "GetFeature",
        "typeName": f"GLIMS:RGI2000-v7.0-G-{region}_epsg3857",
        "outputFormat": "application/json", "srsName": "EPSG:4326",
        "cql_filter": f"BBOX(the_geom,65,28,84,39,'EPSG:4326') AND area_km2>={MINIMUM_AREA}",
        "sortBy": "rgi_id", "maxFeatures": PAGE_SIZE, "startIndex": offset,
    }
    response = httpx.get(GLACIER_URL, params=params, timeout=120, follow_redirects=True)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload.get("totalFeatures"), int) or "features" not in payload:
        raise ValueError(f"Invalid RGI response for {region}")
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return payload


def main():
    basin, main_id = indus_basin()
    pakistan = unary_union([shape(feature["geometry"]) for feature in
                            json.loads((DATA / "pakistan_admin1.geojson").read_text(encoding="utf-8"))["features"]])
    prepared_basin, prepared_pakistan = prep(basin), prep(pakistan)
    raw = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        for region in REGIONS:
            first = glacier_page(region, 0)
            total = first["totalFeatures"]
            pages = list(executor.map(lambda offset: glacier_page(region, offset), range(PAGE_SIZE, total, PAGE_SIZE)))
            features = first["features"] + [feature for page in pages for feature in page["features"]]
            if len(features) != total or len({feature["properties"]["rgi_id"] for feature in features}) != total:
                raise ValueError(f"Incomplete or duplicated RGI pages for {region}")
            print(f"{region}: {total} outlines", flush=True)
            raw.extend(features)
    features = []
    for feature in raw:
        properties = feature["properties"]
        geometry = make_valid(force_2d(shape(feature["geometry"])))
        if geometry.geom_type == "GeometryCollection":
            geometry = unary_union([part for part in geometry.geoms if part.geom_type in ("Polygon", "MultiPolygon")])
        if geometry.geom_type not in ("Polygon", "MultiPolygon") or geometry.is_empty:
            raise ValueError(f"Invalid glacier polygon: {properties['rgi_id']}")
        point = geometry.representative_point()
        connected = prepared_basin.covers(point)
        connection = "pakistan_contributor" if connected else "divide_uncertain" if prepared_basin.intersects(geometry) else "other_basin"
        outside = not prepared_pakistan.covers(point)
        features.append({
            "type": "Feature", "id": properties["rgi_id"],
            "properties": {
                "id": properties["rgi_id"], "name": properties.get("glac_name") or properties["rgi_id"],
                "glims_id": properties["glims_id"], "area_km2": round(properties["area_km2"], 3),
                "source_date": properties["src_date"], "source": "Randolph Glacier Inventory 7.0 / GLIMS",
                "connection": connection, "outside_pakistan_boundary": outside,
                "highlight": "external_contributor" if connected and outside else connection,
                "drainage": "Indus river system" if connected else "Indus drainage divide" if connection == "divide_uncertain" else "Neighboring drainage",
                "main_basin_id": main_id if connected else None,
                "latitude": round(point.y, 6), "longitude": round(point.x, 6),
            },
            "geometry": mapping(geometry.simplify(0.0005, preserve_topology=True)),
        })
    counts = {status: sum(feature["properties"]["connection"] == status for feature in features)
              for status in ("pakistan_contributor", "divide_uncertain", "other_basin")}
    counts["external_contributors"] = sum(feature["properties"]["highlight"] == "external_contributor" for feature in features)
    assert counts["external_contributors"] > 0 and counts["other_basin"] > 0
    metadata = {
        "source": "Randolph Glacier Inventory 7.0 / GLIMS", "source_url": "https://rgidata.org/",
        "service_url": GLACIER_URL, "basin_source": "HydroBASINS v1c Asia level 3", "basin_source_url": BASIN_URL,
        "main_basin_id": main_id, "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "extent": EXTENT, "minimum_area_km2": MINIMUM_AREA, "simplification_degrees": 0.0005,
        "feature_count": len(features), "counts": counts,
        "classification": "Representative point inside connected Indus MAIN_BAS polygons; intersecting outlines with points outside are uncertain at the drainage divide.",
        "boundary_scope": "Inside/outside the portal's Pakistan operational ADM1 footprint; not a sovereignty classification.",
        "note": "RGI 7 inventory snapshot, targeting year 2000. Regional outlines >=1 km2; not all small glaciers. Drainage potential, not measured meltwater discharge, GLOF probability or current glacier extent.",
        "attribution": "RGI 7.0 Consortium (2023), doi:10.5067/f6jmovy5navz; Lehner & Grill (2013), doi:10.1002/hyp.9740",
    }
    for filename, collection in (
        ("glaciers.geojson", {"type": "FeatureCollection", "metadata": metadata, "features": features}),
        ("glacier_indus_basin.geojson", {"type": "FeatureCollection", "metadata": {"source": metadata["basin_source"], "source_url": BASIN_URL},
                                       "features": [{"type": "Feature", "properties": {"name": "Indus drainage", "main_basin_id": main_id},
                                                     "geometry": mapping(basin.simplify(0.005, preserve_topology=True))}]}),
    ):
        (DATA / filename).write_text(json.dumps(collection, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Generated {len(features)} glaciers: {counts}", flush=True)


if __name__ == "__main__":
    main()
