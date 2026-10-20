"""Package the completed USACE Muncie 2D floodplain solve for map replay."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import h5py
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.warp import calculate_default_transform
from rasterio.windows import Window, bounds as window_bounds

from models.hec_ras_2d.export_escondida_replay import RAS, ROOT, FOOT_TO_M, sha256, raster_to_png

SAMPLE = ROOT / "tools/hec_ras/samples/muncie"
RUN = ROOT / "tools/hec_ras/runs/muncie_trial"
PUBLIC = ROOT / "frontend/public/hec-ras-2d"
RECORD = Path(__file__).with_name("muncie-inputs.json")
RESULT = RUN / "Results/recomputed_dwe.h5"
RASTER_RESOLUTION_FT = 10
HOURS = range(25)
DEPTH_STOPS_M = np.array([0.1, 0.5, 1.0, 2.0, 4.0, 8.0])
DEPTH_COLORS = np.array([[73, 218, 248], [44, 181, 239], [30, 122, 224],
                         [37, 82, 202], [64, 55, 170], [131, 50, 160]])


def source_hashes() -> dict[str, str]:
    return {str(path.relative_to(SAMPLE)).replace("\\", "/"): sha256(path)
            for path in SAMPLE.rglob("*") if path.is_file() and "Export" not in path.parts}


def verify_record() -> dict:
    sources = source_hashes()
    if RECORD.exists():
        record = json.loads(RECORD.read_text("utf8"))
        if record["source_files_sha256"] != sources:
            raise ValueError("Official Muncie sample files changed")
    else:
        record = {
            "source": "USACE HEC-RAS 2025 sample: Muncie 2025",
            "source_manifest_url": "https://s3.hecdev.net/ras-public-examples/Muncie%202025-2024-Sep-30%2010-37-23.json",
            "sample_command": "ras sample pull 'Muncie 2025' tools/hec_ras/samples/muncie",
            "source_files_sha256": sources,
            "solver_override": "CPU implicit diffusion-wave, 2 cores; native project copied without changing its hydraulic inputs",
        }
    for relative, expected in sources.items():
        if relative == "Geometries/Base Geometry.h5":
            continue  # Native prepare writes fresh hydraulic property tables here.
        if sha256(RUN / relative) != expected:
            raise ValueError(f"Copied Muncie input differs from source: {relative}")
    record["prepared_geometry_sha256"] = sha256(RUN / "Geometries/Base Geometry.h5")
    record["ready_to_run_sha256"] = sha256(RUN / "Plans/Base Plan/Base Plan.dwe.r2r.h5")
    record["computed_result_sha256"] = sha256(RESULT)
    RECORD.write_text(json.dumps(record, indent=2) + "\n", encoding="utf8")
    return record


def map_frame(hour: int) -> Path:
    target = RUN / "Export" / f"depth-{hour:02d}.tif"
    target.parent.mkdir(exist_ok=True)
    command = [str(RAS), "result", "map", str(RESULT), str(target), "--type", "depth",
               "--profile", str(hour), "--terrain", str(RUN / "Terrains/Terrain.h5"),
               "--projection", "EPSG:2965", "--cell-size", str(RASTER_RESOLUTION_FT), "--force"]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    if process.returncode or not target.exists():
        raise RuntimeError(f"HEC-RAS map export failed at hour {hour}: {process.stdout[-500:]} {process.stderr[-500:]}")
    return target


def corners(left: float, bottom: float, right: float, top: float, crs: str) -> list[list[float]]:
    project = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    west, south = project.transform(left, bottom)
    east, north = project.transform(right, top)
    return [[west, north], [east, north], [east, south], [west, south]]


def main() -> None:
    info = subprocess.run([str(RAS), "result", "info", str(RESULT)], capture_output=True, text=True, check=True).stdout
    if "Computed OK:     True" not in info or "Mesh: 7257 cells" not in info or "Profiles:        25" not in info:
        raise ValueError("Muncie result is not a completed 25-profile, 7,257-cell solve")
    with h5py.File(RESULT) as result:
        times = result["Results/Output Blocks/Base Output/Time"][:]
        flow = result["Boundary Conditions/BC Lines/Payloads/Values"][:25]
        rain = float(result["Boundary Conditions/Meteorology/Precipitation"].attrs["Constant"])
        if len(times) != 25 or not np.allclose(times * 24, np.arange(25)) or rain != 0:
            raise ValueError("Unexpected Muncie time or rainfall inputs")
        if not np.isclose(flow.min(), 1000) or not np.isclose(flow.max(), 20000):
            raise ValueError("Unexpected Muncie upstream hydrograph")
    record = verify_record()
    peak = map_frame(24)
    with rasterio.open(peak) as raster:
        transform, width, height = calculate_default_transform(raster.crs, "EPSG:3857", raster.width, raster.height, *raster.bounds)
        map_bounds = rasterio.transform.array_bounds(height, width, transform)
        focus = window_bounds(Window(469, 384, 600, 300), raster.transform)
        mobile_focus = window_bounds(Window(441, 362, 350, 350), raster.transform)
        depth = raster.read(1)
        mask = (depth != raster.nodata) & (depth * FOOT_TO_M >= 0.1)
        focus_fraction = float(np.mean(mask[384:684, 469:1069]))
        if focus_fraction < 0.6:
            raise ValueError("The chosen floodplain focus no longer shows a broad computed flood")
    metadata = {
        "study": "Muncie 2025 · Indiana, USA",
        "source_url": record["source_manifest_url"],
        "status": "computed",
        "solver": "HEC-RAS 2025 Beta 0.1.0.5048, CPU implicit diffusion-wave",
        "result_sha256": record["computed_result_sha256"],
        "terrain_resolution_ft": 5,
        "map_resolution_ft": RASTER_RESOLUTION_FT,
        "cell_count": 7257,
        "minimum_shown_depth_m": 0.1,
        "main_flow_min_cfs": 1000,
        "main_flow_max_cfs": 20000,
        "display_end_hours": 24,
        "depth_legend_labels": ["0.1", "1", "2", "4", "8+"],
        "bounds_lonlat": corners(*map_bounds, "EPSG:3857"),
        "focus_bounds_lonlat": corners(*focus, "EPSG:2965"),
        "mobile_focus_bounds_lonlat": corners(*mobile_focus, "EPSG:2965"),
        "focus_wet_fraction_at_peak": round(focus_fraction, 3),
        "frames": [],
    }
    for hour in HOURS:
        tif = peak if hour == 24 else map_frame(hour)
        relative = f"muncie/depth-{hour:02d}.png"
        area, maximum = raster_to_png(tif, PUBLIC / relative, (transform, width, height), DEPTH_STOPS_M, DEPTH_COLORS)
        metadata["frames"].append({"hour": hour, "image": relative,
                                   "wet_area_km2": round(area, 5), "max_depth_m": round(maximum, 3)})
    (PUBLIC / "muncie-results.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf8")
    print(f"Saved {len(metadata['frames'])} native Muncie floodplain maps; peak focus wet fraction {focus_fraction:.1%}")


if __name__ == "__main__":
    main()
