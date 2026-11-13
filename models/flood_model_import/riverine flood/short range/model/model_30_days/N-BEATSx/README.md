# N-BEATSx: 30-day forecast

**Status:** trained and evaluated; awaiting feedback.

## Training in plain language

The model looks at the previous 365 days of weather, observed flow and historical weather. Its stacked N-BEATSx blocks combine trend and seasonal patterns with forecast-window weather inputs to predict the next 30 daily flows. It learned from observed targets in 2016-2020, chose its checkpoint using 2021, and was scored on 2022-2024. Missing discharge targets stayed NaN and were masked out of the loss.

The run used seed 42, one model, a 64-unit network and early stopping. It trained for 10 epochs; epoch 3 had the best validation loss. No hyperparameter search was run. Future weather was represented by noisy ERA5-Land reanalysis because archived 30-day forecasts are unavailable. These are retrospective scores, not operational forecast accuracy.

## Day-30 observed test results

| Measure | Result |
|---|---:|
| Observed targets | 1,055 (2022-2024) |
| NSE | 0.564 |
| KGE | 0.740 |
| RMSE | 520.34 m3/s |
| Flood threshold | 2,494.714 m3/s (training-period Q95) |
| Flood days | 51 |
| Flood precision | 0.267 |
| Flood recall | 0.451 (23 of 51 detected) |
| Non-flood precision | 0.971 |
| Non-flood recall | 0.937 |
| 90% quantile interval coverage | 78.4% |
| Training-only climatology NSE | 0.792 |

This run did not beat the climatology baseline on day-30 NSE. Flood recall is higher than N-HiTS on this split, but false alarms increased; only 51 flood targets were observed.

## Run

From this folder:

```powershell
& '..\..\..\experiments\marala_observed\.venv\Scripts\python.exe' train.py
& '..\..\..\experiments\marala_observed\.venv\Scripts\python.exe' evaluate.py
```

## Files

- `config.yaml`, `train.py`, `evaluate.py`: configuration and commands.
- `_nbeatsx/`, `data.py`, `model.py`: local model blocks and data/training adapters.
- `data/marala_daily.csv`: byte-identical observed source table; no discharge filling.
- `runs/initial/`: checkpoint, config, normalization, selected years and training history.
- `reports/initial/`: predictions, per-lead/season scores, flood detection, interval calibration and verification.
- `source_reference/`: N-BEATSx implementation source and license.
- `RUN_RESULTS.md`: full evaluation report.
- Shared comparison is outside `model/`: `../../../evaluation comparison/model_30_days/flood_nonflood_classification_metrics.md` and `.pdf`.
