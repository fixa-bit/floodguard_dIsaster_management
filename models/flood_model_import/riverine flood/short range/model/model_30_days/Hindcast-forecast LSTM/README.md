# Hindcast-forecast LSTM, including pretrained variants: 30-day models

Status: **three variants trained and evaluated; awaiting user feedback**.

[First variant: weather-only LSTM trained from scratch](scratch/README.md). Pretrained variants will be separate experiments after feedback.

[Past-discharge variant](past_discharge/README.md): adds observed flow through the issue day and a missing indicator, with the other settings matched. Day-30 NSE changed from 0.784 to 0.788; the gain is small and shorter-lead scores did not consistently improve. See its matched comparison for the full results. All other model families remain pending feedback.

[Climatology-residual ensemble](climatology_residual_ensemble/README.md): a separate mean-flow objective and three sequential seeds. Day-30 benchmark NSE is 0.858, above exact climatology (0.792) and smoothed climatology (0.820). All choices were fixed on training/validation data before evaluation. High-flow hit rate remains limited at 33%, and weather is still a reanalysis proxy.
