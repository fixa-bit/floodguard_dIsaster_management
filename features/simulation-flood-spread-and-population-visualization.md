# Simulation: flood spread and population visualization

Added 2026-10-15. Open **Simulation → Flood spread & population**. The existing **Monitoring scenario** sub-tab remains the default, preserves its draft readings and results when switching views, and retains its explicit Play/save/threshold-alert behavior.

The later optional **Cinematic 3D** presentation is documented separately in [simulation-cinematic-3d-region-view.md](simulation-cinematic-3d-region-view.md). The original 2D comparison remains available; both presentations use the same district, level, and exposure estimates.

## Experience and scope

- Two zoomable, synchronized maps: **Baseline population** on the left and **Simulated flood spread** on the right. District outlines are neutral; no ten-year scores, planning years, or outlook scenario calculations appear in Simulation.
- Both population and spread layers are initially enabled in this sub-tab. Controls support level 0–5, lowest/highest buttons, clickable population comparison bars, map-cell popups, density legend, footprint area, and approximate exposed population.
- **Play spread / Pause spread** animates through ordinal levels at 1.4-second intervals. Playback stops at level 5; starting again from level 5 restarts at 0. Reset returns to 0. Manual controls and map interaction stop playback; hiding the document, disabling motion, or leaving the view also stops it. Reduced-motion preferences disable playback while preserving static controls.
- The preview uses an explicitly selected district from the eight existing example areas. **Its district is independent of the selected monitoring station.** The station name remains visible as context, with a notice explaining that a district example does not represent that station's catchment. Changing districts never changes the station or draft readings.
- The preview creates no monitoring runs, alerts, incidents, or database entries. Only the existing monitoring form's Play action submits a threshold test. Animation is labeled **Play spread** to distinguish these actions.

## Datasets and methodology

Reuse the same versioned, portable, precomputed sources already used in the outlook visualization:

1. Real display district polygons from the existing Parallax Geo adapter.
2. Approximate derived OSM river references.
3. Modeled WorldPop Pakistan 2025 constrained population counts, R2025A v1, CC BY 4.0, aggregated without count resampling into a 2 km equal-area grid.

Level 0 is empty; levels 1–5 use arbitrary local-UTM river buffers of 250, 500, 1,000, 2,000, and 4,000 metres, clipped to the district. Exposure is known cell population multiplied by its footprint intersection fraction, summed across cells. Population is assumed uniform within each clipped grid cell; NoData is excluded. The population baseline stays fixed at 2025. The widest level is the largest example, not a physical maximum flood.

Seven districts have usable river references. Badin retains the population map but disables spread/playback and reports exposure as unavailable. Requests use the existing compressed static-asset cache. There is no backend analysis job, new dataset download, raster modification, or dependency installation.

Full source provenance and generation details remain in [flood spread](ten-year-flood-spread-layer.md), [population exposure](ten-year-population-exposure-layer.md), and `frontend/src/data/outlook-exposure/metadata.json`. The new in-tab Inputs & Method section describes current inputs, calculations, limitations, and future scope.

## Implementation strategy

- `frontend/src/components/SimulationPanel.tsx`: accessible Simulation sub-tabs; lazy-mount the visualization only while selected. Keep the existing form/result tree mounted but hidden so draft and saved-run state survive.
- `frontend/src/components/SimulationFloodVisualization.tsx`: Simulation-specific neutral maps, independent district selector, playback, context notices, and method panel. It supplies the same map-source/layer contract used by the existing exposure layer.
- `frontend/src/components/TenYearFloodExposure.tsx`: reuse population/water rendering and calculations with optional controlled level, initial layer state, availability callback, and Simulation-specific wording/element ID. Default outlook behavior remains unchanged.
- `frontend/src/simulation.css`: styles scoped to the Simulation workspace and new visualization. Existing outlook styles supply shared map/legend/summary presentation. No sticky decade timeline is copied into Simulation.

Only two map canvases exist while the preview is open. Switching back to monitoring or leaving Simulation removes maps, observers, popups, and animation intervals. The app continues to use the web view; no Flutter/mobile tooling is installed.

## Limitations and future scope

No terrain, levees, drainage, calibrated hydraulics, or validated connection between station discharge/gauge height and inundation supports these examples. The water levels are ordinal UI scenarios, not physical heights or official warning categories. Approximate exposed people are conditional on invented footprints, not confirmed affected residents. No future population growth or trained prediction model is introduced.

Future work should obtain terrain/drainage/levee data, sourced historical footprints, station height/discharge relationships, and validated hydraulic simulations before coupling monitoring readings to spread. Native-resolution exposure validation and sourced future population assumptions can follow.

## Verification

From `frontend`:

```powershell
node scripts/check-simulation-controls.mjs
node scripts/validate-simulation-flood-visualization.mjs
node scripts/validate-outlook-flood-exposure.mjs
npm run build
```

The existing form check uses intercepted backend submissions to verify controls/payloads without database writes. The new preview check verifies draft preservation, both maps and cell popups, zoom synchronization, slider/presets/bar/summary consistency, playback lifecycle, missing river coverage, reduced motion, visibility handling, compact desktop layout, tab keyboard navigation, canvas cleanup, and zero backend writes. The outlook check protects the shared exposure component's original behavior.

All four checks passed on 2026-10-15. Browser suites reported no runtime errors, and preview interactions issued no backend writes. Desktop and compact screenshots are saved under `frontend/screenshots/simulation-flood-visualization*.png`.
