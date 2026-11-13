# Eight-basin CAMELS-US donor-pretrained LSTM

Folder: `pretrained_multibasin_lstm/`

## Trained artifact

- `runs/initial/seed_42/best.pt`

## Files

- `config.yaml`
- `workflow.yaml`
- `train.py`
- `evaluate.py`
- `model.py`

## Own evaluation

- `reports/initial/scores_by_lead.csv`
- Lead 10 NSE: **-0.747** on the recorded observed test days. See the CSV for sample count and other leads.

## Context

[Cross-model comparisons](../../../evaluation%20comparison/README.md) | [Original detailed notes](../../../evaluation%20comparison/archive/original_readmes/pretrained_multibasin_lstm.md)

Saved evaluations use observed target days. Future reanalysis was used as a forecast stand-in in most LSTM experiments; these scores are not operational forecast accuracy.
