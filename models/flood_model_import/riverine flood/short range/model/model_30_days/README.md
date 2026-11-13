# 30-day flood forecasting experiments

One model variant is trained and evaluated at a time. Three hindcast-forecast variants, the fine-tuned 30-day encoder-decoder ensemble, delta-HBV, calibrated physical HBV, both HBV residual corrections, the spatial elevation-band LSTM, N-HiTS and N-BEATSx are complete.

| Order | Model family | Status |
|---:|---|---|
| 1 | [Hindcast-forecast LSTM, including pretrained variants](Hindcast-forecast%20LSTM/README.md) | trained and evaluated; awaiting user feedback |
| 2 | [Encoder-decoder LSTM](Encoder-decoder%20LSTM/README.md) | trained and evaluated; awaiting user feedback |
| 3 | [delta-HBV, physical HBV and HBV residual hybrids](HBV%20hybrids/README.md) | delta-HBV, calibrated physical HBV and both HBV residual variants trained and evaluated; awaiting feedback |
| 4 | [Spatial elevation-band LSTM](Spatial%20elevation-band%20LSTM/README.md) | trained and evaluated; elevation-band model and matched catchment-mean control complete |
| 5 | [N-HiTS](N-HiTS/README.md) | trained and evaluated; awaiting feedback |
| 6 | [N-BEATSx](N-BEATSx/README.md) | trained and evaluated; awaiting user feedback |

The first experiment uses a reanalysis weather proxy because no archived 30-day weather forecasts were found. It cannot establish operational 30-day flood forecast accuracy.

## Day-30 observed test comparison

| Model | Actual class | n | Accuracy | Precision | Recall | F1 | RMSE (m3/s) |
|---|---|---:|---:|---:|---:|---:|---:|
| [Weather-only LSTM](Hindcast-forecast%20LSTM/scratch/README.md) | Flood | 51 | 0.947 | 0.451 | 0.451 | 0.451 | 931.4 |
| [Weather-only LSTM](Hindcast-forecast%20LSTM/scratch/README.md) | Non-flood | 1004 | 0.947 | 0.972 | 0.972 | 0.972 | 311.0 |
| [Past-discharge LSTM](Hindcast-forecast%20LSTM/past_discharge/README.md) | Flood | 51 | 0.951 | 0.490 | 0.471 | 0.480 | 903.8 |
| [Past-discharge LSTM](Hindcast-forecast%20LSTM/past_discharge/README.md) | Non-flood | 1004 | 0.951 | 0.973 | 0.975 | 0.974 | 311.2 |
| [Climatology-residual ensemble](Hindcast-forecast%20LSTM/climatology_residual_ensemble/README.md) | Flood | 51 | 0.955 | 0.548 | 0.333 | 0.415 | 826.1 |
| [Climatology-residual ensemble](Hindcast-forecast%20LSTM/climatology_residual_ensemble/README.md) | Non-flood | 1004 | 0.955 | 0.967 | 0.986 | 0.976 | 241.6 |
| [Fine-tuned encoder-decoder](Encoder-decoder%20LSTM/finetuned_15_to_30/README.md) | Flood | 51 | 0.939 | 0.382 | 0.412 | 0.396 | 801.6 |
| [Fine-tuned encoder-decoder](Encoder-decoder%20LSTM/finetuned_15_to_30/README.md) | Non-flood | 1004 | 0.939 | 0.970 | 0.966 | 0.968 | 256.9 |
| [delta-HBV](HBV%20hybrids/delta-HBV/README.md) | Flood | 51 | 0.955 | 0.543 | 0.490 | 0.515 | 1155.8 |
| [delta-HBV](HBV%20hybrids/delta-HBV/README.md) | Non-flood | 1004 | 0.955 | 0.974 | 0.979 | 0.977 | 424.5 |
| [Calibrated physical HBV](HBV%20hybrids/calibrated-physical-HBV/README.md) | Flood | 51 | 0.951 | 0.485 | 0.314 | 0.381 | 943.4 |
| [Calibrated physical HBV](HBV%20hybrids/calibrated-physical-HBV/README.md) | Non-flood | 1004 | 0.951 | 0.966 | 0.983 | 0.974 | 361.9 |
| [HBV-LSTM residual](HBV%20hybrids/HBV-LSTM-residual/README.md) | Flood | 51 | 0.940 | 0.432 | 0.745 | 0.547 | 559.0 |
| [HBV-LSTM residual](HBV%20hybrids/HBV-LSTM-residual/README.md) | Non-flood | 1004 | 0.940 | 0.987 | 0.950 | 0.968 | 375.4 |
| [HBV-LightGBM residual](HBV%20hybrids/HBV-LightGBM-residual/README.md) | Flood | 51 | 0.944 | 0.435 | 0.529 | 0.478 | 754.0 |
| [HBV-LightGBM residual](HBV%20hybrids/HBV-LightGBM-residual/README.md) | Non-flood | 1004 | 0.944 | 0.976 | 0.965 | 0.970 | 338.3 |
| [Spatial elevation-band LSTM](Spatial%20elevation-band%20LSTM/README.md) | Flood | 51 | 0.941 | 0.392 | 0.392 | 0.392 | 854.2 |
| [Spatial elevation-band LSTM](Spatial%20elevation-band%20LSTM/README.md) | Non-flood | 1004 | 0.941 | 0.969 | 0.969 | 0.969 | 304.9 |
| [Catchment-mean control](Spatial%20elevation-band%20LSTM/README.md) | Flood | 51 | 0.951 | 0.491 | 0.529 | 0.509 | 728.2 |
| [Catchment-mean control](Spatial%20elevation-band%20LSTM/README.md) | Non-flood | 1004 | 0.951 | 0.976 | 0.972 | 0.974 | 266.3 |
| [N-HiTS](N-HiTS/README.md) | Flood | 51 | 0.933 | 0.250 | 0.196 | 0.220 | 1292.7 |
| [N-HiTS](N-HiTS/README.md) | Non-flood | 1004 | 0.933 | 0.960 | 0.970 | 0.965 | 354.3 |
| [N-BEATSx](N-BEATSx/README.md) | Flood | 51 | 0.914 | 0.267 | 0.451 | 0.336 | 1163.9 |
| [N-BEATSx](N-BEATSx/README.md) | Non-flood | 1004 | 0.914 | 0.971 | 0.937 | 0.954 | 464.4 |

Flood is defined as observed flow at or above the training-period Q95 threshold (2494.714 m3/s). Accuracy is overall across both classes; precision, recall and F1 are class-specific. The comparison uses 1055 matched observed day-30 targets from 2022-2024 (51 flood days). High overall accuracy is affected by the smaller flood class; flood recall is more informative for missed floods. Inputs are reanalysis proxies, so these are retrospective scores rather than operational forecast skill.

Reusable comparison procedure: [evaluation skill](../../evaluation%20comparison/evaluation_skill/SKILL.md). Results: [PDF comparison](../../evaluation%20comparison/model_30_days/flood_nonflood_classification_metrics.pdf) and [Markdown table](../../evaluation%20comparison/model_30_days/flood_nonflood_classification_metrics.md).
