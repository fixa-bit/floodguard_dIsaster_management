"""Score calibrated physical HBV forecasts on observed targets only."""
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent


def metrics(y, p, threshold):
    y, p = np.asarray(y, float), np.asarray(p, float)
    keep = np.isfinite(y) & np.isfinite(p)
    y, p = y[keep], p[keep]
    if not len(y):
        return {'n': 0}
    err = p - y
    variance = np.square(y - y.mean()).sum()
    r = np.corrcoef(y, p)[0, 1] if len(y) > 1 and y.std() > 0 and p.std() > 0 else np.nan
    kge = (1 - np.sqrt((r - 1) ** 2 + (p.std() / y.std() - 1) ** 2 + (p.mean() / y.mean() - 1) ** 2)
           if np.isfinite(r) and y.mean() > 0 else np.nan)
    flood = y > threshold
    alerts = p > threshold
    tp, fp = int((flood & alerts).sum()), int((~flood & alerts).sum())
    return {
        'n': len(y), 'NSE': 1 - np.square(err).sum() / variance if variance > 0 else np.nan,
        'KGE': kge, 'RMSE_cumecs': float(np.sqrt(np.square(err).mean())),
        'MAE_cumecs': float(np.abs(err).mean()),
        'PBIAS_pct': float(100 * err.sum() / y.sum()) if y.sum() else np.nan,
        'peak_n': int(flood.sum()),
        'flood_hit_rate': tp / flood.sum() if flood.any() else np.nan,
        'false_alarm_rate': fp / (~flood).sum() if (~flood).any() else np.nan,
        'false_alarm_ratio': fp / alerts.sum() if alerts.any() else np.nan,
    }


def season(month):
    return 'Oct-Mar' if month in (10, 11, 12, 1, 2, 3) else 'Apr-Jun' if month in (4, 5, 6) else 'Jul-Sep'


def score_file(path, threshold, report_dir):
    frame = pd.read_csv(path, parse_dates=['target_date'])
    scores, seasonal, subsets = [], [], []
    for lead, group in frame.groupby('lead_day'):
        scores.append({'model': 'Calibrated_HBV', 'lead_day': int(lead), **metrics(group.observed_cumecs, group.Calibrated_HBV, threshold)})
        for name, part in group.assign(season=group.target_date.dt.month.map(season)).groupby('season'):
            seasonal.append({'model': 'Calibrated_HBV', 'lead_day': int(lead), 'season': name,
                             **metrics(part.observed_cumecs, part.Calibrated_HBV, threshold)})
        for name, part in [('all', group), ('flood', group[group.observed_cumecs > threshold]),
                           ('non_flood', group[group.observed_cumecs <= threshold])]:
            subsets.append({'model': 'Calibrated_HBV', 'lead_day': int(lead), 'group': name,
                            **metrics(part.observed_cumecs, part.Calibrated_HBV, threshold)})
    report_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(scores).to_csv(report_dir / 'scores_by_lead.csv', index=False)
    pd.DataFrame(seasonal).to_csv(report_dir / 'scores_by_season_and_lead.csv', index=False)
    pd.DataFrame(subsets).to_csv(report_dir / 'scores_flood_nonflood_by_lead.csv', index=False)
    return frame, pd.DataFrame(scores), pd.DataFrame(seasonal), pd.DataFrame(subsets)


