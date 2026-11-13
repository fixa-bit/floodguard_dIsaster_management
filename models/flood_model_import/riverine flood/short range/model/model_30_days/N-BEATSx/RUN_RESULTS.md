# N-BEATSx: 30-day observed-test results

Train 2016-2020; validation 2021; test 2022-2024. Missing discharge targets stayed NaN and were masked from loss and scores.

Observed lead-30 targets: **1055**. Flood threshold: training Q95 **2494.714 m3/s**.

## Lead 30 overall

| model   |   lead_day |    n |   NSE |   KGE |   PBIAS_pct |   RMSE_cumecs |   MAE_cumecs |   peak_MAPE_pct |   peak_n |   flood_hit_rate |   false_alarm_rate |   false_alarm_ratio |
|:--------|-----------:|-----:|------:|------:|------------:|--------------:|-------------:|----------------:|---------:|-----------------:|-------------------:|--------------------:|
| NBEATSx |         30 | 1055 | 0.564 | 0.740 |      13.702 |       520.344 |      308.536 |          29.574 |       51 |            0.451 |              0.063 |               0.733 |

## Lead 30 flood and non-flood scores

| model   |   lead_day | group     |    n |    NSE |    KGE |   PBIAS_pct |   RMSE_cumecs |   MAE_cumecs |   peak_MAPE_pct |   peak_n |   flood_hit_rate |   false_alarm_rate |   false_alarm_ratio |
|:--------|-----------:|:----------|-----:|-------:|-------:|------------:|--------------:|-------------:|----------------:|---------:|-----------------:|-------------------:|--------------------:|
| NBEATSx |         30 | flood     |   51 | -3.535 | -0.163 |     -18.239 |      1163.925 |      892.960 |          29.574 |       51 |            0.451 |            nan     |               0.000 |
| NBEATSx |         30 | non_flood | 1004 |  0.461 |  0.601 |      20.137 |       464.430 |      278.849 |         nan     |        0 |          nan     |              0.063 |               1.000 |

## Lead 30 by season

| model   |   lead_day | season   |   n |    NSE |   KGE |   PBIAS_pct |   RMSE_cumecs |   MAE_cumecs |   peak_MAPE_pct |   peak_n |   flood_hit_rate |   false_alarm_rate |   false_alarm_ratio |
|:--------|-----------:|:---------|----:|-------:|------:|------------:|--------------:|-------------:|----------------:|---------:|-----------------:|-------------------:|--------------------:|
| NBEATSx |         30 | Apr-Jun  | 273 | -0.818 | 0.243 |      36.958 |       624.591 |      436.158 |          15.245 |        3 |            0.333 |              0.052 |               0.933 |
| NBEATSx |         30 | Jul-Sep  | 276 | -0.098 | 0.518 |       3.473 |       759.427 |      546.664 |          29.277 |       47 |            0.468 |              0.214 |               0.690 |
| NBEATSx |         30 | Oct-Mar  | 506 | -0.276 | 0.409 |      12.558 |       198.664 |      109.793 |          86.482 |        1 |            0.000 |              0.000 |             nan     |

## Quantile interval coverage

| model   |   lead_day |    n |   nominal_coverage |   empirical_coverage |   mean_interval_width_cumecs |
|:--------|-----------:|-----:|-------------------:|---------------------:|-----------------------------:|
| NBEATSx |         30 | 1055 |              0.900 |                0.784 |                      998.174 |

## Training run

|   seed |   selected_epoch |   epochs_run |   training_seconds |   validation_pinball |   training_samples |   validation_samples |
|-------:|-----------------:|-------------:|-------------------:|---------------------:|-------------------:|---------------------:|
| 42.000 |            3.000 |       10.000 |             12.923 |                0.117 |           1767.000 |              336.000 |

**Future weather uses noisy ERA5-Land reanalysis as a stand-in, not archived 30-day forecasts. Scores are retrospective hindcast skill, not operational forecast accuracy.**

N-BEATSx uses observed past discharge and historical weather. Its held-out test years were inspected in prior project experiments and are not an untouched project-wide holdout.
