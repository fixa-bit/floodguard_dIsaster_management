# Flood Event Report (FER): spec

Status: **initial version** (11 Nov 2026). A report about one flood incident on one
river, issued automatically when a flood is detected in real data, when it escalates
and when it ends. It complements the Daily Flood Situation Report
([daily_report_spec.md](daily_report_spec.md)); the core rules there (data-source label
on everything, simulated data unmistakable, simulated floods on real imagery, honest
impact wording, reproducible data snapshot) apply here too.

## Pipeline

Shared with the daily report: data collection (`app/reports/collector.py`), page
styles and chart helpers (`app/reports/templates/_base.html`, `_helpers.js`, `_tip.js`,
assembled by `app/reports/render.py`) and the snapshot recipes.

| Part | File |
|---|---|
| Signal detection, dedupe, report triggering | `app/reports/flood_events.py` |
| Dedupe table `flood_events` | `app/models/flood_event.py` |
| Report data | `app/reports/event_report.py` |
| Report page body | `app/reports/templates/flood_event_report.js` |
| Automatic trigger (inside the backend) | `app/services/flood_event_watcher.py` |
| Manual run and test events | `scripts/flood_event_check.py` |

Output: `reports/events/<event no>/v<n>/<event no>-v<n>.html` plus `report.json`.
Test events go under `reports/events/test/`.

## Trigger

The watcher checks the stored river-monitoring and upstream-forecast snapshots once a
minute and runs a detection cycle whenever either has been refreshed (monitoring every
15 min, upstream forecasts every 60 min). Settings: `flood_event_reports_enabled`,
`flood_event_close_after_hours` (24), `report_api_base`, `report_frontend_url`,
`report_run_satellite`, `report_capture_snapshots`.

**Qualifying signals (real data only)**

| Kind | Rule | Level |
|---|---|---|
| Observed | FFD category Low flood or higher; reading at most 48 h old | 2 Low · 3 Medium · 4 High · 5 Very high · 6 Exceptionally high |
| Flood API forecast | GloFAS or GEOGloWS peak ≥ the station's low-flood threshold (official FFD where available), and the other provider ≥ 75% of it | 1 Flood watch |
| Model | Operational FloodGuard model at High or above, live data mode, simulation off | 1 Flood watch |

Never triggers: simulated data, placeholder ("dummy") model outputs, and the
flash-flood / urban heuristics (they read CRITICAL in dry weather).

## Dedupe: one incident, one event

- One event per river system; a flood wave moving downstream stays one event.
  Panjnad joins the Chenab event (or the Sutlej event when only the Sutlej floods).
- A new report version is issued only when:
  - **New event**: the first signal on a river with no open event;
  - **Escalated**: the level rises above the highest level already reported;
  - **Closed**: no signal for `flood_event_close_after_hours` (24 h).
- Same level, dips and returns to a level already reported, and new stations at the
  same level do not create reports (they appear in the next version).
- A reading older than 48 h can hold an event open but cannot open or raise one.
- Reports are derived from stored state, so a failed report is retried next cycle and
  never issued twice. A flood after closure starts a new event (`-02`).
- Event number: `FER-<RIVER>-<YYYYMMDD>-<nn>`; test events `FER-TEST-...`.

## Sections

| # | Section | Contents |
|---|---|---|
| — | Header | Event no., version and reason (new / escalated / closed), opened, issued, event level; TEST banner for test events |
| 01 | Event Summary | Headline; key figures (level, peak discharge, stations in flood, next station downstream, people in extent, satellite water); signals that triggered the report; version history; when a new version is issued |
| 02 | Flagged Signals & AI Analysis | The signals that opened or raised the event as flags: measured value and category (code), separate AI explanation with citations and deeper agent analysis; review stamp. Same rules as the daily report (see its spec) |
| 03 | Observed River Conditions | Same as the daily report: network diagram of all 22 FFD stations and the full station table (source, inflow, outflow, 24 h change, % of normal, recent trend, rising days, FFD category, observed time / stale flag); stations on the event river in bold, simulated test reading ringed |
| 04 | Downstream Arrival | Expected arrival time at each downstream station from the flooded station's reading (indicative travel times) |
| 05 | Dams & Barrages: Inflow vs Outflow | Inflow/outflow chart and table for sites on this river, net and reading (storing, releasing, canal withdrawals) |
| 06 | Forecasts & Model Outputs | 6a station forecasts; 6b upstream GloFAS vs GEOGloWS charts with agreement and flood-type signals; 6c model predictions (placeholders labeled `sim`); 6d seasonal outlook (Marala, Chenab only); model and upstream graph captures |
| 07 | Rainfall & Weather along the river | Rainfall last/next 24 h, temperature and screening risk for every corridor district; one-line verdict (upstream flow vs local rain) |
| 08 | Satellite Check | Real Sentinel-1 before/latest at up to 3 flooded stations, water outside permanent water, pass dates |
| 09 | Impact & Districts at Risk | 9a exposure in the flood extent (people, roads, settlements, schools, hospitals, facilities, people by area); 9b districts along the flood path with arrival time; 9c district risk screening for the corridor (highest risk, warning signs); population/extent and simulated spread (2D, 3D) captures |
| 10 | Alerts, Incidents & Citizen Reports | Counts (new / open / total), waiting times, full alert, incident and citizen report tables for this river's stations and corridor districts |
| 11 | Checks for Supervisors | Checklist by level (watch / low / medium / high+ / closed); supports, does not replace, NDMA/PDMA SOPs |
| 12 | Data Sources, Quality & System Health | Share of items by source; feed status; data mode; simulation runs on this river; index of captured portal visuals |
| 13 | Annex | FFD flood categories; corridor districts; sources and notes |

**Corridor**: districts within about 35 km of a station on the event's river
(`CORRIDOR_DEG` in `event_report.py`). Sections 07, 09c, 10 and 12 are scoped to it. System activity logs are not included in either report.

**Flood extent used for impact**
- Real event: the Sentinel-1 potential-flood outline at the flooded station
  (`potential_flood_geojson`, added to the SAR output), labeled `sat` + `est`.
- Test event: the synthetic test polygon of the exposure region, drawn hatched over the
  real radar image, labeled `sim` + `est`.
- Impact is available only where exposure datasets are prepared (Trimmu/Jhang,
  Balloki/Shahdara). Elsewhere the section says so.

## AI analysis

Same pipeline and rules as the daily report (see "Flagged signals and AI analysis" in
[daily_report_spec.md](daily_report_spec.md)). Real events from the watcher are automatic:
AI analysis follows `ai_analysis_enabled` and is published without human review. Test
events get AI analysis only when asked (Test dialog or `flood_event_check.py --ai`); their
simulated flags are analysed and labelled as simulated.

## Testing

```
.venv/Scripts/python.exe scripts/flood_event_check.py --dry-run
.venv/Scripts/python.exe scripts/flood_event_check.py --test TRIMMU="High flood:9500"
.venv/Scripts/python.exe scripts/flood_event_check.py --test TRIMMU="Very high flood:14000"
.venv/Scripts/python.exe scripts/flood_event_check.py --test-quiet --close-after-hours 0
.venv/Scripts/python.exe scripts/flood_event_check.py --list
.venv/Scripts/python.exe scripts/flood_event_check.py --test TRIMMU="High flood" --ai   # with AI analysis
```
