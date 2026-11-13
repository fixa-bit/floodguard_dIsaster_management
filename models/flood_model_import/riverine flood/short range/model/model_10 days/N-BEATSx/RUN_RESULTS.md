# NBEATSx: actual Marala evaluation

**Observed-only retrospective test under noisy future reanalysis weather. Operational forecast accuracy is unverified.**

Train 2016-2020, validation 2021, test 2022-2024. Unique observed test days: 1084; scored issue/lead pairs: 10795; missing-target pairs excluded: 45.

| model | lead_day | n | NSE | KGE | PBIAS_pct | RMSE_cumecs | MAE_cumecs | peak_MAPE_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NBEATSx | 1 | 1084 | 0.883 | 0.937 | -0.462 | 268.099 | 142.175 | 21.060 |
| NBEATSx | 5 | 1080 | 0.794 | 0.876 | -2.233 | 355.067 | 211.307 | 27.740 |
| NBEATSx | 10 | 1075 | 0.718 | 0.830 | -3.913 | 415.743 | 236.153 | 32.678 |

## Flood and non-flood days at lead 10

| model | lead_day | group | n | NSE | KGE | PBIAS_pct | RMSE_cumecs | MAE_cumecs | peak_MAPE_pct | peak_n | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NBEATSx | 10 | flood | 51 | -4.055 | -0.011 | -30.628 | 1228.967 | 1007.744 | 32.678 | 51 | 0.275 | NA | 0.000 |
| NBEATSx | 10 | non_flood | 1024 | 0.730 | 0.857 | 1.390 | 325.926 | 197.724 | NA | 0 | NA | 0.020 | 1.000 |

Flood proxy is observed flow > training Q95 = 2494.714185 m3/s; this is not an official warning level. Groups use observed flow, not the prediction. Subset NSE uses its own group mean and variance.

## Point-forecast flood detection at lead 10

| model | lead_day | TP | FN | FP | TN | POD | false_alarm_ratio | false_alarm_rate | CSI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NBEATSx | 10 | 14 | 37 | 20 | 1004 | 0.275 | 0.588 | 0.020 | 0.197 |

## Quantile coverage

| model | lead_day | n | nominal_coverage | empirical_coverage | mean_interval_width_cumecs |
| --- | --- | --- | --- | --- | --- |
| NBEATSx | 1 | 1084 | 0.900 | 0.751 | 431.916 |
| NBEATSx | 2 | 1083 | 0.900 | 0.711 | 508.750 |
| NBEATSx | 3 | 1082 | 0.900 | 0.591 | 423.941 |
| NBEATSx | 4 | 1081 | 0.900 | 0.624 | 429.689 |
| NBEATSx | 5 | 1080 | 0.900 | 0.538 | 470.623 |
| NBEATSx | 6 | 1079 | 0.900 | 0.614 | 549.927 |
| NBEATSx | 7 | 1078 | 0.900 | 0.564 | 468.809 |
| NBEATSx | 8 | 1077 | 0.900 | 0.511 | 446.627 |
| NBEATSx | 9 | 1076 | 0.900 | 0.525 | 429.144 |
| NBEATSx | 10 | 1075 | 0.900 | 0.673 | 543.648 |

The original basis outputs are projected to ordered quantiles by sorting. Ordering is guaranteed; empirical coverage is measured and is not guaranteed. Multiple seeds average their corresponding quantile outputs, which are not exact mixture quantiles.

## Actual training

