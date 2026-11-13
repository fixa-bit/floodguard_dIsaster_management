# Thirty-day hindcast-forecast LSTM: scratch variant

The first model in the requested 30-day queue. This variant is trained from scratch. Pretrained adaptations and all other families remain pending feedback.

## Experiment

- Past window: 365 days; output: 30 leads with P05/P25/P50/P75/P95 discharge quantiles.
- Hidden size 64, one recurrent layer, dropout 0.15, AdamW with weight decay, seed 42.
- Eight historical weather/snow inputs, future precipitation and temperature, and a lead embedding. No past or future observed discharge input.
- Training 2016-2020; validation/early stopping 2021; observed test targets 2022-2024.
- Masked pinball loss in normalized log-flow space. Maximum 120 epochs, stopping after 12 validation epochs without sufficient improvement. One fixed configuration; no HPO sweep.
- Missing targets remain NaN. Input means, scales and climatology are fitted only on training years.

The original merged daily table is copied byte-for-byte to `data/marala_daily.csv`; `data/preparation_report.json` records source hashes. Model code and its original project versions are local to this folder. Existing 10-day/15-day models are not modified.

## Weather limitation

No archived 30-day TIGGE/GFS inputs were found. This experiment uses the existing noisy-reanalysis proxy: realized ERA5-Land future rain/temperature plus configurable standardized noise growing from 0.05 at lead 1 to 0.775 at lead 30. The assumed noise does not establish operational weather-error behavior. All reported accuracy is retrospective proxy-weather accuracy, not demonstrated operational 30-day flood forecast skill.

## Run

From `riverine flood/short range/model/`:

```powershell
$python = '../experiments/marala_observed/.venv/Scripts/python.exe'
$variant = 'model_30_days/Hindcast-forecast LSTM/scratch'
& $python "$variant/train.py" --config "$variant/config.yaml"
& $python "$variant/evaluate.py" --config "$variant/config.yaml"
& $python -m unittest discover -s "$variant/tests" -v
```

Training automatically evaluates the selected checkpoint and then stops. It refuses to overwrite an existing checkpoint. Retraining requires a new output directory. `finetune.py` can continue this 30-day model with smaller learning rates from config; transferring 10/15-day donor weights requires explicit adaptation in a later separate variant.

## Files and results

- `config.yaml`, `data.py`, `model.py`, `_training.py`, `train.py`, `finetune.py`, `baselines.py`, `evaluate.py`.
- `runs/initial/seed_42/`: checkpoint, config, normalization, year lists and training history.
- `reports/initial/`: this model's observed-day predictions, lead/season/flood scores and interval calibration.
- [Comparison against persistence and climatology](../../../../evaluation%20comparison/model_30_days/hindcast_forecast_lstm_scratch/comparison_report.md), stored outside `model/`.
- `RUN_RESULTS.md`: actual fitting time, selected epoch, sample counts and full interpretation.
- `tests/`: code correctness checks only; synthetic test scores are not real accuracy.

The record is short, floods are sparse, flow is regulated, and the holdout years have already been inspected in earlier experiments. Overlapping windows are not independent. Training Q95 defines a high-flow proxy, not an official flood category. Ordered daily quantiles do not supply calibrated joint 30-day flood-event probabilities.

<!-- ACTUAL_RESULTS -->

## Actual measured results

| model | lead_day | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LSTM_30d | 1 | 1067 | 0.870 | 0.916 | 282.123 | 167.986 | -3.061 |
| LSTM_30d | 10 | 1067 | 0.856 | 0.927 | 297.220 | 180.196 | -0.806 |
| LSTM_30d | 15 | 1067 | 0.841 | 0.920 | 313.078 | 190.045 | 0.399 |
| LSTM_30d | 20 | 1065 | 0.823 | 0.910 | 330.740 | 202.641 | 1.159 |
| LSTM_30d | 30 | 1055 | 0.784 | 0.884 | 366.025 | 224.066 | 3.333 |

Training: 80.9 seconds, 34 epochs, selected epoch 22.

| model | lead_day | group | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct | peak_n | peak_MAPE_pct | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LSTM_30d | 30 | all | 1055 | 0.784 | 0.884 | 366.025 | 224.066 | 3.333 | 51 | 23.931 | 0.451 | 0.028 | 0.549 |
| LSTM_30d | 30 | flood | 51 | -1.903 | 0.287 | 931.351 | 725.652 | -20.995 | 51 | 23.931 | 0.451 | NA | 0.000 |
| LSTM_30d | 30 | non_flood | 1004 | 0.759 | 0.833 | 310.995 | 198.587 | 8.234 | 0 | NA | NA | 0.028 | 1.000 |

See RUN_RESULTS.md for baseline comparisons, calibration and limitations.

At day 30, climatology has slightly better NSE (0.792 versus 0.784) and RMSE (359.4 versus 366.0 cumecs). The LSTM has lower MAE (224.1 versus 231.9 cumecs). Its nominal 90% interval covers only 74.5% of observed targets. These are noisy-reanalysis results, not established operational forecast skill.
