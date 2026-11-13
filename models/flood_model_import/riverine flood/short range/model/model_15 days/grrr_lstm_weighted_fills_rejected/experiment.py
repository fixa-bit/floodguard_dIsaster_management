"""Controlled GRRR feature experiment: NaN gaps vs lower-weight synthetic fills.

Both models share architecture, seed, observed normalization, chronological windows,
checkpoint policy and observed evaluation keys. All synthetic values are labeled.
"""
import hashlib
import json
import random

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from compare import HERE, OBSERVED, PROTOCOL, SEASONS, feature_gate, load_frame, metrics, sampled_peak

CONFIG = PROTOCOL['architecture']
LOOKBACK, HORIZON = CONFIG['lookback'], CONFIG['horizon']
ARMS = ('nan_gaps', 'weighted_fills')


class Forecast(nn.Module):
    def __init__(self, inputs):
        super().__init__()
        self.lstm = nn.LSTM(inputs, CONFIG['hidden_size'], batch_first=True)
        self.head = nn.Linear(CONFIG['hidden_size'], HORIZON)

    def forward(self, x):
        sequence, _ = self.lstm(x)
        return self.head(sequence[:, -1])


def calibrate_fills(frame):
    """Fit only train observations; no interpolation and no future observation use."""
    paired = frame[(frame.split == 'train') & frame.is_observed].dropna(subset=['grrr_lagged_m3_s'])
    corrected = np.full(len(frame), np.nan, dtype=float)
    parameters = {}
    for s in SEASONS:
        train = paired[paired.season == s]
        assert len(train) >= 60
        design = np.column_stack([np.ones(len(train)), train.grrr_lagged_m3_s])
        intercept, slope = np.linalg.lstsq(design, train.observed_discharge_m3_s, rcond=None)[0]
        rows = (frame.season == s) & frame.grrr_lagged_m3_s.notna() & frame.grrr_discharge_m3_s.notna()
        corrected[rows] = np.maximum(0, intercept + slope * frame.loc[rows, 'grrr_lagged_m3_s'])
        parameters[s] = dict(n=len(train), intercept_m3_s=float(intercept), slope=float(slope), first_date=str(train.date.min().date()), last_date=str(train.date.max().date()))
    filled = ~frame.is_observed.to_numpy() & np.isfinite(corrected)
    values = frame.observed_discharge_m3_s.to_numpy().copy()
    values[filled] = corrected[filled]
    return values, filled, parameters


def build_features(frame, values, filled, use_grrr, normalization):
    available = np.isfinite(values)
    mean, std = normalization['observed_mean'], normalization['observed_std']
    days = np.array([day.timetuple().tm_yday for day in frame.date]) - 1
    columns = [np.where(available, (values - mean) / std, 0), frame.is_observed.astype(float), filled.astype(float),
               np.sin(2 * np.pi * days / 365.25), np.cos(2 * np.pi * days / 365.25)]
    if use_grrr:
        grrr = frame.grrr_lagged_m3_s.to_numpy()
        columns += [np.where(np.isfinite(grrr), (grrr - normalization['grrr_mean']) / normalization['grrr_std'], 0), np.isfinite(grrr).astype(float)]
    return np.stack(columns, axis=1).astype(np.float32)


def common_origins(frame):
    observed = frame.is_observed.to_numpy()
    parts = frame.split.to_numpy()
    return {part: np.array([i for i in range(LOOKBACK, len(frame) - HORIZON + 1)
                           if np.all(parts[i:i + HORIZON] == part) and observed[i - 1]
                           and observed[i - LOOKBACK:i].sum() >= 15 and observed[i:i + HORIZON].any()], dtype=int)
            for part in ('train', 'validation', 'test')}


