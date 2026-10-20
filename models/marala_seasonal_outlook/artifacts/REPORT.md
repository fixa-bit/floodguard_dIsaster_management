# 365-day modeled-reach outlook

One daily mean estimate per date, for the next 365 days. Research only.

These targets are modeled GloFAS reach discharge, not measured Marala inflow or 06:00 instantaneous readings.

Forecast: 2026-10-16 through 2027-10-15. Selected: seasonal_climatology.

Fit candidates through 2013, select on 2014-2017, freeze selection, refit through 2017, evaluate 2018-2021.

| Candidate role | Held-out RMSE (m3/s) | MAE (m3/s) |
|---|---:|---:|
| champion | 182.49 | 121.48 |
| best_learned | 188.86 | 114.44 |
| seasonal_naive | 221.23 | 146.15 |
| persistence | 536.75 | 378.71 |
| seasonal_climatology | 182.49 | 121.48 |

Do not choose a new candidate using this final test. Compare errors by lead window in model-card.json.

Daily forecasts are aggregated into monthly averages, with partial first/last months explicitly flagged.
No artificial noise, daily-to-subdaily interpolation, or gauge/proxy mixing is used.

The dashboard feed has not been replaced. This does not establish operational gauge or flood-warning accuracy.
