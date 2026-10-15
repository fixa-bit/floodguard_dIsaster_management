# Simulation: storm replay and line inspection

Added 2026-10-15. Open **Simulation → Storm replay**. This is an additional view inspired by the user-supplied screen recording of animated flood extent, current streaks, timeline charts, and line inspection. The existing **Monitoring scenario** and **Flood spread & population** views, including **2D comparison** and **Cinematic 3D**, remain available.

## Current experience

- A zoomable satellite-context map with a shaded water surface and dense, curved, persistent current trails. The initial sparse-dash/banded presentation was replaced on 2026-10-15; see [natural water rendering](simulation-natural-water-animation.md). Whole-district and river-close-up camera presets use the existing district bounds and river-reference coordinates.
- Lower, moderate, and higher spread examples, peaking at ordinal levels 2, 3, and 5. All begin and end at level 0. A selected district with unsupported water data, currently Badin, retains population context and explicitly disables water replay and line inspection.
- Play/pause, restart, 0.5×/1×/2×/4× speed, a scrubber across six illustrative hours, and jump-to-peak. The example snapshot starts at 02:00; restart selects 00:00. A 1× full replay takes approximately 40 wall-clock seconds while visible. The replay stops at its end and does not loop automatically.
- An area-versus-time chart with a synchronized cursor and faint comparison curves for the other examples. District-wide population exposure and footprint area update at the same saved ordinal level as the map.
- Animated population and affected-area bar cards compare the current amount with the same district's level-5 example, while retaining the numeric values. See [exposure impact bars](simulation-exposure-impact-bars.md).
- Population-layer and decorative-current toggles. Satellite imagery can be turned off, and a tile failure automatically falls back to the local map without disabling data or playback. Satellite can be selected again to retry.
- A two-click inspection line, cancellation with Escape or the cancel button, redraw, and clear. The inspector reports line length and approximate length inside the current hypothetical footprint, with a wet/dry strip. It reports **spatial overlap**, not discharge crossing the line.
- Visible hypothetical labels and an **Inputs & Method** disclosure covering data, features, calculation, limitations, and future scope.

## Inputs and method

No new flood dataset, trained model, station calibration, hydraulic solver, or population calculation is introduced. The view loads the selected district's existing compressed flood/population asset and shares the existing asset request/cache utility. A later addition provides real Jhang terrain as optional geographic context, documented separately in [terrain acquisition and hydraulic references](simulation-jhang-terrain-and-hydraulic-reference.md).

| Input | Fields or features used | Role |
| --- | --- | --- |
| Existing district outlines | District name, geometry | Geographic context and selected boundary |
| Approximate OpenStreetMap river references | Line coordinates | Geographic reference, camera target, decorative current paths |
| Existing hypothetical river-buffer footprints | `min_level`, polygon geometry | Ordinal example extent and line overlap |
| WorldPop 2025 R2025A v1, aggregated to a 2 km equal-area grid | `population_2025`, `density_km2`, saved per-level exposure, saved totals | Optional population display and approximate exposure |
| Esri World Imagery | Raster tiles | Optional satellite context, using the same public service and credit as the existing operational map |
| Hand-authored replay sequence | Elapsed example minute and scenario peak | Chooses a saved extent; not rainfall/runoff simulation |

See the existing [population method](ten-year-population-exposure-layer.md) and [flood footprint method](ten-year-flood-spread-layer.md). The six saved footprints use buffer widths 0, 250, 500, 1,000, 2,000, and 4,000 m, clipped to the district. These widths are not water depths or official warning levels. Population exposure uses the saved fractional-area estimate, assumes uniform distribution within each display cell, fixes population at 2025, and excludes NoData. The replay does not interpolate, extrapolate, or inflate those totals. Map zoom does not change the district-wide metrics.

### Time and chart construction

The timeline's six hours are illustrative, with an arbitrary peak minute of 198 (03:18):

```text
phase = minute / 198                         before the peak
phase = (360 - minute) / (360 - 198)         after the peak
level = round(scenario_peak × sin(phase × π/2)^1.6)
```

Time is clamped to 0–360 and the level is bounded to the selected peak. The chart looks up the existing footprint area for each resulting integer level; it does not fabricate continuous intermediate water geometry. Its stepped appearance reflects the six available extents. Other scenario curves use the same method. The exact selected footprint remains available in the map and numeric summaries.

This is **not** a 10-year/100-year storm comparison, an observed six-hour event, a forecast, or evidence of a particular annual exceedance probability. There are no scenario probabilities or rain, depth, velocity, or discharge values in this version.

### Decorative currents

The initial 520-dash/20-updates-per-second implementation has been replaced by `ReplayWaterRenderer.ts`, using a view-local artistic vector field, continuous shading, soft banks, and up to 4,200 persistent, advected fine trails at at most 30 updates/second. Their displayed direction and speed still have no physical interpretation. See [natural water rendering](simulation-natural-water-animation.md) for the current algorithm, clipping, camera fallback, memory bounds, and tests.

