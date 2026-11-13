# HBV plus LightGBM residual correction: run results

| Item | Result |
|---|---:|
| Forecast horizon | 30 days |
| Training years | 2016–2020 |
| Validation year | 2021 |
| Test years | 2022–2024 |
| Training / validation / test issue sequences | 1,797 / 336 / 1,067 |
| Day-30 observed targets | 1,055 |
| Flood threshold | 2,494.714 m³/s (training-period Q95) |
| Day-30 LightGBM hybrid NSE / KGE | 0.780 / 0.874 |
| Day-30 LightGBM hybrid RMSE / MAE | 369.35 / 238.60 m³/s |
| Day-30 physical HBV NSE / RMSE | 0.730 / 409.46 m³/s |
| Day-30 HBV-LSTM residual NSE / RMSE | 0.760 / 386.27 m³/s |

## Day-30 flood and non-flood results

| Actual class | Days | Precision | Recall | F1 | RMSE (m³/s) | MAE (m³/s) |
|---|---:|---:|---:|---:|---:|---:|
| Flood | 51 | 0.435 | 0.529 | 0.478 | 754.04 | 578.38 |
| Non-flood | 1,004 | 0.976 | 0.965 | 0.970 | 338.33 | 221.34 |

Scores use observed test targets only, aligned with the other models. LightGBM improves day-30 overall flow error and NSE relative to the physical HBV base, but its flood recall (0.529) is below the HBV-LSTM residual model's 0.745. Test weather is reanalysis used as a forecast proxy, so results are retrospective and do not establish operational 30-day forecast skill. Observed discharge was not filled or modified.

The complete shared comparison is in `../../../../evaluation comparison/model_30_days/flood_nonflood_classification_metrics.md` and the matching PDF.
