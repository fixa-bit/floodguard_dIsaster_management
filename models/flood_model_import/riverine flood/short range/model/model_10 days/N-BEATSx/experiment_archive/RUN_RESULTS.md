# Actual N-HiTS / N-BEATSx run

Run date: 2026-11-02, Asia/Karachi. Working directory: `D:/projects/flood_model/flood_model/riverine flood/short range/model`.

Two actual models were trained from scratch: **N-HiTS** and **N-BEATSx**. A third, **matched-input LSTM**, was trained as an architecture control. The original discharge-only N-BEATS was not trained in this run; N-BEATSx is its weather-aware extension. No global pretrained weights were used for these new models.

## What was executed

The published source files were downloaded from Nixtla NeuralForecast revision `cf7449383ac5ff6041ec35cbd97b84c23dd559a0`. The computational block/basis classes were extracted, with source hashes and Apache-2.0 license retained. Each model received a byte-identical copy of the existing observed-only Marala daily table and a separate config before training. The frozen protocol is in `experiment_protocol.json`.

```powershell
$py = '../experiments/marala_observed/.venv/Scripts/python.exe'
& $py -u -m unittest discover -s nhits/tests -v
& $py -u -m unittest discover -s nbeatsx/tests -v
& $py -u -m time_series_mlp.run_all
& $py -u -m time_series_mlp.evaluate
& $py -u compare_flood_nonflood.py --output reports/flood_nonflood_2026-11-02_with_nhits_nbeatsx
```

`run_all` was launched in a hidden background process, logging to `training.log` and `training_errors.log`. It trained all three experiments sequentially and exited normally. No real training was repeated after viewing the test scores. The test suites were repeated after tightening the same-initialization weight-change check: eight passed per new model, **16 total**. These tests verify implementation behavior, not predictive accuracy.

## Actual training

All runs use 365 historical days and predict ten future days, with 2016-2020 training, 2021 validation and 2022-2024 testing. Seed 42, batch 64, dropout 0.1, weight decay 0.0001, gradient clipping 1, maximum 40 epochs and patience 7. Learning rate is 0.0005 for the two basis models and 0.001 for the LSTM control. There was no HPO sweep. Checkpoint selection uses validation pinball loss in standardized log-flow space, with minimum improvement 0.0001.

| Model | Epochs run | Selected epoch | Validation pinball | CPU training seconds | Trainable parameters |
| --- | --- | --- | --- | --- | --- |
| N-HiTS | 17 | 10 | 0.092398 | 36.987 | 829,980 |
| N-BEATSx | 19 | 12 | 0.096148 | 24.225 | 1,737,437 |
| Matched-input LSTM | 18 | 11 | 0.065265 | 42.190 | 43,413 |

The three training loops total approximately 103.4 seconds. The sequential runner recorded 111.123 seconds including dataset loading and checkpoint setup. Downloads, tests, evaluation and report generation are not included in the per-model training times.

Every run has 1,767 training windows and 356 validation windows. Both new models and the control use the same past discharge, weather, missingness and calendar channels. Historical ERA5 rain/temperature supply the past portion of the published future-covariate inputs. The original weather-only LSTM therefore is a context comparison; the new LSTM is the matched-input comparison.

## Actual day-10 test results

There are 1,084 unique observed test days across leads, 10,795 scored issue/lead pairs and 45 missing-target pairs excluded. Lead 10 contains 1,075 observed targets. The future weather tensors are exactly equal to those in the old experiment, including the lead-growing Gaussian noise.

| Model | NSE | KGE | Overall RMSE, m3/s | Flood-day RMSE | Non-flood RMSE |
| --- | --- | --- | --- | --- | --- |
| N-HiTS | 0.704049 | 0.849468 | 425.593 | 1,091.647 | 361.661 |
| N-BEATSx | 0.717590 | 0.830496 | 415.743 | 1,228.967 | 325.926 |
| Matched-input LSTM | **0.880076** | **0.935685** | **270.918** | **767.831** | **218.378** |

Flood proxy: observed target discharge > training Q95, **2,494.714 m3/s**, giving 51 high-flow target days and 1,024 other days at lead 10. These are not official flood warning classes or independent flood events. N-HiTS flood-only NSE is -2.989; N-BEATSx -4.055; matched LSTM -0.973. Flood-only NSE uses the high-flow subset's own mean/variance. None demonstrates strong high-flow forecasting in this single test.

N-BEATSx has better overall and non-flood error than N-HiTS, but N-HiTS has lower flood error. Both are worse than the matched LSTM under these frozen settings. This is a measured outcome for one configuration and seed, not a conclusion that the architectures cannot improve with different validation-selected configurations or more data. No test-driven tuning or automatic ensemble update was performed.

## Integrity and limits

Original and copied daily-table SHA256 remains `d21788d62afc9e54d8e2aa6e1f27dcc244ef3b6a1a734249650abd84ccdbe11f`. All **3,454 observed discharge values and 13,636 NaNs** in the complete source calendar remain unchanged. No discharge was filled or interpolated. Missing input values use training means inside tensors and indicators; individual missing targets remain NaN and are masked before loss arithmetic. All frozen config hashes still match the protocol.

The new quantile projection sorts summed block outputs to prevent crossing. This is a documented project adaptation; it does not guarantee calibrated probabilities. The source computational blocks match the pinned upstream implementation in the tests. Installed packages are captured in `requirements-lock.txt`; checks are in `verification.json`.

**Future weather is realized ERA5-Land with artificial noise, so operational TIGGE/GFS forecast accuracy remains unverified.** Test years were previously inspected in this project. The short record, limited independent floods, larger MLP parameter counts, regulation, input publication latency and observation timing limit conclusions. No 2025-2026 forecast accuracy is claimed.

## Saved files

- `../nhits/`: data, config, source adapters, eight tests, selected checkpoint, normalization, year history, predictions, seasonal/flood scores, calibration and accuracy README.
- `../nbeatsx/`: the corresponding N-BEATSx artifacts.
- `../nhits/controls/lstm/`: matched LSTM checkpoint, metrics and measured accuracy.
- [New-model comparison](reports/initial/comparison_report.md) and [skill plot](reports/initial/skill_by_lead.png).
- [Updated cross-model flood/non-flood comparison](../reports/flood_nonflood_2026-11-02_with_nhits_nbeatsx/report.md), covering all existing main models on common observed target dates.
