# Daily Flood Situation Report (DFSR): template spec

Status: **approved initial template** (11 Nov 2026). The automated report generator
must follow this structure and these rules. New features are added on top of it;
existing sections are not removed or reordered without updating this spec.

- Visual reference: [daily_report_template.html](daily_report_template.html)
  (open in a browser; every figure in it is **sample data** for layout only).
- Published preview: https://claude.ai/artifact/6iLXF3X1w5WpU56eG9aEHt (private)

## Core rules

1. **Fixed coverage.** Every section and every one of the 22 FFD stations appears
   in every report. Missing data is shown as "Unavailable" with a reason and is
   never silently dropped. A satellite location with no recent pass is reported
   as "No recent satellite pass", never as "no flooding".
2. **Data-source label on everything.** Each section heading, table row and figure
   carries one or more labels:

   | Key | Label | Meaning |
   |---|---|---|
   | `obs` | Observed | Measured by a real gauge, or a real citizen report or incident |
   | `off` | Official forecast | Issued by PMD FFD |
   | `api` | Flood API | Modeled data from GloFAS, Google Flood Hub or Open-Meteo |
   | `ml` | Model prediction | FloodGuard model output; pilots are marked "not validated" |
   | `sat` | Satellite | A real Sentinel-1 RTC radar image |
   | `est` | Estimate | Calculated by FloodGuard (travel time, % of normal, exposure) |
   | `sim` | Simulated | Test data from a portal simulation run |
   | `ai` | AI analysis | Written by AI (Claude) to explain a flagged value, from cited documents and data; a draft that never changes a value, category or status (section 02) |

3. **Simulated data is unmistakable.** If any input is simulated, the report shows
   the red striped TEST REPORT banner naming the simulation run ID(s), and the
   Executive Summary opens with a callout listing what is simulated. Simulated
   rows get a red edge. Simulated values are never combined with real values
   in one figure without the `sim` label.
4. **Simulated floods use real imagery.** When a simulation produces a flood
   extent, the generator still fetches the real Sentinel-1 image for that location
   (`app/services/sar_catalog_service.py`) and draws the simulated extent on top
   of it, **hatched**. Real detected water is drawn **solid**. Exposure and impact
   (`app/gis/exposure_engine.py`, `app/services/population_service.py`) then run
   on the simulated extent, and the results are labeled `sim` + `est`.
5. **Honest impact wording.** Population is a modeled estimate, not a count of
   affected people. "Exposed" does not mean damaged or closed. Missing OSM features
   do not prove absence. Satellite image age is always shown.
6. **Reproducible.** Each report stores a snapshot of the data it used, so past
   reports can be regenerated and day-to-day changes calculated.
7. **National status rule.** Only real data raises the status. Radar water found
   at a station location (barrage, headworks or dam) raises it to Watch only if
   that station's gauge is above Below low, because river water at barrages is
   normal. The detection is still listed under concerns, with this reason given.
   Radar water at a district (non-station) location raises the status to Watch on its own.

## Defaults (to confirm at implementation)

- Reporting period: 06:00 → 06:00 PKT, generated at about 06:15 PKT.
- Discharge in cusecs, rainfall in mm.
- Outputs: PDF for supervisors (plus HTML), stored in a portal report archive;
  optional email delivery.

## Sections (in order)

