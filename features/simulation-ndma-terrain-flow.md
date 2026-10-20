# NDMA terrain flow

**Archived experiment.** The user rejected this dry-field point-source setup. The fifth tab now uses the complete USACE White River HEC-RAS model, selected by the user. See [river-channel model and verification](../models/river_channel_hydraulics/README.md). The original exporter and assets remain as provenance and are not loaded by the active tab.

Open Simulation → Storm replay → NDMA terrain flow. The four existing replay modes are preserved; the workspace adds one lazily loaded component.

This mode uses `Pakistan_849790` elevation and slope rasters from `D:/Projects/NDMA_tasks/NDMA_tasks/dataset/sen1floods11_sar_handlabeled_v1_1`. The sample is at approximately 32.54°N, 71.45°E, not the Jhang study. The exporter verifies both inputs against their existing provenance checksums and checks spatial alignment. Source files are read only.

## Calculation

`scripts/build_ndma_terrain_flow.py` averages the aligned terrain to 96 × 96 cells (approximately 45 × 53 m). NoData is rejected rather than treated as low ground. A conservative finite-volume diffusion-wave approximation exchanges water across cell faces based on water-surface elevation (`ground + depth`), overtoppable bed steps and Manning n = 0.045. A donor limiter prevents negative storage while conserving internal transfers. Study edges are closed.

The domain starts dry. An explicitly assumed interior inflow reaches 50 m³/s at 15 minutes, holds until 45 minutes, then declines to zero at 90 minutes. Redistribution continues to three hours. Inlet placement is deterministic, on relatively high ground, and stored in the manifest. This is a localized surface-flow experiment, not measured river inflow or a reconstruction of the Sen1Floods11 flood event.

The solver computes changing water-surface slopes from elevations. The saved slope raster is displayed as terrain context in the cell inspector, not substituted for the water-surface gradient. Numerical conservation is not evidence of predictive accuracy. Inertia, infiltration, rainfall, surveyed channel bathymetry, culverts and levee geometry are omitted. Closed boundaries can produce artificial ponding. The method uses a regularized small-slope denominator of 1e-5; results are uncalibrated.

Conceptual reference: [USACE shallow-water equations and diffusion-wave assumptions](https://www.hec.usace.army.mil/confluence/hecras/beta/technical-reference/hydraulic-equations/shallow-water-equations). This is a custom approximation, not a run of HEC-RAS.

## Browser output

`frontend/public/ndma-terrain-flow/results.json` contains source provenance, grid bounds, elevation/slope values, scenario parameters, numerical checks and per-frame summaries. `frames.bin` stores 121 frames every 90 seconds. Each frame has three row-major, little-endian signed int16 planes: depth in 0.001 m, eastward velocity in 0.0001 m/s, and southward velocity in 0.0001 m/s. Zero depth is dry. The browser validates asset lengths and metadata before rendering.

MapLibre displays a saved terrain image or satellite context. Canvas draws computed water cells at depth ≥ 0.02 m; trails advect through wet-weighted interpolated model velocities, clipped to the same wet mask. Particle travel is accelerated 600× for legibility, independently of timeline speed. Static snapshots develop the same trails. No artistic river-line direction field is used. Water colors have cosmetic shading; calculated cell boundaries remain visible.

Controls include playback, pause, reset, seeking, playback speed, imagery, flow trails, flow close-up and study overview. Clicking a grid cell shows elevation, saved slope, computed depth and speed. Reduced motion disables animation; static seeking remains available. Hidden/offscreen playback pauses. Inputs and method disclose assumptions and provide downloads.

## Rebuild and verification

```powershell
.venv/Scripts/python.exe scripts/build_ndma_terrain_flow.py
.venv/Scripts/python.exe -m pytest tests/test_ndma_terrain_flow.py -q
```

The exporter accepts `--dataset`, `--sample` and `--output`. It checks mass balance and nonnegative depths before writing results. The packaged run has maximum relative water-balance error approximately 5.3e-15 before display quantization. Tests cover a lake at rest, downhill transport, roughness response, dry ridge blocking, limiter positivity and volume conservation, and packaged asset integrity.

From `frontend`, run `npm run build` and, with the Vite server on port 3000, `node scripts/check-ndma-terrain-flow.mjs`. The browser check covers actual animated pixels, pause, seeking, cell inspection, layer controls, restart, reduced motion, mobile overflow, continued availability of the original replay, and asset failure/retry. It deliberately blocks satellite imagery to check the local fallback. Screenshot: `frontend/screenshots/ndma-terrain-flow.png`.
