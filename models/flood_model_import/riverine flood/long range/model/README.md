# Marala long-range models: TFT, flood peaks and 2026–2040 projections

Status: **experimental**. Nothing here feeds alerts.

## Layout

| Path | What it is |
|---|---|
| [common.py](common.py) | Read-only loaders for the short-range data and the ERA5-Land extension; shared metrics. Sources are joined in memory only. |
| [tft/](tft/) | TFT architecture (`tft.py`), training (`train.py`), `config.yaml`, leakage tests, checkpoints (`runs/`) and per-mode outputs (`reports/`) |
| [baselines/](baselines/) | Climatology, damped anomaly persistence and raw GloFAS, scored on the same test |
| [calibration/](calibration/) | Conformal calibration of the P10–P90 interval → [CALIBRATION.md](calibration/reports/CALIBRATION.md) |
| [extremes/](extremes/) | Storm-rainfall flood-peak model → [PEAK_MODEL.md](extremes/reports/PEAK_MODEL.md) |
| [projection/](projection/) | CMIP6 bias correction and 2026–2040 projections → [PROJECTIONS.md](projection/outputs/PROJECTIONS.md) |
| [compare.py](compare.py) → [reports/](reports/) | Scores every model on identical (issue, target) pairs: [COMPARISON.md](reports/COMPARISON.md) |

## Data

| Role | Source | Period |
|---|---|---|
| Inputs (hindcast) | ERA5-Land catchment means: precipitation, temperature, dewpoint, PET, snowmelt, snow depth, SWE, solar radiation | 1980–2024 from short range; 2025-01 to 2026-11 from [`../dataset/era5land_marala_extension`](../dataset/era5land_marala_extension/README.md) |
| Inputs (projection) | NEX-GDDP-CMIP6 precipitation and temperature, 8 GCMs, SSP2-4.5 and SSP5-8.5 | [`../dataset/nex_gddp_cmip6_marala`](../dataset/nex_gddp_cmip6_marala/README.md) |
| Pretraining target | GloFAS v5 simulated discharge (−42 % volume bias at Marala) | 1980–2015 only, so no test-period weather leaks in |
| Fine-tuning and test target | Observed Marala inflow: WAPDA, then Sindh rim-station. Disputed rows excluded | 2016-03 to 2026-11 |
| Flood peaks | PMD published event peaks (instantaneous) | 1970–2016 |

Splits (observed): train 2016–2021, validation 2022–2023, **test: issues from 2024-01-01 on**. Missing observations stay missing: they are masked in the loss.

## 1. TFT (daily flow, 180-day horizon, P10/P50/P90)

Lim et al. (2021) architecture, implemented in PyTorch so gappy targets are masked rather than filled. Encoder 365 days, decoder 180 days, ensemble of 3 seeds. Each model is pretrained on GloFAS, then fine-tuned on observed flow (`tft_finetuned`). Ablations: observed-only training (`tft_scratch`) and GloFAS-only (`tft_pretrained_only`).

| Mode | Inputs after the issue date | Inputs before it | Use |
|---|---|---|---|
| forecast | calendar | all 8 ERA5-Land variables and observed flow | Long-lead forecast from basin state |
| climate_conditioned | precipitation and temperature | all 8 variables and observed flow | Upper bound with perfect future weather |
| **projection** | precipitation and temperature | precipitation and temperature only, **no flow history** | Runs on GCM output; drives the projections |

Held-out test, leads 1–180 days. Skill = 1 − RMSE / RMSE of the observed day-of-year climatology:

| Mode | Model | NSE | KGE | Skill vs climatology | PBIAS % |
|---|---|---:|---:|---:|---:|
| any | climatology | 0.40–0.42 | 0.43–0.44 | 0.00 | −8 to −9 |
| forecast | TFT fine-tuned | 0.41 | 0.47 | −0.00 | −6.3 |
| climate_conditioned | GloFAS raw (reference) | 0.50 | 0.43 | +0.09 | −42.5 |
| climate_conditioned | TFT fine-tuned | **0.57** | **0.60** | **+0.16** | −0.7 |
| projection | TFT fine-tuned | 0.56 | 0.59 | +0.14 | −2.0 |

- **No skill beyond climatology without future weather.** The forecast mode does not beat the seasonal cycle at any lead.
- **With future weather, the fine-tuned TFT is the best model**, and GloFAS pretraining helps (+0.16 vs +0.06 for observed-only training).
- **The projection mode loses little** (+0.14) despite having no flow history. Its encoder relies on past precipitation and day-of-year, and its decoder on temperature and season.

Full tables, including results by lead and by target year: [reports/COMPARISON.md](reports/COMPARISON.md).

## 2. Calibrated intervals

Conformalized quantile regression (Romano et al. 2019). Offsets are computed in log space, separately for the lower and upper bound, per season (Jun–Sep / other) × lead (1–30 / 31–180). They are fitted on the 2022–2023 validation predictions. A second variant refits offsets each month from all outcomes known by then (expanding window). The projections use offsets fitted on 2022–2026.

P10–P90 coverage on the 2024–2026 test (target 0.80), static offsets:

| Mode (TFT fine-tuned) | Raw | Calibrated | 2024 | 2025–26 |
|---|---:|---:|---:|---:|
| climate_conditioned | 0.62 | 0.74 | 0.86 | 0.67 |
| projection | 0.71 | **0.79** | 0.91 | 0.74 |
| forecast | 0.74 | 0.70 | 0.82 | 0.64 |

Calibration fixes the intervals in normal years. The remaining under-coverage in 2025–26 comes from multi-month runs of one-sided error:
- **below P10:** February–April 2025 and May–June 2026
- **above P90:** August–December 2025, the recession after the flood

