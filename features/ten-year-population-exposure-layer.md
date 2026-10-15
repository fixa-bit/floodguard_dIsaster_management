# 10-Year Outlook: population layer and what-if exposure

Implemented 2026-10-14 alongside the separately documented [flood-spread layer](ten-year-flood-spread-layer.md). This is a modest exposure demonstration inside the existing **10-Year Outlook** sub-tab, not a population projection, confirmed-impact report, or validated flood model.

## Dataset used

- Local source: `pak_pop_2025_CN_100m_R2025A_v1.tif` from the existing exposure integration's WorldPop download.
- **WorldPop R2025A v1, Pakistan 2025, constrained approximately 100 m population counts**, licensed **CC BY 4.0**. Counts are modeled people per native pixel, not people/km² and not a household census.
- Official source asset: [WorldPop Pakistan 2025 raster](https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/PAK/v1/100m/constrained/pak_pop_2025_CN_100m_R2025A_v1.tif).
- [WorldPop Global 2 release and limitations](https://data.worldpop.org/repo/prj/Global_2015_2030/R2025A/doc/Global2_Release_Statement_R2025A_v1.pdf). The provider describes R2025A as an alpha release; population is estimated rather than directly counted in every cell.
- Source filename, SHA-256, year, resolution, license, source reference, and processing assumptions are recorded in `frontend/src/data/outlook-exposure/metadata.json`.

## Features and engineered values

1. Read native count pixels and valid-data masks in small windows; no national raster load, value resampling, raw-raster writes, or replacement of NoData with zero.
2. Include native pixels whose centers fall inside each of the eight display district polygons. Boundary assignment therefore has a native-pixel-center approximation. These are app display districts, which can differ from the provider's census boundaries or other exposure pilots.
3. Sum the original counts into 2 km equal-area EPSG:6933 grid cells, clipped to the district. Store known population, density using the clipped cell area, known-raster area, cell area, and six per-level exposure estimates.
4. For each hypothetical footprint, calculate **cell population × (footprint/cell intersection area ÷ clipped cell area)** and sum across cells. This is a coarse uniform-within-cell approximation; it is not the existing native-cell operational population analysis and does not reuse a previous historical flood's exposed count.
5. Precompute all six levels once. The frontend switches layer filters and reads the selected level's saved totals, avoiding per-slider backend jobs. Only the requested district's gzip asset loads; all eight compressed bundles together are roughly 0.65 MB.

No new trained model is introduced. The ten-year hypothetical index and the flood-level experiment remain separate. **Population stays fixed at 2025 for every planning year**, and the interface says so. No unsupported 2036 growth rate, vulnerability coefficient, future census count, or statistical confidence interval is invented.

## Output and controls

**Population map** toggles a density grid on both synchronized comparison maps. Sparse areas are muted; dense cells move through yellow/orange to rose, distinct from the blue example water. Map attribution and a visible source/license note identify WorldPop and OSM. Clicking a cell shows its approximate 2025 population and, on the right when flood spread is enabled, population intersecting the selected example footprint.

The summary shows approximate people within the footprint, percentage of the district's known modeled population, example footprint area, and total known 2025 population. Counts are rounded to the nearest 100, with positive values below 100 shown as `<100`. Six clickable bars compare levels 0–5. Level 0 reports zero exposure for supported districts. Without usable river data, exposure and footprint area show **Unavailable**, including for Badin; lack of a footprint never becomes zero risk. The real population map remains available there.

The common **Inputs & Method** panel documents all datasets, fields, engineering, the intersection formula, outputs, limits, and future scope. A separate population baseline prevents year/scenario changes from being mistaken for population forecasts.

## Limitations and future scope

- Exposure is conditional on an invented footprint; it is not a claim that these people will flood, be displaced, or need evacuation.
- Uniform allocation within a 2 km cell can over- or underestimate exposure for narrow corridors and concentrated settlements. Source population, display boundaries, river alignment, pixel-center masking, and display simplification add uncertainty. NoData is excluded, not asserted to be uninhabited. R2025A source uncertainty is not captured by a statistical band here.
- No building-level results, demographic vulnerability, verified flood depth, population growth, or national exposure estimate is supplied.
- Replace synthetic footprints with validated hydraulic/hazard surfaces; compute native-resolution exposure with explicit coverage diagnostics; compare estimates against observed flood impacts. Add independently sourced population scenarios and demographic/infrastructure data only after the basic exposure pipeline is validated.

## Implementation and checks

`scripts/build_outlook_flood_exposure.py` creates the portable feature assets. It does not modify the existing population API's latest analysis or historical-reference results. `scripts/check_outlook_flood_exposure.py` checks population conservation, finite/nonnegative counts, per-cell and aggregate monotonicity, zero-level behavior, missing coverage, source hashes, and valid clipped display geometry. `frontend/scripts/validate-outlook-flood-exposure.mjs` exercises controls, real map popups, all districts, failure/retry, map cleanup, and zero operational writes. No Flutter tooling or dependencies are installed.
