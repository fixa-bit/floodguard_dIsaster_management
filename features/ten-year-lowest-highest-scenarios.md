# Lowest and highest example scenarios

Added 2026-10-15 to **Predictive Risk Views → 10-Year Outlook**. This feature has two explicit scopes: outlook stress assumptions and quick flood-spread endpoints. Both remain hypothetical.

## Outlook selector

The existing Example scenario selector now contains five ordered choices. Existing choices and the default Moderate stress selection are retained.

| Scenario | Rainfall-stress input | Built-up-stress input | Meaning in this demonstration |
| --- | ---: | ---: | --- |
| Lowest scenario | -15 | -10 | Illustrates reduced stress and an improving index over the decade |
| Stable conditions | 0 | 0 | Keeps the constructed baseline unchanged |
| Moderate stress | 30 | 20 | Existing moderate increase |
| Higher stress | 60 | 40 | Existing larger increase |
| Highest scenario | 90 | 60 | Greatest positive stress among these examples |

These numbers are **arbitrary index inputs**, not measured percentages, climate-model projections, SSP pathways, probabilities, or return periods. Negative values illustrate improvement; they are not negative rainfall. Highest means highest among this fixture's five choices, not a scientifically established maximum flood. Lowest does not mean guaranteed safety.

The existing formula remains `baseline + sensitivity × weighted stress × planning progress`, capped at 0–100. All scenarios start from the same 2026 baseline. The lowest produces a declining example curve; the highest produces a rising curve, which may reach the existing cap. Maps, chart, future score, example changes, and Inputs & Method all use the same selected scenario. The illustrative range remains separate from the scenario endpoints and is not a statistical confidence interval. Fixture provenance is now `hypothetical-outlook-v2`.

A description below the selector explains the chosen assumptions. The selector references it with `aria-describedby`. Inputs & Method also documents the stress values and the distinction between example endpoints and physical/statistical bounds.

## Flood-spread presets and population comparison

Two buttons beside the flood-level slider provide direct access to its endpoints:

- **Lowest flood scenario · Level 0:** no example flooding and zero exposure for a supported district.
- **Highest flood scenario · Level 5:** the widest existing example footprint and its precomputed population exposure.

The slider, selected bar, right map, footprint area, and exposed-population summary update together. Buttons show their selected state with `aria-pressed`, support keyboard interaction, and stop active playback/touring just like manual slider changes. They remain disabled while maps/data are unavailable or the district lacks usable river data, including Badin.

These buttons change only the **spread level**. They do not alter the outlook scenario, planning year, hazard selector, or fixed WorldPop 2025 population baseline. Conversely, selecting lowest/highest outlook stress does not silently alter the water footprint. A calibrated scenario-to-inundation relationship remains future work. The two models must not be presented as physically connected merely because both provide endpoints.

No source datasets, population assets, backend APIs, operational forecasts, alerts, or incidents change. No packages or mobile tooling are installed. Existing spread and population methods remain documented in [flood spread](ten-year-flood-spread-layer.md) and [population exposure](ten-year-population-exposure-layer.md).

## Verification

- `node frontend/scripts/check-ten-year-preview.mjs`: ordering across all five scenarios for every supported year, area, and hazard; shared baseline; improving/worsening direction; bounded indices/ranges; aggregate consistency and invalid-input guards.
- From `frontend`, `node scripts/validate-ten-year-preview.mjs`: selects both new outlook scenarios and verifies map/chart/summary agreement and explanatory text, plus existing preview checks.
- From `frontend`, `node scripts/validate-outlook-flood-exposure.mjs`: tests both spread presets against saved district totals, selected button state, independent outlook/spread controls, disabled missing-data states, and existing population-layer checks.
- From `frontend`, `npm run build`: TypeScript and production build.

All four checks passed on 2026-10-15. The population-popup browser check now projects real populated cell coordinates through the current camera instead of assuming fixed screen pixels, so changes to control layout do not invalidate the interaction check. Browser suites reported no runtime errors or backend writes.

Future scope: replace arbitrary stress inputs with sourced and historically validated scenario assumptions before calling these best/worst forecasts. Add physical scenario-to-flood-extent relationships and future population assumptions only when their datasets and validation are available.
