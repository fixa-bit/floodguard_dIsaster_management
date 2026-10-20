# Jhang dynamic hydraulic trial

The portal now has a separate **Simulation → Storm replay → 2D hydraulic trial**.
It plays precomputed ANUGA two-dimensional shallow-water results over real
Copernicus Jhang surface terrain. It is separate from the older connected-fill
prototype and from discharge forecasting.

HEC-RAS was checked and is not installed on this workstation. ANUGA 4.0.1 is a
suitable runnable open-source alternative for this trial; no claim is made that
it is universally more accurate than HEC-RAS. Both require credible terrain,
channels, boundary conditions and local validation. ANUGA uses finite-volume
shallow-water equations, rather than drawing progressively larger buffers.
Official documentation: https://anuga.readthedocs.io/en/stable/

## What was actually run

- A 6 km × 6 km Jhang/Chenab window, UTM 43N (EPSG:32643).
- Archived real 30 m Copernicus surface terrain and an OSM mapped river.
- 10,000 triangular computational cells, based on a 120 m regular mesh.
- Initially dry surface, Manning n=0.04, transmissive/open study edges.
- A **hypothetical** inlet hydrograph: 100 → 1,200 → 100 m3/s over six hours.
  This is not observed flow, a forecast, a measured Marala-to-Jhang boundary,
  or an historical event replay. The inlet adds a recorded volume in a 240 m
  radius on the mapped river, with no imposed inlet velocity.
- No artificial riverbed carving, no rainfall, no infiltration, no population
  impact estimate, no surveyed bathymetry, structures or operating gates.
- Computed depth, depth-averaged speed, wet area, water volume and mass balance
  at 15-minute reporting intervals. The colour scale saturates at 3 m; the
  numerical maximum remains available in the metrics and downloads.

This improves the physical simulation method. It does **not** establish
accurate Jhang flood depths or arrival times, and it does not generate future
river inflow. Hydraulic solvers route supplied water; a rainfall-runoff model
or a reliable discharge forecast must provide future boundary hydrographs.

## Run and validate

From the project root, using PowerShell:

```powershell
./models/jhang_hydraulic_pilot/setup.ps1
models/jhang_hydraulic_pilot/.venv/Scripts/python.exe -m models.jhang_hydraulic_pilot.run
models/jhang_hydraulic_pilot/.venv/Scripts/python.exe -m models.jhang_hydraulic_pilot.verify
```

The separate environment reads existing GIS libraries and installs its own
solver dependencies. It never installs packages into the backend environment.
On this Windows setup PyMetis has no matching wheel; it is deliberately not
installed. The tested serial regular-mesh path does not call MPI/PyMetis.
`pip check` will therefore report the package's unused PyMetis dependency.
The import, numerical checks and full trial exercise the supported path.
Do not use this environment for MPI/distributed mesh partitioning.

`LATEST_RUN.json` identifies the retained run. New runs create new directories
and do not overwrite previous evidence. They retain exact terrain, waterway
geometry, original source metadata/licence, configuration, hydrograph, inlet
location, code, numerical-library versions, benchmarks, all cell results,
native solver output, reporting time series and output images. Every retained
file has a SHA-256 in `RUN_MANIFEST.json`. Keep sealed runs unchanged.

To rerun with the exact archived inputs, use the selected run's absolute path:

```powershell
models/jhang_hydraulic_pilot/.venv/Scripts/python.exe -m models.jhang_hydraulic_pilot.run --input-run D:/Projects/disaster_management/models/jhang_hydraulic_pilot/runs/RUN_ID --no-publish
```

The active code is used; compare its hash with the run's `code/run.py` for exact
code reproduction. `--no-publish` retains a new research run without replacing
the portal frames. `--mesh-spacing` and `--duration` enable explicit sensitivity
experiments, each with its own archived configuration. The default run publishes
small precomputed products to `frontend/public/hydraulic-pilot/`; no solver runs
in the browser and no backend restart is needed.

## Numerical checks and practical limits

Every run first checks a still lake on variable bed topography and a Ritter
dry-bed dam break against its analytical depth solution. The run also rejects
nonfinite results and volume-balance errors above 0.1%. `verify` checks hashes,
computes source volume independently from the recorded hydrograph, recomputes
metrics from cell arrays, and checks the raster and native solver CRS.

The initial trial passed these numerical checks. This does not validate a
local flood forecast. Proper next work requires surveyed channel/barrage
geometry, datum-aligned observed stages and inflow/outflow hydrographs,
roughness calibration, boundary/domain sensitivity, finer mesh convergence,
and comparison with dated gauge and satellite flood observations. The 120 m
mesh cannot resolve buildings or small drains. Copernicus is a surface model,
not a measured riverbed. Open edges affect results as water reaches them.

Depth maps are maximums over the **stored reporting frames**, not an assertion
of the peak between frames. Native `.sww` files retain stage/momentum time
series and geographic origin. The convenient public files are the latest
preview; sealed runs are the historical audit record.
