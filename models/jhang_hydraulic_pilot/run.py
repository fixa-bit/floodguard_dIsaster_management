"""Run real 2D shallow-water numerics; keep hypothetical forcing explicit."""
import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MPLBACKEND", "Agg")

import anuga
import numpy as np
import rasterio
import shapely
from PIL import Image
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from scipy.ndimage import map_coordinates
from shapely.geometry import box, shape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TERRAIN = ROOT / "frontend/public/jhang-terrain-prototype"
PUBLIC = ROOT / "frontend/public/hydraulic-pilot"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def quantities(domain):
    q = domain.quantities
    depth = np.maximum(q["stage"].centroid_values - q["elevation"].centroid_values, 0)
    speed = np.zeros(len(depth))
    wet = depth >= .1
    speed[wet] = np.hypot(q["xmomentum"].centroid_values[wet], q["ymomentum"].centroid_values[wet]) / depth[wet]
    if not np.isfinite(depth).all() or not np.isfinite(speed).all():
        raise ValueError("Solver returned nonfinite depth or velocity")
    return depth, speed


def benchmarks(folder):
    """Independent still-water and Ritter dry-bed dam-break checks."""
    domain = anuga.rectangular_cross_domain(30, 8, len1=600, len2=160)
    domain.set_flow_algorithm("DE0")
    domain.set_store(False)
    domain.set_quantity("elevation", lambda x, y: .1 * np.sin(x / 80) + y / 1000)
    domain.set_quantity("stage", 2)
    domain.set_quantity("friction", 0)
    wall = anuga.Reflective_boundary(domain)
    domain.set_boundary({key: wall for key in domain.get_boundary_tags()})
    initial = domain.get_water_volume()
    for _ in domain.evolve(yieldstep=10, finaltime=60):
        pass
    stage_error = float(np.max(np.abs(domain.quantities["stage"].centroid_values - 2)))
    _, velocity = quantities(domain)
    lake = {"max_stage_error_m": stage_error, "max_speed_m_s": float(velocity.max()),
            "relative_volume_error": abs(domain.get_water_volume() - initial) / initial}
    if stage_error > 1e-7 or lake["max_speed_m_s"] > 1e-7 or lake["relative_volume_error"] > 1e-9:
        raise ValueError(f"Lake-at-rest benchmark failed: {lake}")

    domain = anuga.rectangular_cross_domain(240, 4, len1=1200, len2=80)
    domain.set_flow_algorithm("DE0")
    domain.set_store(False)
    domain.set_quantity("elevation", 0)
    domain.set_quantity("friction", 0)
    domain.set_quantity("stage", lambda x, y: np.where(x < 600, 2., 0.))
    wall = anuga.Reflective_boundary(domain)
    domain.set_boundary({key: wall for key in domain.get_boundary_tags()})
    initial = domain.get_water_volume()
    for _ in domain.evolve(yieldstep=5, finaltime=20):
        pass
    xy = domain.get_centroid_coordinates()
    c = np.sqrt(9.81 * 2)
    similarity = (xy[:, 0] - 600) / 20
    exact = np.where(similarity <= -c, 2., np.where(similarity < 2 * c, (2 * c - similarity) ** 2 / (9 * 9.81), 0.))
    depth, _ = quantities(domain)
    # L1 depth error over the wave region, excluding remote unchanged cells.
    region = np.abs(xy[:, 0] - 600) < 200
    l1 = float(np.mean(np.abs(depth[region] - exact[region])))
    dam_break = {"time_seconds": 20, "depth_l1_error_m": l1,
                 "relative_volume_error": abs(domain.get_water_volume() - initial) / initial,
                 "depth_l1_acceptance_m": .12}
    if l1 > .12 or dam_break["relative_volume_error"] > 1e-6:
        raise ValueError(f"Ritter dam-break benchmark failed: {dam_break}")
    result = {"lake_at_rest": lake, "ritter_dam_break": dam_break, "passed": True,
              "scope": "Numerical setup checks only, not validation of Jhang flood prediction"}
    write_json(folder / "benchmarks.json", result)
    return result