def main():
    cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    calibration = json.loads((ROOT / cfg['output_dir'] / 'calibration.json').read_text(encoding='utf-8'))
    threshold = float(calibration['flood_threshold_cumecs']) if 'flood_threshold_cumecs' in calibration else None
    if threshold is None:
        daily = pd.read_csv(ROOT / cfg['daily_file'], parse_dates=['date'])
        training = daily.loc[daily.date.dt.year.between(cfg['first_training_year'], cfg['last_training_year']), 'q_cumecs'].dropna()
        threshold = float(training.quantile(cfg['flood_percentile']))
    test_dir = ROOT / cfg['test_output_dir']
    test, scores, seasonal, groups = score_file(test_dir / 'predictions.csv', threshold, test_dir)
    validation_dir = ROOT / cfg['validation_output_dir']
    _, val_scores, _, _ = score_file(validation_dir / 'predictions.csv', threshold, validation_dir)
    summary = {
        'flood_threshold_training_q95_cumecs': threshold,
        'test_years': list(range(cfg['test_years'][0], cfg['test_years'][1] + 1)),
        'test_observed_targets_lead_30': int(test.loc[test.lead_day.eq(cfg['horizon']), 'observed_cumecs'].notna().sum()),
        'test_unique_observed_dates': int(test.target_date.nunique()),
        'test_issue_lead_targets': int(len(test)), 'validation_years': list(range(cfg['validation_years'][0], cfg['validation_years'][1] + 1)),
        'validation_observed_targets_lead_30': int(val_scores.loc[val_scores.lead_day.eq(cfg['horizon']), 'n'].iloc[0]),
        'calibration_cutoff_year': cfg['last_training_year'],
        'future_forcing': 'ERA5-Land reanalysis rainfall quantile-mapped to CHIRPS; temperature identity-mapped; training-only PET climatology',
    }
    (test_dir / 'evaluation_manifest.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    selected = scores[scores.lead_day.isin([1, 10, 20, 30])]
    flood30 = groups[(groups.lead_day == cfg['horizon']) & groups.group.isin(['flood', 'non_flood'])]
    lines = [
        '# Calibrated physical HBV: 30-day results', '',
        f"Calibration used observed discharge from {cfg['first_training_year']}-{cfg['last_training_year']} after {cfg['warmup_days']} spin-up days. Validation: {cfg['validation_years'][0]}-{cfg['validation_years'][1]}. Test: {cfg['test_years'][0]}-{cfg['test_years'][1]}.",
        f"Observed day-30 test targets: **{summary['test_observed_targets_lead_30']}**. Missing targets were skipped; no discharge values were filled.", '',
        f"Training-period flood threshold (Q{int(cfg['flood_percentile']*100)}): **{threshold:.3f} m3/s**.", '',
        '## Lead scores', '',
        '| lead_day | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct |',
        '|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for row in selected.itertuples(index=False):
        lines.append(f'| {row.lead_day} | {row.n} | {row.NSE:.3f} | {row.KGE:.3f} | {row.RMSE_cumecs:.3f} | {row.MAE_cumecs:.3f} | {row.PBIAS_pct:.3f} |')
    lines += ['', '## Flood and non-flood scores at day 30', '',
              '| class | n | NSE | KGE | RMSE_cumecs | MAE_cumecs |',
              '|---|---:|---:|---:|---:|---:|']
    for row in flood30.itertuples(index=False):
        lines.append(f'| {row.group} | {row.n} | {row.NSE:.3f} | {row.KGE:.3f} | {row.RMSE_cumecs:.3f} | {row.MAE_cumecs:.3f} |')
    lines += ['', 'Future forcing uses reanalysis weather as a forecast stand-in. These are retrospective hindcast scores, not operational 30-day forecast skill.', '']
    (test_dir / 'evaluation_report.md').write_text('\n'.join(lines), encoding='utf-8')
    comparison = ROOT / cfg['comparison_dir']
    comparison.mkdir(parents=True, exist_ok=True)
    test.to_csv(comparison / 'matched_predictions.csv', index=False)
    scores.to_csv(comparison / 'scores_by_lead.csv', index=False)
    groups.to_csv(comparison / 'scores_flood_nonflood_by_lead.csv', index=False)
    (comparison / 'comparison_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(pd.DataFrame(selected).to_string(index=False), flush=True)
    print(f"Lead-30 observed targets: {summary['test_observed_targets_lead_30']}; report: {test_dir / 'evaluation_report.md'}", flush=True)


if __name__ == '__main__':
    main()
