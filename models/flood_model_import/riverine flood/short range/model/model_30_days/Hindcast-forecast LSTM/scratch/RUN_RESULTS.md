# Thirty-day hindcast-forecast LSTM: first experiment

Only the scratch LSTM was trained. All other 30-day model families remain pending feedback.

Train: [2016, 2017, 2018, 2019, 2020]; validation selection: [2021]; observed test years: [2022, 2023, 2024]. Training used 1767 issue windows; validation used 336.

Actual fitting took **80.9 seconds**, 34 epochs; selected epoch **22**, seed 42, 42,037 parameters. Stop: validation patience reached. One fixed configuration, no HPO sweep.

Observed test dates: **1084**; observed issue/lead/target pairs: **31932**; day-30 observations: **1055**. Missing targets were never filled or scored.

## Matched observed-day comparison

| model | lead_day | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LSTM_30d | 1 | 1067 | 0.870 | 0.916 | 282.123 | 167.986 | -3.061 |
| Persistence | 1 | 1067 | 0.868 | 0.934 | 284.578 | 135.985 | -0.003 |
| Climatology | 1 | 1067 | 0.782 | 0.849 | 365.863 | 235.512 | 7.634 |
| LSTM_30d | 10 | 1067 | 0.856 | 0.927 | 297.220 | 180.196 | -0.806 |
| Persistence | 10 | 1067 | 0.650 | 0.825 | 463.111 | 275.109 | 0.328 |
| Climatology | 10 | 1067 | 0.789 | 0.850 | 359.501 | 233.108 | 8.020 |
| LSTM_30d | 15 | 1067 | 0.841 | 0.920 | 313.078 | 190.045 | 0.399 |
| Persistence | 15 | 1067 | 0.572 | 0.786 | 513.233 | 321.546 | 0.601 |
| Climatology | 15 | 1067 | 0.791 | 0.848 | 358.813 | 232.386 | 8.347 |
| LSTM_30d | 20 | 1065 | 0.823 | 0.910 | 330.740 | 202.641 | 1.159 |
| Persistence | 20 | 1065 | 0.502 | 0.751 | 554.099 | 349.167 | 0.756 |
| Climatology | 20 | 1065 | 0.791 | 0.847 | 358.981 | 232.234 | 8.482 |
| LSTM_30d | 30 | 1055 | 0.784 | 0.884 | 366.025 | 224.066 | 3.333 |
| Persistence | 30 | 1055 | 0.262 | 0.629 | 677.066 | 446.424 | 1.149 |
| Climatology | 30 | 1055 | 0.792 | 0.845 | 359.398 | 231.857 | 8.837 |

## Day-30 flood and non-flood results

| model | group | n | NSE | KGE | RMSE_cumecs | MAE_cumecs |
| --- | --- | --- | --- | --- | --- | --- |
| LSTM_30d | flood | 51 | -1.903 | 0.287 | 931.351 | 725.652 |
| LSTM_30d | non_flood | 1004 | 0.759 | 0.833 | 310.995 | 198.587 |
| Persistence | flood | 51 | -7.479 | -0.087 | 1591.603 | 1388.691 |
| Persistence | non_flood | 1004 | 0.119 | 0.586 | 594.161 | 398.560 |
| Climatology | flood | 51 | -2.173 | 0.024 | 973.625 | 743.534 |
| Climatology | non_flood | 1004 | 0.781 | 0.808 | 295.932 | 205.866 |

Flood proxy is observed discharge strictly above observed-training Q95 = **2494.714185 m3/s**. This is not an official flood warning category or an independent event count. Subset NSE uses that subset's mean and variance and can be negative.

## Day-30 season scores

