# Marala GRRR results

Run date: 30 October 2026.

**Keep lagged GRRR as an input feature and leave discharge gaps NaN. The lower-weight filling experiment failed the frozen clear-win rule.**

## Seasonal raw comparison

Main release: `distributed_model_2026_11`, basin `subhybas_4120686050`. Actual overlap is 2016-03-01 through 2025-12-30, with **3,332 paired observed dates**. GRRR has no 2026 data. The newer release's reanalysis metadata was uploaded on 28 October 2026; the older documented release is retained separately and ends on 2023-12-23.

Bias = GRRR minus observed. Seasons: winter Dec-Feb, pre-monsoon Mar-May, monsoon Jun-Sep, post-monsoon Oct-Nov. The peak column is the modeled error **on the largest observed paired-date peak in that season across all available years**; it is not an average event-peak error.

| Season | Paired days | Pearson r | Bias (m³/s) | Bias (%) | Error at largest observed peak (%) |
|---|---:|---:|---:|---:|---:|
| Winter | 740 | 0.785 | -18.8 | -6.8% | -55.6% |
| Pre Monsoon | 828 | 0.803 | -105.9 | -16.6% | -60.8% |
| Monsoon | 1202 | 0.791 | -435.7 | -24.3% | -73.9% |
| Post Monsoon | 562 | 0.815 | -10.9 | -3.0% | -55.1% |

Overall r = **0.906**, bias = **-20.4%**. The largest observed paired peak is 21,789.8 m³/s on 2025-08-27; GRRR gives 5,680.3 m³/s on that date (-73.9%). Strong correlation does not make raw GRRR an accurate substitute for extreme observations.

The selected HydroBasins polygon contains Marala and has upstream area 29,080.8 km², within 0.38% of the published 29,192 km². Its modeled outlet is about 18.72 km downstream. The nearest outlet was rejected as a tributary. Raw daily means and observed point readings have unconfirmed interval equivalence.

Year-by-season peak magnitudes, peak-day errors and sampled peak timing are in [comparison/scores.csv](comparison/scores.csv). They use identical paired dates. Missing observations, missing seasons and modeled daily means prevent interpreting those maxima or timing differences as complete-event peak validation. Winter year/season groups use calendar year, so December is not joined to the following January-February.

![Seasonal paired comparison](comparison/seasonal_comparison.png)

## Feature decision

The fixed two-day-lagged feature passes the training-only gate: **r = 0.894** on 2,131 2016-2021 pairs; **monthly-anomaly r = 0.546**; all four seasonal correlations exceed the frozen minimum. Both experiment arms include this GRRR feature and an availability mask. No feature scaling or fill calibration is fitted to validation/test observations.

## Gap experiment

Both 16-unit LSTMs use seed 42, 30 input days, 15 direct outputs, 15 epochs, the same chronological partitions and exactly the same forecast origins. Both select epoch 9 on observed-only 2022 validation loss. Filled training targets have weight 0.2, observed targets weight 1. Filled values may also enter past input context in the experimental arm.

| Split | Observed days | Experimental fills | Remaining NaNs |
|---|---:|---:|---:|
| Train | 2,131 | 1 | 0 |
| Validation | 365 | 0 | 0 |
| Test | 966 | 259 | 167 |

**Only one training day is missing.** Filling 259 test-period days supplies no additional supervised training targets; those values affect eligible past input contexts only. No test fills are treated as truth. This limits evidence about the benefits of training on large quantities of low-weight filled targets.

| Observed-only evaluation | NaN gaps RMSE (m³/s) | Weighted fills RMSE (m³/s) | Persistence RMSE (m³/s) |
|---|---:|---:|---:|
| Validation (5,265 pairs) | 337.03 | 337.01 | 475.83 |
| Test (13,562 pairs) | 831.55 | 831.43 | 1106.07 |

Filling reduces observed-test RMSE by only **0.014%**. Paired 30-day-block bootstrap 95% interval for relative improvement: **[-0.091%, +0.049%]**. Validation improvement is also below the frozen 5% requirement. **Reject the filled version.** Its checkpoint is removed; evaluation artifacts remain labeled as an experiment. The selected checkpoint is [nan_gaps.pt](experiment/nan_gaps.pt), with [preprocessing metadata](experiment/selected_model.json).

| Test lead | Observed pairs | NaN gaps RMSE | Weighted fills RMSE | Persistence RMSE |
|---|---:|---:|---:|---:|
| 1 days | 917 | 765.2 | 763.6 | 913.2 |
| 3 days | 913 | 821.6 | 821.9 | 1106.5 |
| 7 days | 906 | 833.0 | 832.6 | 1013.2 |
| 15 days | 891 | 862.7 | 862.8 | 1217.9 |

All flow errors in the table are m³/s. There are 922 common test origins and 13,562 observed test origin/target/lead pairs. These pairs overlap and are not independent floods.

## Limits that affect interpretation

- No 2026 GRRR values exist in this extraction. All 2026 gaps stay NaN. There are 1,515 scored 2026 pairs, where both models use the missing-GRRR flag. GRRR was complete in training, so this feature-availability pattern was not seen in training. Availability and year breakdowns are in the saved scores.
- Peak flows remain difficult: the selected model has high-flow test RMSE about 2,871 m³/s and high-flow NSE below zero. These metrics use the training 95th percentile, not an official flood-warning threshold. Overall improvement over persistence does not establish reliable extreme-flood warnings.
- The main two-arm experiment isolates the effect of filling because both models contain GRRR. Correlation supports including the feature; a matched no-GRRR ablation would be needed to establish its incremental predictive benefit.
- This is one seeded retrospective run. Global GRRR pretraining overlap, release latency and true issue-time availability are unverified. The new release lacks independently confirmed interval semantics. The modeled outlet and observation measurement basis differ from an exact daily-mean gauge target.
- Fills were fitted on training observations only and never overwrite original observations. Model selection and evaluation use observed truth exclusively. The experiment does not promote the filled dataset to an observed source.

Validation: **17 artifact checks passed**, including recomputed paired scoring, bootstrap, source/protocol hashes, unchanged observations, no 2026 fills and absence of the rejected checkpoint. Four additional integrity unit tests passed. [Full method and reproduction](README.md), [decision and training report](experiment/report.json), [scored predictions](experiment/predictions_observed_days.csv).
