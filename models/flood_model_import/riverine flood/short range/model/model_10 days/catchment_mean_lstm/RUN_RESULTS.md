# Actual spatial model run

## Measured test accuracy

Lead-10 NSE is **0.853** for the elevation-band model and **0.867** for the same-source catchment-mean control (difference -0.0140). Parameter counts differ; this one-seed pilot does not isolate a universally transferable spatial benefit.

**Future weather is realized ERA5-Land with shared lead-dependent noise. These are not operational archived-forecast scores. NSE is not an accuracy percentage.**

Test years: [2022, 2023, 2024]. Observed basin-days across leads: **1084**; observed issue/lead/target pairs: **10795**. No missing discharge was filled or scored.

| model | lead_day | n | NSE | KGE | PBIAS_pct | RMSE_cumecs |
| --- | --- | --- | --- | --- | --- | --- |
| ElevationBands | 1 | 1084 | 0.867 | 0.890 | -1.098 | 284.750 |
| MeanControl | 1 | 1084 | 0.873 | 0.935 | 0.760 | 278.361 |
| persistence | 1 | 1084 | 0.870 | 0.935 | 0.000 | 282.358 |
| climatology | 1 | 1084 | 0.784 | 0.849 | 7.793 | 363.415 |
| original_8input_LSTM | 1 | 1084 | 0.886 | 0.902 | -2.371 | 263.760 |
| gradient_boosting | 1 | 1084 | 0.875 | 0.916 | 2.670 | 276.755 |
| Ensemble | 1 | 1084 | 0.891 | 0.912 | -0.231 | 258.621 |
| ElevationBands | 10 | 1075 | 0.853 | 0.875 | 5.894 | 299.831 |
| MeanControl | 10 | 1075 | 0.867 | 0.931 | 0.512 | 285.182 |
| persistence | 10 | 1075 | 0.652 | 0.826 | 0.364 | 461.403 |
| climatology | 10 | 1075 | 0.790 | 0.850 | 8.144 | 358.575 |
| original_8input_LSTM | 10 | 1075 | 0.857 | 0.910 | 5.644 | 295.702 |
| gradient_boosting | 10 | 1075 | 0.851 | 0.877 | 0.541 | 302.424 |
| Ensemble | 10 | 1075 | 0.866 | 0.916 | 4.630 | 286.462 |

### Seasonal results at lead 10

| model | lead_day | season | n | NSE | KGE | PBIAS_pct | RMSE_cumecs | MAE_cumecs | peak_MAPE_pct | peak_n | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ElevationBands | 10 | Apr-Jun | 273 | 0.586 | 0.684 | 16.372 | 298.116 | 240.899 | 21.020 | 3 | 0.000 | 0.000 | NA |
| MeanControl | 10 | Apr-Jun | 273 | 0.735 | 0.777 | -0.976 | 238.394 | 177.264 | 11.149 | 3 | 0.667 | 0.000 | 0.000 |
| ElevationBands | 10 | Jul-Sep | 276 | 0.590 | 0.602 | 1.067 | 464.070 | 330.372 | 20.360 | 47 | 0.213 | 0.044 | 0.500 |
| MeanControl | 10 | Jul-Sep | 276 | 0.587 | 0.729 | 6.546 | 465.481 | 353.085 | 14.762 | 47 | 0.681 | 0.114 | 0.448 |
| ElevationBands | 10 | Oct-Mar | 526 | 0.257 | 0.526 | 6.100 | 156.842 | 92.213 | 77.459 | 1 | 0.000 | 0.000 | NA |
| MeanControl | 10 | Oct-Mar | 526 | 0.304 | 0.446 | -16.346 | 151.744 | 79.086 | 77.045 | 1 | 0.000 | 0.000 | NA |

### Quantile calibration

| model | lead_day | n | nominal_coverage | actual_coverage |
| --- | --- | --- | --- | --- |
| ElevationBands | 10 | 1075 | 0.900 | 0.873 |
| MeanControl | 10 | 1075 | 0.900 | 0.771 |

### Actual training runs

| model | seed | epochs_run | selected_epoch | validation_pinball | training_seconds | parameters | training_samples | validation_samples |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ElevationBands | 42 | 14 | 8 | 0.085 | 108.114 | 46805 | 1767 | 356 |
| MeanControl | 42 | 24 | 18 | 0.074 | 139.273 | 39829 | 1767 | 356 |

Peak/flood thresholds are training Q95 by default: **2494.71 / 2494.71 cumecs**, not official flood levels or return periods. Positive PBIAS means overprediction. False-alarm rate counts false alerts/non-exceedance days; false-alarm ratio counts false alerts/all alerts.

Six spatial and 20 existing synthetic tests passed. Tests establish code correctness, not accuracy. The original eight-input LSTM and earlier ensemble use different predictors and forecast-error models; they are context, not a matched ablation.


See README for commands and source provenance.
