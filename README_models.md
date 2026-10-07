# Model Records

## Riverine XGBoost Baseline

Purpose: forecast station/reach-specific river discharge and map it to flood class for monitored barrages/headworks. This is the core short-term riverine model; it predicts at gauging points such as Trimmu and Balloki, not one flood value for all Pakistan.

Initial outputs:

- Trimmu discharge after 24 h.
- Balloki discharge after 48 h.
- Flood class: Below Low, Low, Medium, High, Very High, Exceptionally High.

Training entry point:

```bash
python -m app.ml.riverine_baseline --rebuild
```

Use `--rebuild` only for the current synthetic bootstrap dataset. Once an official historical hourly station table is available, place it at the dataset path below and train without `--rebuild`.

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
- Public FFD data supports observed river flows and flood limits, but the operational model needs a historical feature table with hourly lagged discharge, rainfall, reservoir releases, soil moisture, and forecast rainfall.

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
- Flood-class thresholds are station-specific FFD flood limits converted from lacs of cusecs to cumecs. Source: `https://ffd.pmd.gov.pk/flood-limits`.
- LightGBM can be compared later with the same feature table; XGBoost is used now because it is already part of the project dependency set.
- Temporal Fusion Transformer is the planned sequence model once data volume supports it. TFT should consume historical observations, known future rainfall forecasts, static catchment/station attributes, and multiple horizons, then be compared against this baseline.
- A future ensemble can average or stack XGBoost/LightGBM and TFT outputs, then apply calibrated flood-class probabilities.

Real dataset CSV schema:

```text
target_station,forecast_horizon_hours,q_t_cumecs,q_t_minus_3h_cumecs,q_t_minus_6h_cumecs,q_t_minus_12h_cumecs,q_t_minus_24h_cumecs,rainfall_3h_mm,rainfall_6h_mm,rainfall_24h_mm,upstream_q_cumecs,reservoir_release_cumecs,soil_moisture_percent,forecast_rainfall_mm,target_discharge_cumecs,target_flood_class
```

Recommended next data sources:

- FFD/WAPDA hourly observed discharge by station.
- PMD/FFD rainfall observations and NWP rainfall forecasts for each catchment.
- Reservoir inflow/outflow or release records from WAPDA/IRSA where available.
- Soil moisture from a gridded source such as ECMWF/ERA5-Land, NASA SMAP, or a local hydrology feed.

## Flash-Flood LightGBM Baseline

Purpose: forecast fast-onset flash-flood probability for hill torrents, streams, and urban catchments. This is separate from the riverine model because flash flooding is driven by short rainfall bursts, terrain, drainage, and catchment response rather than slow routing along major rivers.

Initial output:

- `P(flash flood within next 6h)`.
- Risk class: No risk, Low, Moderate, High, Extreme.

Training entry point:

```bash
python -m app.ml.flash_flood_baseline --rebuild
```

Use `--rebuild` only for the current synthetic bootstrap dataset. Once observed flash-flood event labels and GIS/rainfall history are available, place the real table at the dataset path below and train without `--rebuild`.

Default artifacts:

- Dataset: `app/ml/data/flash_flood_training.csv`
- Model: `app/ml/artifacts/flash_flood_lightgbm_baseline.txt`
- Model card: `app/ml/artifacts/flash_flood_lightgbm_baseline.model-card.json`

Dataset parameters:

- One row represents one catchment/location timestamp.
- Forecast horizon is fixed at the next `6` hours for the first baseline.
- Numeric units use millimeters for rainfall, percent for soil moisture, degrees for slope, meters for elevation, km/km2 for drainage density, km2 for catchment area, and kilometers for distance to stream.
- Current bootstrap dataset is synthetic until gauge/radar rainfall, event reports, hill-torrent/stream observations, and GIS catchment attributes are joined.

Feature schema:

| Feature | Meaning |
| --- | --- |
| `rainfall_15min_mm` | Rainfall in the last 15 minutes. |
| `rainfall_1h_mm` | Rainfall in the last 1 hour. |
| `rainfall_3h_mm` | Rainfall in the last 3 hours. |
| `rainfall_6h_mm` | Rainfall in the last 6 hours. |
| `forecast_rainfall_6h_mm` | Forecast rainfall over the next 6 hours. |
| `soil_moisture_percent` | Catchment wetness before/at forecast issue time. |
| `slope_degrees` | Representative catchment slope. |
| `elevation_m` | Representative catchment elevation. |
| `drainage_density_km_per_km2` | Stream-channel density in the catchment. |
| `land_cover_code` | Encoded land-cover class. |
| `catchment_area_km2` | Upstream/local catchment area. |
| `distance_to_stream_km` | Distance from forecast point to nearest stream/channel. |

Model output format:

