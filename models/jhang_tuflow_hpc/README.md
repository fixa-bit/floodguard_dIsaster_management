# Retained Jhang TUFLOW HPC trial

The Jhang TUFLOW HPC trial was **withdrawn from the dashboard**. Its map looked like water emerging from the ground because the model starts entirely dry and applies a hypothetical inflow to a 180 m radius area inside the study boundary. The 30 m Copernicus surface DEM has no surveyed riverbed, and this run has no measured initial river level or calibrated inflow. Its computed depths and speeds therefore cannot be presented as a realistic Chenab flood. The trial is retained for audit and future model development only.

The completed run is `runs/20261018T181646Z_1ef49b`. It used TUFLOW HPC 2026.3.0 in CPU mode with `Demo Model == ON`, 25,600 bounding cells, 25,442 active cells, and the permitted ten simulated minutes. It produced 31 native output times at 20-second intervals. The hypothetical inflow totals 115,000 m³. Completion, solver checks, the mass-balance CSV, native GeoTIFFs, inputs, control files, code snapshots, and an inventory of 297 files with SHA-256 checksums are in that sealed run. The run is not a forecast or an observed event.

The copied source DEM, mapped waterways, source metadata and terrain notices are under the run's `inputs/`. `inputs/config.json` records every scenario assumption, including the source area, initial state, boundary conditions, roughness and inflow hydrograph. `installation.json` records the official portable engine download and SHA-256. `environment.json` records the Python preprocessing environment. `RUN_MANIFEST.json` records each retained file's hash and size. `LATEST_RUN.json` points to the completed run and its manifest hash. `portal/model-and-results.zip` contains the raw model and results for offline review. The older setup attempts remain in separate run directories.

To check the retained completed run from the project root:

```powershell
.venv\Scripts\python.exe -m models.jhang_tuflow_hpc.verify
```

The TUFLOW executable remains under `tools/tuflow/2026.3.0/`, outside version control. A new experiment can be prepared with `run.py`, followed by `export.py` and `verify.py`; `export.py` retains outputs under `models/` and does not publish them into `frontend/public`. A future dashboard release requires measured channel geometry and initial water level, defensible inflow and downstream boundary data, and validation against an observed event before these results should be shown as flood behavior.

Official demo-mode limits: <https://docs.tuflow.com/classic-hpc/manual/2026.3/02-Getting-Started.html#licence-free-demo-mode>.
