# Model Records

The [HEC-RAS 2D tutorial replay record](models/hec_ras_2d/README.md) documents the installed portable engine, the official source and hashes, native result verification, and the demonstration's limits.
why it doesnt show time it did forecasting and station
## Riverine XGBoost Baseline

Purpose: forecast station-specific river discharge and map it to flood class for monitored Punjab barrages/headworks.

Initial outputs:

- Trimmu discharge after 24 h.
- Balloki discharge after 48 h.
- Flood class: Below Low, Low, Medium, High, Very High, Exceptionally High.

Training entry point:

```bash
python -m app.ml.riverine_baseline --rebuild
```

Default artifacts:

- Dataset: `app/ml/data/riverine_station_training.csv`
- Model: `app/ml/artifacts/riverine_xgboost_baseline.json`
- Model card: `app/ml/artifacts/riverine_xgboost_baseline.model-card.json`

Dataset parameters:

- One row represents one station timestamp and one forecast horizon.
- Supported baseline stations: `Trimmu`, `Balloki`.
- Supported baseline horizons: `24`, `48` hours.
- Current bootstrap dataset is synthetic until sufficient hourly station history, official FFD observations, reservoir release history, and NWP forecast archives are assembled.
- Numeric units use cumecs for discharge, millimeters for rainfall, percent for soil moisture, and hours for horizons.

Feature schema:

| Feature | Meaning |
| --- | --- |
| `station_code` | Encoded target station (`Trimmu=1`, `Balloki=2`). |
| `forecast_horizon_hours` | Forecast lead time, currently 24 or 48. |
| `q_t_cumecs` | Current target-station discharge. |
| `q_t_minus_3h_cumecs` | Target-station discharge lagged 3 h. |
| `q_t_minus_6h_cumecs` | Target-station discharge lagged 6 h. |
| `q_t_minus_12h_cumecs` | Target-station discharge lagged 12 h. |
| `q_t_minus_24h_cumecs` | Target-station discharge lagged 24 h. |
| `rainfall_3h_mm` | Catchment rainfall over last 3 h. |
| `rainfall_6h_mm` | Catchment rainfall over last 6 h. |
| `rainfall_24h_mm` | Catchment rainfall over last 24 h. |
| `upstream_q_cumecs` | Upstream station/reach discharge. |
| `reservoir_release_cumecs` | Relevant upstream reservoir/canal release. |
| `soil_moisture_percent` | Catchment soil moisture signal. |
| `forecast_rainfall_mm` | Known future NWP rainfall for the forecast window. |

Model output format:

```json
{
  "station": "Trimmu",
  "forecast_horizon_hours": 24,
  "predicted_discharge_cumecs": 2450.25,
  "flood_class": "Medium",
  "model_name": "xgboost_riverine_baseline_v1",
  "model_type": "riverine_discharge_regression"
}
```

Implementation notes:

- The baseline uses XGBoost regression for discharge and applies station-specific flood thresholds after prediction.
- Thresholds in code are provisional development thresholds and must be replaced by official station thresholds before operational use.
- LightGBM can be compared later with the same feature table; XGBoost is used now because it is already part of the project dependency set.
- Temporal Fusion Transformer is the planned sequence model once data volume supports it. TFT should consume historical observations, known future rainfall forecasts, static catchment/station attributes, and multiple horizons, then be compared against this baseline.
- A future ensemble can average or stack XGBoost/LightGBM and TFT outputs, then apply calibrated flood-class probabilities.



"""

Q lags + rainfall + upstream/release + soil/forecast rain
→ XGBoost
→ Trimmu +24h discharge/class and Balloki +48h discharge/class
Also tightened the text to say:
- Horizon: 24-48h
- Scope: Trimmu and Balloki station forecasts
- Model: XGBoost baseline; TFT comparison later
Build check passed with npm run build. The only warning i

"""


why it doesnt show time it did forecasting and station
# Packaged satellite water-extent model

The SAR U-Net inference bundle lives in `app/ml/sar_unet/`, including trained
weights, architecture, and fitted normalization. The water-extent API uses this
bundle by default; deployment does not require the sibling NDMA_tasks project.
Training data and training runs remain in NDMA_tasks. See
[the bundle guide](app/ml/sar_unet/README.md) for inputs and model limitations.

