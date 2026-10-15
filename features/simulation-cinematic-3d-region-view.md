# Simulation: cinematic 3D region view

Added 2026-10-15. Open **Simulation → Flood spread & population**, then choose **Cinematic 3D** in Map presentation above the maps. **2D comparison** remains the default and is preserved as a separate presentation of the same district and selected flood level.

## Visual experience

- A full-width map tilted to 56 degrees with a raised district platform, inset population columns, illuminated river/flood ribbons, a camera compass, and an overlay showing the selected level and approximate exposure.
- **Orbit region / Pause camera** rotates the camera around the district. The animation is optional, runs at no more than 25 updates/second, and does not advance flood levels. **Play spread** can animate the flood levels alongside the camera.
- **Region overview**, **Fly to river**, and **Population focus** provide camera presets. River close-up targets an existing river-reference vertex nearest the area reference point; population focus targets the highest-density display cell. These are navigation targets, not new hydrological outputs.
- **Population map**, **Flood spread**, level slider, lowest/highest presets, comparison bars, and summary counts continue to use the existing shared controls. Blue columns indicate cells intersecting the selected footprint. Clicking a column shows its modeled 2025 population, density, and approximate population within the footprint.
- Returning to 2D restores the two synchronized top-down maps. District, level, and exposure estimates stay the same. Neither presentation submits a monitoring run or changes the existing alert/incident workflow.

## Data, engineering, and display scales

No new datasets or prediction models are introduced. Inputs remain the existing real district outlines, approximate OSM river references, the precomputed hypothetical river-buffer footprints, and WorldPop 2025 modeled population aggregated to a 2 km equal-area grid. See [population methodology](ten-year-population-exposure-layer.md) and [flood-spread methodology](ten-year-flood-spread-layer.md).

`simulationCinematicData.ts` constructs a display glyph for each original population cell by scaling its polygon coordinates to 64% about the cell bounding-box center. Polygon and multipolygon parts are retained; line artifacts in geometry collections are ignored. Original source geometries, counts, footprint intersections, and six saved exposure totals are never mutated or recalculated for the 3D view.

MapLibre fill-extrusion supplies real perspective rendering, with **arbitrary exaggerated display heights**:

- District platform: height 2,600 in renderer units.
- Population columns: base 2,700; top `2,700 + min(34,000, 420 × sqrt(max(0, density_km2)))`. Zero-population cells have no column. Density therefore controls relative height; these are glyphs, not measured buildings or terrain.
- Water: base 2,650; top `2,850 + 220 × selected_level`. Only rings up to the selected level render, and level 0 contains no water. This thickness is a visual effect, not water depth or gauge height.
- Column colors follow density, with a blue override when the cell's saved `exposed_by_level` value is positive. Blue does **not** mean the entire cell population is affected. Popups and totals continue to use the saved fractional-area estimate.

These renderer units are not presented as physical heights in the UI. A visible key and Inputs & Method explain that this is a stylized population visualization, with no terrain, building-height, water-depth, or hydraulic simulation. It does not add predictive accuracy to the underlying hypothetical spread.

## Camera, performance, and accessibility

The mode **reuses the existing two map canvases**. The left baseline pane is hidden in 3D and camera synchronization is suspended, so orbit frames do not rotate or continuously redraw the hidden baseline map. No Three.js, Cesium, new 3D engine, mobile tooling, raster terrain downloads, remote tiles, or extra canvas is installed or loaded.

Population glyphs are prepared lazily when 3D is selected. A single source on the right map holds glyph geometry. Level changes update feature-state colors and the existing water filter rather than uploading the entire geometry on each animation frame. Region changes clear feature state and load only that region's existing compressed assets. The model inputs and population calculation remain unchanged.

Orbit uses `requestAnimationFrame`, capped at one update every 40 ms, at 4.8 degrees/second. Pause, manual level/layer/region/camera selection, motion-off, reduced-motion preference, hidden document, less than 8% scene visibility, changing presentation, and leaving the preview stop the relevant orbit loop. It never restarts automatically after a visibility/preference interruption. Static 3D and camera presets remain available under reduced motion, with zero-duration camera transitions.

Existing map observers and contexts are removed when leaving the Simulation preview. Source/load failures retain existing retry behavior; a cinematic render error returns to the available 2D presentation with an explanatory message. Badin's population columns remain available, while its unsupported water footprint and river camera preset stay unavailable.

## Files

- `frontend/src/components/SimulationFloodVisualization.tsx`: presentation switch, camera presets/orbit, mode-aware framing and synchronization, compass/readouts, and shared controls.
- `frontend/src/components/useSimulationCinematicScene.ts`: lazy extrusion layers, feature state, source attribution, and column popups.
- `frontend/src/components/simulationCinematicData.ts`: immutable glyph preparation and data-backed camera targets.
- `frontend/src/components/TenYearFloodExposure.tsx`: optional data/visibility callbacks and cinematic legend/context wording. Defaults preserve the outlook and basic Simulation presentations.
- `frontend/src/simulation-cinematic.css`: scoped scene styling and responsive controls.

The rendering uses the existing MapLibre APIs, checked against the official [fill-extrusion specification](https://maplibre.org/maplibre-style-spec/layers/#fill-extrusion) and [camera-orbit example](https://maplibre.org/maplibre-gl-js/docs/examples/animate-map-camera-around-a-point/). Dataset attribution remains visible, including on the new glyph source.

## Verification

From `frontend`:

```powershell
node scripts/check-simulation-cinematic-data.mjs
node scripts/validate-simulation-cinematic.mjs
node scripts/validate-simulation-flood-visualization.mjs
node scripts/validate-outlook-flood-exposure.mjs
npm run build
```

The data check covers all eight districts, preservation of cell IDs/counts, nonmutation of source data, and honest camera targets. The cinematic browser check verifies actual rendered extrusion features, canvas reuse, unchanged estimates, orbit/pause, both close-ups, column inspection, level/layer consistency, district switching, missing river data, reduced motion, document/offscreen cleanup, restoration of synchronized 2D cameras, compact layout, and zero backend writes/runtime errors. Existing Simulation and outlook checks cover the original shared behavior.

All five checks passed on 2026-10-15. Browser tests reported zero runtime errors and no backend writes. Overview, river close-up, and compact screenshots are saved as `frontend/screenshots/simulation-cinematic-*.png`. Visual review confirmed the raised columns, footprint highlighting, camera framing, and original comparison restoration.

## Limitations and future scope

This is an advanced **presentation**, not a validated digital twin. It supplies no elevation, buildings, hydraulic routing, true flood depth, or calibrated reading-to-inundation relationship. Before introducing such claims, obtain vetted terrain, drainage, levee/building data, station relationships, and historical flood validation. Those remain future work. Population and inundation uncertainty from the current coarse what-if method remains unchanged.