| # | Section | Contents | Main portal source |
|---|---|---|---|
| — | Header | Report no., period, generated time, data mode, units, national status (Normal / Watch / Warning / Emergency) with change from yesterday | `/system/status` |
| 00 | Where This Report's Data Comes From | Label legend; bar showing share of figures by source | generator |
| 01 | Executive Summary | Headline; key figures with change since yesterday; top 5 concerns; stations by FFD category bar | all |
| 02 | Flagged Signals & AI Analysis | Values a rule flagged, each with its measured value (code), risk category and rule (code) and a separate AI explanation with citations plus, for the top flags, a deeper agent analysis; review stamp | report data, documents, Claude |
| 03 | Observed River Conditions | River network diagram (22 stations by category, ▲ if rising ≥5 of 7 days); table per river: source, discharge, 24 h change, % of normal, 7-day trend line, rising days, FFD category, observed time | `/river/monitoring`, station history |
| 04 | Flood Wave Travel | Arrival time and attenuated peak at each downstream station when a station rises | `RIVER_CHAINS` + travel times |
| 05 | Dams & Barrages: Inflow vs Outflow | Paired bars; net value; reading (storing / releasing / diverting) | FFD inflow/outflow gauges |
| 06 | Hydrological Forecast & Outlook | 6a 72 h station forecasts; 6b upstream watch (observed + GloFAS + Flood Hub chart, forecast agreement flag at >25% difference, flood-type signals); 6c model predictions with status; 6d seasonal Marala outlook vs normal | `/river/upstream-forecasts`, `/flood/*`, `/predictive/marala-monthly` |
| 07 | Forecast Accuracy | Yesterday's forecast vs today's observed, by station; 30-day mean absolute error by source | stored forecasts + observations |
| 08 | Rainfall & Weather | Heaviest observed vs forecast rainfall; heat and snowmelt (GLOF) watch: temperature ≥4 °C above normal while flow rises | `/weather`, `/gis/rainfall` |
| 09 | District Risk Screening | 126 districts by risk band; districts with several warning signs (high risk, station rising, citizen reports, open incident) | `/gis/national-risk` |
| 10 | Alerts, Incidents & Citizen Reports | New/open/closed counts; open incident list; response times vs target | `/alerts`, `/incidents`, `/citizen-reports` |
| 11 | Satellite Flood Detection & Impact | 11a checks at watch locations (pass dates, image age, extent source, area, result); 11b before/after radar images; 11c impact (people, settlements, buildings, roads, schools, health facilities); 11d population by tehsil; 11e exposed facilities; suggested actions; "no new flood water" line when nothing is found | `/sar-water`, `/exposure`, `/population` |
| 12 | App & Simulation Snapshots | 12a simulation runs (station, readings, alerts, incidents); 12b index of the portal visuals in this report (each shown in its own section) | `monitoring_simulation_runs`, headless capture |
| 13 | Data Quality & System Health | Each feed (FFD, FFD bulletin, GloFAS, Flood Hub, Open-Meteo, Sentinel-1, population/OSM, simulation engine, snapshots, AI analysis) with status, last update, coverage; system/simulation/ML mode | `/system/status`, provider timestamps |
| 14 | Annex | FFD flood category definitions; sources and methodology notes | static |

## Flagged signals and AI analysis (section 02)

The report stays deterministic. Code collects and checks readings, applies thresholds and
rules, sets the status and fills every section (including "unavailable" ones). AI is used
only where a rule flagged a value, and only to explain it.

**Flags (code, `app/reports/flags.py`).** Each flag states the measured value, the risk
category, the rule and its effect on the status, from the same rules the report uses:

| Kind | Rule | Effect on status |
|---|---|---|
| Station in flood | FFD category at or above Low flood (fresh reading) | Warning (Low/Medium) or Emergency (High+) |
| Forecast above flood threshold | A GloFAS/GEOGloWS peak at or above the low-flood threshold, every provider at least 75% of it | Opens a flood watch event |
| Possible flood water (satellite) | Radar water outside permanent water where the gauge is above Below low | Watch |
| Forecast sources disagree | Providers differ by more than 25% and more than 100 cumecs | Watch |
| High district screening risk | Screening probability of 60% or more | Watch |
| Sharp rise | More than 50 cumecs and more than 10% in 24 h | None (awareness) |

**AI step (after the report is written, `app/reports/ai/`).**
1. **Explanation (RAG):** for the top 4 flags, a short explanation from retrieved documents,
   with numbered citations to the exact passages. Documents only: FFD bulletins (archived
   automatically), FFC daily flood reports, NDMA/PDMA plans, the FFC flood classification,
   FloodGuard method notes and past FloodGuard reports (code content only, never test
   events, simulated items or earlier AI text). No matching document: no AI call, and the
   box says so. Readings and other structured data are never retrieved this way.
