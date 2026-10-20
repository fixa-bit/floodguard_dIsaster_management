# Marala measured-gauge forecasting experiment

Target: future **06:00 PKT instantaneous inflow**, not a daily mean or a GloFAS grid value.

Data: 322 unique FFD readings (2024-07-18 to 2026-10-15).

2024 trains candidates; 2025 selects them. Frozen candidates are refit on 2024+2025 before the untouched 2026 evaluation. No random split or future weather is used.

| Lead | Validation-selected candidate | 2026 rows | RMSE | Persistence RMSE | Improvement | MAE | Flood recall |
|---|---|---:|---:|---:|---:|---:|---:|
| 1 days | ridge_log_return_100.0 | 117 | 423.98 | 423.82 | -0.0% | 222.26 | 80.0% |
| 3 days | training_median | 115 | 834.25 | 584.99 | -42.6% | 645.86 | 0.0% |
| 7 days | ridge_log_return_1000.0 | 111 | 871.11 | 962.67 | 9.5% | 502.18 | 0.0% |

All discharge errors are in m³/s. Positive improvement means lower RMSE than persistence. A high score in one season does not establish general flood-warning skill.

The best learned ridge/XGBoost candidate is also saved separately from the overall champion; a simple baseline is retained when it wins validation. See model-card.json and validation_leaderboard.csv for the complete comparisons.

Flood recall uses the [FFD Marala low-flood threshold](https://ffd.pmd.gov.pk/flood-limits) of 100,000 cusecs; it is discharge-threshold screening, not a flood probability.

The final inference artifacts refit the frozen candidates on all three seasons after evaluation. The 2026 CSV evaluates the separate pre-2026 fit, not that final refit.

## Limits

- Only 322 measured days across three short, incomplete flood seasons at training time; no year-round coverage.
- No observed upstream Akhnur flow, rainfall forecasts, snowmelt, reservoir releases, or subdaily gauge series.
- One extreme 2025 flood is in validation; a single held-out 2026 season does not establish rare-event skill.
- 06:00 is the measurement time, not guaranteed publication time; bulletin latency reduces operational lead time.
- Missing gauge dates are never interpolated; older optional feature gaps use training-only imputation for ridge.
- Outputs are discharge estimates, not calibrated flood probabilities, inundation, or damage estimates.
- 1-, 3-, 7-day direct targets do not justify recursive seven-month instantaneous predictions.
- The existing dashboard GloFAS feed has not been replaced.

## Artifacts

- `models/<lead>d/champion/`: final inference models.
- `models/<lead>d/best_learned/`: best validation-selected learned model.
- `evaluation_models/`: fits that generated the held-out 2026 predictions.
- `holdout_predictions_2026.csv`: actual, champion, learned, persistence and trend values with source links.
- `latest_predictions.json`: as-of forecasts from the latest available measured input; target timestamps are explicit.
