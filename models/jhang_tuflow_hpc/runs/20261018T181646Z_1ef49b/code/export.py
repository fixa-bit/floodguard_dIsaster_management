"""Preserve completed TUFLOW outputs and publish a replay with actual cell values."""
import argparse
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.warp import calculate_default_transform, reproject, Resampling

from .run import HERE, ROOT, sha256, write_json


def read_grid(path):
    with rasterio.open(path) as source:
        values = source.read(1, masked=True).filled(np.nan)
        if source.crs.to_epsg() != 32643:
            raise ValueError("Unexpected result CRS")
        return values, source.profile.copy(), source.bounds


def parse_seconds(path):
    match = re.search(r"_(\d{3})_(\d{2})_(\d{2})\.tif$", path.name)
    return int(match[1]) * 3600 + int(match[2]) * 60 + int(match[3]) if match else None


def export(folder):
    folder = Path(folder).resolve()
    if (folder / "RUN_MANIFEST.json").exists():
        raise ValueError("Cannot change a sealed run")
    config = json.loads((folder / "inputs/config.json").read_text())
    status = json.loads((folder / "engine_status.json").read_text())
    log = (folder / "engine_console.log").read_bytes().decode("cp1252", errors="replace")
    if status["exit_code"] or "Simulation FINISHED" not in log or "Solution Scheme" not in log:
        raise ValueError("Cannot publish an incomplete TUFLOW run")
    nan_retries = int(re.search(r"HPC NaN Repeated Timesteps:\s*(\d+)", log)[1])
    high_control_retries = int(re.search(r"HPC HCN Repeated Timesteps:\s*(\d+)", log)[1])
    if nan_retries:
        raise ValueError("Solver reported instability retries; review before publishing")
    if config["duration_seconds"] > 600 or config["cell_count"] > 30000:
        raise ValueError("Custom demo exceeds the documented licence-free limits")
    with (folder / "results/Jhang_HPC_Demo_MB.csv").open(newline="") as handle:
        mass = [{key.strip(): float(value) for key, value in row.items() if value.strip()} for row in csv.DictReader(handle)]
    max_mass_error = max(abs(row["Cum ME (%)"]) / 100 for row in mass)
    expected_volume = np.trapezoid(np.asarray(config["inflow_hydrograph_seconds_cumecs"])[:, 1], np.asarray(config["inflow_hydrograph_seconds_cumecs"])[:, 0])
    np.testing.assert_allclose(mass[-1]["Tot Vol"], expected_volume, rtol=.001)
    if max_mass_error > .001:
        raise ValueError("TUFLOW volume-balance error exceeds 0.1%")
    portal = folder / "portal"
    (portal / "frames").mkdir(parents=True, exist_ok=True)
    files = sorted((folder / "results/grids").glob("Jhang_HPC_Demo_d_*.tif"))
    files = [path for path in files if parse_seconds(path) is not None and parse_seconds(path) <= 600]
    frames, depths, speeds = [], [], []
    lonlat = Transformer.from_crs(32643, 4326, always_xy=True)
    to_geo = Transformer.from_crs(3857, 4326, always_xy=True)
    with rasterio.open(folder / "model/grid/dem.tif") as terrain:
        first, profile, bounds = read_grid(files[0])
        height, width = first.shape
        transform = profile["transform"]
        display_transform, display_w, display_h = calculate_default_transform(32643, 3857, width, height, *bounds)
        merc_bounds = rasterio.transform.array_bounds(display_h, display_w, display_transform)
        image_coordinates = [to_geo.transform(x, y) for x, y in ((merc_bounds[0], merc_bounds[3]), (merc_bounds[2], merc_bounds[3]), (merc_bounds[2], merc_bounds[1]), (merc_bounds[0], merc_bounds[1]))]
        dem = np.full((display_h, display_w), np.nan, dtype="float32")
        reproject(rasterio.band(terrain, 1), dem, src_transform=terrain.transform, src_crs=terrain.crs,
                  dst_transform=display_transform, dst_crs=3857, dst_nodata=np.nan, resampling=Resampling.bilinear)
    valid = np.isfinite(dem)
    filled = np.where(valid, dem, np.nanmedian(dem))  # Lighting only; no numeric model terrain is filled.
    gy, gx = np.gradient(filled)
    shade = np.clip(.65 - gx * .15 + gy * .15, 0, 1)
    background = np.zeros((display_h, display_w, 4), dtype="uint8")
    background[:, :, 0] = 70 + shade * 110; background[:, :, 1] = 80 + shade * 110; background[:, :, 2] = 65 + shade * 110
    background[:, :, 3] = np.where(valid, 255, 0)
    Image.fromarray(background).save(portal / "terrain.png")
    rows, cols = np.indices((height, width))
    xx = transform.c + (cols + .5) * transform.a
    yy = transform.f + (rows + .5) * transform.e
    longitude, latitude = lonlat.transform(xx, yy)
    pixel_area = abs(transform.a * transform.e)
    wet_bounds = []
    for index, path in enumerate(files):
        seconds = parse_seconds(path)
        depth, _, _ = read_grid(path)
        speed, _, _ = read_grid(path.with_name(path.name.replace("_d_", "_V_")))
        depths.append(depth); speeds.append(speed)
        wet = np.isfinite(depth) & (depth >= .1)
        observed = []
        for rr, cc in zip(*np.where(wet), strict=True):
            observed.append({"type": "Feature", "properties": {"row": int(rr), "column": int(cc), "depth_m": float(depth[rr, cc]), "speed_m_s": float(speed[rr, cc]) if np.isfinite(speed[rr, cc]) else None},
                             "geometry": {"type": "Point", "coordinates": [float(longitude[rr, cc]), float(latitude[rr, cc])]}})
        write_json(portal / "frames" / f"{index:03d}.geojson", {"type": "FeatureCollection", "features": observed})
        if wet.any():
            wet_bounds.extend(zip(longitude[wet].tolist(), latitude[wet].tolist()))
        for label, array, maximum in (("depth", depth, 2.), ("speed", speed, 3.)):
            display = np.full((display_h, display_w), np.nan, dtype="float32")
            # Only the displayed image is reprojected. Scalar metrics and point
            # inspection retain the original TUFLOW output-grid values.
            source = np.where(wet & np.isfinite(array), array, np.nan).astype("float32")
            reproject(source, display, src_transform=transform, src_crs=32643, src_nodata=np.nan,
                      dst_transform=display_transform, dst_crs=3857, dst_nodata=np.nan, resampling=Resampling.nearest)
            fraction = np.clip(np.nan_to_num(display) / maximum, 0, 1)
            rgba = np.zeros((display_h, display_w, 4), dtype="uint8")
            if label == "depth":
                rgba[:, :, 0] = 40 - fraction * 32; rgba[:, :, 1] = 205 - fraction * 135; rgba[:, :, 2] = 245 - fraction * 70
            else:
                rgba[:, :, 0] = 255; rgba[:, :, 1] = 225 - fraction * 175; rgba[:, :, 2] = 85 - fraction * 65
            rgba[:, :, 3] = np.where(np.isfinite(display), 225, 0)
            Image.fromarray(rgba).save(portal / "frames" / f"{index:03d}-{label}.png", optimize=True)
        m = mass[index]
        frames.append({"elapsed_seconds": seconds, "depth_image": f"frames/{index:03d}-depth.png", "speed_image": f"frames/{index:03d}-speed.png", "points": f"frames/{index:03d}.geojson",
                       "wet_area_km2": float(wet.sum() * pixel_area / 1e6), "maximum_depth_m": float(np.nanmax(depth)) if np.isfinite(depth).any() else 0,
                       "maximum_speed_m_s": float(np.nanmax(speed[wet])) if wet.any() else 0,
                       "water_volume_m3": m["Tot Vol"], "relative_mass_error": abs(m["Cum ME (%)"]) / 100})
    if len(frames) != 31 or frames[0]["elapsed_seconds"] != 0 or frames[-1]["elapsed_seconds"] != 600:
        raise ValueError("Expected all 31 native TUFLOW output times from 0 through 600 seconds")
    np.savez_compressed(folder / "output_grids.npz", depth=np.stack(depths), speed=np.stack(speeds),
                        times=np.asarray([row["elapsed_seconds"] for row in frames]), transform=np.asarray(tuple(transform)), bounds=np.asarray(bounds))
    for name, source in (("maximum-depth.tif", "Jhang_HPC_Demo_d_Max.tif"), ("maximum-speed.tif", "Jhang_HPC_Demo_V_Max.tif")):
        shutil.copy2(folder / "results/grids" / source, portal / name)
    shutil.copy2(folder / "results/Jhang_HPC_Demo_MB.csv", portal / "mass-balance.csv")
    shutil.copy2(folder / "inputs/NOTICE.txt", portal / "NOTICE.txt")
    shutil.copy2(folder / "inputs/mapped-waterways.geojson", portal / "waterways.geojson")
    values = np.asarray(wet_bounds)
    focus = [float(values[:, 0].min()-.002), float(values[:, 1].min()-.002), float(values[:, 0].max()+.002), float(values[:, 1].max()+.002)]
    config["active_cells_engine"] = int(re.search(r"Number active cells\s*=\s*(\d+)", log)[1])
    checks = {"successful_solver_exit": True, "completion_marker": True, "nan_repeated_timesteps": nan_retries,
              "high_control_number_retries": high_control_retries, "maximum_relative_mass_error": max_mass_error,
              "independently_integrated_inflow_m3": float(expected_volume), "final_water_volume_m3": mass[-1]["Tot Vol"],
              "depth_exports": "Native 30m TUFLOW GeoTIFFs; dry/inactive output cells remain masked in the retained numeric arrays"}
    results = {"run_id": folder.name, "solver": "TUFLOW HPC", "version": config["version"], "hardware": config["hardware"],
               "licence_mode": "Demo Model ON; retained playback of one permitted ten-minute simulation", "duration_seconds": 600,
               "calibrated": False, "config": config, "checks": checks, "frames": frames,
               "image_coordinates": image_coordinates, "focus_bounds": focus,
               "study_bounds": [min(x[0] for x in image_coordinates), min(x[1] for x in image_coordinates), max(x[0] for x in image_coordinates), max(x[1] for x in image_coordinates)],
               "limitations": ["Hypothetical inflow and initially dry terrain; not an observed event or future forecast.",
                               "One ten-minute custom demo run, not a stitched or accelerated multi-hour simulation.",
                               "No channel bathymetry, structure/gate survey or calibration against observed Jhang floods.",
                               "Real 30m Copernicus surface terrain; mesh refinement cannot create missing channel or building detail.",
                               "Wet area is calculated from exported raster cells at depth >=0.1m; it is not a surveyed flood footprint.",
                               "Velocity displayed is computed scalar speed; no artificial flow vectors are added."],
               "source_metadata": "Copied source metadata, geometry, control files, engine logs and numeric outputs are retained in this run"}
    write_json(folder / "results.json", results)
    write_json(portal / "results.json", results)
    with (portal / "timeseries.csv").open("w", newline="") as handle:
        fields = [name for name in frames[0] if not name.endswith("image") and name != "points"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore"); writer.writeheader(); writer.writerows(frames)
    # Retain the exact postprocessor used, alongside the numerical runner.
    shutil.copy2(Path(__file__), folder / "code/export.py")
    import zipfile
    with zipfile.ZipFile(portal / "model-and-results.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in folder.rglob("*"):
            if path.is_file() and "portal" not in path.relative_to(folder).parts:
                archive.write(path, str(path.relative_to(folder)))
    inventory = {str(path.relative_to(folder)).replace("\\", "/"): {"sha256": sha256(path), "bytes": path.stat().st_size}
                 for path in sorted(folder.rglob("*")) if path.is_file()}
    write_json(folder / "RUN_MANIFEST.json", {"files": inventory, "policy": "Preserve this run unchanged; new experiments get new run directories"})
    write_json(HERE / "LATEST_RUN.json", {"path": str(folder.relative_to(HERE)).replace("\\", "/"), "manifest_sha256": sha256(folder / "RUN_MANIFEST.json")})
    shutil.copytree(portal, ROOT / "frontend/public/tuflow-hpc", dirs_exist_ok=True)
    print(json.dumps({"run": str(folder), "frames": len(frames), "active_cells": config["active_cells_engine"], "max_depth_m": max(f["maximum_depth_m"] for f in frames),
                      "max_wet_area_km2": max(f["wet_area_km2"] for f in frames), "maximum_relative_mass_error": max_mass_error}, indent=2))
    return folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    args = parser.parse_args()
    folder = args.run or HERE / json.loads((HERE / "PENDING_RUN.json").read_text())["path"]
    export(folder)
