# Ten-year outlook: dataset readiness audit

## Status and scope

Task 2 is complete. The audit inspected local historical flood CSVs, the underlying weather/discharge caches, geographic layers, existing model cards, and read-only database summaries. It also inspected metadata for the app's existing external exposure integration. No training, provider downloads, runtime changes, or geometry repairs were performed. The projection method, selectors, maps, and charts remain the next staged tasks.

The result supports a historical reporting baseline and a limited experimental planning product. It does **not** support a validated national ten-year flood probability, exact future discharge, or future inundation map yet.

Evidence: [machine-readable audit](ten-year-dataset-audit.json). Reproduce with:

```powershell
.venv/Scripts/python.exe scripts/audit_ten_year_datasets.py
```

The script records SHA-256 input signatures, counts, dates, missing fields, district coverage, original request-hash matches for the caches, geometry validity, and read-only database summaries. Database counts are a local snapshot and can change as the running app ingests observations.

## Inventory and coverage

| Input | Verified local contents | Suitable use | Main limitation |
| --- | --- | --- | --- |
| `app/ml/data/pakistan_desinventar_cleaned_events.csv` | 1,704 unique district/date records; 67 districts; 2000-01-01 to 2014-10-18; 1,277 FLOOD and 427 FLASH FLOOD | Historical reported flood-day summaries by location and recorded hazard | Impact/report inventory, largely media-sourced; not a continuous confirmed flood/no-flood record |
| `app/ml/data/pakistan_desinventar_training.csv` | 10,097 sampled daily rows; 1,584 positive and 8,513 comparison rows; 67 districts; 2000-01-01 to 2014-11-15 | Research into historical weather/event associations | Sampled comparison dates do not establish population event frequency or annual probability |
| `app/ml/data/cache/desinventar/*.json` | 178 cache files; 495 weather and 495 discharge location-year series; 200,120 values per precipitation, soil moisture, and discharge field, including padding dates | Recover complete daily data for the location-years actually present | Location-years were selected because they contain reported events; not continuous national coverage |
| `app/ml/data/pakistan_real_flood_training.csv` | 2,410 sampled rows; 730 event-window positives; 28 Pakistan-associated Global Flood Database events; dates 2003-01-17 to 2018-08-10 | Independent event-window reference for research | Event-centroid sample; no district-wide inundation labels; three gauge-level fields are entirely missing |
| `app/ml/data/riverine_station_training.csv` | 2,400 records for Balloki/Trimmu | Development and UI tests | Model card explicitly identifies it as synthetic bootstrap data; exclude from historical baseline and validation |
| Main database gauge tables | Legacy readings span 2026-10-06 to 2026-10-14; typed FFD observations span 2026-10-11 to 2026-10-14 | Current monitoring and short-range comparisons | Days of records cannot estimate multi-year flood extremes |
| Monitoring database station values | 20 records, all marked simulated at audit time | Simulation testing | Exclude every record from real historical analysis |
| Main database district snapshots and generic observations | Both contain zero rows at audit time | Potential future persistence | No additional historical rainfall coverage currently stored there |
| Existing exposure integration | Prepared Balloki and Trimmu/Jhang data; WorldPop 2025 population; local roads/buildings/settlements; UNOSAT 2025 water reference at Jhang | Separately labeled pilot exposure context | Not a national population time series, a future flood map, or ten-year training labels |

