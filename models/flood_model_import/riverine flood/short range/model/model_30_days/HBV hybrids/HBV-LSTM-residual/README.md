# HBV plus LSTM residual correction, 30-day forecast

This model first runs calibrated physical HBV, then uses an LSTM to learn the model's past errors. It adds the LSTM's median residual forecast to the physical flow forecast. The physical parameters are copied from the separately evaluated calibrated HBV model and held fixed during LSTM training.

## Training in plain language

The LSTM trains on Marala residuals from 2016-2020. It uses 2021 to select the best training epoch, then scores 2022-2024 on observed discharge only. Its inputs include past observed flow and weather up to the forecast issue date, plus the physical model's future 30-day flow and weather trajectory. Future weather is reanalysis used as a stand-in, not an archived 30-day forecast. Missing targets are skipped; discharge values are never filled.

## Run

From this folder with the project environment:

```powershell
& '..\..\..\..\experiments\marala_observed\.venv\Scripts\python.exe' prepare.py
& '..\..\..\..\experiments\marala_observed\.venv\Scripts\python.exe' train.py
```

## Files

- `config.json`, `prepare.py`, `train.py`, `evaluate.py`: settings and workflow.
- `data/`: unchanged observed daily data, catchment metadata and MODIS source CSVs.
- `reference/physical_base/`: the calibrated physical HBV parameters and weather mappings used by the correction model.
- `runs/initial/lstm/`: trained residual LSTM checkpoint, normalization and learning history.
- `reports/validation/`: validation forecasts and scores.
- `reports/initial/`: test predictions, physical/HBV-LSTM detail, scores and report.
- `RUN_RESULTS.md`: measured matched comparison and flood/non-flood results.
- `verify.py`: checks test targets and the copied physical-HBV baseline against their source outputs.
- Full cross-model comparison: `../../../../evaluation comparison/model_30_days/hbv_lstm_residual/`.
