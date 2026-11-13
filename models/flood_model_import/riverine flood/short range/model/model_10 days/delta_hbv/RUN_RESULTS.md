# Marala differentiable HBV: actual results

The authors' HBV 1.0 equations are coupled to a new causal LSTM parameter network and trained end to end on Marala. This is a single-basin adaptation of delta-HBV, not downloaded pretrained delta-HBV weights or delta-HBV 2.0.

Train: [2016, 2017, 2018, 2019, 2020]; validation/checkpoint selection: [2021]; test: [2022, 2023, 2024]. Observed test days: **1084**; observed issue/lead pairs: **10795**. Missing targets were never filled or scored.

Actual training: **88.5 seconds**, 40 epochs, selected epoch 40, seed 42, 6,668 trainable parameters. One fixed configuration; no HPO sweep.

## Scores on identical observed records

| model | lead_day | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| delta_HBV | 1 | 1084 | 0.456 | 0.680 | 577.118 | 360.653 | -21.412 |
| LSTM | 1 | 1084 | 0.886 | 0.902 | 263.760 | 157.279 | -2.371 |
| Persistence | 1 | 1084 | 0.870 | 0.935 | 282.358 | 134.178 | 0.000 |
| Climatology | 1 | 1084 | 0.784 | 0.849 | 363.415 | 233.349 | 7.793 |
| delta_HBV | 5 | 1080 | 0.458 | 0.680 | 576.361 | 361.181 | -21.488 |
| LSTM | 5 | 1080 | 0.878 | 0.928 | 273.180 | 164.853 | 0.503 |
| Persistence | 5 | 1080 | 0.735 | 0.868 | 402.659 | 231.663 | 0.012 |
| Climatology | 5 | 1080 | 0.784 | 0.849 | 364.085 | 234.151 | 7.791 |
| delta_HBV | 10 | 1075 | 0.474 | 0.691 | 567.639 | 356.184 | -20.512 |
| LSTM | 10 | 1075 | 0.857 | 0.910 | 295.702 | 187.128 | 5.644 |
| Persistence | 10 | 1075 | 0.652 | 0.826 | 461.403 | 273.370 | 0.364 |
| Climatology | 10 | 1075 | 0.790 | 0.850 | 358.575 | 232.513 | 8.144 |

## Flood and other days at lead 10

| model | group | n | NSE | KGE | RMSE_cumecs | MAE_cumecs |
| --- | --- | --- | --- | --- | --- | --- |
| delta_HBV | flood | 51 | -3.952 | -0.448 | 1216.305 | 978.444 |
| delta_HBV | non_flood | 1024 | 0.328 | 0.636 | 514.374 | 325.193 |
| LSTM | flood | 51 | -0.861 | 0.241 | 745.564 | 528.245 |
| LSTM | non_flood | 1024 | 0.837 | 0.828 | 253.199 | 170.138 |
| Persistence | flood | 51 | -3.695 | 0.062 | 1184.345 | 957.609 |
| Persistence | non_flood | 1024 | 0.610 | 0.770 | 391.964 | 239.291 |
| Climatology | flood | 51 | -2.173 | 0.024 | 973.625 | 743.534 |
| Climatology | non_flood | 1024 | 0.777 | 0.812 | 296.257 | 207.062 |

Flood proxy: observed Q above training Q95 = **2494.714185 m3/s**; other days are at or below it. This is not an official flood category. NSE is not an accuracy percentage.

## Seasonal scores

| model | lead_day | season | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct | peak_n | peak_MAPE_pct | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| delta_HBV | 10 | Apr-Jun | 273 | -0.026 | 0.519 | 469.188 | 340.705 | -3.105 | 3 | 22.972 | 1.000 | 0.011 | 0.500 |
| delta_HBV | 10 | Jul-Sep | 276 | -0.750 | 0.329 | 958.717 | 741.018 | -21.851 | 47 | 33.448 | 0.404 | 0.061 | 0.424 |
| delta_HBV | 10 | Oct-Mar | 526 | -0.873 | 0.157 | 248.953 | 162.290 | -41.186 | 1 | 93.030 | 0.000 | 0.000 | NA |

## Interpretation and limits

Future precipitation/temperature are realized ERA5-Land plus the same seeded standardized noise used in the earlier LSTM experiment. Future PET is a training-only monthly climatology. Real archived weather forecasts are unavailable; operational skill is unverified.

The weather inputs differ from the eight-input original LSTM: this model uses ERA5-Land precipitation, temperature and PET, with no observed flow as a predictor. Architecture differences cannot be isolated from these input differences. The record is short, regulated, and these test years were inspected in earlier experiments; they are not a fresh project-wide holdout.

Three HBV components are averaged. The LSTM learns time-varying BETA, CFMAX and K1; other HBV and gamma-routing parameters are learned as basin constants. Outputs are routed physical runoff converted using a delineated area of 28,780.646 km2. No residual ML discharge head is present. The deterministic model does not provide calibrated forecast intervals.

Every third eligible training issue is used per epoch to control CPU cost; validation and test use every eligible issue. Each sample contains 365 history days and 10 forecast days; the first 305 physical days are upstream no-gradient warmup, leaving 60 history days plus 10 forecast days for parameter gradients. Missing predictor values use training means and indicators; actual 2015-2024 required forcing coverage is complete.

## Provenance and license

[MHPI hydrodl2](https://github.com/mhpi/hydrodl2), pinned commit b163a3c0125c5188f730f379643437d83b4e5d35; unmodified upstream sources and their SHA256 values are in source_reference/. Upstream code is licensed for non-commercial use; commercial use requires permission from PSU. See source_reference/LICENSE.

Synthetic tests check gradients, masking, alignment and loading only; they do not establish forecast accuracy.

![Lead-day skill](../../../evaluation%20comparison/delta_hbv/skill_by_lead.png)