2. **Deeper analysis (bounded agent):** for the top 2 flags, Claude uses read-only tools
   (station readings, upstream stations and releases, forecasts, rainfall, incidents and
   citizen reports, the report's satellite check, document search, and web search limited to
   official Pakistani flood sources and major news sites). Limits: 8 turns, 12 tool calls, 3
   web searches, 240 s. It returns a summary, evidence, possible explanations, uncertainty and
   checks for the reviewer. Code keeps only statements whose references were really returned
   to the agent in that run.
3. **Integrity:** a SHA-256 checksum of every code-owned value is taken before and after the
   AI step. If anything changed, the AI output is discarded. The result is shown in the
   section and in Data Quality.

**Layout.** Each flag shows three separate boxes: *Measured value (code)*, *Risk category
(FloodGuard rule)* and *AI explanation (draft)*, with the `ai` label (violet, dotted). The
deeper analysis follows below. Without an API key, with AI switched off, or on failure, the
flags still appear and the AI box says why it is empty.

**Review.** Set when the report is generated:
- *Automatic* reports (the scheduled daily report, watcher-triggered real event reports):
  AI notes are published without human review, marked "Automatic report: published without
  human review" (`ai_review_automatic`).
- *Manual* reports (Generate now, tests, CLI): "Review in portal" (default) or "Draft label
  only". Reviewers accept or reject each note in Situation Reports; decisions go to
  `review.json` beside `report.json` (never into it) and appear as stamps on the page.

**Settings** (`app/core/config.py`): `anthropic_api_key` (`.env`), `ai_analysis_enabled`,
`ai_model` (`claude-opus-5-5`), effort, limits, `ai_web_search`, `ai_web_search_domains`,
`ai_review_automatic`, `ai_review_manual_default`, `knowledge_dir`.
Tools: `scripts/ai_analyze_report.py <folder>` re-runs the AI step on a saved report;
`scripts/knowledge_index.py` builds or searches the document index.

## App snapshots

Only flood-relevant visuals from the portal are captured: no generic pages (no
Overview, River Monitoring, Alerts, Incidents, Citizen Reports or System Activity
screens). Each capture is an element of the page, set up for a specific case, not a
whole screen. Recipes live in `app/reports/collector.py` (`shot_*` functions) and are
shared with the flood event report.

**Capture rules**
- Headless Chromium (Playwright), 1600 × 1000, the portal's own theme.
- A recipe opens the screen from the sidebar, sets controls (station, region, tab,
  flood source, preset), waits for results, then captures one element.
- Each capture carries data-source labels and a caption; simulated visuals are `sim`.
- A failed capture is listed as "Snapshot unavailable" with the reason, never skipped.

**Visuals captured**

| Visual | Portal screen › setup | Section | Labels |
|---|---|---|---|
| Model prediction graph (riverine short-term) | Predictive Risk Views › first card | 06 | `ml`, or `sim` while models are placeholders |
| GloFAS vs GEOGloWS forecast graph, selected stations only (providers disagree, else the highest riverine signal; max 2) | Upstream Source Flood Watch › station | 06 | `api` |
| Flood-affected population panel | GIS Operations › population panel, region + flood source, Calculate | 11 | `sim` + `est` for test extents, `sat` + `est` for satellite water |
| Flood extent over population density (map) | same as above | 11 | as above |
| Simulated flood spread vs baseline population (2D) | Simulation › Flood spread & population › preview district nearest the station | 11 | `sim`, `est` |
| 3D population exposure (cinematic, population focus) | same, Cinematic 3D › Population focus | 11 | `sim`, `est` |

Flood event reports (see [flood_event_report_spec.md](flood_event_report_spec.md))
use the same recipes for the event's river and station; the simulated spread uses the
widest example level for High flood and above, and the population capture uploads the
satellite water outline when the event is real.

## Visual conventions

- FFD categories: Below low (green), Low (amber), Medium (orange), High and above (red),
  always shown with the text label, never color alone.
- Series colors: observed = blue, GloFAS = orange, Google Flood Hub = aqua.
- Insights added beyond the portal's raw data are tagged "Insight"
  (% of normal, rising days, wave travel, inflow vs outflow, forecast agreement,
  forecast accuracy, snowmelt watch, districts with several warning signs, response times).
- Light and dark themes are both supported. Charts are drawn to scale from the data.