Pausing preserves the developed surface and trail image. Toggling Currents hides trails while retaining the shaded water material. No package or map engine was added. Satellite tiles require network access; flood/population assets and the downloaded Jhang terrain remain local.

### Line inspection

The user selects two WGS84 coordinates. Haversine distance estimates line length. The method samples 512 equally spaced segment midpoints along the coordinate-interpolated line, tests each against the current water polygons with polygon-hole support, and multiplies the wet fraction by line length. Geometry collections are flattened to polygon parts; non-polygon artifacts are excluded. A bounding-box prefilter avoids unnecessary polygon tests. The result is approximate; its sampling interval is line length divided by 512. It is not a water cross-section or a hydraulic flux calculation.

The visible pink A–B line remains when time or scenario changes, so its overlap can be compared. Selecting another district clears the line to prevent stale geography. There is no saved line, backend submission, alert creation, or incident creation from this view.

## Preservation, lifecycle, and accessibility

Only the Simulation panel's subtab selection is extended. The original monitoring form stays mounted and hidden while previewing, preserving drafts and results. The original spread view and new replay mount only when their own subtab is active. Existing monitoring submission, thresholds, persisted simulated alerts, and incident approval behavior are unchanged.

Tab navigation supports left/right arrows with wrapping, Home, and End across all three views. The replay map supports normal keyboard panning/zooming. Playback controls and the timeline are keyboard accessible; the pointer-drawn inspection tool also supports Escape cancellation. The line drawing tool currently requires a pointing device.

Timers and current animation stop on pause, drawing, district/scenario selection, manual seek, manual map navigation, reduced-motion preference, motion-off, document hiding, less than 8% map visibility, and leaving the subtab. Visibility interruptions never restart playback automatically. Reduced-motion users can still select static snapshots and camera presets with zero-duration camera transitions. Leaving the view disconnects observers/listeners, cancels animation frames and timers, and removes its map context. The replay does not keep extra hidden map engines running.

## Files

- `frontend/src/components/SimulationPanel.tsx`: additional lazy replay subtab and three-view keyboard navigation.
- `frontend/src/components/SimulationStormReplay.tsx`: replay controls, inspector, chart, data loading, and method disclosure.
- `frontend/src/components/useStormReplayMap.ts`: independent map, imagery fallback, sources, camera framing, and inspection line.
- `frontend/src/components/useReplayCurrents.ts`: clipped decorative current overlay and animation cleanup.
- `frontend/src/components/stormReplayData.ts`: example progression, geometry helpers, line-overlap calculation, and reference-route sampling.
- `frontend/src/simulation-storm-replay.css`: scoped layout and visual styling.

Map rendering uses the existing MapLibre APIs; references include the official [raster source example](https://maplibre.org/maplibre-gl-js/docs/examples/add-a-raster-tile-source/) and [line animation example](https://maplibre.org/maplibre-gl-js/docs/examples/animate-a-line/). This implementation does not copy the reel's media or proprietary model.

## Verification

From `frontend`:

```powershell
node scripts/check-storm-replay-data.mjs
node scripts/validate-storm-replay.mjs
node scripts/validate-simulation-flood-visualization.mjs
node scripts/validate-simulation-cinematic.mjs
node scripts/validate-outlook-flood-exposure.mjs
npm run build
```

The data check uses independent polygon/hole crossing examples and covers all eight district assets, rise/recession bounds, immutable data, zero-length and missing-water cases. The browser check exercises actual map/current rendering, failed imagery fallback, exact saved exposure reuse, controls, a two-click line, clearing/cancelling, district switching, missing data, accessibility settings, visibility cleanup, draft preservation, keyboard tabs, responsive layout, and absence of operational writes. Existing checks cover the original 2D, cinematic, and outlook behavior.

All six checks passed on 2026-10-15. The browser checks reported no runtime errors or operational writes, and the monitoring draft survived replay exploration. The original 2D comparison, actual 3D extrusions and camera controls, and shared outlook layers passed their existing checks. The production build passed with the repository's existing large-chunk advisory.

A separate visual check loaded 24 satellite tiles successfully, with no failed imagery responses, and confirmed the real satellite background, blue example extents, streaks, inspector, timeline, and method disclosure. Screenshots are saved in `frontend/screenshots/` as `simulation-storm-replay-satellite.png`, `simulation-storm-replay-inspection.png`, `simulation-storm-replay.png`, and `simulation-storm-replay-compact.png`.

## Future scope

Obtain vetted elevation, drainage, channel cross-sections, levees/buildings, rainfall forcing, and boundary conditions. Use a calibrated rainfall/runoff model and 2D hydraulic solver to generate time-varying depth and velocity rasters. Validate extent, timing, and discharge against historical events and gauges, with uncertainty reporting, before adding return-period storm comparisons or calculating flow across a drawn line. Parcel-level decisions require data and validation beyond the current district-scale demonstration.
