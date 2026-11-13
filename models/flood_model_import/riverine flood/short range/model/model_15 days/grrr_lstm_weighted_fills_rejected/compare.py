"""Observed-only seasonal GRRR diagnostics, coverage, peaks and training feature gate."""
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OBSERVED = HERE.parent / 'discharge_history_lstm/data/daily_observed_priority.csv'
SEASONS = ('winter', 'pre_monsoon', 'monsoon', 'post_monsoon')
PROTOCOL = json.loads((HERE / 'protocol.json').read_text())


def season(month):
    return next(s for s, months in PROTOCOL['seasons'].items() if month in months)


def load_frame(path=None):
    frame = pd.read_csv(OBSERVED, parse_dates=['date'])
    # Include all elapsed 2016-2026 dates, including dates with neither source.
    calendar = pd.DataFrame({'date': pd.date_range('2016-01-01', '2026-10-30')})
    frame = calendar.merge(frame, on='date', how='left')
    frame['split'] = np.where(frame.date.dt.year <= 2021, 'train', np.where(frame.date.dt.year == 2022, 'validation', 'test'))
    grrr = pd.read_csv(path or HERE / 'grrr_marala_reanalysis.csv', parse_dates=['date'])
    assert not grrr.date.duplicated().any()
    frame = frame.merge(grrr, on='date', how='left')
    frame['season'] = frame.date.dt.month.map(season)
    frame['year'] = frame.date.dt.year
    frame['is_observed'] = frame.observed_discharge_m3_s.notna()
    frame['grrr_lagged_m3_s'] = frame.grrr_discharge_m3_s.shift(PROTOCOL['grrr_lag_days'])
    return frame


def metrics(actual, predicted):
    actual, predicted = np.asarray(actual, dtype=float), np.asarray(predicted, dtype=float)
    finite = np.isfinite(actual) & np.isfinite(predicted)
    actual, predicted = actual[finite], predicted[finite]
    if not len(actual):
        return dict(n=0, bias_m3_s=None, percent_bias=None, pearson_r=None, mae_m3_s=None, rmse_m3_s=None, nse=None)
    err = predicted - actual
    denom = np.sum((actual - actual.mean())**2)
    r = np.corrcoef(actual, predicted)[0, 1] if len(actual) > 2 and np.std(actual) > 0 and np.std(predicted) > 0 else None
    return dict(n=len(actual), bias_m3_s=float(err.mean()), percent_bias=float(100 * err.sum() / actual.sum()) if actual.sum() else None,
                pearson_r=float(r) if r is not None else None, mae_m3_s=float(abs(err).mean()), rmse_m3_s=float(np.sqrt(np.mean(err**2))),
                nse=float(1 - np.sum(err**2) / denom) if denom > 0 else None)


def sampled_peak(group, prediction='grrr_discharge_m3_s'):
    paired = group.dropna(subset=['observed_discharge_m3_s', prediction])
    if paired.empty:
        return dict(paired_days=0)
    obs = paired.loc[paired.observed_discharge_m3_s.idxmax()]
    pred = paired.loc[paired[prediction].idxmax()]
    peak = obs.observed_discharge_m3_s
    return dict(paired_days=len(paired), observed_peak_date=obs.date.date().isoformat(), observed_peak_m3_s=float(peak),
                modeled_peak_date=pred.date.date().isoformat(), modeled_peak_m3_s=float(pred[prediction]),
                sampled_peak_error_m3_s=float(pred[prediction] - peak), sampled_peak_error_pct=float(100 * (pred[prediction] / peak - 1)),
                error_at_observed_peak_m3_s=float(obs[prediction] - peak), error_at_observed_peak_pct=float(100 * (obs[prediction] / peak - 1)),
                sampled_peak_timing_error_days=int((pred.date - obs.date).days))


def feature_gate(frame):
    train = frame[(frame.split == 'train') & frame.is_observed].dropna(subset=['grrr_lagged_m3_s']).copy()
    overall = metrics(train.observed_discharge_m3_s, train.grrr_lagged_m3_s)
    seasonal = {s: metrics(g.observed_discharge_m3_s, g.grrr_lagged_m3_s) for s, g in train.groupby('season')}
    monthly = train.groupby(train.date.dt.month)[['observed_discharge_m3_s', 'grrr_lagged_m3_s']].transform('mean')
    anomaly = metrics(train.observed_discharge_m3_s - monthly.observed_discharge_m3_s, train.grrr_lagged_m3_s - monthly.grrr_lagged_m3_s)
    # Percent bias is undefined for centered anomalies, whose sum is zero.
    anomaly['percent_bias'] = None
    rule = PROTOCOL['feature_gate']
    passes = sum(v['n'] >= rule['minimum_season_pairs'] and (v['pearson_r'] or -1) >= rule['minimum_season_pearson'] for v in seasonal.values())
    accepted = overall['n'] >= rule['minimum_train_pairs'] and (overall['pearson_r'] or -1) >= rule['minimum_train_pearson'] and passes >= rule['minimum_passing_seasons'] and (anomaly['pearson_r'] or -1) >= rule['minimum_monthly_anomaly_pearson']
    return dict(use_grrr_feature=bool(accepted), lag_days=PROTOCOL['grrr_lag_days'], training_only=True,
                overall=overall, by_season=seasonal, monthly_anomaly=anomaly, passing_seasons=passes, rule=rule)


