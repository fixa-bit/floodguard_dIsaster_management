# Marala Monthly River Flow

## Model

| Item | Value |
|---|---|
| Station | Marala, Chenab |
| Target | Monthly mean discharge near Marala |
| Units | m3/s (cumecs) |
| Horizon | 1-4 complete calendar months |
| Training data | 264 monthly records, 2000-2021 |
| Model | Ridge and XGBoost corrections to seasonal climatology, selected per horizon against baselines |
| Status | Research hindcast; not a calibrated station forecast |

The target is GloFAS modeled discharge at the nearest Chenab grid cell, not a measured Marala headworks value. The historical archive ends in 2021.

## Inputs

All features use the latest complete input month and earlier data. Numeric values are float32.

| Feature | Type / unit | Source |
|---|---|---|
| `flow_anomaly_current_cumecs` | float / m3/s | Current month GloFAS flow minus training monthly mean |
| `flow_anomaly_previous_month_cumecs` | float / m3/s | Previous month GloFAS flow minus its calendar-month mean |
| `flow_anomaly_previous_year_cumecs` | float / m3/s | Same month last year GloFAS flow minus calendar-month mean |
| `flow_change_1m_cumecs` | float / m3/s | Current month minus previous month flow |
| `rainfall_previous_1m_mm` | float / mm | ERA5 monthly precipitation, three upstream points averaged |
| `rainfall_previous_3m_mm` | float / mm | ERA5 precipitation total over the last three complete months |
| `snowfall_previous_1m_cm` | float / cm | ERA5 snowfall total for the latest complete month |
| `temperature_anomaly_c` | float / deg C | Current month ERA5 mean temperature minus its calendar-month mean |

ERA5 is retrospective reanalysis. Rainfall uses ERA5 because ERA5-Land does not provide precipitation.

## Output

| Field | Type | Meaning |
|---|---|---|
| `station_id`, `river` | string | `MARALA`, `Chenab` |
| `issued_at` | ISO datetime | End of the input month, UTC |
| `generated_at` | ISO datetime | Time the local hindcast was generated |
| `target_month` | YYYY-MM | Forecast calendar month |
| `horizon_months` | integer | Lead, 1-4 months |
| `predicted_monthly_mean_discharge_cumecs` | float / m3/s | Monthly mean modeled reach flow |
| `model_type` | string | Ridge/XGBoost adjustment, climatology, persistence, or seasonal naive |
| `research_only`, `current_forecast` | boolean | Whether output is a research hindcast or current forecast |

The current GloFAS forecast is saved separately at `app/ml/marala_pilot/artifacts/seasonal/current_provider_outlook.json`. It is a provider forecast, not a prediction from the trained local model.

| Provider field | Type | Meaning |
|---|---|---|
| `retrieved_at` | ISO datetime | Time the forecast was fetched |
| `forecast_issue_start`, `forecast_available_through` | date | Provider response time range |
| `target_month` | YYYY-MM | Complete forecast month |
| `monthly_mean_discharge_cumecs.mean` | float / m3/s | GloFAS mean monthly daily flow |
| `median`, `p25`, `p75` | float / m3/s | Monthly averages of daily ensemble statistics; not calibrated monthly intervals |

## Data and artifacts

- Monthly training table: `app/ml/marala_pilot/data/seasonal_monthly.csv`
- Sources, grid coordinates, and response hashes: `app/ml/marala_pilot/data/seasonal-sources.json`
- Holdout metrics and selected models: `app/ml/marala_pilot/artifacts/seasonal/model-card.json`
- Selected XGBoost lead models: `app/ml/marala_pilot/artifacts/seasonal/lead-*.xgb.json` (only for leads where XGBoost wins validation)
- Historical example: `app/ml/marala_pilot/artifacts/seasonal/example_outlook.json`
- Measured FFD daily observations: `app/ml/marala_pilot/data/observations.csv` (separate; too short and sparse for monthly gauge targets)
- Dashboard: Predictive Risk Views → Near-Term Screening → Riverine Short-Term → Monthly Marala. It reads the saved dataset and artifacts; it does not train or configure the model.
- Read-only API: `GET /api/v1/predictive/marala-monthly`; CSV download: `GET /api/v1/predictive/marala-monthly/dataset.csv`
- If the backend route is unavailable, the dashboard uses the packaged copy in `frontend/public/data`; regenerate it with `python scripts/export_marala_dashboard_assets.py` after refreshing data or retraining.

Train from the saved data with `python -m app.ml.marala_pilot.seasonal`. Refresh historical data with `--collect`; fetch a separate current provider outlook with `--current-forecast`.

## Sources

- [Open-Meteo Flood API / GloFAS](https://open-meteo.com/en/docs/flood-api): daily modeled discharge and seasonal forecast.
- [Open-Meteo Historical Weather API / ERA5](https://open-meteo.com/en/docs/historical-weather-api): precipitation, temperature, and snowfall.
- [FFD flood limits](https://ffd.pmd.gov.pk/flood-limits): gauge flow class thresholds for a future gauge-calibrated extension.
- Open-Meteo API: CC BY 4.0. GloFAS: Copernicus Emergency Management Service. ERA5: Copernicus Climate Change Service.
