"""Independently check retained TUFLOW inputs, raw rasters and preview metrics."""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import rasterio

from .run import HERE, sha256


def verify(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder / "RUN_MANIFEST.json").read_text())
    for name, expected in manifest["files"].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or not path.is_file() or path.stat().st_size != expected["bytes"] or sha256(path) != expected["sha256"]:
            raise ValueError(f"Retained file changed or missing: {name}")
    meta = json.loads((folder / "results.json").read_text())
    cfg = meta["config"]
    tcf = (folder / "runs/Jhang_HPC_Demo.tcf").read_text()
    if not re.search(r"Demo Model\s*==\s*ON", tcf) or re.search(r"^Tutorial Model\s*==", tcf, re.M):
        raise ValueError("Custom model must use the documented Demo Model mode")
    if meta["duration_seconds"] > 600 or cfg["active_cells_engine"] > 30000 or cfg["cell_count"] > 100000:
        raise ValueError("Recorded demo is outside the documented limits")
    with rasterio.open(folder / "inputs/elevation-30m.tif") as original, rasterio.open(folder / "model/grid/dem.tif") as model:
        np.testing.assert_array_equal(original.read(), model.read())
        if original.transform != model.transform or original.crs != model.crs:
            raise ValueError("DEM re-encoding changed geography")
    values = np.load(folder / "output_grids.npz")
    if len(meta["frames"]) != 31 or values["depth"].shape[0] != 31:
        raise ValueError("Incomplete ten-minute output sequence")
    for index, frame in enumerate(meta["frames"]):
        depth = values["depth"][index]; speed = values["speed"][index]
        if frame["elapsed_seconds"] != index * 20:
            raise ValueError("Demo clock was altered")
        wet = np.isfinite(depth) & (depth >= .1)
        np.testing.assert_allclose(frame["wet_area_km2"], wet.sum() * cfg["cell_size_m"] ** 2 / 1e6)
        np.testing.assert_allclose(frame["maximum_depth_m"], np.nanmax(depth) if np.isfinite(depth).any() else 0)
        np.testing.assert_allclose(frame["maximum_speed_m_s"], np.nanmax(speed[wet]) if wet.any() else 0)
        points = json.loads((folder / "portal" / frame["points"]).read_text())
        if len(points["features"]) != wet.sum():
            raise ValueError("Point inspection does not match wet raster cells")
        for point in points["features"]:
            p = point["properties"]
            np.testing.assert_allclose(p["depth_m"], depth[p["row"], p["column"]])
    with (folder / "portal/mass-balance.csv").open(newline="") as handle:
        mass = [{key.strip(): value.strip() for key, value in row.items()} for row in csv.DictReader(handle)]
    hydro = np.asarray(cfg["inflow_hydrograph_seconds_cumecs"])
    volume = float(np.trapezoid(hydro[:, 1], hydro[:, 0]))
    np.testing.assert_allclose(float(mass[-1]["Tot Vol"]), volume, rtol=.001)
    if meta["checks"]["maximum_relative_mass_error"] > .001:
        raise ValueError("Mass balance failed")
    for name in ("maximum-depth.tif", "maximum-speed.tif"):
        with rasterio.open(folder / "portal" / name) as source:
            if source.crs.to_epsg() != 32643:
                raise ValueError("Result download has wrong CRS")
    return {"status": "passed", "files": len(manifest["files"]), "frames": 31,
            "active_cells": cfg["active_cells_engine"], "maximum_relative_mass_error": meta["checks"]["maximum_relative_mass_error"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    args = parser.parse_args()
    folder = args.run or HERE / json.loads((HERE / "LATEST_RUN.json").read_text())["path"]
    print(json.dumps(verify(folder), indent=2))
