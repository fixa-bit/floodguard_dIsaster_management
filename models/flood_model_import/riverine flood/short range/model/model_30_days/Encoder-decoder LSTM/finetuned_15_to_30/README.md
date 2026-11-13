# Thirty-day encoder-decoder LSTM, fine-tuned from the saved 15-day model

## How training works, in plain words

1. **Start with a model that already knows river patterns.** The saved 15-day model was first taught using eight US river basins, then fine-tuned using observed Marala discharge. We copy its saved weights and keep the original files unchanged.

2. **Extend its forecast to 30 days.** The model's learned identifiers for days 1-15 are retained. Days 16-30 start with day 15's identifier and are then trained. This copies starting parameters, not discharge values. Tests check that the original first-15-day quantile forecasts are preserved before fine-tuning.

3. **Use the past year to describe the river today.** The encoder reads 365 days of precipitation, temperature and past observed flow, with indicators for missing readings. Its memory initializes the decoder, which reads the next 30 days of weather inputs and produces the forecast in one call. Future observed discharge is never an input.

4. **Learn corrections to normal seasonal flow.** A new mean-flow output starts from a training-year seasonal average and learns an upward or downward correction. Large flow errors receive more penalty, and days 21-30 receive double training weight. The model also retains and trains its separate uncertainty output. Source targets remain NaN where observations are missing.

5. **Keep the years separate.** Marala training uses 2016-2020, 2021 chooses the best saved versions and uncertainty adjustments, and 2022-2024 is the existing observed comparison benchmark. Donor pretraining used 1985-1994 and donor selection used 1995-1996. All inherited years are saved and checked against test years.

6. **Train three versions sequentially and average them.** Seeds 42, 43 and 44 change the random training order and dropout. After each training pass, we check 2021 errors for days 21-30. We retain the best pass and stop after 12 passes without sufficient improvement; the initial seasonal prediction is available as a fallback.

7. **Finish settings using validation only.** Before checking the benchmark, we fix the mixing strength with exact climatology for three lead groups and adjust estimated flow ranges using 2021 errors. These ranges have no guaranteed future coverage because the validation year is also used for model selection.

8. **Evaluate on actual observed days.** We compare the selected 30-day forecasts with exact climatology, smoothed climatology and the previous best LSTM ensemble on matching issue/target/lead records. Other model families remain pending feedback.

**Weather limitation:** no archived 30-day weather forecasts were available. Future precipitation and temperature are noisy reanalysis inputs, so operational 30-day flood forecasting skill is unverified. The test years have already been inspected in earlier project experiments.

## What distinguishes this experiment

This is the existing 15-day encoder-decoder extended and fine-tuned for 30 leads. It uses 32 hidden units and two historical weather variables, unlike the previous best ensemble's 64 hidden units and eight weather variables. Both families use encoder/decoder LSTMs; their names do not imply different underlying recurrent architectures. This comparison tests the new trained variant, not an isolated architecture advantage.

The local discharge/weather table is a byte-identical copy of the original 15-day model's 2015-2024 input table. Observed flows and NaN positions were checked against the canonical merged table. `data/preparation_report.json` records these checks and parent source hashes.

## Run and saved files

From `riverine flood/short range/model/`:

```powershell
$python = '../experiments/marala_observed/.venv/Scripts/python.exe'
$variant = 'model_30_days/Encoder-decoder LSTM/finetuned_15_to_30'
& $python -m unittest discover -s "$variant/tests" -v
& $python "$variant/train.py"
& $python "$variant/verify.py"
```

`config.yaml` controls the frozen experiment. `data/` contains its source table. `reference/parent_15day/` holds the copied parent checkpoint and metadata. `runs/initial/seed_*/` holds the new 30-day checkpoints and histories; `validation_postprocessing.json` records validation-only adjustments. `reports/initial/` contains this model's observed predictions, seasonal/flood scores and verification.

The [cross-model comparison](../../../../evaluation%20comparison/model_30_days/encoder_decoder_finetuned_15_to_30/comparison_report.md) remains outside `model/`. `RUN_RESULTS.md` records actual training time and accuracy. Tests check code behavior only; all reported accuracy comes from observed benchmark targets.
<!-- RESULTS -->

## Measured results

Day-30 mean-flow NSE is **0.849**, versus exact climatology **0.792** and smoothed climatology **0.820**. Beats the original climatology: **True**; beats the smoothed control: **True**. Previous best ensemble NSE: **0.858**.

| model | lead_day | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Seq2seq_30d_ensemble | 30 | 1055 | 0.849 | 0.915 | 306.417 | 195.363 | 3.820 |
| Raw_seq2seq_ensemble | 30 | 1055 | 0.849 | 0.915 | 306.417 | 195.363 | 3.820 |
| Climatology | 30 | 1055 | 0.792 | 0.845 | 359.398 | 231.857 | 8.837 |
| Smooth_climatology | 30 | 1055 | 0.820 | 0.835 | 334.475 | 219.162 | 8.781 |
| Weather_only_LSTM | 30 | 1055 | 0.784 | 0.884 | 366.025 | 224.066 | 3.333 |
| Past_discharge_LSTM | 30 | 1055 | 0.788 | 0.871 | 362.871 | 215.196 | -5.660 |
| Previous_best_ensemble | 30 | 1055 | 0.858 | 0.874 | 297.556 | 191.690 | 4.150 |
| Persistence | 30 | 1055 | 0.262 | 0.629 | 677.066 | 446.424 | 1.149 |

Training took 176.8 seconds across three seeds; selected epochs were 9, 15 and 26. Nine correctness tests and saved-result verification passed. Day-30 high-flow RMSE was 801.6 cumecs versus the previous best 826.1, but ordinary-flow RMSE was worse (256.9 versus 241.6). High-flow hit rate increased to 41.2% from 33.3%, while false-alarm ratio increased to 61.8% from 45.2%. The nominal 90% interval covered 82.5% of observations. Overall NSE remains below the previous best.
