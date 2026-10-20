# Marala flat forecast and missing history: 16 October 2026 audit

The running `GET /api/v1/predictive/marala-monthly` endpoint returned HTTP 200.
Its chart still uses `current_provider_outlook` from the saved Open-Meteo/GloFAS
response. Neither new experiment under `models/` is connected to this chart.

## Why the line looks flat

- The current provider forecast has 201 valid daily points, 16 October 2026 to
  4 May 2027, ranging from 210.68 to 387.59 m3/s. The 210-day requested window
  ends 13 May; its final nine days have no values and remain blank.
- The chart's measured historical peak is 21,789.813453 m3/s. The shared
  vertical axis rounds up to 25,000 m3/s over 295 SVG plotting units. The entire
  forecast range therefore occupies about 2.1 SVG units. It has variation,
  compressed by that historical flood peak.
- The forecast dates cover the post-monsoon/winter/spring period, excluding
  June-September 2027. This does not compare the next monsoon with the past one.
- Past points are measured 06:00 PKT inflow; future points are modeled daily
  means at a nearby river reach. Identical labels in m3/s do not make these the
  same target. A daily/ensemble mean also need not reproduce instantaneous peaks.
- The separate 365-day research experiment selected smooth seasonal climatology
  over ridge/XGBoost on validation RMSE. Its curve is an annual seasonal outlook,
  not an event-resolving flood forecast; it has not replaced the dashboard feed.

The user's Bangladesh screenshot displays a five-day water-level hydrograph
(metres), including subdaily points. Bangladesh's [BWDB system upgrade
description](https://www.bwdb.gov.bd/tender_doc/5011.pdf) describes hydrological
and hydrodynamic forecasting, upstream boundary inputs, and rainfall data.
Its short forecast horizon, target and inputs differ from our seasonal discharge
outlook. No inference about that screenshot's accuracy can be made from its
visual similarity to past points.

## Missing readings

For the chart window 16 October 2024 to 15 October 2026, there are 235 measured
dates out of 730: 495 dates are absent from the collected 06:00 dataset. These
are missing **from our dataset**, not proof that the river was not measured.

The collector currently focuses on FFD flood bulletins. Some source entries are
also inconsistent: archive entry `/bulletins/archive/66/view`, labelled
16 October 2024 in the archive, currently returns a PDF dated **16 June 2024**.
Rejecting that document for the requested date is correct; assigning its values
to October would create a false measurement. Other rejections involve units,
multiple dates, or unrecognized station tables. Those need individual checking.

## Additional reported data found

The [IRSA/NESPAK daily-data portal](https://irsa.nespak.co/Home/DailyData)
supports dated report queries through its date-selection form. The unfiltered
page defaults to 15 July 2016, so fetching its default page repeatedly is not a
historical-data collector. The form submits `ReadingDateString=YYYYMMDD`.

The audit sampled the 15th of each month within the chart window plus its
endpoints: **24 of 25** dated responses contain Marala upstream/downstream
values; 15 October 2026 has no Marala card. This is a monthly sampling audit,
not confirmation of complete daily coverage. Examples:

| Report date | Reported upstream discharge (cusecs) |
|---|---:|
| 16 October 2024 | 10,100 |
| 15 January 2025 | 5,533 |
| 15 January 2026 | 7,346 |
| 15 September 2026 | 41,662 |

All eight sampled dates overlapping the existing FFD dataset agree within
44 cusecs, consistent with FFD's 100-cusec reporting precision. This supports
further investigation of this source, but does not independently establish its
observation time or whether each card represents a daily mean. The portal calls
Marala values `U/S DISCHARGE` and `D/S DISCHARGE`; the exact measurement-time
definition is not shown. The audit therefore records `observed_at: null` and
does not silently relabel these as 06:00 observations or daily averages.

The [Federal Flood Commission's 15 January 2025 06:00
report](https://www.ffc.gov.pk/wp-content/uploads/2025/01/Annexure-I-15-01-2025-0600.pdf)
also demonstrates winter river-flow reporting. [Punjab PDMA's 18 July 2025
report](https://pdma.punjab.gov.pk/system/files/PDMA_GAUGES_AND_RIVERS_SITUATION_REPORT_18-07-2025_1300_HRS.pdf)
contains timestamped Marala, Trimmu and Balloki readings, with observations at
12:00 in that report. It is another source for real reported points, with
timestamps retained; it cannot be substituted for a missing 06:00 reading.

## Retained evidence and checks

- Reproducible sampler: `scripts/audit_marala_irsa_source.py`.
- Responses, dates, extracted values, errors and SHA-256 hashes:
  `models/source_audits/20261016T111407Z_irsa_marala/`.
- Parser checks reject wrong report dates, absent station values and unknown
  units; four tests passed in `tests/test_marala_irsa_source.py`.
- This audit changes no chart feed, gauge measurements or sealed training run.

The useful next changes are to verify the alternative source's measurement
definition, collect every date with provenance, reconcile overlaps without
overwriting conflicts, and offer a recent-history forecast view so a two-year
extreme does not hide current variation. Short-range forecasts should use
recent measured state and available rainfall/upstream inputs. Keep the
6-12-month product labelled as a seasonal outlook. Adding arbitrary wiggles or
interpolating missing readings would not improve the underlying forecast.
