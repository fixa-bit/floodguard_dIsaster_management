# HEC-RAS 2D confluence replay

The **Simulation → Storm replay → HEC-RAS 2D** tab shows computed 2D flood depths from the official USACE HEC-RAS 2025 **Escondida Example Project**. This is a New Mexico-projection tutorial model, **not a Pakistan flood forecast or calibrated hazard map**. The sample's synthetic time window is 1–3 January 2000, not the current date.

## Why the display changed

The previous Merced tutorial replay painted each 200–400 ft hydraulic cell as a flat polygon because its source terrain raster was unavailable. Enlarging those polygons made the water visibly blocky. The replacement sample contains its original **5 ft terrain raster** and a 906-cell 2D mesh. The official `ras result map` command combines each computed water surface with that terrain, producing the shorelines in the new PNGs. The frontend uses linear texture sampling only for display; it does **not** claim the hydraulic solve has 5 ft resolution. The original Merced export and its audit files remain under `models/hec_ras_2d/` and `frontend/public/hec-ras-2d/` as archival material, but are not selected by the tab.

## Inputs and cases

The public sample has two distinct upstream flow boundaries and a downstream normal-depth boundary. Its main flow hydrograph varies from 300 to 2,800 cfs. The second flow boundary enters on a branch. We copied the original sample and solved three independently prepared sensitivity cases:

| Case | Main inflow | Branch inflow | Constant rain on mesh |
| --- | --- | ---: | ---: |
| Main river only | Original sample hydrograph | 0 cfs | 0 in/hr |
| Main river + branch | Original sample hydrograph | 50 cfs | 0 in/hr |
| Main river + branch + rain | Original sample hydrograph | 50 cfs | 0.02 in/hr |

The branch and rainfall values are **hypothetical**, not measured values. Rainfall is a uniform precipitation boundary applied directly to the 2D mesh. This example has no calibrated runoff routing, infiltration or catchment rainfall observations. A tributary inflow can be represented by a separate upstream 2D boundary where that branch enters the mesh, as in this sample; the replay does not invent other unmapped streams.

The source project lacks an N-value layer association for its `Base Cell Size` geometry, so `configure_escondida.py` adds the sample's existing `N Values` layer to **the copied project only**. Each case is prepared and solved with the official HEC-RAS 2025 Beta CPU implicit diffusion-wave solver. `ras result info` reports **Computed OK: True** for all three 906-cell, 49-profile results. The exporter samples every other native hourly profile, yielding 25 saved frames per case from model hour 0 to 48. US survey foot depths are converted to metres; the display omits depths below 0.1 m. It does not invent in-between water surfaces.

[escondida-inputs.json](escondida-inputs.json) records SHA-256 of each original sample file, copied boundary HDF and changed project association. The generated [`escondida-results.json`](../../frontend/public/hec-ras-2d/escondida-results.json) records SHA-256 of each completed native result, scenario values, frame statistics and georeferenced image paths. The original sample, case files, native HDF results and map TIFFs are preserved under ignored `tools/hec_ras/`; the 75 display PNGs are packaged with the frontend. Re-running the exporter verifies the embedded branch flow, rainfall, hourly times, computed status and input hashes before publishing metadata.

## Installation and reproduction

The official portable [HEC-RAS 2025 Beta](https://www.hec.usace.army.mil/software/hec-ras/2025/) is available at `tools/hec_ras/2025-beta/HEC-RAS 2025 Beta/ras.exe`; [installation.json](installation.json) records the executable hash. The stable HEC-RAS 7.0.1 installer was downloaded and hashed in [installer-source.json](installer-source.json), but Windows required administrator elevation and it was **not installed**. HEC-GeoRAS is an older ArcGIS 10.2 extension and is not installed; the beta engine's terrain mapping handles this demo.

From the repository root, using the Python environment with `h5py`, `numpy`, `rasterio`, `Pillow` and `pyproj`:

```powershell
& 'tools/hec_ras/2025-beta/HEC-RAS 2025 Beta/ras.exe' sample pull 'Escondida Example Project' 'tools/hec_ras/samples/escondida'
.venv\Scripts\python.exe models/hec_ras_2d/configure_escondida.py mainstem
.venv\Scripts\python.exe models/hec_ras_2d/configure_escondida.py tributary
.venv\Scripts\python.exe models/hec_ras_2d/configure_escondida.py tributary_rain

foreach ($case in @('mainstem', 'tributary', 'tributary_rain')) {
  $run = "tools/hec_ras/runs/escondida_$case"
  & 'tools/hec_ras/2025-beta/HEC-RAS 2025 Beta/ras.exe' plan prepare "$run/Plans/Base Cell Size.h5" "$run/Plans/Base Cell Size/Base Cell Size.dwe.r2r.h5" --equation DWE --time-stepping Implicit --core-count 2
  & 'tools/hec_ras/2025-beta/HEC-RAS 2025 Beta/ras.exe' plan solve "$run/Plans/Base Cell Size/Base Cell Size.dwe.r2r.h5" "$run/Results/recomputed_base_dwe.h5" --core-count 2
}
.venv\Scripts\python.exe models/hec_ras_2d/export_escondida_replay.py
cd frontend
node scripts/check-hec-ras-replay.mjs
npm run build
```

The sample is attributed to the US Army Corps of Engineers Hydrologic Engineering Center under its [tutorial terms](https://www.hec.usace.army.mil/confluence/rasdocs/hecras/latest/tutorials). A running Vite server serves the new static assets without a backend restart; a deployed frontend needs a new build/deployment. The repository's Python backend does not run HEC-RAS for this tab.
