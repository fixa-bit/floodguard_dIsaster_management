# Ten-year outlook: Inputs & Method panel

## Strategy and placement

The user requested datasets, features, engineered features, model, outputs, limitations, and future scope inside the existing ten-year outlook sub-tab. Provide an expandable **Inputs & Method** section below its maps/chart. A button at the top opens and scrolls to that section. This keeps the preview and its explanation on the same page.

Implementation: `frontend/src/components/TenYearInputsMethod.tsx`, controlled by `TenYearRiskOutlook.tsx`.

## Current versus future data

The first table lists only the inputs actually consumed now:

1. Existing Pakistan display polygons: district names, IDs, and coordinates, used solely for map outlines/selection.
2. A hand-authored hypothetical fixture: area references, baseline indices, sensitivity, hazard weights, and stress inputs.
3. WorldPop Pakistan 2025 native population counts and valid-data mask, aggregated to a 2 km grid for the optional population layer. This is a fixed, modeled population baseline and does not feed the outlook scores.
4. Existing derived OSM river reference lines, used for the independent hypothetical flood-spread experiment. Missing alignments remain unavailable.

A separate table describes audited historical data and planned additions. It makes clear that DesInventar, historical rainfall/GloFAS, future CMIP6 climate data, terrain/land cover, and population-exposure pilots do not drive this preview's scores. Dataset availability is not presented as current model use.

## Explanation of calculations and outputs

The panel exposes planning progress, weighted illustrative pressure, the index formula and caps, range construction, aggregation across examples, current selection's stress/weight values, and every area's chosen hazard baseline and sensitivity. Changing hazard or scenario updates this explanation with the chart.

It states that no trained model or historical validation runs for the preview. It identifies the outputs as hypothetical indices/ranges and display categories, with no probability or official threshold interpretation. Formula and fixture details are also documented in [maps and charts](ten-year-hypothetical-maps-and-charts.md).

The later **Flood spread and population method** section explains arbitrary nested river buffers, ordinal levels 0–5, equal-area 2 km population intersection, the uniform-within-cell assumption, source NoData handling, fixed 2025 population, the separate map/bar-chart outputs, and unavailable river coverage. It explicitly separates this experiment from outlook years, hazard indices, and official gauge/discharge thresholds. See [flood spread](ten-year-flood-spread-layer.md) and [population exposure](ten-year-population-exposure-layer.md) for full strategies and regeneration instructions.

## Limitations and future scope

The limitations cover invented values, lack of predictive/statistical interpretation, illustrative urban examples, gray no-example areas, and isolation from operational alerts/incidents.

Future scope starts with consistent historical data and sourced climate projections. It proposes a historical baseline and later-year validation first, then interpretable regression where labels permit, with XGBoost comparison and hydrological/exposure/reservoir extensions only when data supports them. These are clearly future candidates, not models claimed to be implemented now.

## Accessibility and verification

Uses native details/summary and semantic tables, headings, lists, and links. The top button exposes `aria-expanded` and `aria-controls`. The section is part of the page rather than a modal, so users can compare the explanations with the visual outputs.

`frontend/scripts/validate-ten-year-preview.mjs` verifies opening the section from its button, presence of all requested topic headings, its no-trained-model statement, and the absence of backend writes. Production TypeScript/build validation covers component integration.

Result: browser verification and the production build passed. The panel remains in the same sub-tab as the maps/chart; it has no API writes and does not start model training or data acquisition.
