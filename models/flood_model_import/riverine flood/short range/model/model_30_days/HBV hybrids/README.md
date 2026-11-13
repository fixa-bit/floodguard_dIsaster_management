# delta-HBV, physical HBV and HBV residual hybrids: 30-day models

Status: **delta-HBV, calibrated physical HBV and both HBV residual corrections trained and evaluated; awaiting feedback**.

The [30-day delta-HBV run](delta-HBV/README.md), [calibrated physical HBV](calibrated-physical-HBV/README.md), [HBV-LSTM residual correction](HBV-LSTM-residual/README.md), and [HBV-LightGBM residual correction](HBV-LightGBM-residual/README.md) are complete. Day-30 NSE values are 0.620, 0.730, 0.760 and 0.780 on matched observed test targets. HBV-LSTM has flood-day recall 0.745 (precision 0.432); HBV-LightGBM has recall 0.529 (precision 0.435). Each has its own code, copied data, outputs and evaluation in its subfolder.

The shared flood/non-flood comparison is saved outside the model tree at [Markdown](../../../evaluation%20comparison/model_30_days/flood_nonflood_classification_metrics.md) and [PDF](../../../evaluation%20comparison/model_30_days/flood_nonflood_classification_metrics.pdf).