def main():
    output = HERE / 'comparison'
    output.mkdir(exist_ok=True)
    frame = load_frame()
    frame.to_csv(output / 'aligned_daily.csv', index=False, na_rep='nan')
    scores = []
    for scope, keys in [('overall', []), ('season', ['season']), ('year_season', ['year', 'season']), ('split_season', ['split', 'season']), ('source_basis', ['source', 'measurement_basis'])]:
        groups = [((), frame)] if not keys else frame.groupby(keys, dropna=False)
        for key, group in groups:
            if not isinstance(key, tuple):
                key = (key,)
            paired = group.dropna(subset=['observed_discharge_m3_s', 'grrr_discharge_m3_s'])
            result = dict(scope=scope, **dict(zip(keys, key)), calendar_days=len(group), observed_days=int(group.is_observed.sum()), grrr_days=int(group.grrr_discharge_m3_s.notna().sum()),
                          **metrics(group.observed_discharge_m3_s, group.grrr_discharge_m3_s), **sampled_peak(group))
            if len(paired):
                cutoff = paired.observed_discharge_m3_s.quantile(.9)
                top = paired[paired.observed_discharge_m3_s >= cutoff]
                result['top_decile_threshold_m3_s'] = float(cutoff)
                result['top_decile_percent_bias'] = metrics(top.observed_discharge_m3_s, top.grrr_discharge_m3_s)['percent_bias']
            scores.append(result)
    pd.DataFrame(scores).to_csv(output / 'scores.csv', index=False, na_rep='nan')
    coverage = frame.groupby('year').agg(calendar_days=('date', 'size'), observed_days=('is_observed', 'sum'), grrr_days=('grrr_discharge_m3_s', 'count'))
    coverage['paired_days'] = frame.assign(paired=frame.is_observed & frame.grrr_discharge_m3_s.notna()).groupby('year').paired.sum()
    coverage.to_csv(output / 'coverage_by_year.csv')
    gate = feature_gate(frame)
    report = dict(feature_gate=gate, source_receipt=json.loads((HERE / 'source_receipt.json').read_text()),
                  observed_sha256=hashlib.sha256(OBSERVED.read_bytes()).hexdigest(), protocol_sha256=hashlib.sha256((HERE / 'protocol.json').read_bytes()).hexdigest(),
                  grrr_sha256=hashlib.sha256((HERE / 'grrr_marala_reanalysis.csv').read_bytes()).hexdigest(),
                  peak_definition='Maxima and timing on identical paired observed dates only; incomplete hydrographs and seasons cannot establish true event peak/timing.',
                  bias_definition='GRRR minus observed, in m3/s; percent bias = 100 sum(GRRR-observed)/sum(observed). Calendar-date alignment; no lag optimized on test.')
    (output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    # Keep version comparison separate; never splice releases.
    previous = HERE / 'grrr_marala_reanalysis_v0.csv'
    if previous.exists():
        v0 = load_frame(previous)
        pd.DataFrame([dict(season=s, **metrics(g.observed_discharge_m3_s, g.grrr_discharge_m3_s), **sampled_peak(g)) for s, g in v0.groupby('season')]).to_csv(output / 'v0_seasonal_scores.csv', index=False)
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), constrained_layout=True)
    for s, ax in zip(SEASONS, axes.flat):
        g = frame[frame.season == s].dropna(subset=['observed_discharge_m3_s', 'grrr_discharge_m3_s'])
        ax.scatter(g.observed_discharge_m3_s, g.grrr_discharge_m3_s, s=5, alpha=.35)
        limit = max(g.observed_discharge_m3_s.max(), g.grrr_discharge_m3_s.max())
        ax.plot([0, limit], [0, limit], '--', color='gray')
        m = metrics(g.observed_discharge_m3_s, g.grrr_discharge_m3_s)
        ax.set(title=f"{s.replace('_', ' ').title()}: r={m['pearson_r']:.3f}, bias={m['percent_bias']:+.1f}%, n={m['n']}", xlabel='Observed (m³/s)', ylabel='GRRR (m³/s)')
    fig.suptitle('Marala vs GRRR: paired observed dates; raw calendar alignment')
    fig.savefig(output / 'seasonal_comparison.png', dpi=160)
    plt.close(fig)
    print(json.dumps(gate, indent=2))


if __name__ == '__main__':
    main()
