# Ten-year outlook: hypothetical maps and charts

## Authorization and scope

The user explicitly requested a hypothetical picture of the intended future product, with maps, graphs, and change summaries **inside the existing 10-Year Outlook sub-tab**. This replaces the introductory empty state. It does not complete the real projection model or resolve the [dataset audit](ten-year-dataset-audit.md).

## Strategy

Use the existing web dashboard and MapLibre dependency. Reuse its compressed district-boundary asset and shared asset cache, without downloading new datasets or adding packages. Render two synchronized maps for a constructed 2026 baseline and selected 2027-2036 planning year. Use one deterministic fixture for map colors, chart points, summary cards, and change rankings so all displays agree.

District geography is real. All current indices, stress assumptions, sensitivities, future indices, and range widths are hand-authored illustrations. The page, each map, chart, method panel, and footer identify the hypothetical nature. The index is not a flood probability, measured discharge, or inundation footprint. The preview cannot produce alerts or incidents. The later optional [flood-spread layer](ten-year-flood-spread-layer.md) and [WorldPop population layer](ten-year-population-exposure-layer.md) add a separate what-if experiment; they do not drive the hypothetical index.

## Hypothetical data

Fixture version: `hypothetical-outlook-v1` in `frontend/src/components/tenYearPreviewData.ts`.

- Eight example districts: Jhang, Multan, Lahore, Rawalpindi, Charsadda, Sukkur, Dadu, Badin.
- Three demonstration flood types: riverine, flash, urban. The urban example does not imply that urban flood labels exist in the historical data.
- Three arbitrary stress cases: stable, moderate, higher. These are not SSP emissions scenarios or downloaded climate projections.
- Baseline year 2026; annual example points to 2036. Years label hypothetical planning progress, not real future weather realizations.
- Three constructed baseline indices per area, plus an invented sensitivity factor.
- Moderate stress uses rainfall input 30 and built-up input 20; higher stress uses 60 and 40; stable uses zero. These inputs are index units, not measured percentages.

Formula:

```text
progress = (year - 2026) / 10
pressure = rainfall_weight * rainfall_stress + built_up_weight * built_up_stress
index = clamp(baseline + sensitivity * pressure * progress, 0, 100)
illustrative half-range = 3 + 6 * progress
```

Hazard weights are listed in the fixture and visible in Inputs & Method. Values/range endpoints are rounded to one decimal place. Bounds are capped at 0-100. Every returned point carries `isHypothetical: true`; map properties also carry `is_hypothetical: true`.

The all-areas view is an unweighted mean of these eight examples and is explicitly **not a national estimate**. Changes use index points, never probability percentage points. The range is a visual illustration, not a statistical confidence interval. Lower/moderate/higher display bands at 35 and 65 are not official flood-warning thresholds.

## Map behavior

The subsequent [animated exploration feature](ten-year-outlook-motion-and-map-tour.md) adds user-controlled playback, smooth camera framing, and a guided tour. It replaces full GeoJSON score updates with small feature-state updates; the underlying hypothetical data and labeling remain the same.

- Current and future maps show the same real district geography and use the same legend. Districts outside the eight examples stay gray as **No example data**.
- Pan/zoom controls are synchronized. Controls, keyboard panning/zoom, and a reset-view button are available.
- Resizing the browser refits both maps to the selected area or full comparison extent so the overview remains framed at narrower widths.
- Clicking a colored district or example-location dot selects it and updates the rest of the view. Selection highlights the corresponding district and frames both maps together.
- Each map has a current selected-area index readout, so color is not the sole way of reading the example.
- Boundaries are existing display references. No polygon area, inundation, or historical-to-current district crosswalk calculation is performed, and source geometry is unchanged. Known display-geometry issues in the audit still need resolution before analytical spatial operations.
- Basemaps do not require remote raster tiles, Google keys, geocoding, or glyph downloads. Attribution stays visible.
- The comparison component loads lazily when the sub-tab is active. Both maps are removed on leaving it, releasing WebGL canvases and observers. Selections remain in the parent component while switching between the two predictive sub-tabs.

## Chart and change summaries

The chart displays the selected area's example curve, a horizontal current-example reference, an illustrative range, and a selected-year marker. An expandable table exposes all eleven annual example values accessibly. The three cards show baseline, selected-year index/range, and change. The change list shows the four largest constructed changes and lets users select an area.

Selectors for area, flood type, stress scenario, and year change all displays from the same fixture. No API writes or new observation history are introduced. A full page reload restores the default example selections.

## Implementation files

- `frontend/src/components/TenYearRiskOutlook.tsx`: sub-tab preview, selections, cards, change list, lazy map lifecycle.
- `frontend/src/components/tenYearPreviewData.ts`: deterministic hypothetical data and shared calculations.
- `frontend/src/components/TenYearComparisonMaps.tsx`: synchronized vector maps and click selection.
- `frontend/src/components/TenYearOutlookChart.tsx`: SVG chart and accessible value table.
- `frontend/src/ten-year-risk-outlook.css`: scoped preview styling.

## Verification

Run the following with existing tooling:

```powershell
cd frontend
node scripts/check-ten-year-preview.mjs
node scripts/validate-ten-year-preview.mjs
npm run build
```

The pure-data check covers hypothetical provenance, stable-case behavior, scenario ordering, bounded ranges, aggregation, and invalid inputs. Browser verification covers selector consistency across maps/chart/cards, synchronized zoom, actual location-pin clicks, method-panel content, the example-value table, desktop/compact layout, WebGL cleanup, preservation of the near-term dialog, and absence of backend writes. Results are recorded in the completion update after running these checks.

Completion results: all three commands passed. Browser checks ran against the existing web app with Microsoft Edge at 1600 x 1050 and 1024 x 768, without horizontal overflow or runtime errors. A separate injected boundary-request failure verified an explicit fallback, continued chart/selector use, and successful retry of both maps. Screenshots are saved locally as `frontend/screenshots/ten-year-hypothetical-desktop.png` and `frontend/screenshots/ten-year-hypothetical-compact.png`. No packages or mobile tooling were installed.

## Future work

The [real-data audit](ten-year-dataset-audit.md) remains the basis for a validated replacement. Prepare continuous histories, geography crosswalks, real future inputs, and appropriate historical validation before replacing constructed values. Keep the current fixture as an explicitly separate demo mode if retained later.
