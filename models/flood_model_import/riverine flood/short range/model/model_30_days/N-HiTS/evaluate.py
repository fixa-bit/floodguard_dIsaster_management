"""Evaluate N-HiTS on observed test targets and save comparison-ready outputs."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from _nhits.core.data import DataStore, load_config, resolve, years
from _nhits.core.evaluation import metrics, predict_checkpoint, season_for
from _nhits.core.training import load_checkpoint, seed_everything
from _nhits.data import BasisDataset
from _nhits.model import build_model

ROOT = Path(__file__).resolve().parent


def main():
    cfg = load_config(ROOT / 'config.yaml')
    seed_everything(cfg['training']['seeds'][0], cfg['training']['cpu_threads'])
    torch.set_flush_denormal(True)
    output = resolve(cfg, cfg['evaluation']['output_dir'])
    state = json.loads((resolve(cfg, cfg['training']['output_dir']) / 'ensemble.json').read_text(encoding='utf-8'))
    checkpoints = [load_checkpoint(p) for p in state['checkpoints']]
    store = DataStore(cfg)
    for checkpoint in checkpoints:
        if set(checkpoint['training_years']) & set(years(cfg['splits']['test'])):
            raise ValueError('A test year was used for model fitting')
        if set(checkpoint['selection_years']) & set(years(cfg['splits']['test'])):
            raise ValueError('A test year was used for checkpoint selection')
        for key, digest in checkpoint['source_hashes'].items():
            if hashlib.sha256(resolve(cfg, cfg['data'][key]).read_bytes()).hexdigest() != digest:
                raise ValueError('Input table changed after training')
    results = [predict_checkpoint(cfg, store, ck, model_factory=build_model, dataset_factory=BasisDataset)
               for ck in checkpoints]
    dataset = results[0][0]
    if any(ds.samples != dataset.samples for ds, _ in results):
        raise ValueError('Ensemble members do not share test issue dates')
    quantiles = np.mean([values for _, values in results], axis=0)
    tau = cfg['model']['quantiles']
    if not np.isfinite(quantiles).all() or (np.diff(quantiles, axis=-1) < -1e-8).any():
        raise FloatingPointError('Predictions are nonfinite or quantiles cross')
    q50 = quantiles[..., tau.index(0.5)]
    frames = store.frames
    threshold = float(cfg['evaluation']['flood_threshold_cumecs'])
    rows, detail = [], []
    for index, (basin, position) in enumerate(dataset.samples):
        frame = frames[basin]
        issue = frame.index[position]
        for lead in range(1, cfg['data']['forecast_horizon'] + 1):
            day = issue + pd.Timedelta(days=lead)
            row = {'basin_id': basin, 'issue_date': issue, 'target_date': day, 'lead_day': lead,
                   'season': season_for(day), 'observed_cumecs': frame.loc[day, cfg['data']['target_column']],
                   'NHiTS': float(q50[index, lead - 1]),
                   **{f'q{q:g}': float(quantiles[index, lead - 1, j]) for j, q in enumerate(tau)}}
            rows.append(row)
            detail.append({**row, **{f'q{q:g}': float(quantiles[index, lead - 1, j]) for j, q in enumerate(tau)}})
    table = pd.DataFrame(rows)
    observed = table[table.observed_cumecs.notna()].copy()
    output.mkdir(parents=True, exist_ok=True)
    table.to_csv(output / 'predictions.csv', index=False, na_rep='NaN')
    pd.DataFrame(detail).to_csv(output / 'forecasts_quantiles.csv', index=False, na_rep='NaN')

    overall, flood_nonflood, seasonal, calibration, detection = [], [], [], [], []
    for lead, group in observed.groupby('lead_day'):
        overall.append({'model': 'NHiTS', 'lead_day': lead,
                        **metrics(group.observed_cumecs, group.NHiTS, threshold, threshold)})
        for label, subset in [('flood', group[group.observed_cumecs >= threshold]),
                              ('non_flood', group[group.observed_cumecs < threshold])]:
            flood_nonflood.append({'model': 'NHiTS', 'lead_day': lead, 'group': label,
                                   **metrics(subset.observed_cumecs, subset.NHiTS, threshold, threshold)})
        for season, subset in group.groupby('season'):
            seasonal.append({'model': 'NHiTS', 'lead_day': lead, 'season': season,
                             **metrics(subset.observed_cumecs, subset.NHiTS, threshold, threshold)})
        lower, upper = group['q0.05'], group['q0.95']
        calibration.append({'model': 'NHiTS', 'lead_day': lead, 'n': len(group), 'nominal_coverage': 0.9,
                            'empirical_coverage': group.observed_cumecs.between(lower, upper).mean(),
                            'mean_interval_width_cumecs': (upper - lower).mean()})
        actual = group.observed_cumecs >= threshold
        predicted = group.NHiTS >= threshold
        tp, fn = int((actual & predicted).sum()), int((actual & ~predicted).sum())
        fp, tn = int((~actual & predicted).sum()), int((~actual & ~predicted).sum())
        detection.append({'lead_day': lead, 'TP': tp, 'FN': fn, 'FP': fp, 'TN': tn,
                          'flood_precision': tp / (tp + fp) if tp + fp else 0.0,
                          'flood_recall': tp / (tp + fn) if tp + fn else np.nan,
                          'false_alarm_rate': fp / (fp + tn) if fp + tn else np.nan})

    scores = pd.DataFrame(overall)
    groups = pd.DataFrame(flood_nonflood)
    seasons = pd.DataFrame(seasonal)
    calibration = pd.DataFrame(calibration)
    detection = pd.DataFrame(detection)
    for filename, frame in [('scores_by_lead.csv', scores), ('scores_flood_nonflood_by_lead.csv', groups),
                            ('scores_by_season_and_lead.csv', seasons), ('quantile_calibration.csv', calibration),
                            ('flood_detection.csv', detection)]:
        frame.to_csv(output / filename, index=False)

    source = (ROOT / '../../../evaluation comparison/common/data/marala_daily.csv').resolve()
    original = pd.read_csv(source, parse_dates=['date']).set_index('date').q_cumecs
    local = pd.read_csv(resolve(cfg, cfg['data']['daily_file']), parse_dates=['date']).set_index('date').q_cumecs
    pd.testing.assert_series_equal(local.sort_index(), original.sort_index(), check_names=False, check_dtype=False)
    verification = {'daily_input_byte_identical_to_observed_source':
                     hashlib.sha256(source.read_bytes()).hexdigest() == hashlib.sha256(resolve(cfg, cfg['data']['daily_file']).read_bytes()).hexdigest(),
                     'observed_targets_unchanged': True, 'missing_targets_remain_nan': True,
                     'test_years': sorted(observed.target_date.dt.year.unique().tolist()),
                     'observed_test_issue_lead_pairs': len(observed), 'lead30_observed_targets': int((observed.lead_day == 30).sum()),
                     'flood_threshold_training_q95_cumecs': threshold, 'no_discharge_filling': True}
    (output / 'verification.json').write_text(json.dumps(verification, indent=2) + '\n', encoding='utf-8')

    run_rows = []
    for path, ck in zip(state['checkpoints'], checkpoints):
        history = json.loads(Path(path).with_name('history.json').read_text(encoding='utf-8'))
        run_rows.append({'seed': ck['seed'], 'selected_epoch': ck['epoch'], 'epochs_run': len(history['epochs']),
                         'training_seconds': history['elapsed_seconds'], 'validation_pinball': ck['validation_pinball'],
                         'training_samples': ck['train_samples'], 'validation_samples': ck['validation_samples']})
    manifest = {'model': 'NHiTS', 'checkpoints': state['checkpoints'], 'training_years': checkpoints[0]['training_years'],
                'validation_years': checkpoints[0]['selection_years'], 'test_years': verification['test_years'],
                'observed_test_days': int(observed.target_date.nunique()), 'observed_test_issue_lead_pairs': len(observed),
                'lead30_observed_targets': verification['lead30_observed_targets'], 'flood_threshold_cumecs': threshold,
                'forecast_mode': cfg['data']['forecast_mode'], 'past_discharge_as_input': True,
                'no_discharge_filling': True, 'run_details': run_rows}
    (output / 'evaluation_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')

    final = scores[scores.lead_day.eq(30)]
    final_groups = groups[groups.lead_day.eq(30)]
    final_seasons = seasons[seasons.lead_day.eq(30)]
    lines = ['# N-HiTS: 30-day observed-test results', '',
             'Train 2016–2020; validation 2021; test 2022–2024. Missing discharge targets stayed NaN and were masked from the loss and scores.', '',
             f'Observed lead-30 targets: **{manifest["lead30_observed_targets"]}**. Flood threshold: training Q95 **{threshold:.3f} m3/s**.', '',
             '## Lead 30 overall', '', final.to_markdown(index=False, floatfmt='.3f'), '',
             '## Lead 30 flood and non-flood scores', '', final_groups.to_markdown(index=False, floatfmt='.3f'), '',
             '## Lead 30 by season', '', final_seasons.to_markdown(index=False, floatfmt='.3f'), '',
             '## Quantile interval coverage', '', calibration[calibration.lead_day.eq(30)].to_markdown(index=False, floatfmt='.3f'), '',
             '## Training run', '', pd.DataFrame(run_rows).to_markdown(index=False, floatfmt='.3f'), '',
             '**Future weather uses noisy ERA5-Land reanalysis as a stand-in, not archived 30-day forecasts. Scores are retrospective hindcast skill, not operational forecast accuracy.**', '',
             'N-HiTS uses observed past discharge and historical weather. Its held-out test years were inspected in prior project experiments and are not an untouched project-wide holdout.', '']
    report = '\n'.join(lines)
    (output / 'evaluation_report.md').write_text(report, encoding='utf-8')
    (ROOT / 'RUN_RESULTS.md').write_text(report, encoding='utf-8')
    print(final.to_string(index=False), flush=True)
    print(final_groups[['group', 'n', 'RMSE_cumecs', 'MAE_cumecs']].to_string(index=False), flush=True)
    print(detection[detection.lead_day.eq(30)].to_string(index=False), flush=True)
    print('Report:', output / 'evaluation_report.md', flush=True)


if __name__ == '__main__':
    main()
