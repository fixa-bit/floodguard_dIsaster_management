"""Export only completed native HEC-RAS depth maps as a static replay.

The solver maps water-surface elevations against the sample's 5 ft terrain.
PNG resampling is for web display only; it does not refine the 2D mesh.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import h5py
import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject

ROOT = Path(__file__).resolve().parents[2]
RAS = ROOT / "tools/hec_ras/2025-beta/HEC-RAS 2025 Beta/ras.exe"
RUNS = ROOT / "tools/hec_ras/runs"
PUBLIC = ROOT / "frontend/public/hec-ras-2d"
RECORD = Path(__file__).with_name("escondida-inputs.json")
FOOT_TO_M = 1200 / 3937  # US survey foot
THRESHOLD_M = 0.1
HOURS = list(range(0, 49, 2))
CASES = (
    ("mainstem", "Main river only", 0.0, 0.0),
    ("tributary", "Main river + branch", 50.0, 0.0),
    ("tributary_rain", "Main river + branch + rain", 50.0, 0.02),
)
STOPS = np.array([0.1, 0.3, 0.7, 1.1, 1.6, 3.0])
COLORS = np.array([[73, 218, 248], [44, 181, 239], [30, 122, 224],
                   [37, 82, 202], [64, 55, 170], [131, 50, 160]])


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def native_map(case: str, hour: int) -> Path:
    run = RUNS / f"escondida_{case}"
    target = run / "Export" / f"depth-{hour:02d}.tif"
    target.parent.mkdir(exist_ok=True)
    command = [str(RAS), "result", "map", str(run / "Results/recomputed_base_dwe.h5"), str(target),
               "--type", "depth", "--profile", str(hour), "--terrain", str(run / "Terrains/Terrain.h5"),
               "--projection", "EPSG:2258", "--force"]
    process = subprocess.run(command, capture_output=True, text=True, check=False)
    if process.returncode or not target.exists():
        raise RuntimeError(f"Native HEC-RAS map failed for {case} hour {hour}: {process.stdout[-500:]} {process.stderr[-500:]}")
    return target


def raster_to_png(source: Path, output: Path, template: tuple,
                  stops: np.ndarray = STOPS, colors: np.ndarray = COLORS) -> tuple[float, float]:
    transform, width, height = template
    with rasterio.open(source) as raster:
        depth_ft = raster.read(1)
        valid = np.isfinite(depth_ft) & (depth_ft != raster.nodata) & (depth_ft * FOOT_TO_M >= THRESHOLD_M)
        wet_area = float(np.count_nonzero(valid) * abs(raster.res[0] * raster.res[1]) * FOOT_TO_M**2 / 1_000_000)
        max_depth = float(depth_ft[valid].max() * FOOT_TO_M) if valid.any() else 0.0
        warped = np.full((height, width), -9999.0, dtype="float32")
        reproject(source=rasterio.band(raster, 1), destination=warped,
                  src_transform=raster.transform, src_crs=raster.crs, src_nodata=raster.nodata,
                  dst_transform=transform, dst_crs="EPSG:3857", dst_nodata=-9999.0,
                  resampling=Resampling.nearest)
    depths = warped * FOOT_TO_M
    visible = np.isfinite(depths) & (warped != -9999.0) & (depths >= THRESHOLD_M)
    rgba = np.zeros((height, width, 4), dtype="uint8")
    for channel in range(3):
        rgba[:, :, channel] = np.interp(np.clip(depths, stops[0], stops[-1]), stops, colors[:, channel]).astype("uint8")
    rgba[:, :, 3] = np.where(visible, 210, 0).astype("uint8")
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(output, optimize=True)
    return wet_area, max_depth


def main() -> None:
    record = json.loads(RECORD.read_text("utf8"))
    sample = ROOT / "tools/hec_ras/samples/escondida"
    for relative, expected_hash in record["source_files_sha256"].items():
        if sha256(sample / relative) != expected_hash:
            raise ValueError(f"Original sample changed: {relative}")
    metadata = {
        "study": "Escondida Example Project · New Mexico, USA",
        "source_url": "https://s3.hecdev.net/ras-public-examples/Escondida%20Example%20Project-2024-Sep-29%2016-06-28.json",
        "source_provenance": "Official USACE HEC-RAS 2025 sample, copied locally; input SHA-256 in models/hec_ras_2d/escondida-inputs.json",
        "solver": "HEC-RAS 2025 Beta 0.1.0.5048, CPU implicit diffusion-wave",
        "status": "computed",
        "terrain_resolution_ft": 5,
        "cell_count": 906,
        "minimum_shown_depth_m": THRESHOLD_M,
        "display_end_hours": HOURS[-1],
        "main_flow_min_cfs": 300,
        "main_flow_max_cfs": 2800,
        "scenarios": [],
    }
    first_map = native_map("mainstem", HOURS[0])
    with rasterio.open(first_map) as raster:
        transform, width, height = calculate_default_transform(raster.crs, "EPSG:3857", raster.width, raster.height, *raster.bounds)
    bounds = rasterio.transform.array_bounds(height, width, transform)
    to_lonlat = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    west, south = to_lonlat.transform(bounds[0], bounds[1])
    east, north = to_lonlat.transform(bounds[2], bounds[3])
    metadata["bounds_lonlat"] = [[west, north], [east, north], [east, south], [west, south]]
    source_bc = RUNS / "escondida_tributary/Boundary Conditions/Boundary Condition.h5"
    with h5py.File(source_bc) as file:
        points = file["Boundary Conditions/BC Lines/Polyline"][:]
    to_geographic = Transformer.from_crs("EPSG:2258", "EPSG:4326", always_xy=True)
    inlets = []
    for label, pair, color in (("Main upstream inflow", points[0:2], "#f9b84b"),
                               ("Tributary inflow", points[2:4], "#72e3d2")):
        x, y = np.mean(pair, axis=0)
        lon, lat = to_geographic.transform(float(x), float(y))
        inlets.append({"label": label, "lonlat": [lon, lat], "color": color})
    metadata["inlets"] = inlets

    for case, title, branch_cfs, rain in CASES:
        run = RUNS / f"escondida_{case}"
        result = run / "Results/recomputed_base_dwe.h5"
        if not result.exists():
            raise FileNotFoundError(result)
        info = subprocess.run([str(RAS), "result", "info", str(result)], capture_output=True, text=True, check=True).stdout
        if "Computed OK:     True" not in info or "Mesh: 906 cells" not in info or "Profiles:        49" not in info:
            raise ValueError(f"Not a completed expected 906-cell result: {result}")
        with h5py.File(result) as file:
            rain_actual = float(file["Boundary Conditions/Meteorology/Precipitation"].attrs["Constant"])
            payloads = file["Boundary Conditions/BC Lines/Payloads/Payloads"][:]
            branch_actual = float(payloads[1]["Constant"])
            times = file["Results/Output Blocks/Base Output/Time"][:]
            assert len(times) == 49 and np.allclose(times * 24, np.arange(49))
            assert abs(rain_actual - rain) < 1e-6 and branch_actual == branch_cfs
        recorded = next(entry for entry in record["cases"] if entry["id"] == case)
        assert sha256(run / "Boundary Conditions/Boundary Condition.h5") == recorded["boundary_condition_sha256"]
        assert sha256(run / "Escondida Example Project.ras") == recorded["project_association_sha256"]
        scenario = {"id": case, "name": title, "branch_cfs": branch_cfs, "rain_in_per_hr": rain,
                    "result_sha256": sha256(result), "frames": []}
        for hour in HOURS:
            tif = native_map(case, hour)
            relative = f"escondida/{case}/depth-{hour:02d}.png"
            area, maximum = raster_to_png(tif, PUBLIC / relative, (transform, width, height))
            scenario["frames"].append({"hour": hour, "image": relative,
                                       "wet_area_km2": round(area, 5), "max_depth_m": round(maximum, 3)})
        metadata["scenarios"].append(scenario)
        print(f"Exported {case}: {len(scenario['frames'])} verified frames; last wet area {area:.3f} km²")
    (PUBLIC / "escondida-results.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf8")
    print("Saved", PUBLIC / "escondida-results.json")


if __name__ == "__main__":
    main()
