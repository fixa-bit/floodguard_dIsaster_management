# Marala forecasting experiments

Two separate targets are retained to avoid mixing measured gauge inflow with
modeled river-reach discharge.

| Folder | Target | Output | Independent evaluation |
|---|---|---|---|
| `marala_station_forecast` | Actual FFD inflow measured at 06:00 PKT | Direct 1-, 3-, 7-day estimates | Fit 2024, select 2025, test 2026 |
| `marala_seasonal_outlook` | Archived GloFAS modeled reach daily mean | One daily mean for 365 days, plus averages by month | Fit through 2013, select 2014-2017, test 2018-2021 |

The current annual output covers **16 October 2026 through 15 October 2027**.
It is a statistical seasonal outlook, not a validated prediction of individual
Marala flood events. It cannot be labeled a daily instantaneous gauge forecast.

Both experiments train ridge and XGBoost candidates and compare simple
baselines. Candidate choices are frozen before held-out evaluation. The best
learned fit is retained separately when a baseline wins. Every final model is
refit after evaluation; its held-out score belongs to the separate evaluation
fit, not to that final fit.

## Results and deployment decision

The gauge experiment has only 322 actual readings across three incomplete
seasons. Held-out RMSE versus persistence, in m3/s:

| Lead | Validation-selected model | Persistence | Improvement |
|---|---:|---:|---:|
| 1 day | 423.98 | 423.82 | -0.04% |
| 3 days | 834.25 | 584.99 | -42.6% |
| 7 days | 871.11 | 962.67 | 9.5% |

This does not justify replacing the dashboard feed or claiming consistently
better gauge forecasting. The three-day validation winner fails to generalize.

For the annual modeled-target experiment, seasonal climatology wins validation.
Held-out RMSE is 182.49 m3/s, compared with 188.86 for the best learned XGBoost
candidate and 221.23 for the previous-year seasonal baseline. These scores
evaluate a modeled target and cannot be compared with gauge-error scores as
evidence of better gauge accuracy. Smoothness is expected for a seasonal mean
outlook; no artificial variability is added to make forecasts look realistic.

Both are **research only**. No backend route or dashboard feed is changed, and
no backend restart is needed for these offline experiments.

## Data retained for future validation

Each folder's `LATEST_RUN.json` identifies its sealed run and manifest checksum.
Each run retains source snapshots, source URLs and hashes, code/configuration,
package versions, features, labels, splits, candidates, selection, saved fits,
held-out predictions and forecast outputs. Every retained file is inventoried
with SHA-256. Gauge runs additionally retain the original bulletin PDFs/HTML
and extraction audit. Missing observations are never interpolated into labels.

Run the `validate` command documented in each folder to check hashes and replay
held-out predictions offline. Keep all sealed runs for future comparisons; new
experiments create new directories. The convenient `artifacts/` latest copies
are not the historical record.

The next material improvements require longer year-round measured Marala data,
upstream flows/releases and forecast inputs available at each historical issue
time. Subdaily measurements would be needed to train and validate multiple
instantaneous values within each day.
