# Actual hybrid run

Working directory: parent `model` folder.

```powershell
$python = "../experiments/marala_observed/.venv/Scripts/python.exe"
& $python -m unittest discover -s tests -v
& $python -m unittest discover -s hybrid_physics_ml/tests -v
& $python -u hybrid_physics_ml/train.py --config hybrid_physics_ml/config.yaml
& $python -u hybrid_physics_ml/evaluate.py --config hybrid_physics_ml/config.yaml
```

## Measured accuracy on Marala

At lead 10, hybrid NSE is **0.816**, lower than the matched-input plain LSTM (**0.857**); NSE difference: -0.0416. This single-seed experiment does not establish general improvement in extreme floods.

Observed test years: **[2022, 2023, 2024]**. Unique observed test days across leads: **1084**; observed issue/lead/target pairs: **10795**. Individual missing targets were excluded.

**These results use realized future ERA5-Land weather plus noise. They are not operational TIGGE/GFS forecast accuracy. NSE is a skill score, not an accuracy percentage.**

| model | lead_day | n | NSE | KGE | PBIAS_pct | RMSE_cumecs |
| --- | --- | --- | --- | --- | --- | --- |
| Hybrid | 1 | 1084 | 0.823 | 0.832 | 10.276 | 329.437 |
| plain_LSTM | 1 | 1084 | 0.886 | 0.902 | -2.371 | 263.760 |
| persistence | 1 | 1084 | 0.870 | 0.935 | 0.000 | 282.358 |
| climatology | 1 | 1084 | 0.784 | 0.849 | 7.793 | 363.415 |
| gradient_boosting | 1 | 1084 | 0.875 | 0.916 | 2.670 | 276.755 |
| Ensemble | 1 | 1084 | 0.891 | 0.912 | -0.231 | 258.621 |
| Hybrid | 10 | 1075 | 0.816 | 0.851 | 11.003 | 335.983 |
| plain_LSTM | 10 | 1075 | 0.857 | 0.910 | 5.644 | 295.702 |
| persistence | 10 | 1075 | 0.652 | 0.826 | 0.364 | 461.403 |
| climatology | 10 | 1075 | 0.790 | 0.850 | 8.144 | 358.575 |
| gradient_boosting | 10 | 1075 | 0.851 | 0.877 | 0.541 | 302.424 |
| Ensemble | 10 | 1075 | 0.866 | 0.916 | 4.630 | 286.462 |

### Hybrid seasonal results at lead 10

| model | lead_day | season | n | NSE | KGE | PBIAS_pct | RMSE_cumecs | MAE_cumecs | peak_MAPE_pct | peak_n | flood_hit_rate | false_alarm_rate | false_alarm_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Hybrid | 10 | Apr-Jun | 273 | 0.534 | 0.733 | 15.466 | 316.333 | 241.274 | 8.947 | 3 | 1.000 | 0.000 | 0.000 |
| Hybrid | 10 | Jul-Sep | 276 | 0.447 | 0.648 | 13.137 | 538.820 | 437.292 | 15.713 | 47 | 0.617 | 0.179 | 0.586 |
| Hybrid | 10 | Oct-Mar | 526 | 0.201 | 0.513 | -2.091 | 162.576 | 87.205 | 83.703 | 1 | 0.000 | 0.000 | NA |

### Hybrid quantile calibration

| lead_day | n | nominal_coverage | actual_coverage |
| --- | --- | --- | --- |
| 1 | 1084 | 0.900 | 0.878 |
| 2 | 1083 | 0.900 | 0.850 |
| 3 | 1082 | 0.900 | 0.839 |
| 4 | 1081 | 0.900 | 0.826 |
| 5 | 1080 | 0.900 | 0.833 |
| 6 | 1079 | 0.900 | 0.814 |
| 7 | 1078 | 0.900 | 0.821 |
| 8 | 1077 | 0.900 | 0.815 |
| 9 | 1076 | 0.900 | 0.798 |
| 10 | 1075 | 0.900 | 0.786 |

High-flow errors and flood exceedances use a training-derived peak threshold of **2494.71 cumecs** and flood threshold of **2494.71 cumecs**. Defaults use training Q95, not official flood categories or return-period floods. Positive PBIAS means overprediction. False-alarm rate = false alerts/non-exceedance days; false-alarm ratio = false alerts/all alerts.

### Training and physics checks

| seed | epochs_run | selected_epoch | validation_pinball | training_seconds | train_samples | validation_samples |
| --- | --- | --- | --- | --- | --- | --- |
| 42 | 16 | 10 | 0.081 | 234.176 | 1767 | 356 |

| seed | maximum_water_balance_residual_mm | minimum_state_or_flux_mm | forecast_missing_pct | negative_noisy_precipitation_clipped_in_bucket |
| --- | --- | --- | --- | --- |
| 42 | 0.000 | 0.000 | 0.000 | 2191 |

Maximum measured daily bucket residual: **0.00035048 mm**, within the configured **0.002 mm** tolerance.

Water balance is checked inside the conceptual bucket, including its initial water stores. Final LSTM discharge is not constrained to this balance. Internal conservation is not proof of accurate or physically correct basin runoff. Negative precipitation caused by Gaussian forecast noise is clipped only inside the physical module, and is counted above; source values are unchanged.

All 15 shared and 5 hybrid synthetic correctness tests passed. They check implementation, not real accuracy. Observed targets and their NaN positions were not modified. The saved daily-file hash matches both training checkpoints.

[Full evaluation](../../evaluation%20comparison/hybrid_physics_ml/evaluation_report.md) | [Prediction CSV](reports/initial/predictions.csv) | [Training history](runs/initial/seed_42/history.json)