def build_tensors(features, values, filled, observed, origins, normalization, arm):
    mean, std = normalization['observed_mean'], normalization['observed_std']
    parts = {}
    for part, indexes in origins.items():
        x = np.stack([features[i - LOOKBACK:i] for i in indexes])
        obs_mask = np.stack([observed[i:i + HORIZON] for i in indexes])
        weights = obs_mask.astype(np.float32)
        if part == 'train' and arm == 'weighted_fills':
            weights += PROTOCOL['filled_target_weight'] * np.stack([filled[i:i + HORIZON] for i in indexes])
        targets = np.stack([np.nan_to_num((values[i:i + HORIZON] - mean) / std, nan=0) for i in indexes])
        parts[part] = tuple(torch.tensor(v, dtype=torch.float32) for v in (x, targets, weights, obs_mask))
    return parts


def train_arm(arm, tensors, normalization, output):
    seed = CONFIG['seed']
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    model = Forecast(tensors['train'][0].shape[-1])
    optimizer = torch.optim.Adam(model.parameters(), lr=CONFIG['learning_rate'])
    x, y, w, _ = tensors['train']
    loader = DataLoader(TensorDataset(x, y, w), batch_size=CONFIG['batch_size'], shuffle=True, generator=torch.Generator().manual_seed(seed))
    history, best, best_state = [], float('inf'), None
    for epoch in range(1, CONFIG['epochs'] + 1):
        model.train()
        for inputs, targets, weight in loader:
            optimizer.zero_grad()
            loss = (((model(inputs) - targets)**2) * weight).sum() / weight.sum()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1)
            optimizer.step()
        model.eval()
        with torch.no_grad():
            vx, vy, _, observed = tensors['validation']
            validation = float((((model(vx) - vy)**2) * observed).sum() / observed.sum())
        history.append(dict(epoch=epoch, observed_validation_mse_standardized=validation))
        if validation < best:
            best = validation
            best_state = {name: value.detach().clone() for name, value in model.state_dict().items()}
        print(f'{arm}: epoch {epoch}/{CONFIG["epochs"]}; observed validation MSE={validation:.5f}', flush=True)
    assert best_state is not None
    model.load_state_dict(best_state)
    torch.save(best_state, output / f'{arm}.pt')
    predictions = {}
    with torch.no_grad():
        for part in ('validation', 'test'):
            predictions[part] = np.maximum(0, model(tensors[part][0]).numpy() * normalization['observed_std'] + normalization['observed_mean'])
    return predictions, dict(selected_epoch=min(history, key=lambda h: h['observed_validation_mse_standardized'])['epoch'], history=history,
                             training_weight_sum=float(w.sum()), observed_training_target_pairs=int(tensors['train'][3].sum()))


def make_predictions(frame, origins, predictions, threshold):
    records = []
    q = frame.observed_discharge_m3_s.to_numpy()
    for part in ('validation', 'test'):
        for j, origin in enumerate(origins[part]):
            issue = frame.iloc[origin - 1]
            for lead in range(HORIZON):
                target = frame.iloc[origin + lead]
                if not target.is_observed:
                    continue
                records.append(dict(split=part, issue_after_date=issue.date, target_date=target.date, lead_days=lead + 1,
                                    observed_m3_s=q[origin + lead], nan_gaps_m3_s=float(predictions['nan_gaps'][part][j, lead]),
                                    weighted_fills_m3_s=float(predictions['weighted_fills'][part][j, lead]), persistence_m3_s=q[origin - 1],
                                    season=target.season, year=int(target.year), source=target.source, measurement_basis=target.measurement_basis,
                                    highflow=bool(q[origin + lead] >= threshold), grrr_last_input_available=bool(pd.notna(issue.grrr_lagged_m3_s))))
    result = pd.DataFrame(records)
    assert not result.duplicated(['split', 'issue_after_date', 'target_date', 'lead_days']).any()
    assert result[['observed_m3_s', 'nan_gaps_m3_s', 'weighted_fills_m3_s']].notna().all().all()
    return result


