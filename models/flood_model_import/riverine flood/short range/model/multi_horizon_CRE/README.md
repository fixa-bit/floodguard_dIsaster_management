# Multi-horizon Climatology–Residual Ensemble (CRE) POC

## What this experiment answers

It compares one model shared across daily leads 7–30 with a separate model fitted for every lead. Both predict a correction to the same training-only, 31-day seasonal discharge climatology. The POC uses a small ensemble of regularized ridge regressions; it is a deliberately compact, inspectable test of horizon sharing, not a replacement for the existing 30-day LSTM CRE.

## Results

Run `train_poc.py` with the project's `experiments/marala_observed/.venv` Python. It writes:

- Cross-model reports and evaluation outputs are outside `model/` in [`evaluation comparison/multi_horizon_CRE`](../../evaluation%20comparison/multi_horizon_CRE/REPORT.md).
- That evaluation folder contains the lead-by-lead and horizon-band tables, fold scores, out-of-fold predictions, and plots.
- `runs/poc/final_train_through_2024/models.joblib`: fitted final POC artifacts trained on WAPDA targets through 2024.

The walk-forward folds expand the training window through each validation year (2019–2024); no random split is used. Each fold's climatology, imputer, scaler, regression coefficients and high-flow Q95 threshold use only prior WAPDA observations. Missing targets are skipped. FFD-only targets from 2025–2026 are excluded from this POC so source regimes are not mixed without a separate quality review. The local data copy is byte-identical to its recorded source.

### Outcome of the matched POC

The separate Ridge CRE had lower macro-mean RMSE than the shared Ridge CRE on **24/24 leads** (374.0 vs 393.0 m³/s, about 4.8% lower). But it beat training-only climatology on just **4/24 leads**; the shared Ridge CRE beat it on **0/24**. So the POC does **not** establish that either Ridge model is useful by itself, and it does not prove a universal win for separate models. It shows that for this simple setup, per-lead fits made smaller errors than a shared fit, while both still need better predictive signal.

There is also an already-trained, larger **single 30-day LSTM CRE** in the sibling model folder. Re-scoring its saved output shows its NSE exceeded climatology at all leads 7–30 (0.855 at lead 7; 0.858 at lead 30) and RMSE was lower at 24/24 leads. This supports keeping that one model as the current multi-horizon candidate under the project's noisy reanalysis proxy. It is **not** a controlled shared-versus-separate LSTM experiment: the LSTM uses a 365-day encoder and full future-weather sequence while the small Ridge POC has a compact feature set. It therefore cannot settle which LSTM training strategy is better.

Full matched Ridge results and the neural CRE rescore are in [`evaluation comparison/multi_horizon_CRE`](../../evaluation%20comparison/multi_horizon_CRE/REPORT.md).

This is a development comparison, not a fresh independent test: 2019–2024 have appeared in earlier project evaluations. To match the earlier CRE experiment, future weather is realized ERA5-Land precipitation and temperature at the target date, with lead-growing artificial noise. It is a proxy, not an archived weather forecast that was available on the issue date. Assess scores as a matched architecture comparison under this retrospective proxy, not as operational forecast performance.

## What “one model” and “separate models” mean here

- **Shared CRE:** one ridge ensemble fits all lead days together. Lead-day features identify the forecast distance, while weather/history coefficients are shared across leads. This pools the scarce local examples.
- **Separate CRE:** a ridge ensemble is fitted independently for each lead day. Each model can learn a different relationship, but each receives fewer examples.
- **Climatology:** the reference forecast is the training-years' mean flow for that calendar date, smoothed over 31 days.
- **Residual:** the learned model predicts how far flow may sit above or below that usual seasonal value.

The comparison reports RMSE, MAE, NSE, KGE, bias, skill against climatology, and high-flow precision/recall. A single lower average error does not by itself prove better flood warning. Check the per-lead results, year-by-year stability, and false alerts.

## Research takeaway

