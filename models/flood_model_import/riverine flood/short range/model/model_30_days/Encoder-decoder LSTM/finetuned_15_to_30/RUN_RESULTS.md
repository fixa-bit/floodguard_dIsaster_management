# Thirty-day encoder-decoder LSTM: fine-tuned from the saved 15-day model

Day-30 mean-flow NSE is **0.849**, versus exact climatology **0.792** and smoothed climatology **0.820**. Beats the original climatology: **True**; beats the smoothed control: **True**. Previous best ensemble NSE: **0.858**.

Three seeds were trained sequentially: [42, 43, 44]. Selected epochs: [9, 15, 26]; total fitting time 176.8 seconds. All choices, blend strengths and empirical quantile offsets were fixed using 2021 before this benchmark evaluation.

Observed benchmark: 2022-2024, 1084 unique target dates, 31932 issue/lead/target pairs, and 1055 day-30 observations. Original targets and NaNs were never changed.

## Day-30 observed scores

| model | lead_day | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Seq2seq_30d_ensemble | 30 | 1055 | 0.849 | 0.915 | 306.417 | 195.363 | 3.820 |
| Raw_seq2seq_ensemble | 30 | 1055 | 0.849 | 0.915 | 306.417 | 195.363 | 3.820 |
| Climatology | 30 | 1055 | 0.792 | 0.845 | 359.398 | 231.857 | 8.837 |
| Smooth_climatology | 30 | 1055 | 0.820 | 0.835 | 334.475 | 219.162 | 8.781 |
| Weather_only_LSTM | 30 | 1055 | 0.784 | 0.884 | 366.025 | 224.066 | 3.333 |
| Past_discharge_LSTM | 30 | 1055 | 0.788 | 0.871 | 362.871 | 215.196 | -5.660 |
| Previous_best_ensemble | 30 | 1055 | 0.858 | 0.874 | 297.556 | 191.690 | 4.150 |
| Persistence | 30 | 1055 | 0.262 | 0.629 | 677.066 | 446.424 | 1.149 |

## Selected leads

| model | lead_day | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Seq2seq_30d_ensemble | 1 | 1067 | 0.830 | 0.914 | 322.918 | 204.488 | 1.076 |
| Climatology | 1 | 1067 | 0.782 | 0.849 | 365.863 | 235.512 | 7.634 |
| Smooth_climatology | 1 | 1067 | 0.809 | 0.839 | 342.114 | 223.249 | 7.626 |
| Seq2seq_30d_ensemble | 10 | 1067 | 0.850 | 0.924 | 303.073 | 196.259 | 1.114 |
| Climatology | 10 | 1067 | 0.789 | 0.850 | 359.501 | 233.108 | 8.020 |
| Smooth_climatology | 10 | 1067 | 0.817 | 0.840 | 335.291 | 221.013 | 8.004 |
| Seq2seq_30d_ensemble | 20 | 1065 | 0.850 | 0.924 | 304.416 | 193.476 | 1.376 |
| Climatology | 20 | 1065 | 0.791 | 0.847 | 358.981 | 232.234 | 8.482 |
| Smooth_climatology | 20 | 1065 | 0.819 | 0.838 | 334.238 | 219.511 | 8.443 |
| Seq2seq_30d_ensemble | 30 | 1055 | 0.849 | 0.915 | 306.417 | 195.363 | 3.820 |
| Climatology | 30 | 1055 | 0.792 | 0.845 | 359.398 | 231.857 | 8.837 |
| Smooth_climatology | 30 | 1055 | 0.820 | 0.835 | 334.475 | 219.162 | 8.781 |

## High-flow and other days at day 30

| model | group | n | NSE | RMSE_cumecs | MAE_cumecs | flood_hit_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Seq2seq_30d_ensemble | flood | 51 | -1.151 | 801.650 | 572.668 | 0.412 | 0.000 |
| Seq2seq_30d_ensemble | non_flood | 1004 | 0.835 | 256.937 | 176.198 | NA | 1.000 |
| Climatology | flood | 51 | -2.173 | 973.625 | 743.534 | 0.255 | 0.000 |
| Climatology | non_flood | 1004 | 0.781 | 295.932 | 205.866 | NA | 1.000 |
| Smooth_climatology | flood | 51 | -2.155 | 970.846 | 771.454 | 0.000 | NA |
| Smooth_climatology | non_flood | 1004 | 0.826 | 263.966 | 191.108 | NA | NA |
| Past_discharge_LSTM | flood | 51 | -1.734 | 903.829 | 705.947 | 0.471 | 0.000 |
| Past_discharge_LSTM | non_flood | 1004 | 0.758 | 311.236 | 190.267 | NA | 1.000 |

High-flow proxy: observed discharge above training-only Q95 = 2494.714185 cumecs. This is not an official flood category or an independent event count.

## Day-30 seasons

