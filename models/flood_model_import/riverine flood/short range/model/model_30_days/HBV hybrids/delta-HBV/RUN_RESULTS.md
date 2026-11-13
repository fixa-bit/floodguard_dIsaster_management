# 30-day delta-HBV run results

| Metric | delta-HBV | Climatology-residual ensemble | Climatology |
|---|---:|---:|---:|
| Day-30 NSE | 0.620 | 0.858 | 0.792 |
| Day-30 KGE | 0.814 | 0.874 | 0.845 |
| Day-30 RMSE (m3/s) | 485.844 | 297.556 | 359.398 |
| Day-30 MAE (m3/s) | 302.985 | 191.690 | 231.857 |

The matched test has 1,055 observed day-30 targets from 2022-2024. Flood threshold is training-period Q95 = 2494.714185 m3/s; 51 test days exceed it. On those days delta-HBV RMSE is 1155.823 m3/s, flood recall is 0.490 (25/51), and precision is 0.543. On the remaining 1,004 days RMSE is 424.469 m3/s.

Training used 2016-2020, validation selected the checkpoint on 2021, and testing used 2022-2024. Seed 42 ran 80 epochs in 226.6 seconds; epoch 80 was selected while validation loss was still improving, so convergence is not established. No hyperparameter search was run.

The local observed table is byte-identical to its source, and all 31,932 saved issue/lead targets match the original observed values. No discharge values were filled or modified. See `reports/initial/verification.json` and the [full comparison](../../../../evaluation%20comparison/model_30_days/delta_hbv/comparison_report.md).

Weather inputs are noisy realized reanalysis, not operational archived forecasts. The HBV source code is under the non-commercial license in `source_reference/LICENSE`.