```json
{
  "forecast_horizon_hours": 6,
  "flash_flood_probability": 0.62,
  "risk_class": "High",
  "model_name": "lightgbm_flash_flood_baseline_v1",
  "model_type": "flash_flood_probability_classifier"
}
```

Implementation notes:

- The baseline uses LightGBM because tabular rainfall plus GIS attributes are the primary feature shape.
- Deep learning is intentionally deferred; it is not required for the first tabular baseline.
- The probability is mapped to classes with fixed bands: No risk, Low, Moderate, High, Extreme.
- Real deployment needs event labels from verified flash-flood reports, stream/torrent observations, radar or sub-hourly gauge rainfall, and static catchment/GIS layers.

Real dataset CSV schema:

```text
rainfall_15min_mm,rainfall_1h_mm,rainfall_3h_mm,rainfall_6h_mm,forecast_rainfall_6h_mm,soil_moisture_percent,slope_degrees,elevation_m,drainage_density_km_per_km2,land_cover_code,catchment_area_km2,distance_to_stream_km,target_flash_flood_probability,target_flash_flood_next_6h,target_flash_flood_class
```

## Urban Flooding LightGBM/XGBoost Baseline

Purpose: forecast urban flood susceptibility by grid cell or ward for city dashboards such as Islamabad, Rawalpindi, and Lahore. This is separate from flash flooding because the urban problem is strongly controlled by drainage capacity, impervious surface, land use, DEM/slope, and prior waterlogging history.

Initial output:

- Susceptibility class per grid cell/ward: Low, Moderate, High, Extremely high.

Training entry point:

```bash
python -m app.ml.urban_flood_baseline --rebuild
```

Use `--rebuild` only for the current synthetic bootstrap dataset. Once city grid/ward observations and waterlogging reports are available, place the real table at the dataset path below and train without `--rebuild`.

Default artifacts:

- Dataset: `app/ml/data/urban_flood_training.csv`
- Model: `app/ml/artifacts/urban_flood_lightgbm_baseline.txt`
- Model card: `app/ml/artifacts/urban_flood_lightgbm_baseline.model-card.json`

Dataset parameters:

- One row represents one city grid cell or ward at one forecast issue time.
- Forecast horizon is fixed at the next `6` hours for the first baseline.
- Numeric units use millimeters for rainfall, meters for DEM elevation, degrees for slope, millimeters/hour for drainage capacity, percent for impervious surface, and report counts for previous waterlogging.
- Current bootstrap dataset is synthetic until rainfall, DEM/slope, drainage-network capacity, impervious-surface, land-use, and waterlogging-report history are joined.

Feature schema:

| Feature | Meaning |
| --- | --- |
| `rainfall_1h_mm` | Rainfall in the last 1 hour. |
| `rainfall_3h_mm` | Rainfall in the last 3 hours. |
| `rainfall_6h_mm` | Rainfall in the last 6 hours. |
| `forecast_rainfall_6h_mm` | Forecast rainfall over the next 6 hours. |
| `dem_elevation_m` | DEM elevation for the grid cell/ward. |
| `slope_degrees` | Local terrain slope. |
| `drainage_capacity_mm_per_h` | Estimated drainage capacity. |
| `impervious_surface_percent` | Share of sealed/impervious surface. |
| `land_use_code` | Encoded land-use class. |
| `previous_waterlogging_reports_30d` | Recent verified/report-based waterlogging count. |

Model output format:

```json
{
  "forecast_horizon_hours": 6,
  "susceptibility_class": "High",
  "class_probabilities": {
    "Low": 0.05,
    "Moderate": 0.18,
    "High": 0.61,
    "Extremely high": 0.16
  },
  "model_name": "lightgbm_urban_flood_susceptibility_v1",
  "model_type": "urban_flood_susceptibility_classifier"
}
```

Implementation notes:

- Use LightGBM or XGBoost for grid/ward susceptibility because the first model is tabular GIS plus rainfall.
- Do not use this ML susceptibility baseline as a water-depth simulator.
- For predicted water-depth bands such as `0-0.2 m`, `0.2-0.5 m`, `0.5-1 m`, and `>1 m`, use HEC-RAS 2D or another hydraulic model and feed it rainfall/hydrograph/boundary-condition inputs.
- The GIS dashboard can map the susceptibility class directly per grid cell/ward while keeping hydraulic depth as a separate future model layer.

Real dataset CSV schema:

```text
rainfall_1h_mm,rainfall_3h_mm,rainfall_6h_mm,forecast_rainfall_6h_mm,dem_elevation_m,slope_degrees,drainage_capacity_mm_per_h,impervious_surface_percent,land_use_code,previous_waterlogging_reports_30d,target_urban_flood_score,target_urban_flood_class_id,target_urban_flood_class
```
