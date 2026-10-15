# FFD and GloFAS discharge-window alignment

## Scope

This feature applies only to the **Discharge forecast** modal opened from a river station. It does not change the river-monitoring table, overview, GIS views, upstream forecasts, alerts, stored observations, API payloads, or raw provider values.

## Problem

FFD reports discharge at a physical gauge or barrage. Open-Meteo exposes GloFAS discharge from a nearby 5 km model grid cell. A grid cell can have a large systematic offset from the gauge and, at structures such as Chashma, may resolve to a low-flow neighboring cell. Plotting both raw series on one axis can flatten GloFAS near zero or make the observation unreadable.

## Display strategy

The modal applies an additive anomaly alignment when it has both a valid latest FFD observation and a valid latest GloFAS modeled-history point.

```text
offset = latest FFD observation - latest GloFAS modeled history
displayed GloFAS(t) = max(0, raw GloFAS(t) + offset)
```

The same offset is applied to the displayed seven-day model history and five-day forecast. A synthetic point at the exact FFD observation time starts the forecast line, so the observed and forecast series join without a time or vertical gap. Negative adjusted discharge is clipped to zero.

An additive method is used instead of multiplicative scaling because some selected model cells report values close to zero. Multiplicative scaling would amplify those cells by factors of hundreds or thousands and exaggerate small model fluctuations.

## Labels and transparency

- Adjusted legend entries include **FFD-aligned**.
- The modal states the offset, direction, method, and limitation.
- CSV rows exported from the modal identify the additive alignment in the source column.
- The raw backend and all other views remain unchanged.

This makes the two series visually comparable and preserves the GloFAS change in cumecs. It is not gauge calibration and should not be described as a corrected operational forecast.

## Verification

- The data-series check asserts that the latest modeled history equals the FFD observation after alignment.
- The displayed forecast begins at the exact FFD observation time and value.
- Five model forecast days remain after the anchor point.
- Alignment never produces negative discharge.
- A browser check confirms the observed and forecast paths share the same scale in the discharge forecast modal.
