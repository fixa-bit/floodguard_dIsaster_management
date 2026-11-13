# Calibrated physical HBV results (30-day horizon)

| Model | Day-30 NSE | KGE | RMSE (m3/s) | MAE (m3/s) | PBIAS |
|---|---:|---:|---:|---:|---:|
| Calibrated physical HBV | 0.730 | 0.821 | 409.456 | 263.793 | -0.811% |
| delta-HBV | 0.620 | 0.814 | 485.844 | 302.985 | -0.757% |
| Climatology | 0.792 | 0.845 | 359.398 | 231.857 | 8.837% |
| Climatology-residual LSTM ensemble | 0.858 | 0.874 | 297.556 | 191.690 | 4.150% |

Scores use the same 1,055 observed lead-30 targets in 2022-2024. At training Q95 = 2494.714 m3/s, the 51 flood days have RMSE 943.385 m3/s, precision 0.485, and recall 0.314 (16/51 detected). The 1,004 non-flood days have RMSE 361.887 m3/s.

Parameters were calibrated against 1,767 observed days from 2016-2020 after a 730-day physical spin-up. Differential evolution completed its configured 120 generations and 13,552 parameter evaluations but did not meet its convergence condition. Validation year 2021 was not used for calibration. Test data were not used to choose parameters.

The 2014-2024 daily table is byte-identical to the project source, and evaluation includes only observed targets. Future weather uses reanalysis as a forecast stand-in, so operational 30-day forecast skill is unverified. See the [detailed report](reports/initial/evaluation_report.md) and [cross-model comparison](../../../../evaluation%20comparison/model_30_days/calibrated_physical_hbv/comparison_report.md).
