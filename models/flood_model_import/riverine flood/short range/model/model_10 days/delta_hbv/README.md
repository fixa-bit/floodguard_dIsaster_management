# Marala delta-HBV

This is a trained-from-scratch, single-basin adaptation of **delta-HBV 1.0**: an LSTM learns bounded hydrological parameters through the authors' differentiable HBV equations. It is not delta-HBV 2.0 or a global pretrained checkpoint.

The unmodified physical implementation comes from [MHPI hydrodl2](https://github.com/mhpi/hydrodl2), pinned at `b163a3c0125c5188f730f379643437d83b4e5d35`. Original sources, SHA256 hashes and the **PSU non-commercial licence** are retained in `source_reference/`. Commercial use of that code requires permission from PSU.

## Model

- 365 history days and a 10-day forecast horizon; no past discharge predictor.
- A small causal LSTM provides time-varying BETA, CFMAX and K1. Other HBV and gamma-routing parameters are learned as basin constants.
- Three HBV components are averaged. Discharge is routed physical runoff converted from mm/day to cumecs using 28,780.646 km2; there is no residual discharge output head.
- Precipitation, temperature and PET drive HBV. Future precipitation and temperature use the existing noisy ERA5-Land forecast proxy; negative noisy precipitation is clipped to zero. Future PET uses monthly means from training years only.
- The first 305 physical history days provide upstream no-gradient warmup; gradients cover the remaining 60 history days and 10 forecast days.
- Missing targets stay NaN and are masked. Missing predictors use training means plus missing indicators. The required 2015-2024 forcing record is complete.

## Run

Run these from `riverine flood/short range/model/` using the existing Python environment:

```powershell
$python = '../experiments/marala_observed/.venv/Scripts/python.exe'
& $python 'model_10 days/delta_hbv/setup_sources.py'
& $python 'model_10 days/delta_hbv/prepare.py'
& $python 'model_10 days/delta_hbv/train.py' --config 'model_10 days/delta_hbv/config.yaml'
& $python 'model_10 days/delta_hbv/evaluate.py' --config 'model_10 days/delta_hbv/config.yaml'
& $python -m unittest discover -s 'model_10 days/delta_hbv/tests' -v
```

`train.py` automatically evaluates the selected checkpoint. It refuses to overwrite `best.pt`; choose a new `training.output_dir` for retraining. To add years, provide a new daily table, update the chronological splits, and retrain with a separate output/report directory. All statistics are fitted on training years. The current static parameter vector is for one basin; this run does not establish multi-basin transfer skill.

Training uses 2016-2020, checkpoint selection uses 2021, and test scoring uses observed 2022-2024 targets. Every third eligible issue is used during training to control CPU cost; every eligible issue is used for validation and test. The fixed loss is 0.8 training-flow-scaled MSE plus 0.2 standardized log-flow MSE. One seed and one configuration are used; there is no HPO sweep.

## Saved files

- `runs/initial/seed_42/best.pt`: weights, normalization, source hash, inherited year lists and selected epoch.
- `runs/initial/seed_42/history.csv` and `training_summary.json`: real training measurements.
- `data/marala_daily.csv`: byte-identical copy of the observed source table, with a preparation receipt.
- `reports/initial/`: this model's predictions, seasonal scores, flood/non-flood scores and observed test counts.
- [Cross-model comparison](../../../evaluation%20comparison/delta_hbv/comparison_report.md): original LSTM, persistence and climatology on identical observed records.
- [Actual run results](RUN_RESULTS.md).

## Measured accuracy

Training took **88.5 seconds**, with 40 epochs and seed 42; the selected checkpoint is epoch 40. The run reached its configured epoch cap while validation loss was still improving, so convergence is not established.

| lead_day | n | NSE | KGE | RMSE_cumecs | PBIAS_pct |
| --- | --- | --- | --- | --- | --- |
| 1 | 1084 | 0.456 | 0.680 | 577.118 | -21.412 |
| 5 | 1080 | 0.458 | 0.680 | 576.361 | -21.488 |
| 10 | 1075 | 0.474 | 0.691 | 567.639 | -20.512 |

Day-10 NSE is **0.474**, below the original LSTM (**0.857**), persistence (**0.652**) and climatology (**0.790**) on identical observed records. This initial run is not an accuracy improvement.

Five correctness tests and the saved-result verification passed. See reports/initial/verification.json. No accuracy is inferred from these tests.

## Limits

No archived weather forecasts were available. These are hindcast scores using noisy realized weather, and operational forecast skill is unverified. The original LSTM uses different weather inputs. Regulation, a short discharge record, few independent floods and previously inspected test years limit interpretation. This deterministic model does not supply calibrated uncertainty intervals. Synthetic and implementation tests check correctness only; they do not measure real forecast accuracy.

## Reference

Feng, D., Liu, J., Lawson, K., and Shen, C. (2022). Differentiable, learnable, regionalized process-based models with multiphysical outputs can approach state-of-the-art hydrologic prediction accuracy. *Water Resources Research*, 58, e2022WR032404. https://doi.org/10.1029/2022WR032404