def run(mesh_spacing=None, duration=None, input_run=None, publish=True):
    source_inputs = Path(input_run) / "inputs" if input_run else TERRAIN
    config_path = source_inputs / "config.json" if input_run else HERE / "config.json"
    cfg = json.loads(config_path.read_text())
    if mesh_spacing is not None:
        cfg["mesh_spacing_m"] = mesh_spacing
    if duration is not None:
        cfg["duration_seconds"] = duration
    if cfg["mesh_spacing_m"] < 30 or cfg["duration_seconds"] <= 0:
        raise ValueError("Mesh spacing must be at least source terrain spacing, and duration positive")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + os.urandom(3).hex()
    folder = HERE / "runs" / run_id
    (folder / "inputs").mkdir(parents=True, exist_ok=False)
    (folder / "code").mkdir()
    for source in HERE.glob("*.py"):
        shutil.copy2(source, folder / "code" / source.name)
    write_json(folder / "inputs/config.json", cfg)
    for name in ("elevation-30m.tif", "mapped-waterways.geojson", "metadata.json", "NOTICE.txt"):
        shutil.copy2(source_inputs / name, folder / "inputs" / name)
    deps = {name: version(name) for name in ("anuga", "numpy", "scipy", "rasterio", "shapely", "pyproj", "netCDF4", "meshpy", "matplotlib", "dill", "xarray", "Pillow")}
    write_json(folder / "environment.json", {"python": sys.version, "platform": platform.platform(), "packages": deps,
               "compute": "serial CPU; MPI/pymetis partitioning unavailable and unused"})
    benchmark = benchmarks(folder)
    print("Numerical benchmarks passed", flush=True)
    x0, y0 = cfg["centre_utm43n"]
    half = cfg["side_m"] / 2
    bounds = [x0 - half, y0 - half, x0 + half, y0 + half]
    west, south, east, north = bounds
    count = int(np.ceil(cfg["side_m"] / cfg["mesh_spacing_m"]))
    spacing = cfg["side_m"] / count
    points, triangles, boundary_tags = anuga.rectangular_cross(count, count, len1=cfg["side_m"], len2=cfg["side_m"])
    domain = anuga.Domain(points, triangles, boundary_tags,
                          geo_reference=anuga.Geo_reference(epsg=32643, xllcorner=west, yllcorner=south))
    domain.set_flow_algorithm("DE0")
    domain.set_name("jhang_hypothetical_inflow")
    domain.set_datadir(str(folder))
    domain.set_store(True)
    domain.set_store_centroids(True)
    with rasterio.open(folder / "inputs/elevation-30m.tif") as dem:
        grid = dem.read(1)
        inverse = ~dem.transform
        def elevation(x, y):
            cols, rows = inverse * (np.asarray(x) + west, np.asarray(y) + south)
            values = map_coordinates(grid, [rows - .5, cols - .5], order=1, mode="constant", cval=np.nan)
            if not np.isfinite(values).all():
                raise ValueError("Mesh leaves the valid archived DEM: no NoData filling permitted")
            return values
        domain.set_quantity("elevation", elevation)
    domain.set_quantity("friction", cfg["manning_n"])
    domain.set_quantity("stage", expression="elevation")
    boundary = anuga.Transmissive_boundary(domain)
    domain.set_boundary({key: boundary for key in domain.get_boundary_tags()})
    mapped = json.loads((folder / "inputs/mapped-waterways.geojson").read_text(encoding="utf-8"))
    river_geo = shapely.union_all([shape(f["geometry"]) for f in mapped["features"] if f["properties"]["waterway"] == "river"])
    transformer = Transformer.from_crs(4326, 32643, always_xy=True)
    river = shapely.transform(river_geo, transformer.transform, interleaved=False)
    candidates = shapely.get_coordinates(shapely.segmentize(river.intersection(box(west+600, south+600, east-600, north-600)), 60))
    if not len(candidates):
        raise ValueError("No mapped river in the interior of the trial domain")
    point = candidates[np.argmax(candidates[:, 1])]
    region = anuga.Region(domain, center=point.tolist(), radius=cfg["inlet_radius_m"])
    hydro = np.asarray(cfg["hydrograph_seconds_cumecs"], dtype=float)
    discharge = lambda t: float(np.interp(t, hydro[:, 0], hydro[:, 1]))
    anuga.Inlet_operator(domain, region, Q=discharge)
    write_csv(folder / "inputs/hypothetical_inflow.csv", [{"elapsed_seconds": float(t), "discharge_m3_s": float(q)} for t, q in hydro])
    write_json(folder / "inputs/inlet.json", {"centre_utm43n": point.tolist(), "radius_m": cfg["inlet_radius_m"],
               "basis": "Most northerly mapped Chenab point within a 600m interior domain buffer; not a surveyed inflow section",
               "operator": "ANUGA volumetric inlet; no imposed velocity or artificial channel lowering"})
    coordinates = domain.get_centroid_coordinates(absolute=True)
    triangle_vertices = domain.get_vertex_coordinates(absolute=True).reshape(-1, 3, 2)
    initial = domain.get_water_volume()
    frames, depth_series, speed_series = [], [], []
    started = time.perf_counter()
    for t in domain.evolve(yieldstep=cfg["output_interval_seconds"], finaltime=cfg["duration_seconds"]):
        depth, speed = quantities(domain)
        source_volume = float(domain.get_fractional_step_volume_integral())
        boundary_volume = float(domain.get_boundary_flux_integral())
        volume = float(domain.get_water_volume())
        residual = volume - initial - source_volume - boundary_volume
        relative = abs(residual) / max(source_volume, initial, 1)
        wet = depth >= cfg["wet_depth_threshold_m"]
        frames.append({"elapsed_seconds": float(t), "inflow_cumecs": discharge(t), "water_volume_m3": volume,
                       "source_volume_m3": source_volume, "net_boundary_volume_m3": boundary_volume,
                       "mass_residual_m3": residual, "relative_mass_error": relative,
                       "wet_area_km2": float(np.sum(domain.areas[wet]) / 1e6),
                       "maximum_depth_m": float(depth.max()), "maximum_speed_m_s": float(speed.max())})
        depth_series.append(depth.astype("float32")); speed_series.append(speed.astype("float32"))
        print(f"t={t/3600:.2f}h wet={frames[-1]['wet_area_km2']:.3f}km2 depth={depth.max():.2f}m mass_error={relative:.2e}", flush=True)
        if relative > 1e-3:
            raise ValueError("Water-volume balance failed; no portal assets published")
    elapsed = time.perf_counter() - started
    np.savez_compressed(folder / "cell_results.npz", coordinates=coordinates, triangle_vertices=triangle_vertices,
                        area=domain.areas, elevation=domain.quantities["elevation"].centroid_values,
                        depth=np.stack(depth_series), speed=np.stack(speed_series),
                        times=[r["elapsed_seconds"] for r in frames], bounds=bounds)
    write_csv(folder / "timeseries.csv", frames)
    metadata = {"id": "jhang_anuga_trial", "run_id": run_id, "solver": cfg["solver"], "calibrated": False,
                "bounds_utm43n": bounds, "crs": "EPSG:32643", "triangle_count": len(domain), "mesh_spacing_m": spacing,
                "source_dem_spacing_m": 30, "duration_seconds": cfg["duration_seconds"], "runtime_seconds": elapsed,
                "scenario": "Hypothetical inflow pulse on real Jhang surface terrain; not a historical replay or forecast",
                "config": cfg, "numerical_checks": benchmark,
                "max_relative_mass_error": max(r["relative_mass_error"] for r in frames), "frames": frames,
                "source_inlet_utm43n": point.tolist(),
                "limitations": ["No surveyed channel bathymetry, embankments, gates, bridges or culverts.",
                                "Copernicus surface elevations are not surveyed riverbed elevations; no channel was burned into the terrain.",
                                "Hypothetical inflow and assumed Manning n; no station-matched boundary hydrograph or outlet-stage calibration.",
                                "Dry initial surface omits existing river storage; open study edges truncate flow paths.",
                                "120m-scale mesh cannot resolve buildings or small drainage branches.",
                                "Numerical benchmarks and mass balance do not establish Jhang flood accuracy.",
                                "Not a rainfall-runoff model or a 6-12-month discharge forecasting model."],
                "dem_credit": json.loads((folder / "inputs/metadata.json").read_text(encoding="utf-8"))["dem_credit"],
                "source_licence_notice": (folder / "inputs/NOTICE.txt").read_text(encoding="utf-8")}
    write_json(folder / "results.json", metadata)
    render(folder, metadata)
    inventory = {str(p.relative_to(folder)).replace("\\", "/"): {"sha256": digest(p), "bytes": p.stat().st_size} for p in sorted(folder.rglob("*")) if p.is_file()}
    write_json(folder / "RUN_MANIFEST.json", {"files": inventory, "policy": "Retained inputs and outputs; do not modify sealed runs"})
    write_json(HERE / "LATEST_RUN.json", {"path": str(folder.relative_to(HERE)).replace("\\", "/"), "manifest_sha256": digest(folder / "RUN_MANIFEST.json")})
    if publish:
        shutil.copytree(folder / "portal", PUBLIC, dirs_exist_ok=True)
    print(f"Completed and sealed {folder}; {len(domain)} triangles in {elapsed:.1f}s", flush=True)
    return folder


