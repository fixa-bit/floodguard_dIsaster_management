# Global Caravan-pretrained LSTM fine-tuned on Marala

Folder: `fine_tuned_global_pretrained_lstm/`

## Trained artifact

- `runs/finetuned/seed_42/best.pt`

## Files

- `config.yaml`
- `finetune.py`
- `evaluate.py`
- `model.py`

## Own evaluation

- `reports/initial/scores_by_lead.csv`
- Lead 10 NSE: **0.876** on the recorded observed test days. See the CSV for sample count and other leads.

## Context

[Cross-model comparisons](../../../evaluation%20comparison/README.md) | [Original detailed notes](../../../evaluation%20comparison/archive/original_readmes/fine_tuned_global_pretrained_lstm.md)

Saved evaluations use observed target days. Future reanalysis was used as a forecast stand-in in most LSTM experiments; these scores are not operational forecast accuracy.
