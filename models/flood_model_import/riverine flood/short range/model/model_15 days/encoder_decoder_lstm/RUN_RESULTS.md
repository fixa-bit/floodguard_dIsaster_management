# Actual 15-day seq2seq LSTM training

Run date: 2026-10-30 (Asia/Karachi).

A 365-day encoder hands hidden/cell states to a 15-day decoder. Each forward pass returns all 15 leads and five ordered quantiles. Days 7-15 are summarized separately; no observed future discharge or teacher forcing is used.

The local donor-only checkpoint was pretrained on eight observed CAMELS-US basins during 1985-1994, selected on 1995-1996. This is a workspace-trained checkpoint, not an official global foundation model. Its 10 lead embeddings were retained; five new rows copy day 10 and learn during fine-tuning. Observed-discharge/missingness input columns start with zero weights, preserving transferred weather/calendar weights.

Public search also found Fine Flood Forecasts, but its released model predicts one day, not a 15-day encoder-decoder sequence. The compatible local donor checkpoint was used instead. See pretrained_search.json for sources and the selection rationale.

Marala train: 2016-2020; validation: 2021; test: 2022-2024. Whole-year chronological partitions contain every target date in each sample. No target filling is performed. Missing targets are masked. Normalization is recomputed on Marala training years; both alternatives use the same features, architecture, target dates, training period and early-stopping criterion. Learning rates differ for transfer and scratch.

| stage | epochs_run | best_epoch | validation_pinball | training_seconds |
| --- | --- | --- | --- | --- |
| finetuned | 60 | 50 | 0.069 | 165.750 |
| scratch | 49 | 37 | 0.065 | 102.841 |

Selected by validation pinball only: **scratch**. Test scores do not select deployment weights.

## Means of lead-specific scores, days 7-15

| model | KGE | NSE | MAE_cumecs | RMSE_cumecs | Brier_score |
| --- | --- | --- | --- | --- | --- |
| climatology | 0.849 | 0.788 | 232.829 | 360.320 | 0.055 |
| finetuned | 0.851 | 0.818 | 209.616 | 334.277 | 0.032 |
| persistence | 0.816 | 0.632 | 285.403 | 474.795 | 0.071 |
| scratch | 0.854 | 0.819 | 205.249 | 333.569 | 0.034 |

## Selected leads

| model | lead_day | n | NSE | KGE | MAE_cumecs |
| --- | --- | --- | --- | --- | --- |
| finetuned | 1 | 1082 | 0.849 | 0.912 | 182.766 |
| scratch | 1 | 1082 | 0.882 | 0.919 | 157.931 |
| persistence | 1 | 1082 | 0.870 | 0.935 | 134.406 |
| climatology | 1 | 1082 | 0.784 | 0.849 | 233.665 |
| finetuned | 7 | 1078 | 0.824 | 0.863 | 202.852 |
| scratch | 7 | 1078 | 0.827 | 0.859 | 198.782 |
| persistence | 7 | 1078 | 0.680 | 0.840 | 257.468 |
| climatology | 7 | 1078 | 0.783 | 0.848 | 234.475 |
| finetuned | 10 | 1075 | 0.821 | 0.854 | 209.355 |
| scratch | 10 | 1075 | 0.821 | 0.848 | 206.731 |
| persistence | 10 | 1075 | 0.652 | 0.826 | 273.370 |
| climatology | 10 | 1075 | 0.790 | 0.850 | 232.513 |
| finetuned | 15 | 1070 | 0.810 | 0.837 | 213.845 |
| scratch | 15 | 1070 | 0.810 | 0.845 | 211.509 |
| persistence | 15 | 1070 | 0.573 | 0.786 | 320.750 |
| climatology | 15 | 1070 | 0.791 | 0.848 | 231.945 |

Fine-tuning has higher NSE than scratch at 5/15 leads and higher KGE at 6/15. A single seed and these previously inspected test years do not establish a robust transfer advantage.

## Limits

Weather inputs are realized ERA5-Land plus reproducible artificial standardized noise, not archived issued forecasts or a genuine meteorological ensemble. These are stand-in-weather hindcasts and can overstate operational 7-15-day performance. Weather noise does not demonstrate authentic forecast uncertainty. Actual forecast-provider inputs need archived-forecast training and validation.

Discharge reading times are largely unconfirmed in the historical WAPDA series. Issue-time observed flow availability and UTC-day alignment require validation. No 2025-2026 accuracy is claimed because complete weather inputs stop in 2024. Q95 is training-derived, not an official flood category. Uncertainty tails outside P05/P95 are not modeled, and no coverage guarantee is made.

Donor forcings use NLDAS daily rainfall and the midpoint of Tmax/Tmin; Marala uses ERA5-Land rainfall and daily mean temperature. The source/target climates, basin scales and forcing definitions differ, so useful transfer must be measured rather than assumed.

## Saved outputs

- `pretrained/`: original/adapted checkpoint and exact transfer provenance.
- `data/`: isolated, observed-only training table and preservation checks.
- `runs/finetuned/seed_42/` and `runs/scratch/seed_42/`: best weights, optimizer, normalization, config, epochs and year history.
- `runs/selected_model.json`: validation-selected checkpoint for inference.
- `reports/initial/`: predictions, all 15 lead scores, monsoon scores, days 7-15 summary, quantile coverage, plots and verification.
