# Marala short-range models by saved forecast horizon

Models are grouped by the maximum forecast lead in their saved run. A 15-day model includes leads 1-15, including the first ten days.

- [10-day models](model_10%20days/README.md): 19 model/run folders.
- [15-day models](model_15%20days/README.md): 5 model/run folders.
- [30-day experiments](model_30_days/README.md): one model at a time, followed by user feedback.
- [Multi-horizon CRE POC](multi_horizon_CRE/README.md): shared-versus-lead-specific validation for daily leads 7–30; seasonal 1–6-month work is readiness-only because observed target coverage is insufficient.
- [Evaluation comparisons](../evaluation%20comparison/README.md).

There are no combined 10/15-day trained variants. Donor/reference checkpoints remain with the model that uses them. The rejected GRRR-filled run has no retained checkpoint.
