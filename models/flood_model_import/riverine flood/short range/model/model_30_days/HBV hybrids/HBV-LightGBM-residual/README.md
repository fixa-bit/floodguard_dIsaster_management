# HBV plus LightGBM residual correction, 30-day forecast

This model runs calibrated physical HBV, then uses separate LightGBM quantile models to learn the HBV prediction error for each forecast lead. The median predicted residual is added to physical HBV flow. Its 10th and 90th residual quantiles provide a range of corrected flows.

## Training in plain language

LightGBM models train on residuals from 2016-2020. They use 2021 to select the number of boosting iterations, then are scored on observed targets from 2022-2024. Features include past observed flow and weather up to the issue date, plus the physical model's 30-day flow and weather trajectory. The physical HBV parameters are fixed from the separately calibrated physical model. Missing discharge targets are skipped; no discharge values are filled.

Future weather uses reanalysis as a hindcast stand-in, not archived 30-day forecasts.

## Run

From this folder with the project environment:

```powershell
& '..\..\..\..\experiments\marala_observed\.venv\Scripts\python.exe' prepare.py
& '..\..\..\..\experiments\marala_observed\.venv\Scripts\python.exe' train.py
```

## Files

- `config.json`, `prepare.py`, `train.py`, `evaluate.py`: settings and workflow.
- `physical.py`, `forcing.py`, `learning.py`, `data.py`: physical model, weather processing, boosting helpers and feature builder.
- `data/`: unchanged observed discharge/weather table, catchment metadata and MODIS snow data.
- `reference/physical_base/`: calibrated HBV parameters and weather maps.
- `runs/initial/lightgbm/`: 90 per-lead quantile models, metadata and feature importance.
- `reports/validation/`: validation forecasts and scores.
- `reports/initial/`: observed test predictions, physical/HBV-LightGBM details and scores.
- `RUN_RESULTS.md`: measured results and the flood/non-flood comparison.
- Shared cross-model comparison: `../../../../evaluation comparison/model_30_days/flood_nonflood_classification_metrics.md` and `.pdf`.
