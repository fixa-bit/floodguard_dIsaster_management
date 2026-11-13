"""Rebuild a separate observed-priority Marala dataset using only local sources."""
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = HERE.parents[2] / 'dataset/chenab_marala'
SOURCE = MODEL / 'processed/marala/discharge/marala_discharge_all_sources.csv'
OUT = HERE / 'data'
FACTOR = 0.028316846592


def split(day):
    return 'train' if day.year <= 2021 else 'validation' if day.year == 2022 else 'test'


def interpolate(rows):
    """Fill bounded 1-3 day gaps, never across partitions or measurement bases."""
    i = 0
    while i < len(rows):
        if rows[i]['is_observed']:
            i += 1
            continue
        start = i
        while i < len(rows) and not rows[i]['is_observed']:
            i += 1
        n = i - start
        if start == 0 or i == len(rows) or n > 3:
            continue
        left, right = rows[start - 1], rows[i]
        if left['split'] != right['split'] or left['measurement_basis'] != right['measurement_basis']:
            continue
        for k in range(n):
            row = rows[start + k]
            row['discharge_with_short_fill_m3_s'] = left['observed_discharge_m3_s'] + (right['observed_discharge_m3_s'] - left['observed_discharge_m3_s']) * (k + 1) / (n + 1)
            row['is_interpolated'] = 1
            row['interpolation_left_date'] = left['date']
            row['interpolation_right_date'] = right['date']
            row['quality_note'] += '; retrospective interpolation; right endpoint unavailable before its observation'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    records = list(csv.DictReader(SOURCE.open(encoding='utf-8-sig', newline='')))
    grouped = defaultdict(list)
    excluded = []
    for r in records:
        reason = ''
        if r['station'] != 'Marala' or r['measurement'] not in ('inflow', 'mean_inflow'):
            reason = 'not daily inflow (outflow or selected event peak)'
        elif 'printed_date_differs_from_archive' in r['quality_flag']:
            reason = 'unresolved printed/archive date disagreement'
        elif not math.isfinite(float(r['discharge_cusecs'])) or float(r['discharge_cusecs']) <= 0:
            reason = 'nonfinite or nonpositive discharge needs review'
        if reason:
            excluded.append({**r, 'exclusion_reason': reason})
        else:
            grouped[r['date']].append(r)
    start, end = min(grouped), max(grouped)
    rows, conflicts = [], []
    priority = {'WAPDA': 0, 'FFD/PMD': 1, 'IRSA': 2}
    day = date.fromisoformat(start)
    while day <= date.fromisoformat(end):
        candidates = grouped.get(day.isoformat(), [])
        candidates.sort(key=lambda r: (priority.get(r['source'], 99), r['source_file']))
        # Disagreements within the top-priority source cannot be resolved by filename.
        top = [r for r in candidates if r['source'] == candidates[0]['source']] if candidates else []
        ambiguous = len({float(r['discharge_cusecs']) for r in top}) > 1
        selected = candidates[0] if candidates and not ambiguous else None
        values = {float(r['discharge_cusecs']) for r in candidates}
        if len(values) > 1:
            conflicts.extend({**r, 'selected': int(r is selected)} for r in candidates)
        q = float(selected['discharge_cusecs']) * FACTOR if selected else float('nan')
        basis = ('daily_mean_unknown_bounds' if selected['source'] == 'IRSA' else 'dated_reading_time_unconfirmed' if selected['source'] == 'WAPDA' and not selected['time_pakistan'] else 'point_reading_0600_PKT') if selected else ''
        rows.append(dict(date=day.isoformat(), split=split(day), observed_discharge_m3_s=q,
                         discharge_with_short_fill_m3_s=q, is_observed=int(selected is not None),
                         is_interpolated=0, observed_target_mask=int(selected is not None),
                         source=selected['source'] if selected else '', measurement_basis=basis,
                         time_pakistan=selected['time_pakistan'] if selected else '',
                         source_url=selected['source_url'] if selected else '',
                         source_file=selected['source_file'] if selected else '',
                         candidate_count=len(candidates), source_disagreement=int(len(values) > 1),
                         quality_note=('unresolved within-source conflict' if ambiguous else selected['quality_flag'] if selected else 'no eligible observed record'),
                         interpolation_left_date='', interpolation_right_date=''))
        day += timedelta(days=1)
    interpolate(rows)
    def write(name, data):
        if not data:
            return
        with (OUT / name).open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    write('daily_observed_priority.csv', rows)
    write('excluded_candidates.csv', excluded)
    write('source_conflicts.csv', conflicts)
    report = dict(source_catalog_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  start=start, end=end, days=len(rows), observed=sum(r['is_observed'] for r in rows),
                  interpolated=sum(r['is_interpolated'] for r in rows),
                  remaining_nan=sum(not math.isfinite(r['discharge_with_short_fill_m3_s']) for r in rows),
                  selected_sources=dict(Counter(r['source'] for r in rows if r['is_observed'])),
                  by_split={s: dict(days=sum(r['split'] == s for r in rows), observed=sum(r['is_observed'] for r in rows if r['split'] == s)) for s in ('train', 'validation', 'test')},
                  source_disagreement_dates=sum(r['source_disagreement'] for r in rows),
                  priority=['WAPDA', 'FFD/PMD', 'IRSA'],
                  policy='Keep WAPDA in cross-source disagreements; reject ambiguous dates and within-source conflicts. IRSA daily means are observed but have a different measurement basis. Event peaks and outflows excluded. Observed targets only; interpolated values never become observations.',
                  glofas='No local GloFAS dataset found; no synthetic filling performed.')
    (OUT / 'preparation_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
