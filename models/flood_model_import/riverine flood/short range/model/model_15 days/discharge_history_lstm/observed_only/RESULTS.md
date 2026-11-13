# Observed-only LSTM results

Single seeded run, checkpoint chosen on 2022 validation loss. Test targets are 2023-2026, scored only where observations exist. This is a discharge-history baseline with retrospective date alignment.

| Lead | Observed test pairs | LSTM RMSE (m3/s) | Persistence RMSE (m3/s) | LSTM NSE |
|---|---:|---:|---:|---:|
| 1 days | 917 | 749.5 | 913.2 | 0.589 |
| 3 days | 913 | 823.9 | 1106.5 | 0.521 |
| 7 days | 906 | 850.4 | 1013.2 | 0.505 |
| 15 days | 891 | 872.3 | 1217.9 | 0.485 |

Selected epoch: 13. Windows: {'train': 2087, 'validation': 351, 'test': 922}.

Scores are conditional on an observed latest input and at least 15 observations in the 30-day input window. Missing targets are skipped independently by lead. Forecasts from overlapping windows are correlated; these counts are forecast/target pairs, not independent floods.

IRSA daily means remain labeled separately. Breakdown below uses lead 1 only; it does not equate means and point readings.

| Target source | Pairs | LSTM RMSE (m3/s) | Persistence RMSE (m3/s) |
|---|---:|---:|---:|
| WAPDA | 719 | 254.6 | 261.6 |
| FFD/PMD | 198 | 1538.2 | 1901.0 |

No GloFAS alternative was trained because no local GloFAS data was found. No test-based tuning was performed. Improvements against persistence do not by themselves establish extreme-flood warning reliability, operational input availability, or superiority to a weather-driven model.
