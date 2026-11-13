# Thirty-day climatology-residual LSTM ensemble

## How training works, in plain words

The idea is: **start with the river's usual flow for that time of year, then learn how much to increase or decrease it using weather and recent river conditions.**

1. **Give each year a job.** We use 2016-2020 to teach the model, 2021 to choose the best saved version and adjust its uncertainty ranges, and 2022-2024 to measure performance afterward. Those final years had already been examined in earlier project experiments, so they are an existing comparison benchmark.

2. **Make a normal seasonal starting point.** From the training years, we calculate the usual discharge around each calendar date using a 31-day window. For example, a forecast for early August starts from typical flows around early August. When teaching the model with a 2019 example, we leave 2019 out of this average so that the example cannot help set its own starting point.

3. **Show the model the recent conditions.** Each example contains the previous 365 days of weather, snow information and observed discharge, plus weather inputs for the next 30 days. Discharge readings are supplied only through the forecast issue day. Missing readings have a separate indicator; missing target days are skipped when calculating errors. The original discharge table is never filled or changed.

4. **Teach it to correct the seasonal flow.** We start with the river-pattern knowledge learned by the earlier past-discharge LSTM. The new model learns an upward or downward correction to the seasonal starting point. Large discharge errors receive a stronger penalty, and errors for days 21-30 receive double weight. A separate part of the model learns lower and upper flow estimates.

5. **Check progress after each training pass.** One pass, called an epoch, goes through all 1,767 training examples. After each pass, we check errors for forecast days 21-30 using 2021 data. We keep the best saved version and stop after 12 passes without enough improvement. The initial seasonal forecast is also available as a fallback if learning makes validation results worse.

6. **Train three versions, one after another.** They use the same data and settings but different random seeds: 42, 43 and 44. Their forecasts are averaged to reduce dependence on one training run. Actual training was:

   | Version | Training passes completed | Best saved pass |
   |---|---:|---:|
   | Seed 42 | 16 | 4 |
   | Seed 43 | 14 | 2 |
   | Seed 44 | 22 | 10 |

   Total fitting time was **150.5 seconds**. An earlier pass can be the best because further fitting can make the model perform worse on the validation year.

7. **Use 2021 to finish the forecast settings.** We check whether mixing the averaged forecast with the original calendar average helps. For this run, validation selected the ensemble forecast in full for all three lead groups: days 1-10, 11-20 and 21-30. We also use 2021 errors to adjust the lower and upper estimates. These settings are fixed before checking the benchmark years.

8. **Measure the result on observed benchmark days.** We compare the final forecasts with actual 2022-2024 discharge, using the same dates as climatology and the earlier LSTMs. At day 30, there are 1,055 observed targets. The new model achieves NSE **0.858**, versus **0.792** for the original climatology and **0.820** for smoothed climatology. NSE is a forecast skill score, not an accuracy percentage.

**What this result means:** the model beat both seasonal-average controls on this benchmark. Future weather in the experiment comes from historical reanalysis with added noise, so this does not yet establish accuracy with real operational weather forecasts. The estimated 90% range contained 90.6% of benchmark observations, but future coverage is not guaranteed. High-flow detection remains limited: the point forecast identified 33% of days above the training high-flow threshold.

## Technical details

This variant targets mean-flow MSE/NSE instead of using a quantile median as the point forecast. Three seeds are fitted sequentially. All model selection, shrinkage coefficients and empirical quantile corrections use 2021 validation only and are frozen before benchmark evaluation. Existing weather-only and past-discharge models are preserved.

The model learns corrections to a 31-day circular, count-weighted climatology fitted on observed 2016-2020 flows. Training anchors exclude the target's own year; validation/test anchors use all training years. The original exact month/day mean remains the benchmark, and the smoothed calendar curve is reported separately so its benefit is not attributed automatically to the neural network.

The existing past-discharge LSTM initializes the encoder/decoder. New heads predict a nonnegative mean and five ordered quantiles. Linear-flow scaled MSE drives the mean head, with auxiliary pinball loss and a residual penalty. Leads 21-30 receive double training weight. Early stopping selects validation scaled MSE across leads 21-30; an epoch-zero smooth-climatology fallback prevents selecting a worse validation checkpoint.

Selected members are averaged. Validation-fitted coefficients in lead groups 1-10, 11-20 and 21-30 shrink predictions toward exact climatology. Empirical validation quantile offsets adjust intervals. Selection and calibration reuse the same validation year, so no independent conformal coverage guarantee is claimed.

Train 2016-2020; validation 2021; previously inspected benchmark 2022-2024. Original discharge targets stay NaN where missing. Past observed flow through issue day, its missing indicator and weather inputs are used; future discharge is excluded. Weather still uses noisy reanalysis, so operational thirty-day forecasting skill is unverified.

From `riverine flood/short range/model/`:

```powershell
$python = '../experiments/marala_observed/.venv/Scripts/python.exe'
$variant = 'model_30_days/Hindcast-forecast LSTM/climatology_residual_ensemble'
& $python -m unittest discover -s "$variant/tests" -v
& $python "$variant/train.py"
& $python "$variant/verify.py"
```

`config.yaml` holds the fixed setup. `data/` has an unchanged local source table; `runs/initial/seed_*/` holds member checkpoints and histories. `validation_postprocessing.json` and `selection_complete.json` record choices frozen before test evaluation. `reports/initial/` contains this variant's observed predictions and scores. The [comparison report](../../../../evaluation%20comparison/model_30_days/climatology_residual_ensemble/comparison_report.md) is outside `model/`.

Tests check implementation behavior only. Real accuracy comes from observed benchmark days. One frozen ensemble is evaluated; no further model is trained after its benchmark is inspected without a new, explicitly documented experiment.
<!-- RESULTS -->

## Measured results

Day-30 mean-flow NSE is **0.858**, versus exact climatology **0.792** and smoothed climatology **0.820**. Beats the original climatology: **True**; beats the smoothed control: **True**.

| model | lead_day | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Residual_ensemble | 30 | 1055 | 0.858 | 0.874 | 297.556 | 191.690 | 4.150 |
| Raw_residual_ensemble | 30 | 1055 | 0.858 | 0.874 | 297.556 | 191.690 | 4.150 |
| Climatology | 30 | 1055 | 0.792 | 0.845 | 359.398 | 231.857 | 8.837 |
| Smooth_climatology | 30 | 1055 | 0.820 | 0.835 | 334.475 | 219.162 | 8.781 |
| Weather_only_LSTM | 30 | 1055 | 0.784 | 0.884 | 366.025 | 224.066 | 3.333 |
| Past_discharge_LSTM | 30 | 1055 | 0.788 | 0.871 | 362.871 | 215.196 | -5.660 |
| Persistence | 30 | 1055 | 0.262 | 0.629 | 677.066 | 446.424 | 1.149 |

Training: 150.5 seconds across three sequential seeds; selected epochs 4, 2 and 10. Nine implementation tests passed, and verification reproduced all validation choices and benchmark scores. Day-30 P05-P95 coverage was 90.6%. High-flow hit rate was 33%, compared with 25.5% for climatology and 47.1% for the earlier past-discharge model. Warning detection remains limited even with improved flow NSE.
