# Matched_LSTM: actual Marala evaluation

**Observed-only retrospective test under noisy future reanalysis weather. Operational forecast accuracy is unverified.**

Train 2016-2020, validation 2021, test 2022-2024. Unique observed test days: 1084; scored issue/lead pairs: 10795; missing-target pairs excluded: 45.

| model | lead_day | n | NSE | KGE | PBIAS_pct | RMSE_cumecs | MAE_cumecs | peak_MAPE_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Matched_LSTM | 1 | 1084 | 0.905 | 0.953 | 0.111 | 240.621 | 138.215 | 12.929 |
| Matched_LSTM | 5 | 1080 | 0.885 | 0.938 | -1.804 | 265.039 | 154.172 | 15.451 |
| Matched_LSTM | 10 | 1075 | 0.880 | 0.936 | -0.754 | 270.918 | 162.780 | 17.370 |

## Flood and non-flood days at lead 10

| model | lead_day | group | n | NSE | KGE | PBIAS_pct | RMSE_cumecs | MAE_cumecs | peak_MAPE_pct | peak_n | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Matched_LSTM | 10 | flood | 51 | -0.973 | 0.266 | -16.987 | 767.831 | 552.927 | 17.370 | 51 | 0.451 | NA | 0.000 |
| Matched_LSTM | 10 | non_flood | 1024 | 0.879 | 0.890 | 2.468 | 218.378 | 143.349 | NA | 0 | NA | 0.018 | 1.000 |

Flood proxy is observed flow > training Q95 = 2494.714185 m3/s; this is not an official warning level. Groups use observed flow, not the prediction. Subset NSE uses its own group mean and variance.

## Point-forecast flood detection at lead 10

| model | lead_day | TP | FN | FP | TN | POD | false_alarm_ratio | false_alarm_rate | CSI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Matched_LSTM | 10 | 23 | 28 | 18 | 1006 | 0.451 | 0.439 | 0.018 | 0.333 |

## Quantile coverage

| model | lead_day | n | nominal_coverage | empirical_coverage | mean_interval_width_cumecs |
| --- | --- | --- | --- | --- | --- |
| Matched_LSTM | 1 | 1084 | 0.900 | 0.913 | 777.088 |
| Matched_LSTM | 2 | 1083 | 0.900 | 0.875 | 697.497 |
| Matched_LSTM | 3 | 1082 | 0.900 | 0.839 | 668.367 |
| Matched_LSTM | 4 | 1081 | 0.900 | 0.788 | 626.507 |
| Matched_LSTM | 5 | 1080 | 0.900 | 0.860 | 716.044 |
| Matched_LSTM | 6 | 1079 | 0.900 | 0.826 | 667.957 |
| Matched_LSTM | 7 | 1078 | 0.900 | 0.844 | 695.048 |
| Matched_LSTM | 8 | 1077 | 0.900 | 0.843 | 701.045 |
| Matched_LSTM | 9 | 1076 | 0.900 | 0.809 | 649.045 |
| Matched_LSTM | 10 | 1075 | 0.900 | 0.807 | 655.465 |

The matched LSTM uses its original positive-increment head to enforce quantile ordering. Ordering is guaranteed; empirical coverage is measured and is not guaranteed. Multiple seeds average their corresponding quantile outputs, which are not exact mixture quantiles.

## Actual training

| seed | epochs_run | selected_epoch | validation_pinball | training_seconds | trainable_parameters | train_samples | validation_samples |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 42 | 18 | 11 | 0.065 | 42.190 | 43413 | 1767 | 356 |

Single frozen configuration and one seed per architecture; no HPO sweep or test-driven retry was performed. Early stopping/checkpoint selection use validation pinball loss only. Synthetic tests establish implementation behavior only.

## Observed days by year

| year | observed_days |
| --- | --- |
| 2022 | 365 |
| 2023 | 365 |
| 2024 | 354 |

## Seasonal scores

