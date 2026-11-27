"""Rebuild the map's catchment file from the original HydroBASINS polygons, without gaps or overlaps.

The catchments came from a web map service that simplified each sub-basin on its own (0.005 deg), which left
slivers of up to ~400 m between neighbours, plus five invalid polygons. This script takes the same sub-basins
from the original HydroBASINS v1c level-5 download (free; Asia, plus Europe/Middle East for the western ones),
and simplifies them so that every boundary two sub-basins share is simplified once and used by both. The
result is valid, neighbours share exact edges, and the only gaps are the holes the original data has too.

    python scripts/rebuild_catchments_from_hydrobasins.py            # rebuild frontend/src/data/pakistan/catchment_areas.geojson
    python scripts/rebuild_catchments_from_hydrobasins.py --tolerance 0.002 --out other.geojson

Sub-basins keep their ids, names and published areas; each gains its HydroBASINS id (hybas_id), which later
runs use to match. Sub-basins under 1 km2 are left out. The downloads are cached in .local-cache/hydrobasins.
"""
from __future__ import annotations

import argparse
import json
import struct
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

from pyproj import Geod
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from shapely.validation import make_valid

ROOT = Path(__file__).resolve().parents[1]
CATCHMENTS = ROOT / "frontend" / "src" / "data" / "pakistan" / "catchment_areas.geojson"
CACHE = ROOT / ".local-cache" / "hydrobasins"
REGIONS = ("as", "eu")  # Pakistan's sub-basins are in the Asia file; the western ones in Europe/Middle East
URL = "https://data.hydrosheds.org/file/HydroBASINS/standard/hybas_{region}_lev05_v1c.zip"
geod = Geod(ellps="WGS84")


# ---- HydroBASINS shapefiles (read directly: polygons and their dBASE attributes) ------------------------------
def read_dbf(path: Path) -> list[dict]:
    data = path.read_bytes()
    n, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields, pos = [], 32
    while data[pos] != 0x0D:
        fields.append((data[pos:pos + 11].split(b"\0")[0].decode(), chr(data[pos + 11]), data[pos + 16], data[pos + 17]))
        pos += 32
    rows = []
    for i in range(n):
        rec, off, row = data[header_len + i * record_len: header_len + (i + 1) * record_len], 1, {}
        for name, ftype, size, dec in fields:
            raw = rec[off:off + size].decode("latin-1").strip()
            off += size
            row[name] = (float(raw) if dec else int(raw)) if ftype in "NF" and raw else raw
        rows.append(row)
    return rows


def read_shp(path: Path) -> list:
    data, pos, shapes = path.read_bytes(), 100, []
    while pos < len(data):
        _, length = struct.unpack(">ii", data[pos:pos + 8])
        content = data[pos + 8: pos + 8 + length * 2]
        pos += 8 + length * 2
        if struct.unpack("<i", content[:4])[0] == 0:
            shapes.append(None)
            continue
        nparts, npoints = struct.unpack("<ii", content[36:44])
        parts = list(struct.unpack(f"<{nparts}i", content[44:44 + 4 * nparts]))
        coords = struct.unpack(f"<{2 * npoints}d", content[44 + 4 * nparts: 44 + 4 * nparts + 16 * npoints])
        points = [(coords[2 * i], coords[2 * i + 1]) for i in range(npoints)]
        shapes.append([points[parts[k]:(parts[k + 1] if k + 1 < nparts else npoints)] for k in range(nparts)])
    return shapes


def rings_to_geometry(rings):
    """Shapefile rings: outer rings clockwise, holes counter-clockwise."""
    outers = [r for r in rings if not Polygon(r).exterior.is_ccw]
    holes = [r for r in rings if Polygon(r).exterior.is_ccw]
    polys, assigned = [Polygon(o) for o in outers], [[] for _ in outers]
    for h in holes:
        for i, p in enumerate(polys):
            if p.contains(Polygon(h).representative_point()):
                assigned[i].append(h)
                break
    result = [orient(Polygon(o, assigned[i]), 1.0) for i, o in enumerate(outers)]
    return result[0] if len(result) == 1 else MultiPolygon(result)


