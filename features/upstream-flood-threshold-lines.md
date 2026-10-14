# Upstream flood threshold lines

## Purpose

Show a horizontal reference line on every upstream discharge forecast chart so the forecast can be compared with a documented flood-onset value. The line is a screening reference; it does not claim that modeled discharge alone proves flooding at a specific community.

## Station values

All chart values use cubic metres per second (cumecs).

| Station | Reference | Value | Classification |
| --- | --- | ---: | --- |
| Besham Upper Indus | Median of annual maximum modeled flow, 1980-2025 | 318.62 cumecs | Model-derived 2-year flow reference |
| Danyor Gilgit River | Median of annual maximum modeled flow, 1980-2025 | 25.01 cumecs | Model-derived 2-year flow reference |
| Chenab Marala | FFD low flood, 100,000 cusecs | 2,831.68 cumecs | Official threshold |
| Ravi Jassar | FFD low flood, 50,000 cusecs | 1,415.84 cumecs | Official threshold |

The official values use `1 cusec = 0.028316846592 cumecs`.

## Source strategy

Marala and Jassar use the Pakistan Flood Forecasting Division's published low-flood classifications:

- FFD, [Flood Limits of Rivers & Nullahs](https://ffd.pmd.gov.pk/flood-limits)
- Federal Flood Commission, [Flood Classification of Major Rivers](https://ffc.gov.pk/flood-classification-of-major-rivers/)

FFD does not publish Besham or Danyor in that classification table. Those stations therefore use the exact GEOGloWS reach displayed by the application and its daily retrospective series from 1 January 1980 through 31 December 2025. For each of the 46 complete calendar years, the maximum daily flow was selected. The median of those annual maxima is used as an empirical two-year-flow proxy.

- GEOGLOWS explains that its ERA5 retrospective record is used to derive return periods: [GEOGLOWS model overview](https://geoglows.ecmwf.int/about)
- Retrospective API pattern: `https://geoglows.ecmwf.int/api/v2/retrospectivedaily/{river_id}`
- Besham reach: `440341343`
- Danyor reach: `440121137`

As a historical cross-check, the Besham reach reached 522.39 cumecs on 29 July 2010, above its 318.62-cumec reference. The local DesInventar data includes Gilgit flood and flash-flood dates, but the Danyor reach did not consistently show a large-river peak on those dates. Its 25.01-cumec line is therefore labeled as a modeled river-flow reference and must not be interpreted as a local flash-flood threshold.

## Display and risk behavior

- The chart scale includes the reference, so the dashed threshold line is always visible.
- The legend and line state the reference type and value.
- A note below the chart identifies whether the line is official or model-derived.
- Riverine risk compares the highest trusted provider peak with this reference.
- Flash-flood risk remains separate and uses rapid modeled rise plus rainfall because a river-flow reference does not cover localized flash flooding.

## Verification

- Backend tests assert a documented value, type, label, and basis for all four upstream stations.
- Marala and Jassar tests assert the official converted thresholds.
- Browser verification checks that each selected station renders one labeled dashed line at its own value.

Sources and retrospective values were checked on 13 October 2026.
