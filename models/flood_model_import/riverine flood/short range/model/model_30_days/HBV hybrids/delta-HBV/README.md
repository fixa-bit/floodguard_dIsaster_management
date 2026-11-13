# 30-day differentiable HBV (delta-HBV)

This is the next trained model in the 30-day queue. An LSTM learns some HBV parameters while the HBV equations turn rain, temperature and snowmelt-related inputs into routed streamflow. The model predicts 30 days from a 365-day history. It has no separate machine-learning head that can directly alter the physical discharge output.

## Training in plain language

The model learns from Marala observations dated 2016-2020. It checks each training run against 2021, keeps the checkpoint with the best validation loss, then evaluates that checkpoint on observed 2022-2024 targets. Missing discharge targets stay missing and are excluded from the loss and scores. Input averages and scales are calculated from training years only. One fixed setup and one seed are used; there is no hyperparameter search.

The future weather inputs are noisy ERA5-Land reanalysis values, not archived weather forecasts. The 30-day results therefore do not measure operational forecast skill.

## Run

From `riverine flood/short range/model/` using the existing `.venv`:

```powershell
$python = '../experiments/marala_observed/.venv/Scripts/python.exe'
& $python 'model_30_days/HBV hybrids/delta-HBV/prepare.py'
& $python 'model_30_days/HBV hybrids/delta-HBV/train.py' --config 'model_30_days/HBV hybrids/delta-HBV/config.yaml'
```

Training automatically evaluates the saved checkpoint. Model scores below come from observed test targets, not synthetic data.

## Measured results

| Model | Lead day | Observed targets | NSE | KGE | RMSE (m3/s) | MAE (m3/s) | PBIAS |
|---|---:|---:|---:|---:|---:|---:|---:|
| delta-HBV | 30 | 1055 | 0.620 | 0.814 | 485.844 | 302.985 | -0.757% |
| Climatology-residual LSTM ensemble | 30 | 1055 | 0.858 | 0.874 | 297.556 | 191.690 | 4.150% |
| Climatology | 30 | 1055 | 0.792 | 0.845 | 359.398 | 231.857 | 8.837% |

On the 51 flood-threshold days, delta-HBV RMSE is 1155.823 m3/s and recall is 0.490 (25 of 51 days detected); precision is 0.543. On 1004 other days, RMSE is 424.469 m3/s. This run does not beat either climatology or the best LSTM ensemble on overall day-30 NSE or flow error.

Training took 226.6 seconds on CPU: 80 epochs, seed 42, with the selected checkpoint at epoch 80. Validation loss was still improving at the epoch cap, so convergence is not established. There was no hyperparameter search.

Full matched comparison: [report](../../../../evaluation%20comparison/model_30_days/delta_hbv/comparison_report.md) · [flood/non-flood PDF](../../../../evaluation%20comparison/model_30_days/flood_nonflood_classification_metrics.pdf). Integrity checks: `reports/initial/verification.json`.

## Files

- `config.yaml`: 30-day horizon, chronological splits and training settings.
- `data/`: byte-identical copy of the observed daily table and preparation receipt.
- `runs/initial/seed_42/`: checkpoint, normalization and training history.
- `reports/initial/`: predictions and observed-only scores.
- `verify.py`: checks saved target values and score calculations against the original observations.
- `RUN_RESULTS.md`: measured results and limits.
- `_vendor/` and `source_reference/`: pinned upstream HBV equations and license.