These are consistent with upstream regulation or storage changes that are not among the inputs (the Indus Waters Treaty was put in abeyance in April 2025). The expanding-window variant does not fix them. For forecast mode, calibration slightly hurts, because 2022–2023 were calmer than 2025. Details: [CALIBRATION.md](calibration/reports/CALIBRATION.md).

## 3. Extreme peaks

**Daily data cannot represent Marala flood peaks.** The 2025 peak (769.5k cusecs on 2025-08-27) is a single 06:00 reading between 107k and 192k cusecs. The 2016 PMD event peak (11,669 m³/s) appears in the WAPDA daily series as 4,117 m³/s. The TFT never saw a daily value above 7,232 m³/s in fine-tuning.

A separate **annual event-peak model** (censored log-normal regression) is fitted on 1980–2016. PMD-listed floods are exact values; other years are treated as below the High-class floor of 200k cusecs. The predictor is the largest June–September 3-day catchment rainfall. It was chosen by leave-one-year-out cross-validation over antecedent-rain and temperature variants.

- Leave-one-year-out Brier score for ≥400k cusecs: **0.146**, against 0.209 with no predictor.
- **2025 test:** median 12,642 m³/s, P10–P90 6,134–26,058, containing the observed 21,789. P(≥400k) = 0.58 and P(≥600k) = 0.30. The TFT's best was about 4,000.
- It assumes the PMD list is complete for High-class floods in 1980–2016. It predicts instantaneous event peaks, so it cannot be checked against daily data for 2017–2024.

Details: [PEAK_MODEL.md](extremes/reports/PEAK_MODEL.md). Flood classes were inferred from the PMD labels: High ≥200k, Very High ≥400k, Exceptionally High ≥600k cusecs.

## 4. Projections 2026–2040

Chain: 8 NEX-GDDP-CMIP6 GCMs → bias correction to ERA5-Land (1985–2014) → projection-mode TFT (calibrated P10/P50/P90) and the peak model → changes against each GCM's own 1986–2014 run.

Bias correction:
- **Historical runs:** quantile mapping.
- **Scenarios:** quantile delta mapping. Precipitation uses an offset ratio, and each calendar month is rescaled to keep the GCM's own change in the monthly mean.
- **Why the extra steps:** ERA5-Land has rain on 79 % of days and the GCMs on about 40 %. Plain ratio QDM inflated or flipped the GCM changes; for example NorESM2-MM went from −9 % raw to +3 %.

Unit tests cover these cases (`projection/test_bias_correction.py`). In the reference check, corrected monthly precipitation is within 0.09 mm/day of ERA5-Land.

Pooled 2026–2040, ensemble median [min, max] across 8 GCMs, change against 1986–2014:

| | SSP2-4.5 | SSP5-8.5 |
|---|---|---|
| Temperature | +1.15 °C [+0.66, +1.34] | +1.27 °C [+0.71, +1.57] |
| Annual precipitation | +7.8 % [+0.6, +20.9] | +8.9 % [+4.5, +16.8] |
| Mean flow | **+7.3 %** [+0.5, +13.0] | **+9.3 %** [+4.8, +12.1] |
| Apr–Jun / Jul–Sep / Oct–Mar flow | +7.3 / +7.4 / +1.9 % | +9.6 / +9.2 / +8.1 % |
| Annual P(flood ≥400k cusecs) | 0.29 → 0.33 [0.23, 0.44] | 0.29 → 0.34 [0.29, 0.42] |
| Annual P(flood ≥600k cusecs) | 0.13 → 0.15 [0.10, 0.22] | 0.13 → 0.15 [0.12, 0.20] |

Read the ranges, not single numbers:
- Natural variability alone moves 5-year storm rainfall by −27 % to +32 % for one GCM, so the 5-year sub-period flood numbers in [PROJECTIONS.md](projection/outputs/PROJECTIONS.md) are mostly noise.
- The two scenarios barely differ before 2040, as expected.
- The seasonal peak stays in July, with no earlier melt shift by 2040.

Outputs (`projection/outputs/`):
- `period_statistics.csv` and `change_vs_gcm_historical.csv`
- `daily_flow_quantiles.csv.gz`: daily P10/P50/P90 for every GCM and scenario
- `annual_peak_probabilities.csv`
- `bias_correction_check.csv`
- `projection_overview.png`

## Limits

- About 8 observed years for fine-tuning. The test window is dominated by an extreme 2025 event and by possible regulation changes.
- Projections assume unregulated flow upstream of Marala, and glacier change is not modelled explicitly. The TFT can only represent melt responses seen in 1980–2023.
- Daily issues overlap, so (issue, target) pairs are not independent.
- 2025+ ERA5-Land precipitation differs slightly in day attribution from the stored 1980–2024 series (see the extension README).

## Run

```powershell
cd "riverine flood/long range/model"
../.venv/Scripts/python.exe tft/train.py                      # all modes (~30 min, RTX 5050); --modes projection for one
../.venv/Scripts/python.exe baselines/train_evaluate.py
../.venv/Scripts/python.exe calibration/calibrate.py
../.venv/Scripts/python.exe extremes/peak_model.py
../.venv/Scripts/python.exe compare.py
../.venv/Scripts/python.exe projection/run_projection.py      # about 1 min
../.venv/Scripts/python.exe -m pytest tft/test_tft.py projection/test_bias_correction.py
```

Environment: `../.venv` (Python 3.11, torch 2.11 + CUDA 12.8, pandas, numpy, scipy, pyyaml, matplotlib, earthengine-api).