| model | lead_day | season | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct | peak_n | peak_MAPE_pct | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Seq2seq_30d_ensemble | 30 | Apr-Jun | 273 | 0.541 | 0.671 | 313.694 | 236.707 | 10.854 | 3 | 32.538 | 0.000 | 0.000 | NA |
| Seq2seq_30d_ensemble | 30 | Jul-Sep | 276 | 0.566 | 0.724 | 477.510 | 371.285 | 3.660 | 47 | 15.568 | 0.447 | 0.148 | 0.618 |
| Seq2seq_30d_ensemble | 30 | Oct-Mar | 506 | 0.408 | 0.553 | 135.268 | 77.101 | -6.428 | 1 | 74.202 | 0.000 | 0.000 | NA |
| Climatology | 30 | Apr-Jun | 273 | 0.283 | 0.571 | 392.331 | 310.523 | 22.996 | 3 | 40.333 | 0.000 | 0.000 | NA |
| Climatology | 30 | Jul-Sep | 276 | 0.470 | 0.657 | 527.632 | 380.299 | -0.117 | 47 | 20.938 | 0.277 | 0.087 | 0.606 |
| Climatology | 30 | Oct-Mar | 506 | -0.113 | 0.331 | 185.507 | 108.447 | 17.340 | 1 | 88.229 | 0.000 | 0.000 | NA |
| Smooth_climatology | 30 | Apr-Jun | 273 | 0.309 | 0.583 | 385.059 | 312.840 | 24.403 | 3 | 37.033 | 0.000 | 0.000 | NA |
| Smooth_climatology | 30 | Jul-Sep | 276 | 0.553 | 0.639 | 484.327 | 341.152 | -1.453 | 47 | 22.248 | 0.000 | 0.000 | NA |
| Smooth_climatology | 30 | Oct-Mar | 506 | 0.181 | 0.388 | 159.088 | 102.081 | 19.356 | 1 | 83.428 | 0.000 | 0.000 | NA |

## Day-30 interval coverage

| lead_day | version | n | coverage_05_95 | interval_width_cumecs |
| --- | --- | --- | --- | --- |
| 30 | raw | 1055 | 0.777 | 1104.837 |
| 30 | validation_adjusted | 1055 | 0.825 | 1523.810 |

Nominal P05-P95 coverage is 90%. The separate quantile head is trained with pinball loss. Empirical offsets use validation residual quantiles in three predefined lead groups; ordering is projected after correction. The same validation year was used for checkpoint selection and correction fitting, so there is no independent conformal coverage guarantee. Quantiles remain daily marginal values, not joint event probabilities.

## Model and objective

This 32-unit encoder-decoder reads 365 days of ERA5-Land precipitation, temperature and past observed discharge, then decodes all 30 forecast-weather leads in one call. Its two weather inputs and smaller network differ from the previous best 64-unit, eight-weather-input ensemble, so performance differences do not isolate architecture. The mean-flow head predicts a correction to a 31-day circular, count-weighted climatology fitted only on observed 2016-2020 discharge. Training anchors are cross-fitted by excluding the target year. Validation and benchmark use full training climatology. A separate exact month/day climatology is retained as the original benchmark.

The encoder, decoder and quantile head start from the saved 15-day CAMELS-US/Marala model. Lead vectors 1-15 are copied exactly; leads 16-30 initially copy day 15, and every lead remains trainable. The extra climatology input column is zero-initialized. The mean head is new; the transferred ordered log-quantile head is converted to physical flow for training. Training uses linear-flow MSE scaled by training flow standard deviation, auxiliary ordered-quantile pinball loss, and a residual penalty. Leads 21-30 receive double training weight. Selection uses validation mean scaled MSE across leads 21-30, with the initial smooth-climatology prediction retained as an epoch-zero fallback.

The three selected mean/quantile outputs are averaged. A validation-fitted coefficient in each predefined group (1-10, 11-20, 21-30) shrinks them toward exact climatology. Mean and median are separate outputs; NSE is scored on the mean forecast, unlike the earlier median-based LSTMs.

## Limits and interpretation

Weather is still noisy future reanalysis, not archived operational forecasts. Only past observed flow through issue time is an input. Source publication latency is unverified. These previously inspected 2022-2024 years are a comparison benchmark, not a fresh project-wide holdout. One three-seed encoder-decoder ensemble does not establish general performance across future periods. There was no test-driven retry after this evaluation.

The source donor pretraining used 1985-1994, with donor selection 1995-1996; local fine-tuning used 2016-2020 and selection 2021. All inherited years are carried into the new checkpoints and checked against benchmark years. Both the original and smoothed climatology controls are reported so a benefit from calendar smoothing is not attributed automatically to the neural network. Epoch-zero selections, if any, appear in the training summaries. No other model family was trained in this step.

![Lead-day comparison](../../../../evaluation%20comparison/model_30_days/encoder_decoder_finetuned_15_to_30/skill_by_lead.png)

## Trade-offs against the previous best

Training took 176.8 seconds across three seeds; selected epochs were 9, 15 and 26. Nine correctness tests and saved-result verification passed. Day-30 high-flow RMSE was 801.6 cumecs versus the previous best 826.1, but ordinary-flow RMSE was worse (256.9 versus 241.6). High-flow hit rate increased to 41.2% from 33.3%, while false-alarm ratio increased to 61.8% from 45.2%. The nominal 90% interval covered 82.5% of observations. Overall NSE remains below the previous best.
