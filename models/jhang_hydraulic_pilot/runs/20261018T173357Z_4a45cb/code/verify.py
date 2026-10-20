"""Verify retained input/output hashes, independent source volume and map exports."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from netCDF4 import Dataset

HERE = Path(__file__).resolve().parent


def verify(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "RUN_MANIFEST.json").read_text())
    for name, expected in manifest["files"].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError(f"Missing or invalid retained file: {name}")
        if path.stat().st_size != expected["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
            raise ValueError(f"Retained file changed: {name}")
    result = json.loads((folder / "results.json").read_text())
    array = np.load(folder / "cell_results.npz")
    depth, speed, area = array["depth"], array["speed"], array["area"]
    if depth.shape != speed.shape or depth.shape[0] != len(result["frames"]) or depth.shape[1] != len(area):
        raise ValueError("Retained results have inconsistent dimensions")
    if not np.isfinite(depth).all() or not np.isfinite(speed).all() or (depth < 0).any() or (speed < 0).any():
        raise ValueError("Nonphysical retained depth or speed")
    hydro = np.asarray(result["config"]["hydrograph_seconds_cumecs"])
    for index, frame in enumerate(result["frames"]):
        t = frame["elapsed_seconds"]
        knots = np.unique(np.r_[0., hydro[(hydro[:, 0] > 0) & (hydro[:, 0] < t), 0], t])
        independent_volume = float(np.trapezoid(np.interp(knots, hydro[:, 0], hydro[:, 1]), knots))
        np.testing.assert_allclose(frame["source_volume_m3"], independent_volume, rtol=1e-3, atol=1)
        np.testing.assert_allclose(np.sum(depth[index].astype(float) * area), frame["water_volume_m3"], rtol=1e-6, atol=1e-4)
        wet_area = float(area[depth[index] >= result["config"]["wet_depth_threshold_m"]].sum() / 1e6)
        np.testing.assert_allclose(wet_area, frame["wet_area_km2"], atol=1e-6)
        np.testing.assert_allclose(float(depth[index].max()), frame["maximum_depth_m"], rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(float(speed[index].max()), frame["maximum_speed_m_s"], rtol=1e-6, atol=1e-6)
        if frame["relative_mass_error"] > 1e-3:
            raise ValueError("Mass conservation check failed")
    with rasterio.open(folder / "portal/maximum-depth.tif") as image:
        if image.crs.to_epsg() != 32643:
            raise ValueError("Depth GeoTIFF CRS is wrong")
        np.testing.assert_allclose(list(image.bounds), array["bounds"], atol=1e-6)
        if not np.isfinite(image.read(1)).all():
            raise ValueError("Depth GeoTIFF contains nonfinite results")
    with Dataset(folder / "jhang_hypothetical_inflow.sww") as dataset:
        if dataset.zone != 43 or dataset.hemisphere != "northern":
            raise ValueError("Raw solver output is not georeferenced to UTM 43N")
        np.testing.assert_allclose([dataset.xllcorner, dataset.yllcorner], array["bounds"][:2])
    if not result["numerical_checks"]["passed"]:
        raise ValueError("Numerical benchmark checks did not pass")
    return {"status": "passed", "verified_files": len(manifest["files"]), "frames": len(result["frames"]),
            "triangles": len(area), "max_relative_mass_error": result["max_relative_mass_error"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    args = parser.parse_args()
    folder = args.run or HERE / json.loads((HERE / "LATEST_RUN.json").read_text())["path"]
    print(json.dumps(verify(folder), indent=2))