The public Global Flood Database product covers 2000-2018, but the local Pakistan-associated sample has its own narrower dates. Source-product availability must not be confused with locally downloaded coverage. [Official dataset description](https://developers.google.com/earth-engine/datasets/catalog/GLOBAL_FLOOD_DB_MODIS_EVENTS_V1)

## Historical flood labels and missingness

The original preparation quality report records 2,912 raw flood/flash-flood rows, 719 pre-2000 exclusions, 8 invalid dates, 33 unmapped district rows, and 448 duplicate district/date removals. The cleaned output has 1,704 unique district/date entries and no duplicate identities in the audit.

The training file excludes **all 120 recorded days in 2007**, leaving 1,584 positive rows. The preparation report attributes this to an exhausted free provider quota and deliberately avoids retaining a partial year in training.

Important gaps:

- No DesInventar event records later than October 2014 are prepared locally. Later events, including 2022 and 2025, are absent from this CSV. This describes the local file, not necessarily the current upstream inventory.
- Only 67 of the 126 historical-geometry districts have records. The other 59 include Jhang, Lahore, Sukkur, Peshawar, and Dera Ghazi Khan. Display these as **no records in this dataset**, never as zero physical flood risk.
- Nine recorded districts appear in fewer than three distinct years. Gujranwala and Islamabad Capital Territory appear in only one year. Apparent decreases or increases can reflect reporting coverage.
- The cleaned file retains district, date, event type, and source. It does not retain event duration, flood extent, gauge exceedance, impact totals, or reporting-completeness indicators.
- The cleaner deduplicates by district/date, so multiple reports or different hazards on the same day can collapse into one record. A retained date is a recorded flood day, not necessarily a distinct flood episode.
- FLOOD does not establish a specifically riverine mechanism. FLASH FLOOD is retained, but urban flooding has no dedicated verified label. Initial hazard selectors must respect those distinctions.
- Negative training rows were sampled at offsets of 7, 14, 21, and 28 days around recorded events, excluding only the immediate three-day neighborhood. They are unreported comparison dates, not confirmed dry/no-flood dates; long events and unreported floods can contaminate them.
- Consequently, 1,584 / 10,097 is a sampling ratio. It must never be displayed as annual or ten-year flood probability.

## Rainfall, soil moisture, and modeled discharge

The local cache contains 495 identifiable location-years for each of weather and discharge, with full calendar-day values within every cached location-year. There were no null/nonfinite values, negative precipitation/discharge, mismatched array lengths, or duplicate dates within the audited daily series. This is a positive result about **existing series**, not proof that all required location-years exist.

There are 511 district-years containing recorded flood days. Sixteen of these have no weather/discharge cache, all in 2007. That year has only 24 cached districts, so the existing whole-year training exclusion remains appropriate. Even outside 2007, districts without recorded events were not sampled, leaving broad gaps for estimating an unbiased climate baseline.

| Year | Cached districts | Year | Cached districts | Year | Cached districts |
| --- | ---: | --- | ---: | --- | ---: |
| 2000 | 22 | 2005 | 39 | 2010 | 37 |
| 2001 | 43 | 2006 | 50 | 2011 | 32 |
| 2002 | 18 | 2007 | 24 | 2012 | 35 |
| 2003 | 38 | 2008 | 40 | 2013 | 29 |
| 2004 | 43 | 2009 | 34 | 2014 | 11 |

The cached dates span 1999-11-25 to 2015-01-02 because requests include padding for rolling features. These edges do not constitute complete 1999 or 2015 coverage. There is no prepared continuous 2015-2025 rainfall history in these audited inputs. The live provider and regional rainfall map request hours/days of weather, not a historical climate series.

All 178 original cache request hashes were reproduced using the **legacy rounded bounding-box midpoint** coordinates from the initial repository version. The current interior-point routine produces different request keys. Some legacy points are outside their own district: Azad Kashmir and Rawalpindi occur in the recorded dataset; Nagar is also affected in the geometry source but has no recorded events here. Reuse must preserve original requested coordinates, returned model-grid coordinates, date ranges, and source identity. Do not silently relabel old cached data as if it was sampled at the current location.

The historical API supplies reanalysis, while discharge is modeled GloFAS flow. Neither represents a continuously observed local rain-gauge or discharge-gauge series. For newly prepared multi-decade weather, explicitly select one consistent reanalysis instead of using an evolving default. [Open-Meteo historical documentation](https://open-meteo.com/en/docs/historical-weather-api)

## Existing features and engineering

| Source | Existing fields | Engineering or interpretation |
| --- | --- | --- |
| Historical weather | `precipitation_sum` in mm; `soil_moisture_0_to_7cm_mean` in volumetric units | Rain sums over 1, 3, 7, 14, 30 days; soil moisture multiplied by 100 |
| Historical weather | `forecast_rainfall_1d` training field | Actually uses **the next day's realized reanalysis precipitation**. It is not an archived forecast and must be removed from a causal forecast validation or replaced by a genuine forecast available at issue time. |
| Modeled river discharge | Daily m3/s | Current value, one-day change, ratios to 7-/30-day means, and 30-day z-score |
| Provider grid metadata | `elevation` | Single sampled-location elevation, not district-average elevation, terrain slope, drainage capacity, or a floodplain model |
| Calendar | Month | Sine/cosine seasonality features |
| Cleaned event file | District, date, recorded event type | May produce recorded-day counts and coverage summaries; reporting completeness remains unknown |

The CSV has no empty/nonfinite numeric fields, but preprocessing uses `value or 0` for weather nulls and supplies zero for missing days in rainfall windows. That code path could hide missingness in a future rebuild; it must be guarded when preparing new outlook inputs. No such nulls were found in the inspected raw caches.

The Global Flood Database training file has **all 2,410 values missing** for `river_level`, `river_level_relative_to_warning`, and `river_rise_rate`. Those fields must remain unavailable. Future-model temperature, land-use change, reservoir operations, and future population inputs are not in the existing DesInventar training feature set.

## Geography and spatial joins

| Layer | Features | Audit finding |
| --- | ---: | --- |
| Historical `app/gis/data/pakistan_districts.geojson` | 126 | All geometries valid; all 67 recorded district names match this layer |
| Display `frontend/src/data/pakistan/pakistan_districts.geojson` | 146 | 145 named district features and one unnamed context feature; Barkhan and Batagram have self-intersections |
| Display ADM1 boundaries | 7 | Punjab has nested shells under geometry validity checks |
| HydroBASINS catchment display layer | 54 | Five invalid geometries; display-simplified sub-basins, not verified station upstream watersheds |
| Regional rainfall coverage | 1 | Valid MultiPolygon; broad hydrological monitoring extent, not a district risk layer |

Only 59 of the 67 historical names exactly match a named display district after punctuation/case normalization. The other eight are Azad Kashmir, Battagram, Dera Ismail Khan, Diamer, Islamabad Capital Territory, Jafarabad, Musakhel, and Qilla Saifullah. Several are spelling/name differences; Azad Kashmir is an aggregate whose original district detail was collapsed in preprocessing. Do not copy its aggregate value into every displayed AJK district.

An explicit versioned historical-to-display crosswalk is needed. A name match alone does not establish boundary equivalence. For derived intersections in the new view, validate or repair a copy of geometries and record the transformation; preserve source files. National display, historical training, and the separate HDX exposure boundaries are different inventories and must not be joined by feature index.

No prepared national slope, land-cover, imperviousness, drainage-capacity, or reservoir-management feature table was found in the audited inputs. The SAR module can obtain small DEM/slope windows remotely, but this does not supply an existing national long-range terrain dataset.

## Existing models and validation

The DesInventar V2, Global Flood Database, and Lower Indus pilot model cards all have `deployment_eligible: false` and `operational_status: rejected_holdout_quality`. The riverine discharge model is explicitly trained on synthetic data. None should become the new long-range production engine by changing its label.

DesInventar V2 validation recorded:

| Holdout | ROC AUC | Precision | Recall |
| --- | ---: | ---: | ---: |
| District | 0.6815 | 0.1765 | 0.8039 |
| Geographic | 0.5704 | 0.2654 | 0.2877 |
| Temporal | 0.7029 | 0.3396 | 0.3600 |

These are reported at the model card's selected thresholds. Its required gates are AUC >= 0.75, precision >= 0.60, and recall >= 0.60 on all three holdouts. Temporal partitions are train 2000-2010, validation 2011-2012, test 2013-2014; they contain no recent independent 2022/2025 test.

Future validation must keep later years separate, fit preprocessing only to training data, remove realized future-weather leakage, and compare against a simple historical baseline. Ensembles and confidence intervals cannot resolve systematic underreporting, missing spatial coverage, or absent true-negative observations.

## Climate-scenario data still required

No future climate inputs are prepared for the outlook. Two researched sourcing options are:

- **Open-Meteo Climate API:** provides daily multi-model HighResMIP climate data to 2050, useful for a small cached pilot with precipitation extremes. It is not an API for selecting arbitrary moderate/high SSP pathways; the documented model experiment uses a high-forcing setup. A model percentile must be labeled ensemble spread, not a separate emissions scenario. Historical climate-model output is also not observed weather. [Official documentation](https://open-meteo.com/en/docs/climate-api)
- **World Bank Climate Change Knowledge Portal:** provides CMIP6 datasets and metadata suitable for explicitly sourced scenario comparisons. Match the native geography, aggregation period, and variables before adding selectors. Do not manufacture distinct annual forecasts by interpolating a multi-year climate period. [Data access](https://climateknowledgeportal.worldbank.org/index.php/download-data), [metadata](https://climateknowledgeportal.worldbank.org/metadata)

Sourcing has not been executed in this audit. Source availability in documentation is not proof of a complete local Pakistan download or validated model skill.

## Recommended next implementation

1. Prepare a compact, versioned pilot dataset with continuous daily rainfall for a fixed set of explicitly supported locations and a stated baseline period. Preserve missingness and source/grid metadata. Continue to expose recorded-flood history as a separate reporting metric.
2. Add real future climate inputs. Use either correctly named SSP scenarios from a source that provides them, or a clearly named climate-model ensemble from Open-Meteo. Do not implement arbitrary percentage increases as climate scenarios.
3. Start with climate-driven flood-pressure/susceptibility indicators, such as changes in heavy-rain days and annual maximum multi-day rainfall, alongside historical reported flood activity. Calibrated physical flood probabilities, discharge thresholds, and future inundation require additional labels, gauge records, and hydrological validation.
4. Present model spread separately from sampling uncertainty. Display coverage/unsupported states for missing locations and hazard types. An annual model value describes a simulated climate year, not the actual weather expected in that year; prefer the ten-year planning period and supported checkpoints.
5. Add selectors and maps only for available data combinations. Retain urban flood projection, detailed exposure changes, and adaptation scenarios in future scope until validated inputs exist.

This recommendation narrows the initial product to what the audit can substantiate. The previous feature-plan mention of logistic regression or an existing XGBoost model was a possible research direction, not evidence that those models are validated or ready for this use.

## Verification performed

- Audit script completed successfully using the existing virtual environment; no dependencies installed.
- Recomputed CSV totals, unique district/date identities, year distributions, missing fields, and missing positive-event rows.
- Matched all 178 cache files to original request identities, checked all daily arrays, and quantified full-year versus missing location-year coverage.
- Checked validity of 334 geometries across the five selected layers; recorded eight invalid geometries without modifying them.
- Queried SQLite inputs using `mode=ro` and summarized source/type and time coverage.
- Preserved SHA-256 signatures for the nine CSV/geography input files. The script writes only the audit JSON; documentation is maintained separately.
