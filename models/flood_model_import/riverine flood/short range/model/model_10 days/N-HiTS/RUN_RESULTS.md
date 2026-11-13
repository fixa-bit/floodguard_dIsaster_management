# NHITS: actual Marala evaluation

**Observed-only retrospective test under noisy future reanalysis weather. Operational forecast accuracy is unverified.**

Train 2016-2020, validation 2021, test 2022-2024. Unique observed test days: 1084; scored issue/lead pairs: 10795; missing-target pairs excluded: 45.

| model | lead_day | n | NSE | KGE | PBIAS_pct | RMSE_cumecs | MAE_cumecs | peak_MAPE_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NHITS | 1 | 1084 | 0.890 | 0.933 | -1.088 | 259.674 | 135.020 | 19.687 |
| NHITS | 5 | 1080 | 0.797 | 0.898 | 0.624 | 352.695 | 207.712 | 22.947 |
| NHITS | 10 | 1075 | 0.704 | 0.849 | 1.932 | 425.593 | 248.540 | 28.709 |

## Flood and non-flood days at lead 10

| model | lead_day | group | n | NSE | KGE | PBIAS_pct | RMSE_cumecs | MAE_cumecs | peak_MAPE_pct | peak_n | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NHITS | 10 | flood | 51 | -2.989 | -0.030 | -18.912 | 1091.647 | 864.918 | 28.709 | 51 | 0.471 | NA | 0.000 |
| NHITS | 10 | non_flood | 1024 | 0.668 | 0.767 | 6.070 | 361.661 | 217.842 | NA | 0 | NA | 0.049 | 1.000 |

Flood proxy is observed flow > training Q95 = 2494.714185 m3/s; this is not an official warning level. Groups use observed flow, not the prediction. Subset NSE uses its own group mean and variance.

## Point-forecast flood detection at lead 10

| model | lead_day | TP | FN | FP | TN | POD | false_alarm_ratio | false_alarm_rate | CSI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NHITS | 10 | 24 | 27 | 50 | 974 | 0.471 | 0.676 | 0.049 | 0.238 |

## Quantile coverage

| model | lead_day | n | nominal_coverage | empirical_coverage | mean_interval_width_cumecs |
| --- | --- | --- | --- | --- | --- |
| NHITS | 1 | 1084 | 0.900 | 0.696 | 400.415 |
| NHITS | 2 | 1083 | 0.900 | 0.638 | 387.952 |
| NHITS | 3 | 1082 | 0.900 | 0.665 | 464.253 |
| NHITS | 4 | 1081 | 0.900 | 0.592 | 429.394 |
| NHITS | 5 | 1080 | 0.900 | 0.556 | 412.351 |
| NHITS | 6 | 1079 | 0.900 | 0.453 | 342.590 |
| NHITS | 7 | 1078 | 0.900 | 0.528 | 458.290 |
| NHITS | 8 | 1077 | 0.900 | 0.539 | 466.904 |
| NHITS | 9 | 1076 | 0.900 | 0.529 | 428.882 |
| NHITS | 10 | 1075 | 0.900 | 0.497 | 432.654 |

The original basis outputs are projected to ordered quantiles by sorting. Ordering is guaranteed; empirical coverage is measured and is not guaranteed. Multiple seeds average their corresponding quantile outputs, which are not exact mixture quantiles.

## Actual training