def hydrobasins(bounds) -> list[tuple[dict, object]]:
    minx, miny, maxx, maxy = bounds
    found = []
    for region in REGIONS:
        folder = CACHE / f"hybas_{region}_lev05_v1c"
        stem = folder / f"hybas_{region}_lev05_v1c"
        if not stem.with_suffix(".shp").exists():
            folder.mkdir(parents=True, exist_ok=True)
            archive = folder / "download.zip"
            print(f"downloading {URL.format(region=region)}")
            request = urllib.request.Request(URL.format(region=region), headers={"User-Agent": "floodguard-catchment-rebuild"})
            archive.write_bytes(urllib.request.urlopen(request, timeout=600).read())
            with zipfile.ZipFile(archive) as z:
                for name in z.namelist():
                    if name.endswith((".shp", ".dbf", ".prj")):
                        (folder / Path(name).name).write_bytes(z.read(name))
            archive.unlink()
        for attrs, rings in zip(read_dbf(stem.with_suffix(".dbf")), read_shp(stem.with_suffix(".shp"))):
            if not rings:
                continue
            xs = [x for r in rings for x, _ in r]
            ys = [y for r in rings for _, y in r]
            if max(xs) >= minx and min(xs) <= maxx and max(ys) >= miny and min(ys) <= maxy:
                found.append((attrs, rings_to_geometry(rings)))
    return found


# ---- Shared-edge simplification ---------------------------------------------------------------------------------
KEY = lambda p: (round(p[0], 7), round(p[1], 7))  # HydroBASINS vertices sit on a 15-arc-second grid


def simplify_shared(originals: list[tuple[dict, object]], tol: float) -> list[tuple[dict, object]]:
    features = []
    for props, geometry in originals:
        g = geometry if geometry.is_valid else make_valid(geometry)
        if g.geom_type == "GeometryCollection":
            g = unary_union([p for p in g.geoms if p.geom_type in ("Polygon", "MultiPolygon")])
        polys = [[[KEY(c) for c in p.exterior.coords[:-1]], [[KEY(c) for c in r.coords[:-1]] for r in p.interiors]]
                 for p in (g.geoms if isinstance(g, MultiPolygon) else [g])]
        features.append((props, polys))

    edge_users = defaultdict(set)
    for fi, (_, polys) in enumerate(features):
        for ext, holes in polys:
            for r in [ext, *holes]:
                for i in range(len(r)):
                    a, b = r[i], r[(i + 1) % len(r)]
                    edge_users[(a, b) if a < b else (b, a)].add(fi)
    neighbours = defaultdict(set)
    for a, b in edge_users:
        neighbours[a].add(b)
        neighbours[b].add(a)
    users = lambda a, b: frozenset(edge_users[(a, b) if a < b else (b, a)])

    def is_junction(r, i):
        v, prev, nxt = r[i], r[i - 1], r[(i + 1) % len(r)]
        return len(neighbours[v]) != 2 or users(prev, v) != users(v, nxt)

    cache, arc_tol = {}, {}
    canon = lambda arc: min(tuple(arc), tuple(reversed(arc)))

    def simplify_arc(arc, used):
        c = canon(arc)
        used.append(c)
        t = arc_tol.get(c, tol)
        if (c, t) not in cache:
            cache[(c, t)] = list(LineString(list(c)).simplify(t, preserve_topology=False).coords) if len(c) > 2 else list(c)
        return cache[(c, t)] if tuple(arc) == c else list(reversed(cache[(c, t)]))

    def simplify_ring(r, used):
        n, junctions = len(r), [i for i in range(len(r)) if is_junction(r, i)]
        if not junctions:  # a ring touching no neighbour (island, lake)
            s = simplify_arc(r + [r[0]], used)
            return s[:-1] if len(s) >= 4 else r
        out = []
        for k, j in enumerate(junctions):
            nxt = junctions[(k + 1) % len(junctions)]
            out.extend(simplify_arc([r[(j + t) % n] for t in range(((nxt - j) % n or n) + 1)], used)[:-1])
        return out

    def build():
        result = []
        for props, polys in features:
            parts, used = [], []
            for ext, holes in polys:
                e = simplify_ring(ext, used)
                hs = [h for h in (simplify_ring(h, used) for h in holes) if len(h) >= 3]
                if len(e) >= 3:
                    parts.append(orient(Polygon(e, hs), 1.0))
            result.append((props, parts[0] if len(parts) == 1 else MultiPolygon(parts), used))
        return result

    # Lower the tolerance where simplified stretches cross; a polygon still invalid at a quarter of it is not a
    # simplification problem (basin 1719's near-touch, repaired after rounding), so its stretches go back.
    for _ in range(3):
        result = build()
        bad = [used for _, geom, used in result if not geom.is_valid]
        if not bad:
            break
        for used in bad:
            for c in used:
                arc_tol[c] = arc_tol.get(c, tol) / 2
    else:
        for _, geom, used in build():
            if not geom.is_valid:
                for c in used:
                    arc_tol.pop(c, None)
        result = build()
    return [(p, g) for p, g, _ in result]


