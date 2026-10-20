"""Export native USACE HEC-RAS 2025 2D cell depths as georeferenced replay PNGs.

Source: official Simple_Plans tutorial; only complete, CRC-checked ZIP members
are used. Frames are sampled every two hours from actual ten-minute solver output.
No geometry, depth, or time interpolation is performed.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import h5py
import numpy as np
from PIL import Image, ImageDraw
from pyproj import CRS, Transformer

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tools/hec_ras/tutorial_recovered/Simple_Plans/Results"
DEST = ROOT / "frontend/public/hec-ras-2d"
PLANS = (("400ft", "1c. 400ft nCh wCh"), ("200ft", "2a. 200ft wCh1"))
METRES_PER_FOOT = 0.3048
WIDTH, HEIGHT = 1400, 850
FRAME_INDICES = tuple(range(72, 649, 12))  # 12 to 108 h, every 2 h


def shade(depth_m):
    if depth_m < 0.1:
        return None
    stops = ((0.1, (96, 236, 248)), (0.3, (47, 185, 234)),
             (0.8, (17, 118, 218)), (1.6, (26, 67, 189)),
             (3.0, (38, 28, 153)), (5.0, (96, 31, 143)))
    for (lo, a), (hi, b) in zip(stops, stops[1:]):
        if depth_m <= hi:
            t = (depth_m - lo) / (hi - lo)
            return tuple(round(a[i] * (1-t) + b[i]*t) for i in range(3)) + (207,)
    return stops[-1][1] + (215,)


def cell_polygons(mesh, to_mercator, extent):
    nodes = mesh["Node Coordinates"][:]
    centres = mesh["Cell Coordinates"][:]
    faces = mesh["Face Data"][:]
    links = defaultdict(set)
    for left, right, u, v in faces:
        for cell in (left, right):
            if 0 <= cell < len(centres):
                links[int(cell)].update((int(u), int(v)))
    minx, miny, maxx, maxy = extent
    pixels = []
    areas = []
    for cell in range(len(centres)):
        vertices = nodes[list(links[cell])]
        cx, cy = centres[cell]
        vertices = vertices[np.argsort(np.arctan2(vertices[:, 1]-cy, vertices[:, 0]-cx))]
        # Shoelace area in US survey feet²; report wet area in km².
        area = abs(np.dot(vertices[:, 0], np.roll(vertices[:, 1], 1)) -
                   np.dot(vertices[:, 1], np.roll(vertices[:, 0], 1))) / 2
        areas.append(area * (1200/3937)**2 / 1_000_000)
        xx, yy = to_mercator.transform(vertices[:, 0], vertices[:, 1])
        pixels.append([(round((x-minx)/(maxx-minx)*(WIDTH-1)),
                        round((maxy-y)/(maxy-miny)*(HEIGHT-1))) for x, y in zip(xx, yy)])
    return pixels, np.asarray(areas)


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    with h5py.File(SOURCE / (PLANS[0][1]+".h5")) as result:
        crs = CRS.from_wkt(result.attrs["Project Projection"].decode())
        assert crs.to_epsg() == 2227
        mercator = Transformer.from_crs(crs, 3857, always_xy=True)
        lonlat = Transformer.from_crs(3857, 4326, always_xy=True)
        mesh = result["Geometry/2D Flow Areas/Mesh"]
        xx, yy = mercator.transform(mesh["Node Coordinates"][:, 0], mesh["Node Coordinates"][:, 1])
        pad_x, pad_y = (max(xx)-min(xx))*.06, (max(yy)-min(yy))*.10
        extent = (float(min(xx)-pad_x), float(min(yy)-pad_y),
                  float(max(xx)+pad_x), float(max(yy)+pad_y))
        bounds = [list(lonlat.transform(extent[0], extent[3])),
                  list(lonlat.transform(extent[2], extent[3])),
                  list(lonlat.transform(extent[2], extent[1])),
                  list(lonlat.transform(extent[0], extent[1]))]
    manifest = {
        "study": "Merced River, Yosemite Valley, California",
        "source": "USACE HEC-RAS 2025 Beta Simple_Plans tutorial",
        "source_url": "https://www.hec.usace.army.mil/confluence/rasdocs/hecras/latest/tutorials/plans-and-results",
        "source_archive_complete": False,
        "source_members_crc_checked": True,
        "input_event": "January 1997 Event (official tutorial label)",
        "simulation_start": "1997-01-01 00:00:00 (model time)",
        "status": "Demonstration only; not a Pakistan flood simulation or forecast",
        "solver": "HEC-RAS 2025 Beta CPU, Diffusion Wave Equation",
        "time_step_minutes": 1,
        "native_output_interval_minutes": 10,
        "display_interval_hours": 2,
        "display_start_hours": 12,
        "display_end_hours": 108,
        "depth_unit": "m",
        "minimum_shown_depth_m": 0.1,
        "bounds_lonlat": bounds,
        "plans": [],
    }
    for slug, name in PLANS:
        source = SOURCE / (name + ".h5")
        with h5py.File(source) as h:
            mesh = h["Geometry/2D Flow Areas/Mesh"]
            polygons, areas = cell_polygons(mesh, mercator, extent)
            dataset = h["Results/Output Blocks/Base Output/2D Flow Areas/Mesh/Cell Depth"]
            times = h["Results/Output Blocks/Base Output/Time"][:]
            assert len(dataset) == len(times) == 649
            assert len(polygons) == dataset.shape[1]
            bc = h["Boundary Conditions/BC Lines/Attributes"][:]
            assert b"Merced Inflow" in bc["Name"]
            plan = {"id": slug, "name": name, "mesh_spacing_ft": int(slug[:-2]),
                    "cell_count": len(polygons), "result_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "frames": []}
            folder = DEST / slug
            folder.mkdir(exist_ok=True)
            for index in FRAME_INDICES:
                depths = dataset[index] * METRES_PER_FOOT
                canvas = Image.new("RGBA", (WIDTH, HEIGHT))
                paint = ImageDraw.Draw(canvas, "RGBA")
                wet = depths >= 0.1
                # Paint each *solver cell*, using its native depth; leave dry cells transparent.
                for cell, polygon in enumerate(polygons):
                    if wet[cell]:
                        paint.polygon(polygon, fill=shade(float(depths[cell])))
                path = folder / f"depth-{index:03d}.png"
                canvas.save(path, optimize=True)
                hours = round(float(times[index])*24, 4)
                date_label = (datetime(1997, 1, 1) + timedelta(hours=hours)).strftime("%d %b %Y · %H:%M")
                plan["frames"].append({"hour": hours, "date_label": date_label, "image": f"{slug}/{path.name}",
                                       "wet_area_km2": round(float(areas[wet].sum()), 3),
                                       "max_depth_m": round(float(depths.max()), 3),
                                       "wet_cells": int(wet.sum())})
            manifest["plans"].append(plan)
            print(name, len(plan["frames"]), "frames", len(polygons), "cells", flush=True)
    (DEST / "results.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8")
    print("Map bounds", bounds)


if __name__ == "__main__":
    main()
