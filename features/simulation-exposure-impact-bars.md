# Simulation: animated population and affected-area bars

Added 2026-10-15 in **Simulation → Storm replay → Event inspector**. The numeric people and affected-area readouts now sit in prominent colored bar cards: teal for population and blue for area. Numeric values, units, approximate-population labels, existing scenario controls, maps, and monitoring workflows remain available.

## Data and scale

Both bars use the existing selected-level data without recalculating exposure or adding a model:

```text
population fraction = selected.exposed_population / level_5.exposed_population
area fraction       = selected.flood_area_km2 / level_5.flood_area_km2
```

Each bar explicitly labels its percentage **of level 5** and displays the level-5 reference amount. This scale stays fixed when switching lower/moderate/higher replay scenarios, making their relative impacts visible. It resets to the new district's own values when selecting another district. Level 5 means the largest existing hypothetical footprint, not a physical upper bound, the whole district, or a flood probability.

The amount printed beside each bar is the same saved estimate used by the replay's current map level and chart. Population keeps its original approximate formatting and fixed WorldPop 2025 semantics; area is in square kilometres. Zero is a valid empty bar. Missing footprints, including Badin, show **Unavailable** and no numerical meter instead of implying zero people/area are affected. A zero or invalid scale cannot produce a division-by-zero fill.

## Animation and accessibility

During playback, changed values transition bar width over 650 ms. A subtle moving highlight continues while the timeline is playing, including level plateaus; this highlight does not change the amount or percentage. Pause settles to the exact current value and pauses the highlight. Static manual selections show their exact widths immediately.

Motion-off, reduced-motion preferences, hidden documents, and the existing map visibility gate disable decorative motion. No timer, request, rendering engine, dependency, or backend write is introduced. Each available bar uses the accessible `meter` role, its actual saved numeric range/value, and a text description that identifies the level-5 comparison. The source estimates and their limitations remain unchanged.

## Files and verification

- `frontend/src/components/ReplayImpactBar.tsx`: shared semantic bar card with numeric values and scale handling.
- `frontend/src/components/SimulationStormReplay.tsx`: current population/area amounts, district-specific reference amounts, and the existing motion gate.
- `frontend/src/simulation-storm-replay.css`: scoped bar appearance, width transitions, and playback-only highlight.
- `frontend/scripts/validate-storm-replay.mjs`: saved-value/scale checks for both actual bar widths, peak/lower/zero/missing cases, an observed intermediate animation frame, pause/reduced-motion checks, and the existing replay regression checks.

`node scripts/validate-storm-replay.mjs` and `npm run build` passed on 2026-10-15. The browser check verified actual intermediate bar widths during playback, both saved-value scales, peak/lower/zero/missing-data states, paused and reduced-motion behavior, compact layout, and all original replay controls. It reported no browser errors or operational writes, and the monitoring draft was preserved. The build retained only the existing large-chunk advisory.

Visual review confirmed clear teal/blue bars, readable numeric values and reference labels, and the retained map/chart/line inspector. Screenshots are available under `frontend/screenshots/`, including `simulation-exposure-impact-bars.png` and the existing replay compact screenshot.
