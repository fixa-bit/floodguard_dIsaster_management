# N-HiTS: 30-day forecast

**Status:** trained and evaluated.

## How it was trained

N-HiTS reads the previous 365 days of weather and observed discharge, then predicts all 30 future flow days with multiscale identity, trend and seasonal blocks. It was trained on 2016–2020 observed targets; missing targets remain NaN and are masked from the loss. The checkpoint was selected using 2021 validation data (best epoch 3 of 10). Test results use 2022–2024 and seed 42.

The model uses noisy ERA5-Land reanalysis for future rain and temperature because archived 30-day forecasts are not available. That makes this a retrospective hindcast experiment, not operational forecast accuracy. The test years were inspected in earlier project work, and the flood sample is small.

## Day-30 test results

| Measure | N-HiTS |
|---|---:|
| Observed targets | 1,055 |
| NSE | 0.678 |
| KGE | 0.813 |
| RMSE | 447.52 m³/s |
| 90% quantile interval coverage | 70.8% |
| Flood precision | 0.250 |
| Flood recall | 0.196 |
| Flood-day RMSE | 1,292.69 m³/s |
| Non-flood RMSE | 354.35 m³/s |

For context, this day-30 NSE is below the evaluated training-climatology baseline (0.792). Flood recall is also low: the model detected 10 of 51 observed flood days at the training Q95 threshold.

## Run

From this folder, using the project Python environment:

```powershell
& '..\..\..\experiments\marala_observed\.venv\Scripts\python.exe' train.py
& '..\..\..\experiments\marala_observed\.venv\Scripts\python.exe' evaluate.py
```

## Files

- `config.yaml`, `train.py`, `evaluate.py`: configuration and train/evaluation commands.
- `_nhits/`, `data.py`, `model.py`: model blocks, masked data windows and model adapter.
- `data/marala_daily.csv`: source daily table, copied byte-for-byte; observed discharge was not filled or modified.
- `runs/initial/`: checkpoint, training history, normalization and year records.
- `reports/initial/`: observed-only predictions, flood/non-flood and seasonal scores, quantile coverage and integrity report.
- `source_reference/`: N-HiTS implementation provenance and license.
- `requirements.txt`: direct Python packages needed to run this copy.
- `RUN_RESULTS.md`: full results.
- Shared comparison is outside the model folder: `../../../evaluation comparison/model_30_days/flood_nonflood_classification_metrics.md` and `.pdf`.