There is no general rule that one shared model or one model per horizon always wins. Direct multi-step research describes a bias/variance trade-off: sharing information can reduce estimation variance, while lead-specific fits can better match lead-specific behavior but may be noisier. The choice should be made with rolling-origin comparisons on the target basin, not by assumption. [Ben Taieb & Hyndman, ICML/PMLR (2014)](https://proceedings.mlr.press/v32/taieb14.html).

For longer ranges, the forecast product should also change:

| Range | Useful product | Marala readiness |
|---|---|---|
| 7–30 days | Daily flow trajectory and high-flow probabilities by lead | POC implemented and walk-forward compared; not operationally validated |
| About 1–3 months | Weekly/monthly mean-flow anomalies, water-volume outlook and probabilities; not exact daily flood timing | Not trained here; needs archived sub-seasonal ensemble forecasts, more independent years and hindcast verification |
| About 3–6 months | Monthly/seasonal water availability and above/near/below-normal flow or flood-tendency probabilities | Not trained here; current observed target record is too short for a reliable local seasonal model |

The labels overlap at the boundaries: operational S2S usage commonly covers roughly 2–6 weeks (some definitions extend to about 12 weeks), while seasonal hydrological products are usually monthly means over at least a three-month range. For this project, treat a 1–3-month request as an **aggregated probabilistic outlook**, not a precise day-by-day hydrograph. Treat 3–6 months as seasonal water-volume and high-flow-tendency probabilities, not dates of individual floods.

WMO practice describes sub-seasonal hydrological forecast products at weekly/daily aggregation and seasonal streamflow products with forecast ranges of at least three months. ECMWF seasonal products provide ensemble monthly averages to seven months. Operational hydrological systems convert those meteorological ensembles through hydrological models and reduce stated forecast range when skill falls with lead. Those are the appropriate input types and product scales to investigate for Marala. [WMO seasonal hydrological prediction](https://wmo.int/media/news/guidelines-seasonal-hydrological-prediction-wmo-no-1274), [WMO seasonal product guidance](https://public.wmo.int/activities/wmo-integrated-processing-and-prediction-system-wipps/wipps-seasonal-prediction), [ECMWF seasonal forecast data](https://www.ecmwf.int/en/forecasts/datasets/set-v), [Copernicus flood forecast system description](https://confluence.ecmwf.int/spaces/CEMS/pages/483297828/Description+of+the+real+time+forecasts+reforecasts+and+climatologies+as+components+of+the+CEMS-flood+sub-seasonal+and+seasonal+forecasts).

Seasonal outlooks should be evaluated probabilistically and against climatology. The WMO verification guidelines call for performance, reliability and decision usefulness, not only point-error scores. [WMO Guidelines on Verification of Hydrological Forecasts (No. 1364)](https://public.wmo.int/media/news/wmo-issues-guidelines-verification-of-hydrological-forecasts). A sensible next CRE target is the probability of seasonal discharge volume in the below-normal, near-normal or above-normal tercile, plus a separately defined high-flow-tendency probability. Verify with leave-year-out hindcasts and reliability/Brier or ranked-probability scores; do not tune these probabilities on the final years.

## Why the POC stops at 30 days

The selected continuous WAPDA target segment has about nine years (2016–2024), with gaps. It supports a useful small daily-horizon experiment, but it provides very few independent year-to-year examples for verifying a 3–6-month high-flow tendency. A longer-range model also needs archived, issue-dated weather ensemble hindcasts and initial snow/soil-water information. Reanalysis after the forecast issue date cannot stand in for a real forecast when claiming operational skill. Seasonal training is therefore marked **not run**, rather than presenting a weakly supported result as proven.

## Files and rerun

```powershell
$python = '../experiments/marala_observed/.venv/Scripts/python.exe'
& $python 'multi_horizon_CRE/train_poc.py'
```

The run reads `config.yaml` and the unchanged CSV copy in `data/`. Settings include daily leads, validation years, Q95 rule and ridge-ensemble strengths. This folder contains no claim that CRE is proven better for every horizon; the saved walk-forward comparison shows where the shared fit did or did not help on this record.

`predict_poc.py` can score a forecast issue when a merged daily input table and a 7–30 day forecast CSV are provided. The forecast CSV must contain `lead_day`, `rain_era5_mm`, and `temperature_c` for each lead. This inference path is exploratory: the model was trained with noisy realized ERA5-Land rather than archived operational weather forecasts, so providing real forecasts changes the input domain and is not validated yet.
