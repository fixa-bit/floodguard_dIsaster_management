# Marala station forecast

This independent experiment predicts **measured Marala inflow at 06:00 PKT**, 1,
3 and 7 days after the origin reading. It uses actual FFD observations, not the
GloFAS daily means currently displayed by the dashboard. It does not replace
the dashboard feed or train an inundation model.

Run from `D:\Projects\disaster_management` with the existing environment:

```powershell
.venv\Scripts\python.exe -m models.marala_station_forecast.train
.venv\Scripts\python.exe -m models.marala_station_forecast.predict
.venv\Scripts\python.exe -m models.marala_station_forecast.predict --role best_learned
```

Training uses `numpy` and `xgboost`, already installed in the project environment.
It reads the existing FFD observation caches, verifies station/time/source/hash
metadata, rejects conflicting daily readings, and writes its own data snapshot,
models and reports here. Original source datasets are read-only.

Read [artifacts/REPORT.md](artifacts/REPORT.md) for the actual held-out results.
The full candidate comparison is in `artifacts/validation_leaderboard.csv`;
`artifacts/holdout_predictions_2026.csv` contains every measured target and
prediction with bulletin links. Data and code hashes are in `data/manifest.json`.

## Experiment

- 2024: train persistence, damped trends, ridge and XGBoost correction candidates.
- 2025: choose candidates by RMSE, using MAE only to break ties.
- Freeze all horizon selections before evaluating 2026.
- Refit the frozen candidates on 2024+2025; evaluate 2026 once using rolling
  measured origins. Features never read beyond each origin date.
- After evaluation, refit the same candidates on all eligible observations for
  the final inference artifacts. Those fits have no new independent test.

Both an overall champion and the best learned candidate are saved. If persistence
or a trend wins validation, it remains the default; the code does not force an
ML model merely to produce a less flat curve. Candidate configurations and split
years are declared in source/config, not chosen after inspecting the final test.

The model requires the current and previous day's measured inflow. Optional
older lags remain missing; ridge learns imputation values only from fitting data.
Missing targets are excluded, never interpolated. Reanalysis weather is excluded
because it is retrospective and not reliably available at the forecast origin.

## Using updated readings

Supply a verified JSON array or CSV matching `data/observations.csv`:

```powershell
.venv\Scripts\python.exe -m models.marala_station_forecast.predict --observations path\to\updated-observations.csv
```

Use actual FFD-reported inflow/outflow at 06:00 PKT, preserving date, source URL
and SHA-256 evidence. The latest measurement anchors the forecast. `--as-of`
cannot be earlier than the fitted model's last target: otherwise the requested
hindcast would use future training information.

## Practical limits

This is a small-data research model, not a certified warning system. Its nominal
lead is measured from one 06:00 reading to a later 06:00 target; FFD bulletin
publication delays shorten the operational lead. Exact-time observations do not
make future predictions exact or certain.

Three short, incomplete seasons cannot establish rare-event reliability or
justify months of daily instantaneous predictions. Further progress needs more
years of gauge records, upstream inflow/release observations, availability-aligned
rainfall forecasts and independently evaluated flood events. Do not interpret a
discharge estimate or threshold class as a calibrated flood probability.
