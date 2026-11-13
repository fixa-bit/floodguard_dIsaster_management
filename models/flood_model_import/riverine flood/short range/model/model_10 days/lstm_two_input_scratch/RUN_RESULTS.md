# Actual multi-basin transfer run - 2026-10-30

Working directory: `D:/projects/flood_model/flood_model/riverine flood/short range/model`.

## Commands executed

```powershell
$python = "../experiments/marala_observed/.venv/Scripts/python.exe"
& $python pretrained_multibasin_lstm/prepare_data.py --config pretrained_multibasin_lstm/config.yaml
& $python pretrained_multibasin_lstm/train.py --stage all --config pretrained_multibasin_lstm/config.yaml
& $python pretrained_multibasin_lstm/evaluate.py --config pretrained_multibasin_lstm/config.yaml
& $python -m unittest discover -s tests -v
```

The source-coverage audit initially rejected 1981-1990 because Gallatin had only 2,556 observed days. The final 1985-1994 period has 3,652 observed days for each of eight donors and was selected before any training or test scoring. Data preparation was then completed without interpolation. The three real-data training stages were each run once. Evaluation was rerun to add this summary, with unchanged weights and test scores. Python compilation checks passed for the new scripts. All 15 correctness tests passed; their synthetic fine-tuning checks are not real accuracy results.

## Real training results

| stage | epochs_run | selected_epoch | validation_pinball | train_samples | validation_samples | training_seconds |
| --- | --- | --- | --- | --- | --- | --- |
| pretrain | 7 | 4 | 0.150 | 29144 | 5776 | 163.871 |
| finetune | 30 | 27 | 0.077 | 1767 | 356 | 41.243 |
| scratch | 30 | 30 | 0.077 | 1767 | 356 | 66.787 |

Pretraining used 1985-1994, validation 1995-1996. Fine-tuning and the matched scratch model used Marala 2016-2020, validation 2021. Test years were 2022-2024. Every training/validation year inherited through the parent checkpoint was checked before test scoring. Fine-tuning retained all pretrained model weights and recomputed normalization from Marala training data, using the configured smaller learning rate.

| year | observed_days |
| --- | --- |
| 2022 | 365 |
| 2023 | 365 |
| 2024 | 354 |

Unique observed Marala test days: **1084**; issue/lead/target pairs: **10795**. Day-10 scores use 1075 observed targets.

## What the scores show

Day-10 overall NSE: fine-tuned **0.814**, matched scratch **0.810** (difference +0.0037). Day-10 monsoon NSE: fine-tuned **0.506**, scratch **0.507**. This pilot shows a small overall transfer gain, with no monsoon NSE improvement. These results do not establish a robust advantage across seeds, basins or extremes.

| model | lead_day | n | NSE | KGE | PBIAS_pct | RMSE_cumecs |
| --- | --- | --- | --- | --- | --- | --- |
| pretrained_only | 1 | 1084 | -0.854 | -0.321 | -91.335 | 1065.174 |
| finetuned | 1 | 1084 | 0.820 | 0.880 | 7.687 | 331.637 |
| scratch | 1 | 1084 | 0.823 | 0.855 | 11.637 | 328.752 |
| original_8input_LSTM | 1 | 1084 | 0.886 | 0.902 | -2.371 | 263.760 |
| persistence | 1 | 1084 | 0.870 | 0.935 | 0.000 | 282.358 |
| climatology | 1 | 1084 | 0.784 | 0.849 | 7.793 | 363.415 |
| pretrained_only | 10 | 1075 | -0.747 | -0.265 | -88.878 | 1033.909 |
| finetuned | 10 | 1075 | 0.814 | 0.830 | 12.171 | 337.712 |
| scratch | 10 | 1075 | 0.810 | 0.823 | 14.180 | 341.090 |
| original_8input_LSTM | 10 | 1075 | 0.857 | 0.910 | 5.644 | 295.702 |
| persistence | 10 | 1075 | 0.652 | 0.826 | 0.364 | 461.403 |
| climatology | 10 | 1075 | 0.790 | 0.850 | 8.144 | 358.575 |

| model | lead_day | season | n | NSE | KGE | PBIAS_pct | RMSE_cumecs | MAE_cumecs | peak_MAPE_pct | peak_n | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| finetuned | 10 | Apr-Jun | 273 | 0.347 | 0.656 | 21.865 | 374.409 | 280.510 | 9.271 | 3 | 1.000 | 0.000 | 0.000 |
| scratch | 10 | Apr-Jun | 273 | 0.266 | 0.626 | 27.199 | 396.942 | 304.528 | 11.119 | 3 | 0.667 | 0.000 | 0.000 |
| finetuned | 10 | Jul-Sep | 276 | 0.506 | 0.738 | 13.642 | 509.418 | 405.070 | 12.591 | 47 | 0.766 | 0.218 | 0.581 |
| scratch | 10 | Jul-Sep | 276 | 0.507 | 0.697 | 13.506 | 508.959 | 408.422 | 12.877 | 47 | 0.766 | 0.201 | 0.561 |
| finetuned | 10 | Oct-Mar | 526 | 0.270 | 0.517 | -6.314 | 155.443 | 87.497 | 76.437 | 1 | 0.000 | 0.000 | NA |
| scratch | 10 | Oct-Mar | 526 | 0.393 | 0.537 | -2.315 | 141.679 | 74.499 | 78.071 | 1 | 0.000 | 0.000 | NA |

| model | lead_day | n | nominal_coverage | actual_coverage |
| --- | --- | --- | --- | --- |
| pretrained_only | 10 | 1075 | 0.900 | 0.041 |
| finetuned | 10 | 1075 | 0.900 | 0.850 |
| scratch | 10 | 1075 | 0.900 | 0.828 |
| original_8input_LSTM | 10 | 1075 | 0.900 | 0.833 |

The earlier eight-input LSTM remains stronger overall than this two-input transfer pilot. The new model uses fewer inputs and a smaller hidden size, so that comparison does not isolate transfer. The matched scratch model is the relevant control. The donor-only model performs poorly without Marala adaptation. No conceptual model was evaluated.

These are stand-in-weather results using future realized weather plus noise. Archived TIGGE/GFS forecasts were not available. Monsoon transfer is weak, the record and donor set are limited, and prediction intervals are not guaranteed to be calibrated. No operational accuracy or robust transfer advantage is established.

## Data and artifacts verified

Original CAMELS files match their saved SHA256 hashes. Original Marala file SHA256 is unchanged. Prepared Marala observed values and NaN positions exactly match the source table. Missing targets remain NaN, masked from loss and evaluation. All three checkpoints, config snapshots, normalization statistics, training histories and inherited year lists are saved under this model folder.

| package | version |
| --- | --- |
| torch | 2.15.0+cpu |
| numpy | 2.4.6 |
| pandas | 3.1.0 |
| scikit-learn | 1.9.1 |

[Full evaluation](reports/initial/evaluation_report.md) | [Instructions](README.md) | [Stage manifest](runs/stages.json)

