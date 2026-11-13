# Spatial elevation-band LSTM: 30-day evaluation

Observed discharge targets were retained as recorded; missing targets were excluded from loss and scoring. Future reanalysis with lead-dependent noise is a stand-in, not archived forecast data.

Test years: 2022–2024. Flood threshold: 2494.714 m³/s (training Q95). Observed target pairs: 31932.

## Lead 30 overall

| model                 |   lead_day |    n |   NSE |   KGE |   PBIAS_pct |   RMSE_cumecs |   MAE_cumecs |   flood_precision |   flood_recall |   flood_days |
|:----------------------|-----------:|-----:|------:|------:|------------:|--------------:|-------------:|------------------:|---------------:|-------------:|
| Spatial_ElevationBand |         30 | 1055 | 0.801 | 0.874 |       8.214 |       351.791 |      220.357 |             0.392 |          0.392 |           51 |
| CatchmentMean_Control |         30 | 1055 | 0.850 | 0.919 |       2.893 |       305.147 |      188.889 |             0.491 |          0.529 |           51 |

## Lead 30 by season

| model                 |   lead_day | season   |   n |   NSE |   KGE |   PBIAS_pct |   RMSE_cumecs |   MAE_cumecs |   flood_precision |   flood_recall |   flood_days |
|:----------------------|-----------:|:---------|----:|------:|------:|------------:|--------------:|-------------:|------------------:|---------------:|-------------:|
| Spatial_ElevationBand |         30 | Apr-Jun  | 273 | 0.306 | 0.649 |      14.705 |       385.899 |      292.216 |             1.000 |          0.333 |            3 |
| Spatial_ElevationBand |         30 | Jul-Sep  | 276 | 0.468 | 0.612 |       8.604 |       528.378 |      399.795 |             0.380 |          0.404 |           47 |
| Spatial_ElevationBand |         30 | Oct-Mar  | 506 | 0.178 | 0.551 |      -3.055 |       159.389 |       83.711 |             0.000 |          0.000 |            1 |
| CatchmentMean_Control |         30 | Apr-Jun  | 273 | 0.541 | 0.725 |       2.358 |       313.902 |      229.619 |             1.000 |          0.333 |            3 |
| CatchmentMean_Control |         30 | Jul-Sep  | 276 | 0.572 | 0.731 |       6.218 |       473.925 |      362.404 |             0.481 |          0.553 |           47 |
| CatchmentMean_Control |         30 | Oct-Mar  | 506 | 0.403 | 0.561 |      -7.507 |       135.899 |       72.269 |             0.000 |          0.000 |            1 |

## Quantile coverage

|   lead_day |        n |   coverage_90 |
|-----------:|---------:|--------------:|
|     30.000 | 1055.000 |         0.860 |

## Architecture and inputs

Each of four elevation bands has its own 365-day encoder and 30-day decoder. Area-weighted decoder features feed a shared monotonic quantile head. Rain, temperature, SWE and snowmelt are inputs to the history encoders; per-band rain and temperature reanalysis with lead-growing noise are decoder inputs. A same-source catchment-mean LSTM was trained as the spatial ablation control.

Weather bands cover 2015–2024. Training uses 2016–2020, validation 2021, and held-out test targets 2022–2024. The 2022–2024 period was inspected in prior workspace experiments and is not an untouched project-wide holdout.

NSE is not a percentage accuracy. These retrospective test scores do not establish operational forecast skill because realized reanalysis is used as a noisy future-weather proxy. Sparse flood observations also limit flood-case conclusions.
