# Encoder-decoder LSTM: 30-day models

Status: **trained and evaluated; awaiting user feedback**.

[Fine-tuned 15-to-30-day encoder-decoder ensemble](finetuned_15_to_30/README.md): extends the saved CAMELS-US/Marala model to 30 leads, with its own data, parent reference, code, checkpoints and measured results.

Day-30 NSE is **0.849**, compared with climatology **0.792** and the previous best ensemble **0.858**. High-flow RMSE is lower than the previous best, but the false-alarm ratio is higher. This run uses noisy reanalysis weather; operational forecasting skill is unverified. Later model families remain pending feedback.
