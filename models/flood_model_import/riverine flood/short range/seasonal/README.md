# Seasonal forecasting workspace

Each seasonal approach gets its own subfolder with its code, configuration, training outputs, evaluation, and README.

## Current experiment

- [`Observed_residual_Ridge`](Observed_residual_Ridge/README.md): observed-only 90- and 180-day residual model. Validation selects regularization; 2024 observed data is held out for final scoring.
- [`GloFAS_pretrained_finetuned`](GloFAS_pretrained_finetuned/README.md): simulated GloFAS pretraining followed by observed WAPDA fine-tuning; retained as a comparison because it did not beat climatology.

## Held-out comparison

Scores use the same WAPDA 2024 test origins and observed-data climatology.

| Horizon | Model | RMSE (m³/s) | Climatology RMSE | Skill vs climatology |
|---:|---|---:|---:|---:|
| 90 days | Observed residual Ridge | 90.2 | 110.8 | +18.6% |
| 90 days | GloFAS-pretrained MLP | 410.6 | 110.8 | −270.7% |
| 180 days | Observed residual Ridge | 70.1 | 77.8 | +9.8% |
| 180 days | GloFAS-pretrained MLP | 212.6 | 77.8 | −173.4% |

The Ridge model is the current candidate. The test has only 9 and 7 overlapping monthly origins from one year, so its apparent improvement needs confirmation on more held-out observed years.

Across the 2020–2024 rolling-origin check, Ridge reduces pooled RMSE by 6.9% at 90 days and 8.1% at 180 days; it is worse than climatology in some individual years. See [`ROLLING_OOF.md`](Observed_residual_Ridge/reports/ROLLING_OOF.md).

The GloFAS and observed discharge series remain separate. No discharge values are filled or changed. See each model's README for limits and results.
