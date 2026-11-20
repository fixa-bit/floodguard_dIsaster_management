# Riverine outlook snapshot

Feeds the **Riverine Forecast** tab (`GET /api/v1/predictive/riverine-outlook/{station_id}`).

`build_marala_outlook.py` runs the trained flood_model riverine models forward from
the latest Marala data and writes `artifacts/marala_outlook.json`:

| Block | Model | What it gives |
|---|---|---|
| `seasonal` | Long-range TFT, forecast mode, fine-tuned 3-seed ensemble | 180 daily P10/P50/P90 values from the last day with complete ERA5-Land forcing, conformally calibrated; monthly means; the same issue one year earlier against what was measured |
| `seasonal_means` | Observed residual Ridge | Mean flow over the next 90 and 180 days vs the month-of-issue normal |
| `climate` | Projection-mode TFT + 8 CMIP6 GCMs, flood-peak model | 2026–2040 changes in flow and temperature, annual flood odds by FFD class, typical-year hydrograph |
| `evidence`, `peak_model` | Saved test reports | Held-out scores shown in the tab's evidence cards |
| `ten_day_research` | 10-day research models | Day-10 high-flow detection on identical 2022–2024 days |
| `replay` | All 24 trained short-range models (10-, 15- and 30-day; AI, physics-based, hybrid, statistical, baselines) | Each model's saved 2022–2024 test forecasts at leads 1–30 around the three largest high-flow events, and matched scores (high-flow days caught, false alarms, RMSE, NSE) per lead |

The normal range is the 10th–90th percentile of observed inflow (2016–2025) within
±15 days of each calendar day.

Model weights come from `../flood_model_import`. Input data and saved projection
outputs are read from the flood_model project **at build time only**; the app reads
only the JSON. Nothing is filled. The forward run reproduces the saved TFT test
predictions to within 0.06 m³/s.

## Rebuild

Run after new ERA5-Land forcing or observed flow is added to flood_model, or after
models are retrained and re-imported (`../flood_model_import/export_from_flood_model.py`):

```powershell
.venv\Scripts\python.exe models\riverine_outlook\build_marala_outlook.py
```

Uses the app's `.venv` (torch CPU, scikit-learn); takes under a minute. The tab flags
the outlook as stale when its issue date is more than 45 days old.

The 1/3/7-day gauge model and the 30-day GloFAS series are live and are not part of
this snapshot.

Other stations return `available: false` until their own models and snapshot exist;
add them to `SNAPSHOTS` in `app/services/riverine_outlook.py`.
