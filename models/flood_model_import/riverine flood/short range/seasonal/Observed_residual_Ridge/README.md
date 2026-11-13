# Observed-only residual Ridge seasonal model

This is the improved local candidate. It predicts 90-day and 180-day mean discharge as a correction to a month-of-issue climatology. Predictors use Marala flow and weather/snow data available up to the forecast issue date. No future weather is used, and no discharge value is filled.

## Data split

- Training: WAPDA observed Marala, 2016–2021.
- Validation: WAPDA observed Marala, 2022–2023; selects Ridge regularization.
- Final fit: WAPDA observed Marala, 2016–2023.
- Test: WAPDA observed Marala, 2024 only.
- GloFAS simulated discharge is excluded from training targets. Its separate experiment is in `../GloFAS_pretrained_finetuned/`.

## Run

```powershell
& '..\..\experiments\marala_observed\.venv\Scripts\python.exe' '.\train_evaluate.py'
```

Scores, test predictions, provenance and plot are in `reports/`. The fitted horizon models are in `runs/`. Paths, horizons, year split and model candidates are in `config.yaml`.

## Results

The rolling-origin check tests 2020–2024 one year at a time. Each fold chooses its regularization from the two preceding validation years, trains on earlier observed years, and tests on the held-out year.

| Horizon | Held-out origins | Model RMSE (m³/s) | Climatology RMSE | Skill vs climatology | Pooled NSE |
|---:|---:|---:|---:|---:|---:|
| 90 days | 57 | 120.9 | 129.9 | +6.9% | 0.958 |
| 180 days | 55 | 85.0 | 92.5 | +8.1% | 0.954 |

It does not win in every year: the 90-day result was slightly worse than climatology in 2020 and 2023; the 180-day result was worse in 2023. The 2024-only test was better, but it has just 9 and 7 overlapping monthly origins. Treat this as an improved candidate, not proven seasonal forecast skill.

The flood-hit metric uses a threshold on future seasonal mean flow. It does not measure detection or timing of individual flood events.

## Limits

The observed record is short and monthly target windows overlap. Results are exploratory. Archived seasonal weather forecasts are still needed for operational forecasting; historical reanalysis is not a forecast.