| seed | epochs_run | selected_epoch | validation_pinball | training_seconds | trainable_parameters | train_samples | validation_samples |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 42 | 17 | 10 | 0.092 | 36.987 | 829980 | 1767 | 356 |

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
| NHITS | 1 | Apr-Jun | 273 | 0.788 | 0.879 | 1.789 | 213.393 | 141.555 | 21.669 | 3 | 0.667 | 0.000 | 0.000 |
| NHITS | 1 | Jul-Sep | 276 | 0.676 | 0.827 | -2.167 | 412.175 | 276.476 | 18.065 | 47 | 0.553 | 0.057 | 0.333 |
| NHITS | 1 | Oct-Mar | 535 | 0.376 | 0.589 | -1.785 | 160.456 | 58.709 | 89.980 | 1 | 0.000 | 0.000 | NA |
| NHITS | 2 | Apr-Jun | 273 | 0.728 | 0.846 | 1.600 | 241.762 | 177.036 | 10.898 | 3 | 0.333 | 0.004 | 0.500 |
| NHITS | 2 | Jul-Sep | 276 | 0.475 | 0.734 | -2.688 | 525.010 | 342.390 | 19.799 | 47 | 0.553 | 0.079 | 0.409 |
| NHITS | 2 | Oct-Mar | 534 | 0.257 | 0.479 | -4.013 | 175.207 | 69.982 | 87.475 | 1 | 0.000 | 0.000 | NA |
| NHITS | 3 | Apr-Jun | 273 | 0.557 | 0.783 | 3.575 | 308.372 | 210.064 | 35.765 | 3 | 0.667 | 0.000 | 0.000 |
| NHITS | 3 | Jul-Sep | 276 | 0.423 | 0.725 | 1.760 | 550.213 | 389.710 | 21.199 | 47 | 0.532 | 0.118 | 0.519 |
| NHITS | 3 | Oct-Mar | 533 | 0.220 | 0.462 | -4.357 | 179.558 | 77.503 | 85.426 | 1 | 0.000 | 0.000 | NA |
| NHITS | 4 | Apr-Jun | 273 | 0.507 | 0.758 | 1.070 | 325.314 | 229.131 | 17.558 | 3 | 0.333 | 0.004 | 0.500 |
| NHITS | 4 | Jul-Sep | 276 | 0.477 | 0.748 | 0.509 | 524.018 | 390.610 | 22.528 | 47 | 0.468 | 0.100 | 0.511 |
| NHITS | 4 | Oct-Mar | 532 | 0.191 | 0.405 | -8.240 | 182.983 | 79.494 | 87.491 | 1 | 0.000 | 0.000 | NA |
| NHITS | 5 | Apr-Jun | 273 | 0.453 | 0.714 | -0.303 | 342.609 | 241.222 | 27.287 | 3 | 0.000 | 0.004 | 1.000 |
| NHITS | 5 | Jul-Sep | 276 | 0.426 | 0.723 | 2.870 | 548.772 | 408.487 | 21.262 | 47 | 0.532 | 0.162 | 0.597 |
| NHITS | 5 | Oct-Mar | 531 | 0.128 | 0.370 | -4.979 | 190.066 | 86.125 | 89.098 | 1 | 0.000 | 0.000 | NA |
| NHITS | 6 | Apr-Jun | 273 | 0.484 | 0.694 | -2.864 | 332.899 | 231.864 | 33.698 | 3 | 0.000 | 0.004 | 1.000 |
| NHITS | 6 | Jul-Sep | 276 | 0.355 | 0.683 | -1.322 | 582.009 | 431.190 | 26.225 | 47 | 0.426 | 0.109 | 0.556 |
| NHITS | 6 | Oct-Mar | 530 | 0.160 | 0.387 | -4.143 | 186.686 | 87.056 | 87.133 | 1 | 0.000 | 0.000 | NA |
| NHITS | 7 | Apr-Jun | 273 | 0.470 | 0.709 | -1.380 | 337.149 | 235.245 | 32.970 | 3 | 0.000 | 0.000 | NA |
| NHITS | 7 | Jul-Sep | 276 | 0.279 | 0.639 | -4.074 | 615.109 | 450.570 | 26.495 | 47 | 0.468 | 0.096 | 0.500 |
| NHITS | 7 | Oct-Mar | 529 | 0.175 | 0.410 | -3.272 | 185.154 | 91.953 | 75.932 | 1 | 0.000 | 0.000 | NA |
| NHITS | 8 | Apr-Jun | 273 | 0.414 | 0.697 | -3.014 | 354.640 | 251.436 | 31.069 | 3 | 0.000 | 0.011 | 1.000 |
| NHITS | 8 | Jul-Sep | 276 | 0.083 | 0.584 | 0.962 | 693.740 | 506.343 | 25.535 | 47 | 0.511 | 0.201 | 0.657 |
| NHITS | 8 | Oct-Mar | 528 | 0.163 | 0.398 | -2.876 | 186.688 | 92.158 | 79.457 | 1 | 0.000 | 0.000 | NA |
| NHITS | 9 | Apr-Jun | 273 | 0.447 | 0.675 | -1.511 | 344.559 | 246.260 | 42.461 | 3 | 0.000 | 0.000 | NA |
| NHITS | 9 | Jul-Sep | 276 | 0.112 | 0.590 | 0.802 | 682.850 | 499.346 | 24.284 | 47 | 0.447 | 0.205 | 0.691 |
| NHITS | 9 | Oct-Mar | 527 | 0.061 | 0.356 | -2.409 | 197.329 | 93.308 | 94.956 | 1 | 0.000 | 0.000 | NA |
| NHITS | 10 | Apr-Jun | 273 | 0.397 | 0.656 | 0.274 | 359.639 | 253.179 | 49.581 | 3 | 0.000 | 0.000 | NA |
| NHITS | 10 | Jul-Sep | 276 | 0.012 | 0.558 | 3.485 | 720.369 | 539.409 | 26.186 | 47 | 0.511 | 0.218 | 0.676 |
| NHITS | 10 | Oct-Mar | 526 | 0.070 | 0.462 | -0.583 | 175.383 | 93.510 | 84.660 | 1 | 0.000 | 0.000 | NA |

## Limits

Past discharge and historical ERA5-Land rain/temperature are additional inputs compared with the old weather-only LSTM. Use the newly trained matched-input LSTM to assess the architecture comparison. All future rain/temperature channels and errors match the old experiment exactly. Future observed discharge is never supplied. Missing past inputs use training means with separate indicators, while targets remain NaN and masked.

The networks were trained from scratch, not from global pretrained weights. The computational blocks are copied from pinned Nixtla source; data windows, training-only normalization, masking, AdamW, dropout, small widths and quantile ordering are project adaptations. The comparison period was inspected in earlier experiments and is not an untouched project-wide holdout. Limited independent floods, regulation, observation times and operational weather latency remain limitations.

