# Pakistan flash-flood model (20 km grid, next 24 hours)

Status: **experimental first model**. It ranks where reported flash floods are likely; it is not a warning service.

For every 20 km cell in Pakistan (2,306 cells, including AJK and Gilgit-Baltistan), the model gives the chance that a flood report starts in that cell on the coming Pakistan-local day. It is trained on all of Pakistan, because flash floods are rare in any one cell, and scored separately for the Chenab districts (Sialkot, Gujrat, Gujranwala, Mandi Bahauddin, Hafizabad, Chiniot and Jhang; 67 cells). Inputs and sources are described in [`../dataset`](../dataset/README.md).

## What counts as a flash flood

There is no official flash-flood record for Pakistan, so labels come from **Groundsource**, Google's news-derived flood events (CC-BY-4.0). It has no flood-type field. A cell-day is a positive when a report **starts** there and:
- lasts at most 3 days, so long riverine episodes are left out;
- is located to at most 2,000 km² (district-level or coarser locations are dropped);
- covers at least 25 % of the report's area in that cell, or the cell holds the report's centroid;
- follows no other onset in the same cell in the previous 3 days.

The days of an ongoing reported flood, and the 3 days after an onset, are excluded from training and scoring. This keeps continued news coverage of one flood from counting as new floods or as misses. 22,655 reports pass the filter, giving 13,264 onset cell-days in 2009-12 to 2026-01. The rule is tested in `test_data.py`.

## Models

| Model | Inputs |
|---|---|
| Climatology | Each cell's onset rate by calendar month in 2010–2019. Its odds are scaled by the national report count of the previous 365 days, because news coverage grew about tenfold after 2010. |
| Climatology + rain trigger | Logistic regression on the climatology plus the day's rainfall and its wettest 3 hours. |
| **LightGBM, with the day's rain** | Starts from the climatology and adds: rainfall on the day and in the surrounding 3×3 cells, rain over the previous 1, 3, 7 and 30 days, soil moisture, temperature, snowmelt, terrain, land cover, built-up share, population density, season, and recent reporting relative to national volume. The day's rain is realised IMERG, standing in for a perfect rainfall forecast: no archived rainfall forecasts exist for Pakistan, as in the riverine experiments. |
| LightGBM, rain before the day only | Same, without the target day's rain: what can be said from antecedent conditions alone. |
| LightGBM, weather and terrain only | Same as the main model without any news-reporting inputs, to show how much skill is physical. |

Split by time: train 2010–2019, validation 2020–2021 (early stopping and the alarm threshold), test 2022-01-01 to 2026-01-31.

## Results (test, 2022 – January 2026)

8,614 onset cell-days among 3.4 million scored cell-days: a base rate of 0.25 %. A model with no skill would have a PR-AUC equal to that base rate.

| Model | PR-AUC | ROC-AUC | Onsets in each day's top 5 % of cells | CSI at the validation threshold |
|---|---:|---:|---:|---:|
| LightGBM, with the day's rain | **0.062** | **0.938** | **40 %** | 0.067 |
| LightGBM, weather and terrain only | 0.061 | 0.936 | 39 % | 0.066 |
| Climatology + rain trigger | 0.052 | 0.915 | 37 % | 0.060 |
| LightGBM, rain before the day only | 0.048 | 0.929 | 37 % | 0.053 |
| Climatology | 0.035 | 0.903 | 34 % | 0.039 |

The main model's PR-AUC is 77 % above climatology's. On an average test day, the 115 cells it rates highest hold 40 % of the cells that go on to report a flood.

**Chenab districts** (639 onsets, base rate 0.66 %): PR-AUC 0.070 against 0.048 for climatology, and ROC-AUC 0.908.

What the numbers mean:
- **Skill is physical.** Without any reporting inputs the model scores almost the same (PR-AUC 0.061). Its most-used inputs are then the day's rain in and around the cell, season, 30-day rain, built-up share and soil moisture.
- **A rainfall forecast matters most.** Without the day's rain, PR-AUC drops to 0.048. An operational version would need archived rainfall forecasts to show what part of the 0.062 survives real forecast error.
- **Brier skill is about zero (−0.01 to +0.01).** At a 0.25 % base rate the Brier score is dominated by how many floods the news reports each year. That swings from year to year (2022 and 2025 heavy, 2023 light) and no input can know it in advance. Calibration in the top decile is good: 1.9 % predicted, 2.1 % observed.
- **Alarms are mostly false.** At the validation threshold the model catches 16 % of onsets with a false-alarm ratio of 0.90. Ranking (the daily top 5 %) is the honest way to use it today.
- **It is strongest in the monsoon** by PR-AUC (0.068 against 0.027 in other months), and in Punjab, Sindh and the AJK/Gilgit-Baltistan mountains. It is weakest in Balochistan (0.031).

Full tables by year, season and province: [reports/RESULTS.md](reports/RESULTS.md). Figures:
- [reliability.png](reports/reliability.png)
- [test_period_maps.png](reports/test_period_maps.png): reported onsets against expected onsets per cell
- [case_days.png](reports/case_days.png): 14 August 2025 (KP, Gilgit-Baltistan and AJK cloudbursts) and 27 August 2022 (KP)

## Limits

- **Labels are news reports, not measurements.** Google's checks found about 60–75 % of Groundsource events correct in place and time. Reports cluster where people and newsrooms are, so cities are over-represented. Coverage before 2010 is too thin to use.
- **Riverine flooding is mixed in.** Groundsource has no flood type. Short reports of river inundation, such as the Chenab, Ravi and Sutlej floods of late August 2025 in Punjab, pass the filter. In the Chenab districts, 728 of the 1,718 reports since 2010 are from 2025, so the Chenab scores partly measure riverine flooding, which local rain cannot foresee.
- **Satellite rain misses cloudbursts.** In the Buner cells on 15 August 2025, IMERG shows at most 58 mm for the day and 26 mm in any 3 hours. The actual cloudburst was far heavier and shorter. This caps what any IMERG-driven model can do for the most violent events.
- **The day's rain is a perfect-forecast stand-in, and ERA5-Land is reanalysis.** Neither is how an operational system would receive its inputs.
- Consecutive days and neighbouring cells are not independent samples.

## Run

From this folder, after the dataset scripts have run:

```powershell
../../.venv/Scripts/python.exe train.py      # about 3 minutes on CPU
../../.venv/Scripts/python.exe report.py     # RESULTS.md and figures
../../.venv/Scripts/python.exe -m pytest test_data.py
```

`runs/` holds the trained boosters and every test prediction. It is ignored by git and rebuilt by `train.py`. The environment is `flash flood/.venv` (Python 3.11: numpy, pandas, pyarrow, shapely, pyproj, scikit-learn, LightGBM, earthengine-api, matplotlib, pytest).
