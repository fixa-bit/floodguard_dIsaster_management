# N-HiTS: 30-day observed-test results

Train 2016–2020; validation 2021; test 2022–2024. Missing discharge targets stayed NaN and were masked from the loss and scores.

Observed lead-30 targets: **1055**. Flood threshold: training Q95 **2494.714 m3/s**.

## Lead 30 overall

| model   |   lead_day |    n |   NSE |   KGE |   PBIAS_pct |   RMSE_cumecs |   MAE_cumecs |   peak_MAPE_pct |   peak_n |   flood_hit_rate |   false_alarm_rate |   false_alarm_ratio |
|:--------|-----------:|-----:|------:|------:|------------:|--------------:|-------------:|----------------:|---------:|-----------------:|-------------------:|--------------------:|
| NHiTS   |         30 | 1055 | 0.678 | 0.813 |      -3.841 |       447.516 |      262.709 |          36.723 |       51 |            0.196 |              0.030 |               0.750 |

## Lead 30 flood and non-flood scores

| model   |   lead_day | group     |    n |    NSE |   KGE |   PBIAS_pct |   RMSE_cumecs |   MAE_cumecs |   peak_MAPE_pct |   peak_n |   flood_hit_rate |   false_alarm_rate |   false_alarm_ratio |
|:--------|-----------:|:----------|-----:|-------:|------:|------------:|--------------:|-------------:|----------------:|---------:|-----------------:|-------------------:|--------------------:|
| NHiTS   |         30 | flood     |   51 | -4.593 | 0.018 |     -33.014 |      1292.686 |     1112.550 |          36.723 |       51 |            0.196 |            nan     |               0.000 |
| NHiTS   |         30 | non_flood | 1004 |  0.687 | 0.836 |       2.036 |       354.345 |      219.540 |         nan     |        0 |          nan     |              0.030 |               1.000 |

## Lead 30 by season

| model   |   lead_day | season   |   n |    NSE |   KGE |   PBIAS_pct |   RMSE_cumecs |   MAE_cumecs |   peak_MAPE_pct |   peak_n |   flood_hit_rate |   false_alarm_rate |   false_alarm_ratio |
|:--------|-----------:|:---------|----:|-------:|------:|------------:|--------------:|-------------:|----------------:|---------:|-----------------:|-------------------:|--------------------:|
| NHiTS   |         30 | Apr-Jun  | 273 |  0.358 | 0.641 |      -7.014 |       371.217 |      264.618 |          42.234 |        3 |            0.000 |              0.000 |             nan     |
| NHiTS   |         30 | Jul-Sep  | 276 | -0.063 | 0.474 |      -6.393 |       747.011 |      550.708 |          35.312 |       47 |            0.213 |              0.131 |               0.750 |
| NHiTS   |         30 | Oct-Mar  | 506 | -0.256 | 0.441 |       9.632 |       197.066 |      104.588 |          86.468 |        1 |            0.000 |              0.000 |             nan     |

## Quantile interval coverage

| model   |   lead_day |    n |   nominal_coverage |   empirical_coverage |   mean_interval_width_cumecs |
|:--------|-----------:|-----:|-------------------:|---------------------:|-----------------------------:|
| NHiTS   |         30 | 1055 |              0.900 |                0.708 |                      836.139 |

## Training run

|   seed |   selected_epoch |   epochs_run |   training_seconds |   validation_pinball |   training_samples |   validation_samples |
|-------:|-----------------:|-------------:|-------------------:|---------------------:|-------------------:|---------------------:|
| 42.000 |            3.000 |       10.000 |             12.525 |                0.109 |           1767.000 |              336.000 |

**Future weather uses noisy ERA5-Land reanalysis as a stand-in, not archived 30-day forecasts. Scores are retrospective hindcast skill, not operational forecast accuracy.**

N-HiTS uses observed past discharge and historical weather. Its held-out test years were inspected in prior project experiments and are not an untouched project-wide holdout.