| model | lead_day | season | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct | peak_n | peak_MAPE_pct | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LSTM_30d | 30 | Apr-Jun | 273 | 0.383 | 0.597 | 363.879 | 282.007 | 12.999 | 3 | 26.610 | 0.000 | 0.000 | NA |
| LSTM_30d | 30 | Jul-Sep | 276 | 0.338 | 0.620 | 589.572 | 447.670 | 1.645 | 47 | 22.735 | 0.489 | 0.122 | 0.549 |
| LSTM_30d | 30 | Oct-Mar | 506 | 0.408 | 0.562 | 135.272 | 70.840 | -5.791 | 1 | 72.125 | 0.000 | 0.000 | NA |
| Persistence | 30 | Apr-Jun | 273 | -0.089 | 0.341 | 483.474 | 343.733 | -31.215 | 3 | 64.871 | 0.000 | 0.004 | 1.000 |
| Persistence | 30 | Jul-Sep | 276 | -1.334 | -0.150 | 1107.067 | 916.696 | 1.079 | 47 | 43.867 | 0.106 | 0.197 | 0.900 |
| Persistence | 30 | Oct-Mar | 506 | -4.213 | -0.511 | 401.466 | 245.316 | 51.009 | 1 | 88.999 | 0.000 | 0.000 | NA |
| Climatology | 30 | Apr-Jun | 273 | 0.283 | 0.571 | 392.331 | 310.523 | 22.996 | 3 | 40.333 | 0.000 | 0.000 | NA |
| Climatology | 30 | Jul-Sep | 276 | 0.470 | 0.657 | 527.632 | 380.299 | -0.117 | 47 | 20.938 | 0.277 | 0.087 | 0.606 |
| Climatology | 30 | Oct-Mar | 506 | -0.113 | 0.331 | 185.507 | 108.447 | 17.340 | 1 | 88.229 | 0.000 | 0.000 | NA |

## Quantile calibration

| lead_day | n | coverage_05_95 | mean_interval_width_cumecs | fraction_below_q0.05 | fraction_below_q0.25 | fraction_below_q0.5 | fraction_below_q0.75 | fraction_below_q0.95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1067 | 0.843 | 866.467 | 0.060 | 0.241 | 0.461 | 0.667 | 0.903 |
| 10 | 1067 | 0.744 | 650.927 | 0.127 | 0.343 | 0.468 | 0.665 | 0.872 |
| 15 | 1067 | 0.741 | 695.984 | 0.136 | 0.346 | 0.486 | 0.684 | 0.877 |
| 20 | 1065 | 0.744 | 692.973 | 0.158 | 0.367 | 0.496 | 0.702 | 0.901 |
| 30 | 1055 | 0.745 | 742.839 | 0.168 | 0.382 | 0.529 | 0.718 | 0.913 |

The nominal P05-P95 coverage is 90%. Quantiles are ordered by construction; this does not guarantee calibration. Quantiles are marginal daily values and do not define joint 30-day flood-event probabilities.

## Limits

Archived 30-day TIGGE/GFS weather forecasts were not found. Future rain and temperature are realized ERA5-Land plus the existing configurable lead-growing standardized noise (0.05 at lead 1, increasing 0.025 per day to 0.775 at lead 30). The assumed error distribution is not validated against operational weather forecasts. These results therefore establish only retrospective proxy-weather performance, not operational 30-day flood forecast accuracy.

Past weather uses the same eight variables as the original weather-only LSTM, including CHIRPS rainfall; future rainfall is ERA5-Land. Product differences, short observed flow history, regulation, sparse extremes and previously inspected test years limit interpretation. Overlapping forecast windows are not independent samples. No observed past or future discharge is supplied to the LSTM.

Persistence holds the last observation available at issue time. Climatology uses only training-period month/day means. Both are evaluated on exactly the same observed targets as the LSTM. Flow normalization and input mean filling use training years only; original target NaNs and source bytes are preserved.

Synthetic tests establish code behavior only and are not accuracy evidence. Further 30-day architectures will be trained only after feedback on this run.

![Lead-day skill](../../../../evaluation%20comparison/model_30_days/hindcast_forecast_lstm_scratch/skill_by_lead.png)
