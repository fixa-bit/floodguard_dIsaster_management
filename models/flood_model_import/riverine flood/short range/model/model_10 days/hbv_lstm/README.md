# HBV plus LSTM residual correction

Folder: `hbv_lstm/`

## Trained artifact

- `runs/2026-10-30/final/physical/calibration.json`
- `runs/2026-10-30/final/physical/water_balance_audit.json`
- `runs/2026-10-30/final/models/lstm/best.pt`

## Files

- `config.json`
- `train.py`

## Own evaluation

- `reports/2026-10-30/scores_by_lead.csv`
- Lead 10 nse: **0.604** on the recorded observed test days. See the CSV for sample count and other leads.

## Context

[Cross-model comparisons](../../../evaluation%20comparison/README.md) | [Original detailed notes](../../../evaluation%20comparison/archive/original_readmes/hbv_lstm.md)

Saved evaluations use observed target days. Future reanalysis was used as a forecast stand-in in most LSTM experiments; these scores are not operational forecast accuracy.
