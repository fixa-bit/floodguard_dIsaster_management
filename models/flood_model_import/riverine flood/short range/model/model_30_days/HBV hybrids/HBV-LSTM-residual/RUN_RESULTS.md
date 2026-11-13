# HBV plus LSTM residual correction results (30-day horizon)

| Model | Day-30 NSE | KGE | RMSE (m3/s) | MAE (m3/s) | PBIAS |
|---|---:|---:|---:|---:|---:|
| HBV plus LSTM residual | 0.760 | 0.778 | 386.267 | 239.728 | 16.475% |
| Calibrated physical HBV | 0.730 | 0.821 | 409.456 | 263.793 | -0.811% |
| Climatology | 0.792 | 0.845 | 359.398 | 231.857 | 8.837% |
| Climatology-residual LSTM ensemble | 0.858 | 0.874 | 297.556 | 191.690 | 4.150% |

The observed test contains 1,055 day-30 targets from 2022-2024. At training Q95 = 2494.714 m3/s, the 51 flood days have RMSE 559.027 m3/s. Flood recall is 0.745 (38/51 detected) and precision is 0.432. Non-flood RMSE is 375.375 m3/s. The residual model catches more floods than the physical model, with more false alerts; overall NSE remains below climatology.

Training used 1,797 issue sequences from 2016-2020, with early stopping on 336 issue sequences from 2021. The best checkpoint was epoch 18 of 28 run epochs (configured cap 65), seed 42. Test scoring used 1,067 issue sequences and 1,055 observed lead-30 targets. The physical HBV parameters were fixed from the separately calibrated training-only model. LSTM feature and target scaling were fit on training sequences only.

The source discharge table was copied byte-identically and missing targets remained excluded. Future weather uses reanalysis as a stand-in for an issued 30-day forecast; operational skill is unverified. See [detailed scores](reports/initial/evaluation_report.md) and the [shared comparison PDF](../../../../evaluation%20comparison/model_30_days/flood_nonflood_classification_metrics.pdf).
