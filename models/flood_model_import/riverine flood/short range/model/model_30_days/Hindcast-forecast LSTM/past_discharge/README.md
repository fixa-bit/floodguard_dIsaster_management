# Thirty-day LSTM with past observed discharge

This is a separate matched variant of the weather-only `../scratch/` model. The change is `data.past_discharge: true`: the hindcast LSTM receives training-normalized log discharge through issue day t and a missing indicator. The data table is copied byte-for-byte; no discharge value is filled or replaced in the source. Targets remain NaN and masked where unobserved.

Hidden size 64, one recurrent layer, dropout 0.15, optimizer, noise assumptions, seed 42, maximum 120 epochs and 12-epoch validation patience are unchanged. The input dimension increases from 18 to 20, adding 512 weights. The 30-lead network is trained from scratch. This step does not change the loss or calibrate intervals, add an ensemble, or train another model family.

Train: 2016-2020; validation/checkpoint selection: 2021; observed comparison benchmark: 2022-2024. All normalization uses training years only. Future observed flow is never an input. Weather remains a noisy-reanalysis proxy; operational 30-day flood forecast skill is unverified. The benchmark years have already been inspected and are not a fresh project-wide holdout.

From `riverine flood/short range/model/`:

```powershell
$python = '../experiments/marala_observed/.venv/Scripts/python.exe'
$variant = 'model_30_days/Hindcast-forecast LSTM/past_discharge'
& $python -m unittest discover -s "$variant/tests" -v
& $python "$variant/train.py"
& $python "$variant/verify.py"
```

Training automatically evaluates the checkpoint and compares both variants on identical observed issue/target/lead records. It then stops for user feedback. Existing checkpoints are protected against overwrite.

- `data/`: source discharge/weather table and copy receipt.
- `config.yaml`, `data.py`, `model.py`, `_training.py`, `train.py`, `evaluate.py`, `baselines.py`, `compare_variants.py`, `finetune.py`: local code and configuration.
- `runs/initial/seed_42/`: checkpoint, normalization, config, years and training history.
- `reports/initial/`: own observed-day scores, predictions, interval calibration and verification.
- [Matched variant comparison](../../../../evaluation%20comparison/model_30_days/hindcast_forecast_lstm_past_discharge/variant_comparison.md), outside `model/`.
- `RUN_RESULTS.md`: own actual fitting measurements and observed results.
- `reference_artifacts_before.json`: original weather-only variant hashes, checked after the new run.

Implementation tests use synthetic data to check shapes, masking, causal flow inputs and loading. They do not establish real forecast accuracy. All accuracy figures come from observed benchmark targets.
<!-- ACTUAL_RESULTS -->

## Actual measured results

| model | lead_day | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LSTM_30d_pastQ | 1 | 1067 | 0.856 | 0.898 | 297.275 | 172.651 | -5.982 |
| LSTM_30d_pastQ | 10 | 1067 | 0.853 | 0.922 | 299.689 | 181.220 | -2.605 |
| LSTM_30d_pastQ | 15 | 1067 | 0.830 | 0.910 | 323.386 | 192.185 | -1.935 |
| LSTM_30d_pastQ | 20 | 1065 | 0.820 | 0.906 | 332.701 | 197.070 | -2.875 |
| LSTM_30d_pastQ | 30 | 1055 | 0.788 | 0.871 | 362.871 | 215.196 | -5.660 |

Training: 80.0 seconds, 33 epochs, selected epoch 21.

| model | lead_day | group | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct | peak_n | peak_MAPE_pct | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LSTM_30d_pastQ | 30 | all | 1055 | 0.788 | 0.871 | 362.871 | 215.196 | -5.660 | 51 | 23.678 | 0.471 | 0.025 | 0.510 |
| LSTM_30d_pastQ | 30 | flood | 51 | -1.734 | 0.290 | 903.829 | 705.947 | -18.694 | 51 | 23.678 | 0.471 | NA | 0.000 |
| LSTM_30d_pastQ | 30 | non_flood | 1004 | 0.758 | 0.874 | 311.236 | 190.267 | -3.034 | 0 | NA | NA | 0.025 | 1.000 |

See RUN_RESULTS.md for baseline comparisons, calibration and limitations.
<!-- MATCHED_COMPARISON -->

## Matched comparison with weather-only LSTM

Day-30 NSE changed from **0.784** to **0.788** (+0.004). RMSE reduction: **+0.9%** overall, **+3.0%** on high-flow days, and **-0.1%** on other days. Positive reductions indicate improvement.

| model | lead_day | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Weather_only_LSTM | 30 | 1055 | 0.784 | 0.884 | 366.025 | 224.066 | 3.333 |
| Past_discharge_LSTM | 30 | 1055 | 0.788 | 0.871 | 362.871 | 215.196 | -5.660 |
| Persistence | 30 | 1055 | 0.262 | 0.629 | 677.066 | 446.424 | 1.149 |
| Climatology | 30 | 1055 | 0.792 | 0.845 | 359.398 | 231.857 | 8.837 |

| model | lead_day | n | coverage_05_95 | interval_width_cumecs |
| --- | --- | --- | --- | --- |
| Weather_only_LSTM | 30 | 1055 | 0.745 | 742.839 |
| Past_discharge_LSTM | 30 | 1055 | 0.768 | 679.129 |

The measured gain is small: day-30 NSE remains below climatology (0.792), and shorter-lead scores did not improve consistently. P05-P95 coverage increased from 74.5% to 76.8%, still below the nominal 90%. No general improvement is established by this single-seed, previously inspected benchmark.
