"""Evaluate HBV plus LSTM residual correction on observed targets only."""
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent


def metrics(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    valid = np.isfinite(y) & np.isfinite(p)
    y, p = y[valid], p[valid]
    if not len(y):
        return {'n': 0}
    error = p - y
    var = np.square(y - y.mean()).sum()
    corr = np.corrcoef(y, p)[0, 1] if len(y) > 1 and y.std() > 0 and p.std() > 0 else np.nan
    kge = (1 - np.sqrt((corr - 1) ** 2 + (p.std() / y.std() - 1) ** 2 + (p.mean() / y.mean() - 1) ** 2)
           if np.isfinite(corr) and y.mean() > 0 else np.nan)
    return {'n': len(y), 'NSE': 1 - np.square(error).sum() / var if var > 0 else np.nan,
            'KGE': kge, 'RMSE_cumecs': float(np.sqrt(np.square(error).mean())),
            'MAE_cumecs': float(np.abs(error).mean()),
            'PBIAS_pct': float(100 * error.sum() / y.sum()) if y.sum() else np.nan}


def main():
    cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    cal = json.loads((ROOT / cfg['base_calibration']).read_text(encoding='utf-8'))
    q = pd.read_csv(ROOT / cfg['daily_file'], parse_dates=['date'])
    train_q = q.loc[q.date.dt.year.between(cfg['first_training_year'], cfg['last_training_year']), 'q_cumecs'].dropna()
    threshold = float(train_q.quantile(0.95))
    test_dir = ROOT / cfg['test_output_dir']
    predictions = pd.read_csv(test_dir / 'predictions.csv', parse_dates=['target_date'])
    detail = pd.read_csv(test_dir / 'forecast_detail.csv', parse_dates=['target_date'])
    rows, season_rows, class_rows = [], [], []
    for lead, group in detail.groupby('lead_day'):
        for model, column in [('HBV_physical', 'HBV_physical'), ('HBV_LSTM', 'hybrid_p50')]:
            rows.append({'model': model, 'lead_day': int(lead), **metrics(group.observed_cumecs, group[column])})
            for season, sub in group.assign(season=group.target_date.dt.month.map(
                    lambda m: 'Oct-Mar' if m in (10, 11, 12, 1, 2, 3) else 'Apr-Jun' if m in (4, 5, 6) else 'Jul-Sep')).groupby('season'):
                season_rows.append({'model': model, 'lead_day': int(lead), 'season': season,
                                    **metrics(sub.observed_cumecs, sub[column])})
            if int(lead) == cfg['horizon']:
                for name, selected in [('flood', group.observed_cumecs > threshold),
                                       ('non_flood', group.observed_cumecs <= threshold)]:
                    part = group.loc[selected]
                    class_rows.append({'model': model, 'lead_day': int(lead), 'group': name,
                                       **metrics(part.observed_cumecs, part[column])})
    scores = pd.DataFrame(rows)
    seasonal = pd.DataFrame(season_rows)
    classes = pd.DataFrame(class_rows)
    scores.to_csv(test_dir / 'scores_by_lead.csv', index=False)
    seasonal.to_csv(test_dir / 'scores_by_season_and_lead.csv', index=False)
    classes.to_csv(test_dir / 'scores_flood_nonflood_by_lead.csv', index=False)
    manifest = {
        'forecast_horizon_days': cfg['horizon'],
        'training_years': list(range(cfg['first_training_year'], cfg['last_training_year'] + 1)),
        'validation_years': list(range(cfg['validation_years'][0], cfg['validation_years'][1] + 1)),
        'test_years': list(range(cfg['test_years'][0], cfg['test_years'][1] + 1)),
        'observed_test_targets_lead_30': int(predictions.loc[predictions.lead_day.eq(cfg['horizon']), 'observed_cumecs'].notna().sum()),
        'observed_issue_lead_pairs': len(predictions), 'training_q95_flood_threshold_cumecs': threshold,
        'physical_base_calibration_kge': cal['calibration_kge'],
        'future_forcing': 'ERA5-Land reanalysis weather as hindcast proxy; PET from training climatology',
        'discharge_values_filled_or_modified': False,
    }
    (test_dir / 'evaluation_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    selected = scores.loc[scores.lead_day.isin([1, 10, 20, 30])]
    flood30 = classes.loc[classes.lead_day.eq(cfg['horizon'])]
    lines = [
        '# HBV plus LSTM residual correction: 30-day results', '',
        'The LSTM predicts the physical HBV model error from past hydro-weather features and the 30-day HBV/weather trajectory. The median predicted residual is added to physical HBV flow; the 10th and 90th residual quantiles are also saved.', '',
        f"Train: {cfg['first_training_year']}-{cfg['last_training_year']}; early stopping validation: {cfg['validation_years'][0]}-{cfg['validation_years'][1]}; observed test: {cfg['test_years'][0]}-{cfg['test_years'][1]}. Day-30 observed targets: **{manifest['observed_test_targets_lead_30']}**.",
        f"Flood threshold: training Q95 = **{threshold:.3f} m3/s**. Missing targets were omitted; no discharge values were changed.", '',
        '## Lead scores', '', '| Model | lead_day | n | NSE | KGE | RMSE_cumecs | MAE_cumecs | PBIAS_pct |',
        '|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for row in selected.itertuples(index=False):
        lines.append(f'| {row.model} | {row.lead_day} | {row.n} | {row.NSE:.3f} | {row.KGE:.3f} | {row.RMSE_cumecs:.3f} | {row.MAE_cumecs:.3f} | {row.PBIAS_pct:.3f} |')
    lines += ['', '## Flood and non-flood flow errors at lead 30', '',
              '| Model | Group | n | NSE | RMSE_cumecs | MAE_cumecs |', '|---|---|---:|---:|---:|---:|']
    for row in flood30.itertuples(index=False):
        lines.append(f'| {row.model} | {row.group} | {row.n} | {row.NSE:.3f} | {row.RMSE_cumecs:.3f} | {row.MAE_cumecs:.3f} |')
    lines += ['', 'Future weather is a reanalysis proxy, so this is a retrospective hindcast evaluation rather than operational 30-day forecast skill.', '']
    (test_dir / 'evaluation_report.md').write_text('\n'.join(lines), encoding='utf-8')
    comparison = ROOT / cfg['comparison_dir']
    comparison.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(comparison / 'matched_predictions.csv', index=False)
    scores.to_csv(comparison / 'scores_by_lead.csv', index=False)
    classes.to_csv(comparison / 'scores_flood_nonflood_by_lead.csv', index=False)
    (comparison / 'comparison_report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(pd.DataFrame(selected).to_string(index=False), flush=True)
    print(f"Lead-30 observed targets: {manifest['observed_test_targets_lead_30']}; report: {test_dir / 'evaluation_report.md'}", flush=True)


if __name__ == '__main__':
    main()
