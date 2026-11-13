"""Evaluate selected checkpoints once on observed held-out discharge."""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

from .core.data import DataStore, StreamflowDataset, load_config, resolve, years
from .core.evaluation import markdown, metrics, predict_checkpoint, season_for
from .core.training import load_checkpoint, seed_everything
from _nbeatsx.data import BasisDataset
from _nbeatsx.model import build_model


MODEL_ROOT = Path(__file__).resolve().parents[1]


def evaluate_family(name, path):
    cfg = load_config(path)
    seed_everything(cfg['training']['seeds'][0], cfg['training']['cpu_threads'])
    torch.set_flush_denormal(True)
    output = resolve(cfg, cfg['evaluation']['output_dir'])
    if name == 'Matched_LSTM':
        output = Path(cfg['_root']) / 'controls/lstm/reports/initial'
    state = json.loads((resolve(cfg, cfg['training']['output_dir']) / 'ensemble.json').read_text())
    checkpoints = [load_checkpoint(p) for p in state['checkpoints']]
    store = DataStore(cfg)
    for ck in checkpoints:
        for key, digest in ck['source_hashes'].items():
            if hashlib.sha256(resolve(cfg, cfg['data'][key]).read_bytes()).hexdigest() != digest:
                raise ValueError('Source data changed after training')
    results = [predict_checkpoint(cfg, store, ck, model_factory=build_model, dataset_factory=BasisDataset) for ck in checkpoints]
    ds = results[0][0]
    if any(other.samples != ds.samples for other, _ in results):
        raise ValueError('Seed members do not share test issue dates')
    quantile_prediction = np.mean([values for _, values in results], axis=0)
    tau = cfg['model']['quantiles']; median = quantile_prediction[..., tau.index(.5)]
    # Independent same-date check against the original weather-only LSTM experiment.
    reference_cfg = load_config(resolve(cfg, cfg['reference']['config']))
    reference_ck = load_checkpoint(resolve(cfg, cfg['reference']['checkpoint']))
    reference = StreamflowDataset(DataStore(reference_cfg), 'test', reference_ck['statistics'])
    if reference.samples != ds.samples:
        raise ValueError('Original and new model issue/target dates do not match')
    for index in range(len(ds)):
        torch.testing.assert_close(ds[index]['future'], reference[index]['future'], atol=0, rtol=0)
    train = store.frames[cfg['data']['default_basin_id']]
    observed_train = train.loc[train.index.year.isin(years(cfg['splits']['train'])), cfg['data']['target_column']].dropna()
    threshold = float(observed_train.quantile(cfg['evaluation']['peak_percentile']))
    flood = cfg['evaluation']['flood_threshold_cumecs']
    flood = threshold if flood is None else float(flood)
    rows = []
    for index in range(len(ds)):
        basin, issue = ds.metadata(index)
        for lead in range(1, cfg['data']['forecast_horizon'] + 1):
            day = issue + pd.Timedelta(days=lead)
            rows.append({'basin_id': basin, 'issue_date': issue, 'target_date': day, 'lead_day': lead,
                         'season': season_for(day), 'observed_cumecs': store.frames[basin].loc[day, cfg['data']['target_column']],
                         name: median[index, lead - 1],
                         **{f'q{q:g}': quantile_prediction[index, lead - 1, j] for j, q in enumerate(tau)}})
    table = pd.DataFrame(rows); valid = table[table.observed_cumecs.notna()]
    overall, groups, seasonal, calibration, detection = [], [], [], [], []
    for lead, group in valid.groupby('lead_day'):
        overall.append({'model': name, 'lead_day': lead, **metrics(group.observed_cumecs, group[name], threshold, flood)})
        for label, subset in [('flood', group[group.observed_cumecs > flood]), ('non_flood', group[group.observed_cumecs <= flood])]:
            groups.append({'model': name, 'lead_day': lead, 'group': label, **metrics(subset.observed_cumecs, subset[name], threshold, flood)})
        calibration.append({'model': name, 'lead_day': lead, 'n': len(group), 'nominal_coverage': tau[-1] - tau[0],
                            'empirical_coverage': float(group.observed_cumecs.between(group[f'q{tau[0]:g}'], group[f'q{tau[-1]:g}']).mean()),
                            'mean_interval_width_cumecs': float((group[f'q{tau[-1]:g}'] - group[f'q{tau[0]:g}']).mean())})
        observed_alert = group.observed_cumecs > flood; predicted_alert = group[name] > flood
        tp = int((observed_alert & predicted_alert).sum()); fn = int((observed_alert & ~predicted_alert).sum())
        fp = int((~observed_alert & predicted_alert).sum()); tn = int((~observed_alert & ~predicted_alert).sum())
        divide = lambda a, b: a / b if b else np.nan
        detection.append({'model': name, 'lead_day': lead, 'TP': tp, 'FN': fn, 'FP': fp, 'TN': tn,
                          'POD': divide(tp, tp + fn), 'false_alarm_ratio': divide(fp, tp + fp),
                          'false_alarm_rate': divide(fp, fp + tn), 'CSI': divide(tp, tp + fp + fn)})
    for (lead, season), group in valid.groupby(['lead_day', 'season']):
        seasonal.append({'model': name, 'lead_day': lead, 'season': season, **metrics(group.observed_cumecs, group[name], threshold, flood)})
    overall, groups, seasonal, calibration, detection = map(pd.DataFrame, [overall, groups, seasonal, calibration, detection])
    output.mkdir(parents=True, exist_ok=True)
    table.to_csv(output / 'predictions.csv', index=False, na_rep='NaN')
    for filename, data in [('scores_by_lead', overall), ('scores_flood_nonflood_by_lead', groups),
                           ('scores_by_season_and_lead', seasonal), ('quantile_calibration', calibration), ('flood_detection', detection)]:
        data.to_csv(output / f'{filename}.csv', index=False)
    counts = valid[['basin_id', 'target_date']].drop_duplicates().assign(year=lambda x: x.target_date.dt.year).groupby('year').size().reset_index(name='observed_days')
    run_rows = []
    for checkpoint_path, ck in zip(state['checkpoints'], checkpoints):
        history = json.loads(Path(checkpoint_path).with_name('history.json').read_text())
        model = build_model(cfg, tuple(ck['dimensions']), ck['statistics'])
        run_rows.append({'seed': ck['seed'], 'epochs_run': len(history['epochs']), 'selected_epoch': ck['epoch'],
                         'validation_pinball': ck['validation_pinball'], 'training_seconds': history['elapsed_seconds'],
                         'trainable_parameters': sum(p.numel() for p in model.parameters() if p.requires_grad),
                         'train_samples': ck['train_samples'], 'validation_samples': ck['validation_samples']})
    manifest = {'model': name, 'checkpoints': state['checkpoints'], 'test_years': sorted(valid.target_date.dt.year.unique().tolist()),
                'unique_observed_test_days': int(counts.observed_days.sum()), 'observed_issue_lead_pairs': len(valid),
                'missing_target_pairs_not_scored': int(table.observed_cumecs.isna().sum()), 'peak_threshold_cumecs': threshold,
                'flood_threshold_cumecs': flood, 'past_discharge': True, 'forecast_mode': cfg['data']['forecast_mode'],
                'all_future_weather_inputs_identical_to_original_experiment': True,
                'source_sha256': hashlib.sha256(resolve(cfg, cfg['data']['daily_file']).read_bytes()).hexdigest(),
                'no_discharge_filling': True, 'run_details': run_rows}
    (output / 'evaluation_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    cols = ['model', 'lead_day', 'n', 'NSE', 'KGE', 'PBIAS_pct', 'RMSE_cumecs', 'MAE_cumecs', 'peak_MAPE_pct']
    report = [f'# {name}: actual Marala evaluation', '',
              '**Observed-only retrospective test under noisy future reanalysis weather. Operational forecast accuracy is unverified.**', '',
              f'Train 2016-2020, validation 2021, test 2022-2024. Unique observed test days: {manifest["unique_observed_test_days"]}; '
              f'scored issue/lead pairs: {len(valid)}; missing-target pairs excluded: {manifest["missing_target_pairs_not_scored"]}.', '',
              markdown(overall[overall.lead_day.isin([1, 5, 10])][cols]), '',
              '## Flood and non-flood days at lead 10', '', markdown(groups[groups.lead_day.eq(10)]), '',
              f'Flood proxy is observed flow > training Q95 = {flood:.6f} m3/s; this is not an official warning level. '
              'Groups use observed flow, not the prediction. Subset NSE uses its own group mean and variance.', '',
              '## Point-forecast flood detection at lead 10', '', markdown(detection[detection.lead_day.eq(10)]), '',
              '## Quantile coverage', '', markdown(calibration), '',
              ('The matched LSTM uses its original positive-increment head to enforce quantile ordering. ' if name == 'Matched_LSTM' else
               'The original basis outputs are projected to ordered quantiles by sorting. ')
              + 'Ordering is guaranteed; empirical coverage is measured and is not guaranteed. '
              'Multiple seeds average their corresponding quantile outputs, which are not exact mixture quantiles.', '',
              '## Actual training', '', markdown(pd.DataFrame(run_rows)), '',
              'Single frozen configuration and one seed per architecture; no HPO sweep or test-driven retry was performed. '
              'Early stopping/checkpoint selection use validation pinball loss only. Synthetic tests establish implementation behavior only.', '',
              '## Observed days by year', '', markdown(counts), '', '## Seasonal scores', '', markdown(seasonal), '',
              '## Limits', '',
              'Past discharge and historical ERA5-Land rain/temperature are additional inputs compared with the old weather-only LSTM. '
              'Use the newly trained matched-input LSTM to assess the architecture comparison. All future rain/temperature channels and errors match the old experiment exactly. '
              'Future observed discharge is never supplied. Missing past inputs use training means with separate indicators, while targets remain NaN and masked.', '',
              'The networks were trained from scratch, not from global pretrained weights. '
              'N-HiTS/N-BEATSx computational blocks are copied from pinned Nixtla source; the matched LSTM uses this project\'s existing encoder-decoder. '
              'Data windows, training-only normalization, masking, AdamW, dropout, small widths and basis-model quantile ordering are project adaptations. '
              'The comparison period was inspected in earlier experiments and is not an untouched project-wide holdout. '
              'Limited independent floods, regulation, observation times and operational weather latency remain limitations.', '']
    (output / 'evaluation_report.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    readme = Path(cfg['_root']) / ('README.md' if name != 'Matched_LSTM' else 'controls/lstm/README.md')
    readme.parent.mkdir(parents=True, exist_ok=True)
    body = readme.read_text(encoding='utf-8').split('<!-- REAL_RESULTS -->')[0] if readme.exists() else f'# {name}\n\n'
    readme.write_text(body + '<!-- REAL_RESULTS -->\n\n## Actual observed-test results\n\n'
                      + markdown(overall[overall.lead_day.isin([1, 5, 10])][cols]) + '\n\n'
                      + markdown(groups[groups.lead_day.eq(10)][['group', 'n', 'NSE', 'KGE', 'RMSE_cumecs', 'MAE_cumecs', 'PBIAS_pct']])
                      + '\n\nThese use noisy future reanalysis; operational forecast accuracy is unverified. Full files are in reports/initial/.\n', encoding='utf-8')
    (Path(cfg['_root']) / ('RUN_RESULTS.md' if name != 'Matched_LSTM' else 'controls/lstm/RUN_RESULTS.md')).write_text('\n'.join(report) + '\n', encoding='utf-8')
    print(name, overall[overall.lead_day.eq(10)][cols].to_string(index=False), flush=True)
    return overall, groups, pd.DataFrame(run_rows).assign(model=name), table


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(MODEL_ROOT / 'config.yaml'))
    args = parser.parse_args()
    cfg = load_config(args.config)
    name = 'NHITS' if cfg['architecture']['name'] == 'nhits' else 'NBEATSx' if cfg['architecture']['name'] == 'nbeatsx' else 'Matched_LSTM'
    evaluate_family(name, args.config)


if __name__ == '__main__':
    main()
