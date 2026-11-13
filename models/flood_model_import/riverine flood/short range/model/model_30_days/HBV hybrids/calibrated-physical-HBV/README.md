# Calibrated physical HBV, 30-day forecast

This model uses HBV water-balance equations for snow, soil moisture, runoff stores and routing. It finds a set of physical parameters that best matches observed Marala discharge during the training years. It does not include an LSTM or LightGBM correction.

## Training in plain language

The model first runs through the daily weather record to warm up its snow and water stores. It then calibrates HBV parameters against observed discharge from 2016-2020. Calibration uses KGE as its fit score. The calibrated parameters are frozen for 30-day hindcasts. Year 2021 is a validation period; observed 2022-2024 targets are the test period. Missing discharge targets stay NaN and are excluded from scores. The source data copy is byte-identical to the project table.

The future weather driver is ERA5-Land reanalysis rainfall mapped to CHIRPS monthly distributions, with temperature passed through and PET taken from a training-only month/day average. These are retrospective hindcasts; archived 30-day weather forecasts were unavailable.

## Run

From this folder, using the project Python environment:

```powershell
& '..\..\..\..\experiments\marala_observed\.venv\Scripts\python.exe' prepare.py
& '..\..\..\..\experiments\marala_observed\.venv\Scripts\python.exe' train.py
```

## Files

- `config.json`, `prepare.py`, `train.py`, `evaluate.py`: settings and full workflow.
- `physical.py`, `forcing.py`: physical model and weather mapping code copied into this folder.
- `data/marala_daily.csv`: unchanged source table and preparation receipt.
- `runs/initial/`: calibrated parameters, calibration trace, state/flux history and run manifest.
- `reports/validation/`: 2021 validation predictions and scores.
- `reports/initial/`: observed 2022-2024 test predictions, scores and report.
- `RUN_RESULTS.md`: actual model comparison and calibration status.
- Full matched comparison: `../../../../evaluation comparison/model_30_days/calibrated_physical_hbv/`.
