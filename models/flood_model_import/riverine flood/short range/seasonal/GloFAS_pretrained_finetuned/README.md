# Seasonal GloFAS-pretrained model

This experiment tests whether simulated GloFAS discharge can help a small model learn long-range patterns, then adapts it to observed Marala discharge.

## Data separation

- Pretraining targets: GloFAS simulated discharge, 1980–2015.
- Fine-tuning targets: WAPDA-observed Marala discharge, 2016–2023.
- Epoch selection: observed 2022–2023 validation origins.
- Final test: observed 2024 origins only.
- Forecast products: mean discharge over the next 90 and 180 days. Inputs are only prior discharge and antecedent weather/snow indicators.

The original source files are read only. Missing observations are left missing; no discharge values are interpolated or filled. GloFAS discharge is model output, not observed truth.

A small GloFAS seasonal-reforecast archive sample is stored under `data/raw/` with its source receipt. It was not used by this model: the attempted full 180-day request exceeded the EWDS request-size limit, and the downloaded sample only contains leads 1–30 days.

## Run

```powershell
& '..\..\experiments\marala_observed\.venv\Scripts\python.exe' '.\train_evaluate.py'
```

Results go to `reports/`; fitted models go to `runs/`. `config.yaml` contains the data paths, split years, forecast horizons and model settings.

## Latest held-out result

2024 observed test origins; monthly origins overlap, so these are not independent samples.

| Horizon | Origins | RMSE (m³/s) | NSE | RMSE skill vs observed climatology | Flood hit rate |
|---:|---:|---:|---:|---:|---:|
| 90 days | 9 | 410.6 | 0.366 | −2.707 | 0.333 |
| 180 days | 7 | 212.6 | 0.193 | −1.734 | 0.000 |

**Verdict:** this run does not beat the observed-data climatology at either horizon. The test set is only one observed year, so these scores are preliminary and not a reliable estimate of future skill.

## Limits

There are only a few independent observed seasonal origins in the 2024 test year. Treat the scores as exploratory, not proof of operational 1–6 month skill. Real long-range operation requires archived, issue-dated seasonal weather forecast hindcasts; historical reanalysis is not a future forecast. The GloFAS product is biased at Marala, so the model must beat an observed-data climatology on independent observed years before being considered useful.