def summarize(predictions):
    records = []
    groups = [('overall', []), ('lead', ['lead_days']), ('season', ['season']), ('year', ['year']),
              ('lead_season', ['lead_days', 'season']), ('grrr_availability', ['grrr_last_input_available']),
              ('source_basis', ['source', 'measurement_basis']), ('highflow', ['highflow'])]
    for part, split_frame in predictions.groupby('split'):
        for scope, keys in groups:
            iterator = [((), split_frame)] if not keys else split_frame.groupby(keys)
            for key, group in iterator:
                if not isinstance(key, tuple):
                    key = (key,)
                for arm in (*ARMS, 'persistence'):
                    records.append(dict(split=part, scope=scope, **dict(zip(keys, key)), arm=arm,
                                        **metrics(group.observed_m3_s, group[arm + '_m3_s'])))
    return pd.DataFrame(records)


def bootstrap_test(test):
    """Resample target-date calendar blocks, keeping predictions paired and leads together."""
    daily = test.assign(a=(test.nan_gaps_m3_s - test.observed_m3_s)**2,
                        b=(test.weighted_fills_m3_s - test.observed_m3_s)**2).groupby('target_date').agg(a=('a', 'sum'), b=('b', 'sum'), n=('a', 'size'))
    daily = daily.reindex(pd.date_range(test.target_date.min(), test.target_date.max()), fill_value=0)
    values = daily[['a', 'b', 'n']].to_numpy()
    rng = np.random.default_rng(PROTOCOL['bootstrap']['seed'])
    block = PROTOCOL['bootstrap']['block_days']
    samples = []
    for _ in range(PROTOCOL['bootstrap']['replicates']):
        starts = rng.integers(0, len(values), size=(len(values) + block - 1) // block)
        indexes = ((starts[:, None] + np.arange(block)) % len(values)).ravel()[:len(values)]
        a, b, n = values[indexes].sum(axis=0)
        if n:
            samples.append(float(1 - np.sqrt(b / a)))
    return dict(improvement_fraction_95pct_ci=np.quantile(samples, [.025, .975]).tolist(),
                replicates=len(samples), block_days=block, independent_sampling_unit='30-day blocks of target calendar dates; all leads kept together')


def peak_scores(predictions):
    records = []
    for key, group in predictions.groupby(['split', 'year', 'season', 'lead_days']):
        data = group.rename(columns={'target_date': 'date', 'observed_m3_s': 'observed_discharge_m3_s'}).copy()
        data = data.reset_index(drop=True)
        for arm in ARMS:
            records.append(dict(zip(('split', 'year', 'season', 'lead_days'), key), arm=arm, **sampled_peak(data, arm + '_m3_s')))
    return pd.DataFrame(records)


def select_arm(scores, peaks, uncertainty):
    rule = PROTOCOL['clear_win']
    checks = {}
    for part in ('validation', 'test'):
        subset = scores[(scores.split == part) & (scores.scope == 'overall')].set_index('arm')
        improvement = 1 - subset.loc['weighted_fills', 'rmse_m3_s'] / subset.loc['nan_gaps', 'rmse_m3_s']
        checks[f'{part}_rmse_improvement'] = dict(passed=bool(improvement >= rule[f'minimum_{part}_rmse_improvement_fraction']), value=float(improvement), minimum=rule[f'minimum_{part}_rmse_improvement_fraction'])
    lower = uncertainty['improvement_fraction_95pct_ci'][0]
    checks['test_bootstrap_lower_positive'] = dict(passed=bool(lower > 0), value=lower)
    for scope, key, limit in [('season', 'season', 'max_season_rmse_degradation_fraction'), ('year', 'year', 'max_year_rmse_degradation_fraction'),
                              ('lead', 'lead_days', 'max_lead_rmse_degradation_fraction'), ('highflow', 'highflow', 'max_highflow_rmse_degradation_fraction')]:
        subset = scores[(scores.split == 'test') & (scores.scope == scope) & scores.arm.isin(ARMS)]
        if scope == 'highflow':
            subset = subset[subset.highflow == True]
        paired = subset.pivot(index=key, columns='arm', values='rmse_m3_s')
        worst = float((paired.weighted_fills / paired.nan_gaps - 1).max())
        checks[f'{scope}_no_material_degradation'] = dict(passed=bool(worst <= rule[limit]), worst_degradation_fraction=worst, maximum=rule[limit])
    # At least 30 observed target dates in a year-season-lead stratum; sampled peaks only.
    subset = peaks[(peaks.split == 'test') & (peaks.paired_days >= 30)].copy()
    peak_mae = subset.assign(error=subset.sampled_peak_error_m3_s.abs()).groupby('arm').error.mean()
    degradation = float(peak_mae['weighted_fills'] / peak_mae['nan_gaps'] - 1)
    checks['sampled_peak_no_material_degradation'] = dict(passed=bool(degradation <= rule['max_sampled_peak_mae_degradation_fraction']), degradation_fraction=degradation, mae_m3_s=peak_mae.to_dict())
    winner = 'weighted_fills' if all(c['passed'] for c in checks.values()) else 'nan_gaps'
    return dict(selected_arm=winner, filled_version_clearly_wins=winner == 'weighted_fills', checks=checks,
                policy='Experimental artifacts retained for audit; selected model uses fills only if every frozen criterion passes.')


def main():
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    output = HERE / 'experiment'
    output.mkdir(exist_ok=True)
    frame = load_frame()
    observed_source = pd.read_csv(OBSERVED)
    frame = frame[(frame.date >= observed_source.date.min()) & (frame.date <= observed_source.date.max())].reset_index(drop=True)
    gate = feature_gate(frame)
    use_grrr = gate['use_grrr_feature']
    if not use_grrr:
        raise RuntimeError('GRRR did not pass the frozen training-only gate; do not run synthetic filling automatically')
    original = frame.observed_discharge_m3_s.to_numpy().copy()
    observed = frame.is_observed.to_numpy()
    filled_values, filled_mask, calibration = calibrate_fills(frame)
    assert np.array_equal(original[observed], filled_values[observed])
    assert not np.any(filled_mask & ~np.isfinite(frame.grrr_discharge_m3_s.to_numpy()))
    training = (frame.split == 'train').to_numpy() & observed
    grrr_train = frame.loc[frame.split == 'train', 'grrr_lagged_m3_s'].dropna()
    normalization = dict(observed_mean=float(original[training].mean()), observed_std=float(original[training].std()),
                         grrr_mean=float(grrr_train.mean()), grrr_std=float(grrr_train.std(ddof=0)))
    threshold = float(np.quantile(original[training], .95))
    origins = common_origins(frame)
    working = frame[['date', 'split', 'season', 'source', 'measurement_basis', 'observed_discharge_m3_s', 'is_observed', 'grrr_discharge_m3_s', 'grrr_lagged_m3_s']].copy()
    working['experimental_discharge_m3_s'] = filled_values
    working['is_modeled_fill'] = filled_mask
    working['filled_from_grrr_date'] = (working.date - pd.Timedelta(days=PROTOCOL['grrr_lag_days'])).where(filled_mask)
    working['training_target_weight'] = np.where(frame.split == 'train', np.where(observed, 1., np.where(filled_mask, PROTOCOL['filled_target_weight'], 0.)), 0.)
    working.to_csv(output / 'experimental_daily.csv', index=False, na_rep='nan')
    predictions, arms = {}, {}
    for arm in ARMS:
        values = original if arm == 'nan_gaps' else filled_values
        mask = np.zeros(len(frame), dtype=bool) if arm == 'nan_gaps' else filled_mask
        features = build_features(frame, values, mask, use_grrr, normalization)
        tensors = build_tensors(features, values, mask, observed, origins, normalization, arm)
        predictions[arm], arms[arm] = train_arm(arm, tensors, normalization, output)
    paired = make_predictions(frame, origins, predictions, threshold)
    paired.to_csv(output / 'predictions_observed_days.csv', index=False)
    scores = summarize(paired)
    scores.to_csv(output / 'scores.csv', index=False, na_rep='nan')
    peaks = peak_scores(paired)
    peaks.to_csv(output / 'sampled_peak_scores.csv', index=False, na_rep='nan')
    uncertainty = bootstrap_test(paired[paired.split == 'test'])
    decision = select_arm(scores, peaks, uncertainty)
    selected = decision['selected_arm']
    if selected != 'weighted_fills':
        (output / 'weighted_fills.pt').unlink(missing_ok=True)
    # Only the selected checkpoint is designated for later use; alternatives remain experimental.
    (output / 'selected_model.json').write_text(json.dumps(dict(arm=selected, checkpoint=f'{selected}.pt', feature_gate=use_grrr,
                                                              predictors=['past discharge with observation/fill flags', 'seasonal sine/cosine', 'two-day-lagged GRRR with availability flag'],
                                                              normalization=normalization, lookback=LOOKBACK, horizon=HORIZON,
                                                              operationally_validated=False), indent=2) + '\n')
    report = dict(protocol=PROTOCOL, protocol_sha256=hashlib.sha256((HERE / 'protocol.json').read_bytes()).hexdigest(),
                  source_hashes={str(p.relative_to(HERE.parent)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (OBSERVED, HERE / 'grrr_marala_reanalysis.csv', HERE / 'source_receipt.json')},
                  feature_gate=gate, normalization=normalization, calibration=calibration, highflow_threshold_m3_s=threshold,
                  highflow_definition='Observed training 95th percentile; descriptive diagnostic, not an official flood category.',
                  fill_counts={p: dict(days=int((frame.split == p).sum()), observed=int(((frame.split == p) & frame.is_observed).sum()),
                                       filled=int((filled_mask & (frame.split == p)).sum()), remaining_nan=int((~np.isfinite(filled_values) & (frame.split == p)).sum())) for p in origins},
                  origins={p: len(o) for p, o in origins.items()}, arms=arms, uncertainty=uncertainty, decision=decision,
                  numpy_version=np.__version__, torch_version=torch.__version__,
                  limitations=['Single seeded architecture comparison; no seed uncertainty or hyperparameter search.',
                               'Overlapping leads and dates are dependent; bootstrap approximates target-date clustering, not independent flood-event uncertainty.',
                               'Daily reanalysis from a previously trained global model; global-model training overlap with local holdouts is unverified.',
                               'Later observations are sparse and measurement bases differ; matched observed-day scores do not validate complete hydrographs.',
                               '2026 lacks GRRR, so 2026 gaps remain unfilled; newer release interval metadata inferred from GRRR family.',
                               'GRRR is complete during training; unavailable-GRRR inputs in 2026 are outside the training feature-availability pattern.',
                               'Both arms use the GRRR feature: the two-arm comparison isolates filling; it does not establish incremental feature skill versus a matched no-GRRR model.'])
    (output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    fig, ax = plt.subplots(figsize=(8, 4), constrained_layout=True)
    for arm in (*ARMS, 'persistence'):
        rows = scores[(scores.split == 'test') & (scores.scope == 'lead') & (scores.arm == arm)].sort_values('lead_days')
        ax.plot(rows.lead_days, rows.rmse_m3_s, marker='o', label=arm.replace('_', ' '))
    ax.set(xlabel='Lead (days)', ylabel='RMSE (m³/s)', title='Identical observed test pairs, 2023–2026')
    ax.legend()
    fig.savefig(output / 'observed_test_rmse.png', dpi=160)
    plt.close(fig)
    print(json.dumps(dict(fill_counts=report['fill_counts'], decision=decision, uncertainty=uncertainty), indent=2))


if __name__ == '__main__':
    main()
