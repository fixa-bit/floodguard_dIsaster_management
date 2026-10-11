# Station discharge provenance

Research checked 11 October 2026. Primary station view uses official FFD data only.

## Verified public products

- FFD live map: https://ffd.pmd.gov.pk/river-state?zoom=6
  Its public JSON contains separately typed INFLOW and OUTFLOW gauges, raw cusecs,
  and a station recording time. The top-level discharge is not necessarily inflow.
  Trimmu at 12:00 PKT has inflow 15,359 cusecs and outflow 1,159 cusecs.
- FFD bulletin: https://ffd.pmd.gov.pk/bulletin
  The marked station table contains observed inflow/outflow at 06:00 PST and
  next-24-hour inflow forecasts in THOUSANDS of cusecs. The 11 October bulletin
  gives Trimmu 16.0 / 1.2 thousand cusecs at 06:00, not the live map's 12:00 reading.
  Numeric forecasts are intervals; narrative forecasts are not numeric curves.
  Its issue time is explicit, but exact forecast start/end timestamps are not.
  Therefore the forecast interval is displayed separately from the observation
  timeline, rather than assigning invented validity timestamps or hourly values.
- FFD historical publications: https://ffd.pmd.gov.pk/bulletins/archive
  Public bulletin documents exist. No public numerical five-day station forecast
  API or documented station time-series API was verified. This is not a claim
  that FFD has no internal or agency-accessible service.
- FFD early-warning description: https://ffd.pmd.gov.pk/flood-ews
  Describes telemetry and forecasting systems; it is not an API specification.
- WAPDA public river-flow page: https://wapda.gov.pk/river-flow/
  No documented public station-forecast API was verified there. Agency data
  sharing with PMD/FFD/WAPDA is the stronger future route for an NDMA portal.

## Model context, not an official station forecast

- Open-Meteo GloFAS: https://open-meteo.com/en/docs/flood-api
  Daily simulated discharge is already m3/s. A nearby 5 km grid cell may select
  the wrong river. Changing display units does not fix spatial or gauge mismatch.
- GEOGLOWS: https://training.geoglows.org/rfs/bias-correction/forecasted-bias-correction/
  Forecast bias correction requires historical modeled and observed distributions.
  Scaling a curve to one reading is not verified calibration. GEOGLOWS is not
  introduced as another official station-data source in this change.

## Implementation safeguards

One cusec = 0.028316846592 m3/s. Bulletin numbers have an additional factor of
1,000. Numeric observations retain their recording timestamp and source URL;
SQLite persistence normalizes PKT timestamps to UTC first. Typed history has a
separate table, so legacy untyped observations cannot become inferred inflows.
History builds as the portal collects observations; the latest bulletin adds
its explicitly timed observation. No historical measurements are fabricated.

The official view defaults to inflow. Outflow never receives the inflow forecast.
Forecast ranges are retained in display and CSV, and narrative outlooks remain
text. Older bulletins/readings are visibly marked stale. Parsing or network
failures leave the forecast unavailable rather than silently substituting models.
Bulletins are cached for five minutes, fetched only when station details request
official history, and shared across stations. Hover requires no additional fetch.
The separate model-comparison view preserves the available model horizon and
does not mix station readings or perform unverified rescaling.

## Checks

Run backend bulletin, station-history and river-monitoring tests; frontend
`check-station-forecast.mjs` and `check-station-hover-browser.mjs`; then build.
In the browser open Taunsa or Trimmu, select Discharge forecast, switch Inflow /
Outflow, inspect source timestamps, and switch to Model comparison. Check mobile
layout and verify the original Station details tab remains unchanged.
