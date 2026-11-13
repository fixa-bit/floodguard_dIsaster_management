# Executed global-LSTM transfer experiment

The published Fine Flood Forecasts Caravan checkpoint was downloaded and actually fine-tuned on Marala. This was not a new global pretraining run: the authors' 6,375-basin weights were reused. Donor discharge datasets were not downloaded or claimed as newly trained here. Parent download URLs, revision and SHA256 hashes are in [the receipt](pretrained/download_receipt.json).

## Commands executed

Working directory: `D:/projects/flood_model/flood_model/riverine flood/short range/model`.

```powershell
$py = '../experiments/marala_observed/.venv/Scripts/python.exe'
$eePy = '../dataset/chenab_marala/raw/marala/rainfall/google_earth_engine/.venv/Scripts/python.exe'
& $py fine_tuned_global_pretrained_lstm/download_pretrained.py
& $eePy -u fine_tuned_global_pretrained_lstm/download_data.py
& $py -u fine_tuned_global_pretrained_lstm/prepare_data.py --config fine_tuned_global_pretrained_lstm/config.yaml
& $py -u fine_tuned_global_pretrained_lstm/finetune.py --config fine_tuned_global_pretrained_lstm/config.yaml
& $py -m unittest discover -s fine_tuned_global_pretrained_lstm/tests -v
& $py -u fine_tuned_global_pretrained_lstm/evaluate.py --config fine_tuned_global_pretrained_lstm/config.yaml
```

The extraction and training commands were launched in hidden background processes with stdout/stderr logs. Extraction completed all ten years; training completed normally. Unit tests were run again after adding checkpoint continuation/year-history checks: **8 passed**, including loading a synthetic fine-tuned checkpoint and continuing it. Evaluation was repeated after final guard/report changes; the numerical results reproduced. No real training was repeated or tuned after viewing the test scores.

An initial extractor attempt stopped because the Earth Engine environment lacked PyYAML. It was corrected to use JSON. A separate preliminary CPU benchmark required `map_location='cpu'` when reading the CUDA-saved parent; the actual training loader already used that setting. Neither diagnostic changed discharge or produced an accuracy claim. Download/extraction and training logs remain in this folder.

## Actual training

- Published model: `EmilRyd/caravan_model`, pinned revision `43f1ab45d2c3678e728b552919b898824e5f1069`, final epoch 40. Global training: 2001-2020; global validation: 1981-1990.
- Local train: 2016-2020, 1,767 issue windows and 17,625 observed target pairs. Validation: 2021, 356 windows and 3,550 observed target pairs.
- Seed 42; CPU; 25 epochs; selected epoch **25** by lowest validation normalized-runoff MSE **0.0589908408**. Last training MSE: **0.0825602853**. Actual recorded training time: **242.577 seconds**. No GPU was used.
- Learning rates: recurrent 0.00001, embedding/head/adapters 0.00005; batch 32; dropout 0.4 inherited from the parent; weight decay 0.00001; clipping 1; patience 5.
- Full 365-day forward context, with backpropagation through the last 60 history days and all ten forecast steps. Original global normalization retained unchanged. All eight published weight tensors loaded exactly before fine-tuning, and all eight changed in the selected fine-tuned checkpoint.
- Saved model: [runs/finetuned/seed_42/best.pt](runs/finetuned/seed_42/best.pt). Its SHA256 is `a3275abdbd445258f7e6d130fa44d1679024e5fcbb659c2c85b1660f23eccad8`. Epoch history, config, global normalization and year lists are beside it.

## Real observed-only comparison

Test years 2022-2024 contain **1,084 unique observed days**: 365, 365 and 354 by year. There are 1,084 issue windows, 10,795 scored issue/lead pairs, and 45 missing-target pairs excluded. Lead 10 contains 1,075 observed pairs. All target dates and values match those used by the existing local LSTM.

| Model | Lead | NSE | KGE | RMSE (m3/s) | Peak-flow MAPE |
| --- | --- | --- | --- | --- | --- |
| Existing local LSTM | 1 | 0.886299 | 0.902012 | 263.760 | 17.520% |
| Fine-tuned global LSTM | 1 | 0.878846 | 0.918454 | 272.268 | 17.707% |
| Existing local LSTM | 5 | 0.878148 | 0.928441 | 273.180 | 16.081% |
| Fine-tuned global LSTM | 5 | 0.875942 | 0.926540 | 275.641 | 17.011% |
| Existing local LSTM | 10 | 0.857131 | 0.910494 | 295.702 | 16.507% |
| Global parent without local fine-tuning | 10 | -0.862277 | -0.328774 | 1067.596 | 94.569% |
| Fine-tuned global LSTM | 10 | **0.876028** | **0.930602** | **275.453** | **19.026%** |

Day-10 NSE increased by 0.018897 and RMSE decreased by approximately 6.85%. Peak-flow MAPE worsened. At leads 1 and 5 the existing local model has higher NSE. The global parent alone transfers poorly to this large basin; fine-tuning was necessary in this experiment. Keep both models for later validation/ensemble experiments rather than replacing the local model on every lead or metric.

| Day-10 season | Local NSE | Fine-tuned global NSE |
| --- | --- | --- |
| Oct-Mar | 0.254442 | 0.316303 |
| Apr-Jun | 0.600737 | 0.734814 |
| Jul-Sep | 0.602365 | 0.626518 |

Day-10 monsoon flood-hit rate changed from 0.617 to 0.638, while false-alarm ratio increased from 0.431 to 0.464. These are daily exceedances of training Q95 = 2,494.714 m3/s, not independent flood events or official warning categories. Overall NSE should not be interpreted as equivalent accuracy on extremes.

Both models receive matched future rain/temperature with the same Gaussian weather errors; maximum floating-point discrepancy is 0.0000122 in physical units. The other twelve future global-model predictors are persisted from issue day. The global head is deterministic, so no quantile-coverage claim is made. Model/input/objective differences prevent attributing all score differences to pretraining alone.

**These scores use noisy realized ERA5-Land as a stand-in forecast. They are not established operational 10-day forecast accuracy.** The test years were excluded from this fitting/selection run but were inspected in earlier project experiments. NSE is not percentage accuracy. Synthetic tests provide no evidence about forecast skill.

## Integrity and deliverables

Downloaded 3,653 ERA5-Land days (2015-2024) and HydroATLAS intersections. All 51 required Marala static attributes are present. Training/validation/test dynamic input missingness is 0% for this run. The full source table's **3,454 observed discharge values and 13,636 NaNs** remain exactly unchanged, as do all source labels. Original table SHA256 remains `d21788d62afc9e54d8e2aa6e1f27dcc244ef3b6a1a734249650abd84ccdbe11f`.

Parent weight/config/scaler hashes and all raw-weather hashes were rechecked. Saved normalization was compared directly with the published global scaler. Full audit: [verification.json](verification.json); environment: [requirements-lock.txt](requirements-lock.txt).

See [the full report](../../evaluation%20comparison/global_pretrained_lstm/comparison_report.md), [per-lead scores](reports/initial/scores_by_lead.csv), [seasonal scores](reports/initial/scores_by_season_and_lead.csv), [predictions including target NaNs](reports/initial/predictions.csv), [data availability](../../evaluation%20comparison/global_pretrained_lstm/data_availability.csv), [evaluation manifest](../../evaluation%20comparison/global_pretrained_lstm/evaluation_manifest.json), and [skill plot](../../evaluation%20comparison/global_pretrained_lstm/skill_by_lead.png).