def rounded(geometry):
    rnd = lambda ring: [[round(x, 5), round(y, 5)] for x, y in ring]
    g = mapping(geometry)
    coords = [rnd(r) for r in g["coordinates"]] if g["type"] == "Polygon" else [[rnd(r) for r in p] for p in g["coordinates"]]
    out = shape({"type": g["type"], "coordinates": coords})
    if not out.is_valid:  # rounding can make a boundary that passes within a centimetre of itself touch itself
        out = make_valid(out)
        if out.geom_type == "GeometryCollection":
            out = unary_union([x for x in out.geoms if x.geom_type in ("Polygon", "MultiPolygon")])
    return json.loads(json.dumps(mapping(out)))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tolerance", type=float, default=0.003, help="simplification in degrees (default 0.003, ~300 m)")
    parser.add_argument("--out", type=Path, default=CATCHMENTS)
    args = parser.parse_args()

    app = json.loads(CATCHMENTS.read_text(encoding="utf-8"))
    bounds = unary_union([shape(f["geometry"]) for f in app["features"]]).buffer(1).bounds
    candidates = hydrobasins(bounds)
    by_id = {a["HYBAS_ID"]: (a, g) for a, g in candidates}
    matched = []
    for f in app["features"]:
        hid = f["properties"].get("hybas_id")
        if hid in by_id:
            attrs, geometry = by_id[hid]
        else:  # first run: the original sub-basin overlapping this one most
            own = shape(f["geometry"]).buffer(0)
            attrs, geometry = max(candidates, key=lambda c: c[1].intersection(own).area if c[1].intersects(own) else 0)
        props = {k: f["properties"][k] for k in ("basin_id", "name", "area_km2", "source", "level")}
        props["hybas_id"] = attrs["HYBAS_ID"]
        matched.append((props, geometry))
    ids = [p["hybas_id"] for p, _ in matched]
    assert len(ids) == len(set(ids)), "two app sub-basins matched the same HydroBASINS polygon"

    features, dropped = [], []
    for props, geometry in simplify_shared(matched, args.tolerance):
        if abs(geod.geometry_area_perimeter(geometry)[0]) / 1e6 < 1:
            dropped.append(props["basin_id"])
            continue
        features.append({"type": "Feature", "properties": props, "geometry": rounded(geometry)})
    earlier = set(app.get("metadata", {}).get("dropped_under_1_km2", [])) | set(app.get("metadata", {}).get("geometry_repair", {}).get("dropped_under_1_km2", []))
    meta = {k: v for k, v in app.get("metadata", {}).items() if k not in ("service_url", "geometry_repair")}
    meta.update({
        "source_url": "https://www.hydrosheds.org/products/hydrobasins",
        "download_url": "https://data.hydrosheds.org/file/HydroBASINS/standard/hybas_as_lev05_v1c.zip (and hybas_eu_lev05_v1c.zip for the western sub-basins)",
        "simplification_degrees": args.tolerance,
        "simplification": "topology-preserving: each boundary shared by two sub-basins is simplified once and used by both, so neighbours share exact edges",
        "dropped_under_1_km2": sorted(earlier | set(dropped)),
        "script": "scripts/rebuild_catchments_from_hydrobasins.py",
        "note": "Full transboundary HydroBASINS level 5 sub-basins intersecting the portal's operational ADM1 areas (original v1c polygons, simplified for display without gaps or overlaps). These are sub-basins, not station-specific upstream watersheds.",
    })
    args.out.write_text(json.dumps({"type": "FeatureCollection", "metadata": meta, "features": features}, separators=(",", ":")), encoding="utf-8")
    invalid = [f["properties"]["basin_id"] for f in features if not shape(f["geometry"]).is_valid]
    print(f"wrote {args.out} ({len(features)} sub-basins, {args.out.stat().st_size // 1024} KB); dropped under 1 km2: {dropped}; invalid: {invalid}")


if __name__ == "__main__":
    main()