| seed | epochs_run | selected_epoch | validation_pinball | training_seconds | trainable_parameters | train_samples | validation_samples |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 42 | 19 | 12 | 0.096 | 24.225 | 1737437 | 1767 | 356 |

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
| NBEATSx | 1 | Apr-Jun | 273 | 0.803 | 0.886 | -0.820 | 205.811 | 143.247 | 15.791 | 3 | 1.000 | 0.000 | 0.000 |
| NBEATSx | 1 | Jul-Sep | 276 | 0.648 | 0.824 | -1.109 | 430.115 | 288.112 | 20.024 | 47 | 0.617 | 0.074 | 0.370 |
| NBEATSx | 1 | Oct-Mar | 535 | 0.307 | 0.604 | 2.016 | 169.061 | 66.342 | 85.574 | 1 | 0.000 | 0.000 | NA |
| NBEATSx | 2 | Apr-Jun | 273 | 0.731 | 0.854 | -0.646 | 240.170 | 174.722 | 13.125 | 3 | 0.667 | 0.004 | 0.333 |
| NBEATSx | 2 | Jul-Sep | 276 | 0.428 | 0.680 | -7.252 | 547.828 | 376.005 | 23.591 | 47 | 0.426 | 0.052 | 0.375 |
| NBEATSx | 2 | Oct-Mar | 534 | 0.269 | 0.523 | 0.637 | 173.818 | 73.667 | 81.943 | 1 | 0.000 | 0.000 | NA |
| NBEATSx | 3 | Apr-Jun | 273 | 0.568 | 0.787 | 2.874 | 304.538 | 218.045 | 31.791 | 3 | 0.667 | 0.007 | 0.500 |
| NBEATSx | 3 | Jul-Sep | 276 | 0.468 | 0.732 | -3.031 | 528.325 | 378.566 | 21.047 | 47 | 0.489 | 0.087 | 0.465 |
| NBEATSx | 3 | Oct-Mar | 533 | 0.192 | 0.440 | -3.334 | 182.802 | 80.341 | 88.327 | 1 | 0.000 | 0.000 | NA |
| NBEATSx | 4 | Apr-Jun | 273 | 0.544 | 0.768 | 1.905 | 312.770 | 225.794 | 25.665 | 3 | 0.333 | 0.004 | 0.500 |
| NBEATSx | 4 | Jul-Sep | 276 | 0.451 | 0.731 | -1.119 | 536.812 | 388.472 | 23.645 | 47 | 0.489 | 0.109 | 0.521 |
| NBEATSx | 4 | Oct-Mar | 532 | 0.124 | 0.405 | -5.727 | 190.446 | 85.827 | 88.936 | 1 | 0.000 | 0.000 | NA |
| NBEATSx | 5 | Apr-Jun | 273 | 0.473 | 0.722 | 3.499 | 336.390 | 239.853 | 26.827 | 3 | 0.000 | 0.007 | 1.000 |
| NBEATSx | 5 | Jul-Sep | 276 | 0.416 | 0.695 | -5.043 | 553.671 | 407.405 | 26.538 | 47 | 0.426 | 0.052 | 0.375 |
| NBEATSx | 5 | Oct-Mar | 531 | 0.061 | 0.397 | -1.601 | 197.240 | 94.704 | 86.987 | 1 | 0.000 | 0.000 | NA |
| NBEATSx | 6 | Apr-Jun | 273 | 0.447 | 0.706 | 4.819 | 344.418 | 252.082 | 26.702 | 3 | 0.000 | 0.004 | 1.000 |
| NBEATSx | 6 | Jul-Sep | 276 | 0.314 | 0.673 | -3.043 | 600.126 | 433.106 | 28.508 | 47 | 0.404 | 0.122 | 0.596 |
| NBEATSx | 6 | Oct-Mar | 530 | 0.093 | 0.379 | -1.706 | 193.947 | 95.387 | 85.810 | 1 | 0.000 | 0.000 | NA |
| NBEATSx | 7 | Apr-Jun | 273 | 0.467 | 0.686 | -2.059 | 338.132 | 237.079 | 38.193 | 3 | 0.000 | 0.000 | NA |
| NBEATSx | 7 | Jul-Sep | 276 | 0.288 | 0.649 | -1.692 | 611.650 | 448.752 | 27.699 | 47 | 0.426 | 0.140 | 0.615 |
| NBEATSx | 7 | Oct-Mar | 529 | 0.148 | 0.426 | -4.239 | 188.179 | 97.110 | 70.806 | 1 | 0.000 | 0.000 | NA |
| NBEATSx | 8 | Apr-Jun | 273 | 0.465 | 0.646 | -3.849 | 338.707 | 242.291 | 47.068 | 3 | 0.000 | 0.000 | NA |
| NBEATSx | 8 | Jul-Sep | 276 | 0.186 | 0.609 | 1.339 | 653.856 | 475.436 | 25.616 | 47 | 0.383 | 0.153 | 0.660 |
| NBEATSx | 8 | Oct-Mar | 528 | 0.051 | 0.421 | -2.583 | 198.698 | 100.162 | 73.545 | 1 | 0.000 | 0.000 | NA |
| NBEATSx | 9 | Apr-Jun | 273 | 0.427 | 0.627 | -5.557 | 350.730 | 247.126 | 51.212 | 3 | 0.000 | 0.000 | NA |
| NBEATSx | 9 | Jul-Sep | 276 | 0.240 | 0.598 | -3.520 | 631.797 | 449.314 | 25.535 | 47 | 0.426 | 0.100 | 0.535 |
| NBEATSx | 9 | Oct-Mar | 527 | 0.032 | 0.368 | -6.589 | 200.423 | 96.216 | 89.976 | 1 | 0.000 | 0.000 | NA |
| NBEATSx | 10 | Apr-Jun | 273 | 0.343 | 0.591 | -0.105 | 375.410 | 255.269 | 53.827 | 3 | 0.000 | 0.000 | NA |
| NBEATSx | 10 | Jul-Sep | 276 | 0.119 | 0.535 | -5.881 | 680.342 | 479.979 | 30.259 | 47 | 0.298 | 0.087 | 0.588 |
| NBEATSx | 10 | Oct-Mar | 526 | -0.125 | 0.407 | -3.169 | 192.938 | 98.293 | 82.945 | 1 | 0.000 | 0.000 | NA |

## Limits

Past discharge and historical ERA5-Land rain/temperature are additional inputs compared with the old weather-only LSTM. Use the newly trained matched-input LSTM to assess the architecture comparison. All future rain/temperature channels and errors match the old experiment exactly. Future observed discharge is never supplied. Missing past inputs use training means with separate indicators, while targets remain NaN and masked.

The networks were trained from scratch, not from global pretrained weights. The computational blocks are copied from pinned Nixtla source; data windows, training-only normalization, masking, AdamW, dropout, small widths and quantile ordering are project adaptations. The comparison period was inspected in earlier experiments and is not an untouched project-wide holdout. Limited independent floods, regulation, observation times and operational weather latency remain limitations.

