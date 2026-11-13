# Spatial elevation-band LSTM: 30-day forecast

**Status:** trained and evaluated. The same-source catchment-mean control scored better than the elevation-band model at day 30 on this test period.

## How training works

The model gives each of four elevation bands its own LSTM encoder. Each encoder reads 365 days of band-specific rain, temperature, snow water equivalent and snowmelt. Four lead decoders read the next 30 days of band rain and temperature, using ERA5-Land reanalysis with noise that grows by lead day as a stand-in for weather forecasts. The band representations are combined using the area fractions and a shared quantile output layer.

Training uses observed Marala discharge from 2016–2020. Missing discharge targets stay missing and are masked out of loss. The 2021 validation year selects the checkpoint; 2022–2024 are used for the reported test scores. A second LSTM is trained on the area-averaged inputs with the same dates, noise setup and observed targets as a spatial control. Its hidden size is 64, compared with 32 per elevation band.

The available band weather covers 2015–2024. There are no archived 30-day weather forecasts in this run, so the results measure retrospective hindcasts with a reanalysis proxy, not operational forecast skill. The 2022–2024 test period has also been inspected in earlier project experiments.

## Day-30 results

| Model | Observed targets | NSE | KGE | RMSE (m³/s) | Flood precision | Flood recall |
|---|---:|---:|---:|---:|---:|---:|
| Elevation-band LSTM | 1,055 | 0.801 | 0.874 | 351.79 | 0.392 | 0.392 |
| Catchment-mean control | 1,055 | 0.850 | 0.919 | 305.15 | 0.491 | 0.529 |

On this split, retaining separate elevation bands did not improve on the catchment-mean control. These metrics do not establish that the same result will hold on other periods or basins.

| Run | Best validation epoch | Epochs run | Training time |
|---|---:|---:|---:|
| Elevation-band LSTM | 12 | 18 | 147 s |
| Catchment-mean control | 18 | 24 | 68 s |

Both runs used seed 42 and 2021 validation data for checkpoint selection.

## Run

From this folder, using the project Python environment:

```powershell
& '..\..\..\experiments\marala_observed\.venv\Scripts\python.exe' train.py
```

Training creates the spatial model and control checkpoints, then scores them on the test years. `evaluate.py` can be run independently to regenerate the saved predictions and scores.

## Files

- `config.yaml`, `prepare_data.py`, `train.py`, `evaluate.py`: 30-day settings and workflow.
- `data.py`, `model.py`, `spatial_data.py`, `lstm/`, `spatial_model.py`: data handling, training and network definitions.
- `data/spatial_daily.csv`: prepared daily inputs and original observed targets; no discharge was filled.
- `data/raw/era5land_elevation_bands_v2/`: the source band weather, metadata and download receipt.
- `runs/spatial/` and `runs/mean_control/`: best checkpoints, validation histories, normalization and year records.
- `reports/initial/`: forecasts, lead and seasonal scores, interval coverage and integrity checks.
- `RUN_RESULTS.md`: measured results.
- Shared comparison is outside the model folder: `../../../evaluation comparison/model_30_days/flood_nonflood_classification_metrics.md` and `.pdf`.