def render(folder, metadata):
    """Render retained triangle-centroid results, preserving depth units."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    from matplotlib.collections import PolyCollection
    values = np.load(folder / "cell_results.npz")
    vertices, depth = values["triangle_vertices"], values["depth"]
    west, south, east, north = values["bounds"]
    portal = folder / "portal"
    (portal / "frames").mkdir(parents=True)
    # Fixed pixel geometry and fixed 0-3m colour scale across all frames.
    width, height = 600, 600
    transform = from_bounds(west, south, east, north, width, height)
    polygons = [shapely.Polygon(points) for points in vertices]
    dem = rasterize(zip(polygons, values["elevation"]), out_shape=(height, width), transform=transform, dtype="float32")
    shade = LightSource(azdeg=315, altdeg=45).hillshade(dem, vert_exag=1, dx=10, dy=10)
    background = np.zeros((height, width, 4), dtype="uint8")
    for channel in range(3):
        background[:, :, channel] = np.uint8(70 + shade * 125)
    background[:, :, 3] = 255
    Image.fromarray(background).save(portal / "terrain.png")
    legend = plt.get_cmap("Blues")
    for index, row in enumerate(metadata["frames"]):
        grid = rasterize(zip(polygons, depth[index]), out_shape=(height, width), transform=transform, dtype="float32")
        rgba = np.uint8(legend(np.clip(grid / 3, 0, 1)) * 255)
        rgba[:, :, 3] = np.where(grid >= metadata["config"]["wet_depth_threshold_m"], 220, 0).astype("uint8")
        Image.fromarray(rgba).save(portal / "frames" / f"{index:03d}.png", optimize=True)
        row["image"] = f"frames/{index:03d}.png"
    write_json(portal / "results.json", metadata)
    (portal / "NOTICE.txt").write_text(metadata["source_licence_notice"], encoding="utf-8")
    write_csv(portal / "timeseries.csv", metadata["frames"])
    maximum = np.max(depth, axis=0)
    with rasterio.open(portal / "maximum-depth.tif", "w", driver="GTiff", height=height, width=width, count=1,
                       dtype="float32", crs="EPSG:32643", transform=transform, compress="deflate") as target:
        target.write(rasterize(zip(polygons, maximum), out_shape=(height, width), transform=transform, dtype="float32"), 1)
        target.set_band_description(1, "Maximum sampled trial depth, m; hypothetical inflow, uncalibrated")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].imshow(background, extent=(west, east, south, north))
    plot = PolyCollection(vertices, array=maximum, cmap="Blues", clim=(0, 3), edgecolors="none")
    axes[0].add_collection(plot); axes[0].set_xlim(west, east); axes[0].set_ylim(south, north); axes[0].set_aspect("equal")
    axes[0].set_title("Maximum sampled depth · ANUGA trial")
    axes[0].set_xlabel("UTM 43N easting (m)"); axes[0].set_ylabel("Northing (m)")
    fig.colorbar(plot, ax=axes[0], label="Depth (m), colours saturate at 3 m")
    hours = [f["elapsed_seconds"] / 3600 for f in metadata["frames"]]
    axes[1].plot(hours, [f["wet_area_km2"] for f in metadata["frames"]], color="#1769aa")
    axes[1].set_xlabel("Elapsed scenario time (hours)"); axes[1].set_ylabel("Area with depth ≥0.1m (km²)")
    axes[1].set_title("Computed wet area through time"); axes[1].grid(alpha=.2)
    fig.suptitle("Jhang: real surface terrain + hypothetical inflow · uncalibrated")
    fig.tight_layout(); fig.savefig(folder / "trial-summary.png", dpi=160); plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh-spacing", type=float)
    parser.add_argument("--duration", type=float)
    parser.add_argument("--input-run", type=Path, help="Reuse the exact archived configuration and terrain of this run")
    parser.add_argument("--no-publish", action="store_true", help="Retain a research run without replacing the portal assets")
    args = parser.parse_args()
    run(args.mesh_spacing, args.duration, args.input_run, not args.no_publish)