| model | lead_day | season | n | NSE | KGE | PBIAS_pct | RMSE_cumecs | MAE_cumecs | peak_MAPE_pct | peak_n | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Matched_LSTM | 1 | Apr-Jun | 273 | 0.813 | 0.876 | 1.234 | 200.186 | 146.274 | 8.089 | 3 | 1.000 | 0.004 | 0.250 |
| Matched_LSTM | 1 | Jul-Sep | 276 | 0.718 | 0.829 | 2.871 | 384.699 | 270.661 | 12.021 | 47 | 0.702 | 0.092 | 0.389 |
| Matched_LSTM | 1 | Oct-Mar | 535 | 0.503 | 0.526 | -9.893 | 143.231 | 65.776 | 70.142 | 1 | 0.000 | 0.000 | NA |
| Matched_LSTM | 2 | Apr-Jun | 273 | 0.796 | 0.860 | 0.144 | 209.270 | 155.192 | 10.311 | 3 | 0.667 | 0.000 | 0.000 |
| Matched_LSTM | 2 | Jul-Sep | 276 | 0.692 | 0.827 | 5.016 | 402.428 | 294.220 | 11.634 | 47 | 0.745 | 0.140 | 0.478 |
| Matched_LSTM | 2 | Oct-Mar | 534 | 0.407 | 0.464 | -10.453 | 156.458 | 68.501 | 78.326 | 1 | 0.000 | 0.000 | NA |
| Matched_LSTM | 3 | Apr-Jun | 273 | 0.779 | 0.841 | 0.614 | 217.741 | 162.324 | 12.382 | 3 | 0.333 | 0.000 | 0.000 |
| Matched_LSTM | 3 | Jul-Sep | 276 | 0.700 | 0.816 | 2.868 | 396.877 | 285.435 | 12.420 | 47 | 0.702 | 0.096 | 0.400 |
| Matched_LSTM | 3 | Oct-Mar | 533 | 0.333 | 0.411 | -11.085 | 166.002 | 71.001 | 82.407 | 1 | 0.000 | 0.000 | NA |
| Matched_LSTM | 4 | Apr-Jun | 273 | 0.766 | 0.838 | 0.898 | 224.108 | 166.912 | 11.602 | 3 | 0.667 | 0.000 | 0.000 |
| Matched_LSTM | 4 | Jul-Sep | 276 | 0.687 | 0.813 | 2.607 | 405.545 | 292.226 | 13.504 | 47 | 0.638 | 0.096 | 0.423 |
| Matched_LSTM | 4 | Oct-Mar | 532 | 0.314 | 0.394 | -12.551 | 168.450 | 73.333 | 81.867 | 1 | 0.000 | 0.000 | NA |
| Matched_LSTM | 5 | Apr-Jun | 273 | 0.753 | 0.820 | -1.047 | 230.104 | 170.563 | 14.272 | 3 | 0.333 | 0.000 | 0.000 |
| Matched_LSTM | 5 | Jul-Sep | 276 | 0.682 | 0.796 | 1.554 | 408.625 | 293.022 | 14.123 | 47 | 0.617 | 0.074 | 0.370 |
| Matched_LSTM | 5 | Oct-Mar | 531 | 0.303 | 0.377 | -13.177 | 169.889 | 73.573 | 81.383 | 1 | 0.000 | 0.000 | NA |
| Matched_LSTM | 6 | Apr-Jun | 273 | 0.748 | 0.814 | -0.521 | 232.770 | 173.507 | 12.833 | 3 | 0.333 | 0.000 | 0.000 |
| Matched_LSTM | 6 | Jul-Sep | 276 | 0.667 | 0.778 | 1.960 | 418.252 | 300.986 | 14.892 | 47 | 0.574 | 0.087 | 0.426 |
| Matched_LSTM | 6 | Oct-Mar | 530 | 0.297 | 0.380 | -11.869 | 170.771 | 74.629 | 80.550 | 1 | 0.000 | 0.000 | NA |
| Matched_LSTM | 7 | Apr-Jun | 273 | 0.742 | 0.819 | -0.459 | 235.535 | 173.746 | 11.823 | 3 | 0.667 | 0.000 | 0.000 |
| Matched_LSTM | 7 | Jul-Sep | 276 | 0.677 | 0.772 | 1.941 | 411.802 | 293.407 | 14.992 | 47 | 0.511 | 0.074 | 0.415 |
| Matched_LSTM | 7 | Oct-Mar | 529 | 0.289 | 0.380 | -12.445 | 171.889 | 76.077 | 79.668 | 1 | 0.000 | 0.000 | NA |
| Matched_LSTM | 8 | Apr-Jun | 273 | 0.742 | 0.822 | -0.633 | 235.308 | 176.108 | 12.940 | 3 | 0.333 | 0.000 | 0.000 |
| Matched_LSTM | 8 | Jul-Sep | 276 | 0.674 | 0.769 | 2.656 | 413.453 | 296.295 | 14.613 | 47 | 0.638 | 0.096 | 0.423 |
| Matched_LSTM | 8 | Oct-Mar | 528 | 0.284 | 0.376 | -11.973 | 172.564 | 76.346 | 80.720 | 1 | 0.000 | 0.000 | NA |
| Matched_LSTM | 9 | Apr-Jun | 273 | 0.720 | 0.810 | -0.400 | 245.242 | 182.572 | 14.150 | 3 | 0.333 | 0.000 | 0.000 |
| Matched_LSTM | 9 | Jul-Sep | 276 | 0.667 | 0.744 | 2.324 | 418.221 | 294.657 | 15.015 | 47 | 0.617 | 0.087 | 0.408 |
| Matched_LSTM | 9 | Oct-Mar | 527 | 0.283 | 0.386 | -11.738 | 172.454 | 76.678 | 80.387 | 1 | 0.000 | 0.000 | NA |
| Matched_LSTM | 10 | Apr-Jun | 273 | 0.703 | 0.808 | -1.265 | 252.630 | 186.596 | 14.605 | 3 | 0.000 | 0.000 | NA |
| Matched_LSTM | 10 | Jul-Sep | 276 | 0.654 | 0.722 | 2.740 | 426.285 | 309.404 | 16.207 | 47 | 0.489 | 0.079 | 0.439 |
| Matched_LSTM | 10 | Oct-Mar | 526 | 0.349 | 0.476 | -11.016 | 146.724 | 73.483 | 80.364 | 1 | 0.000 | 0.000 | NA |

## Limits

Past discharge and historical ERA5-Land rain/temperature are additional inputs compared with the old weather-only LSTM. Use the newly trained matched-input LSTM to assess the architecture comparison. All future rain/temperature channels and errors match the old experiment exactly. Future observed discharge is never supplied. Missing past inputs use training means with separate indicators, while targets remain NaN and masked.

The networks were trained from scratch, not from global pretrained weights. N-HiTS/N-BEATSx computational blocks are copied from pinned Nixtla source; the matched LSTM uses this project's existing encoder-decoder; data windows, training-only normalization, masking, AdamW, dropout, small widths and quantile ordering are project adaptations. The comparison period was inspected in earlier experiments and is not an untouched project-wide holdout. Limited independent floods, regulation, observation times and operational weather latency remain limitations.

