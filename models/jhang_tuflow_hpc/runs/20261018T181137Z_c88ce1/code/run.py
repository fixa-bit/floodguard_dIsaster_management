"""Build/run a permitted ten-minute TUFLOW HPC demo with retained real inputs."""
import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import fiona
import numpy as np
import rasterio
import shapely
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point, box, mapping, shape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / "frontend/public/jhang-terrain-prototype"
BOUNDS = [237560., 3464540., 242360., 3469340.]
CELL = 30
DURATION_SECONDS = 600


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_shape(path, geometry, properties, schema):
    with fiona.open(path, "w", driver="ESRI Shapefile", crs="EPSG:32643", schema=schema) as target:
        target.write({"geometry": mapping(geometry), "properties": properties})


def prepare():
    install = json.loads((HERE / "installation.json").read_text())
    engine = ROOT / install["engine_relative_path"]
    if sha256(engine) != install["engine_sha256"]:
        raise ValueError("Installed TUFLOW engine checksum changed")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + os.urandom(3).hex()
    folder = HERE / "runs" / run_id
    for name in ("inputs", "code", "model/gis", "model/grid", "bc_dbase", "runs/log", "results", "check"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    for file in HERE.glob("*.py"):
        shutil.copy2(file, folder / "code" / file.name)
    shutil.copy2(HERE / "installation.json", folder / "inputs/installation.json")
    for name in ("elevation-30m.tif", "metadata.json", "mapped-waterways.geojson", "NOTICE.txt"):
        shutil.copy2(SOURCE / name, folder / "inputs" / name)
    shutil.copy2(SOURCE / "elevation-30m.tif", folder / "model/grid/dem.tif")
    (folder / "model/gis/projection.prj").write_text(CRS.from_epsg(32643).to_wkt(version="WKT1_ESRI"))
    west, south, east, north = BOUNDS
    with rasterio.open(folder / "model/grid/dem.tif") as dem:
        window = rasterio.windows.from_bounds(west, south, east, north, dem.transform)
        if not np.isfinite(dem.read(1, window=window)).all():
            raise ValueError("Study window has missing terrain; no filling is allowed")
    data = json.loads((folder / "inputs/mapped-waterways.geojson").read_text(encoding="utf-8"))
    transformer = Transformer.from_crs(4326, 32643, always_xy=True)
    river = shapely.transform(shapely.union_all([shape(f["geometry"]) for f in data["features"] if f["properties"]["waterway"] == "river"]), transformer.transform, interleaved=False)
    points = shapely.get_coordinates(shapely.segmentize(river.intersection(box(west+600, south+600, east-600, north-600)), 30))
    centre = points[np.argmax(points[:, 1])]
    source_area = Point(centre).buffer(180)
    write_shape(folder / "model/gis/2d_sa_inflow_R.shp", source_area, {"Name": "JHANG_TEST"},
                {"geometry": "Polygon", "properties": {"Name": "str:100"}})
    schema = {"geometry": "LineString", "properties": {"Type": "str:2", "Flags": "str:3", "Name": "str:100", **{k: "float:19.8" for k in ("f", "d", "td", "a", "b")}}}
    props = {"Type": "HQ", "Flags": None, "Name": None, "f": None, "d": None, "td": None, "a": None, "b": .0002}
    write_shape(folder / "model/gis/2d_bc_outlet_L.shp", LineString([(west+CELL, south+CELL/2), (east-CELL, south+CELL/2)]), props, schema)
    # This retains the first ten minutes of the earlier hypothetical six-hour
    # hydrograph; the time axis is not accelerated to evade demo-mode limits.
    hydro = [[0., 100.], [DURATION_SECONDS, 100 + 1100 * DURATION_SECONDS / 3600]]
    with (folder / "bc_dbase/inflow.csv").open("w", newline="") as handle:
        writer = csv.writer(handle); writer.writerow(["time_hr", "flow_m3s"])
        writer.writerows((t / 3600, q) for t, q in hydro)
    (folder / "bc_dbase/bc_dbase.csv").write_text("Name,Source,Column 1,Column 2\nJHANG_TEST,inflow.csv,time_hr,flow_m3s\n")
    (folder / "model/materials.csv").write_text("Material ID,Manning's n,Rainfall Losses,Land Use Hazard ID\n1,0.04,,\n")
    (folder / "model/jhang.tgc").write_text(f"""! Real terrain; no channel carving or invented structures
Origin == {west}, {south}
Orientation Angle == 0
Cell Size == {CELL}
Grid Size (X,Y) == {east-west}, {north-south}
Set Code == 1
Set Zpts == 99999
Read GRID Zpts == grid\\dem.tif
Set Mat == 1
""")
    (folder / "model/jhang.tbc").write_text("Read GIS SA ALL == gis\\2d_sa_inflow_R.shp\nRead GIS BC == gis\\2d_bc_outlet_L.shp\n")
    tcf = folder / "runs/Jhang_HPC_Demo.tcf"
    tcf.write_text(f"""! Permitted custom demo. No Tutorial Model flag is used for Jhang.
Demo Model == ON
Solution Scheme == HPC
Hardware == CPU
CPU Threads == 2
GIS Format == SHP
SHP Projection == ..\\model\\gis\\projection.prj
Use GDAL == ON
TIF Projection == EPSG:32643
Geometry Control File == ..\\model\\jhang.tgc
BC Control File == ..\\model\\jhang.tbc
BC Database == ..\\bc_dbase\\bc_dbase.csv
Read Materials File == ..\\model\\materials.csv
Timestep == 1
Start Time == 0
End Time == {DURATION_SECONDS / 3600:.14f}
Log Folder == log
Output Folder == ..\\results
Write Check Files == ..\\check
Map Output Format == TIF
Map Output Data Types == h d V
Map Output Interval == 20
Grid Output Cell Size == {CELL}
Grid Output Origin == Model Origin
Time Series Output Interval == 10
""")
    config = {"solver": "TUFLOW HPC", "version": install["version"], "hardware": "CPU, 2 threads",
              "licence_mode": "official licence-free custom demo", "duration_seconds": DURATION_SECONDS,
              "bounds_utm43n": BOUNDS, "cell_size_m": CELL, "cell_count": int((east-west)*(north-south)/CELL**2),
              "source_dem_spacing_m": 30, "initial_condition": "dry; no observed initial river level",
              "manning_n": .04, "inflow_hydrograph_seconds_cumecs": hydro,
              "source_area_centre_utm43n": centre.tolist(), "source_radius_m": 180,
              "source_kind": "hypothetical inflow, not observed or forecast",
              "outlet": "south-edge automatic HQ with assumed slope 0.0002; remaining boundaries closed",
              "rainfall": "none", "infiltration": "none", "calibrated": False,
              "licence_limits": {"maximum_active_cells": 30000, "maximum_bounding_cells": 100000, "maximum_duration_seconds": 600},
              "licence_documentation": "https://docs.tuflow.com/classic-hpc/manual/2026.3/02-Getting-Started.html#licence-free-demo-mode"}
    write_json(folder / "inputs/config.json", config)
    write_json(HERE / "PENDING_RUN.json", {"path": str(folder.relative_to(HERE)).replace("\\", "/")})
    print(f"Prepared TUFLOW model: {folder}", flush=True)
    return folder


def compute(folder):
    folder = Path(folder).resolve()
    if (folder / "RUN_MANIFEST.json").exists():
        raise ValueError("Cannot overwrite a sealed run")
    installation = json.loads((folder / "inputs/installation.json").read_text())
    engine = (ROOT / installation["engine_relative_path"]).resolve()
    command = [str(engine), "-b", "-nmb", "-hwcpu", "-nt2", str(folder / "runs/Jhang_HPC_Demo.tcf")]
    write_json(folder / "command.json", {"args": command, "started_at": datetime.now(timezone.utc).isoformat()})
    started = time.perf_counter()
    with (folder / "engine_console.log").open("w", encoding="utf-8") as handle:
        process = subprocess.run(command, cwd=folder / "runs", stdout=handle, stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=300)
    log = (folder / "engine_console.log").read_bytes().decode("cp1252", errors="replace")
    result = {"exit_code": process.returncode, "elapsed_seconds": time.perf_counter() - started}
    write_json(folder / "engine_status.json", result)
    print(json.dumps(result), flush=True)
    print(log[-4500:].encode("ascii", errors="backslashreplace").decode(), flush=True)
    if process.returncode:
        raise RuntimeError("TUFLOW did not complete successfully; see the retained engine log")
    return folder


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compute-existing", type=Path)
    args = parser.parse_args()
    compute(args.compute_existing or prepare())
