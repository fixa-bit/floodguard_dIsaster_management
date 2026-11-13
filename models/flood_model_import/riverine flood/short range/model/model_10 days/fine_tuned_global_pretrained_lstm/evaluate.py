"""Compare the global transfer with the saved local LSTM on identical observations."""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

import argparse
import hashlib
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import DataStore, load_config as local_config
from evaluate import markdown, metrics, predict_checkpoint, season_for
from lstm.train import load_checkpoint
from fine_tuned_global_pretrained_lstm.data import GlobalDataset, inverse_flow, load_config, resolve
from fine_tuned_global_pretrained_lstm.finetune import KEYS, check_years, configure_seed, years
from fine_tuned_global_pretrained_lstm.model import GlobalPretrainedLSTM


def predict(model, dataset, cfg):
    model.eval()
    outputs = []
    with torch.no_grad():
        for batch in DataLoader(dataset, batch_size=cfg['training']['batch_size'], shuffle=False):
            outputs.append(model(*(batch[k] for k in KEYS)).numpy())
    result = inverse_flow(np.concatenate(outputs), dataset.norm, dataset.area_km2)
    if not np.isfinite(result).all():
        raise FloatingPointError('Nonfinite discharge predictions')
    return result


def verify_alignment(dataset, local_dataset):
    if len(dataset) != len(local_dataset):
        raise ValueError('Comparison samples do not match')
    n = dataset.cfg['data']['forecast_horizon']
    maximum_error = 0.
    for index, (basin, position) in enumerate(local_dataset.samples):
        if basin != dataset.cfg['data']['basin_id'] or local_dataset.store.frames[basin].index[position] != dataset.issue_date(index):
            raise ValueError('Issue dates differ between models')
        q = dataset.q[dataset.samples[index] + 1:dataset.samples[index] + n + 1]
        original = local_dataset.store.frames[basin]['q_cumecs'].iloc[position + 1:position + n + 1].to_numpy()
        np.testing.assert_array_equal(q, original)
        item = dataset[index]; local_item = local_dataset[index]
        raw = item['future'].numpy() * np.array(dataset.norm['dynamic_scale']) + np.array(dataset.norm['dynamic_center'])
        old = (local_item['future'][:, :2].numpy() * np.array(local_dataset.stats['forecast']['scale'])
               + np.array(local_dataset.stats['forecast']['center']))
        error = np.abs(raw[:, dataset.forecast_indices] - old)
        maximum_error = max(maximum_error, float(error.max()))
        np.testing.assert_allclose(raw[:, dataset.forecast_indices], old, rtol=2e-5, atol=5e-5)
    return maximum_error


def run_evaluation(cfg, checkpoint_path=None):
    configure_seed(cfg)
    checkpoint_path = Path(checkpoint_path) if checkpoint_path else resolve(cfg, cfg['training']['output_dir']) / 'best.pt'
    checkpoint = load_checkpoint(checkpoint_path)
    norm = checkpoint['normalization']
    check_years(cfg, norm['source_config'])
    if set(years(cfg['splits']['test'])) & set(checkpoint['training_years'] + checkpoint['selection_years']):
        raise ValueError('Test years were used for training or selection')
    paths = {'daily': cfg['data']['daily_file'], 'static': cfg['data']['static_file'],
             'parent': cfg['pretrained']['checkpoint'], 'global_scaler': cfg['pretrained']['scaler']}
    for name, path in paths.items():
        if hashlib.sha256(resolve(cfg, path).read_bytes()).hexdigest() != checkpoint['source_hashes'][name]:
            raise ValueError(f'Training source changed: {name}')
    reference_cfg = local_config(resolve(cfg, cfg['reference']['config']))
    if reference_cfg['splits'] != cfg['splits']:
        raise ValueError('Use identical split ranges for the comparison')
    reference_ck = load_checkpoint(resolve(cfg, cfg['reference']['checkpoint']))
    store = DataStore(reference_cfg)
    local_dataset, local_quantiles = predict_checkpoint(reference_cfg, store, reference_ck)
    dataset = GlobalDataset(cfg, 'test', norm, reference_ck['statistics'])
    forcing_error = verify_alignment(dataset, local_dataset)
    parent = GlobalPretrainedLSTM(norm['source_config'])
    parent.load_published_weights(torch.load(resolve(cfg, cfg['pretrained']['checkpoint']), map_location='cpu', weights_only=True))
    tuned = GlobalPretrainedLSTM(norm['source_config'])
    tuned.load_state_dict(checkpoint['model_state'])
    forecasts = {'Existing_local_LSTM': local_quantiles[:, :, reference_cfg['model']['quantiles'].index(.5)],
                 'Global_zero_shot': predict(parent, dataset, cfg),
                 'Global_finetuned': predict(tuned, dataset, cfg)}
    training_q = dataset.frame.loc[dataset.dates.year.isin(years(cfg['splits']['train'])), 'q_cumecs'].dropna()
    peak = float(training_q.quantile(cfg['evaluation']['peak_percentile']))
    flood = cfg['evaluation']['flood_threshold_cumecs']
    flood = peak if flood is None else float(flood)
    rows = []
    for index, position in enumerate(dataset.samples):
        for lead in range(1, cfg['data']['forecast_horizon'] + 1):
            day = dataset.dates[position + lead]
            rows.append({'basin_id': cfg['data']['basin_id'], 'issue_date': dataset.issue_date(index),
                         'target_date': day, 'lead_day': lead, 'season': season_for(day),
                         'observed_cumecs': dataset.q[position + lead],
                         **{name: prediction[index, lead - 1] for name, prediction in forecasts.items()}})
    table = pd.DataFrame(rows)
    observed = table[table.observed_cumecs.notna()]
    seasonal, overall = [], []
    for (lead, season), group in observed.groupby(['lead_day', 'season']):
        for name in forecasts:
            seasonal.append({'model': name, 'lead_day': lead, 'season': season,
                             **metrics(group.observed_cumecs, group[name], peak, flood)})
    for lead, group in observed.groupby('lead_day'):
        for name in forecasts:
            overall.append({'model': name, 'lead_day': lead, **metrics(group.observed_cumecs, group[name], peak, flood)})
    overall, seasonal = pd.DataFrame(overall), pd.DataFrame(seasonal)
    out = resolve(cfg, cfg['evaluation']['output_dir']); out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / 'predictions.csv', index=False, na_rep='NaN')
    overall.to_csv(out / 'scores_by_lead.csv', index=False)
    seasonal.to_csv(out / 'scores_by_season_and_lead.csv', index=False)
    unique = observed[['basin_id', 'target_date']].drop_duplicates()
    by_year = unique.assign(year=unique.target_date.dt.year).groupby('year').size().rename('observed_days').reset_index()
    by_year.to_csv(out / 'observed_test_days_by_year.csv', index=False)
    selected = overall[overall.lead_day.isin([1, 5, 10])][['model', 'lead_day', 'n', 'NSE', 'KGE', 'PBIAS_pct', 'RMSE_cumecs', 'peak_MAPE_pct']]
    day10 = overall[overall.lead_day.eq(10)].set_index('model')
    delta = float(day10.loc['Global_finetuned', 'NSE'] - day10.loc['Existing_local_LSTM', 'NSE'])
    conclusion = ('Fine-tuning improved day-10 NSE over the existing local LSTM.' if delta > 0 else
                  'Fine-tuning did not improve day-10 NSE over the existing local LSTM; retain the local LSTM as the stronger day-10 model in this comparison.')
    peak_note = (f'Day-10 peak-flow MAPE: existing local {day10.loc["Existing_local_LSTM", "peak_MAPE_pct"]:.3f}% '
                 f'versus fine-tuned global {day10.loc["Global_finetuned", "peak_MAPE_pct"]:.3f}%. '
                 'Check flood metrics separately from overall NSE; the existing local model also has higher NSE at leads 1 and 5 in this run.')
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for name, group in overall.groupby('model'):
        axes[0].plot(group.lead_day, group.NSE, marker='o', label=name)
        axes[1].plot(group.lead_day, group.RMSE_cumecs, marker='o', label=name)
    axes[0].set(xlabel='Lead day', ylabel='NSE'); axes[1].set(xlabel='Lead day', ylabel='RMSE (m3/s)')
    axes[0].legend(fontsize=8); fig.tight_layout(); fig.savefig(out / 'skill_by_lead.png', dpi=180); plt.close(fig)
    manifest = {'checkpoint': str(checkpoint_path.resolve()), 'checkpoint_sha256': hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
                'parent_repository': checkpoint['pretrained_model_repository'], 'parent_basin_count': checkpoint['pretrained_basin_count'],
                'pretrained_training_years': checkpoint['global_training_years'], 'local_training_years': checkpoint['local_training_years'],
                'local_validation_years': checkpoint['local_selection_years'], 'test_years': years(cfg['splits']['test']),
                'best_epoch': checkpoint['epoch'], 'test_samples': len(dataset), 'unique_observed_test_days': len(unique),
                'observed_issue_lead_pairs': len(observed), 'missing_target_pairs_not_scored': int(table.observed_cumecs.isna().sum()),
                'peak_threshold_cumecs': peak, 'flood_threshold_cumecs': flood, 'same_target_values_and_dates': True,
                'matched_future_rain_temperature_max_abs_difference': forcing_error, 'no_discharge_filled': True,
                'source_hashes': checkpoint['source_hashes'], 'day10_nse_change_vs_existing': delta,
                'forecast_mode': 'reanalysis_with_noise; other 12 predictors persisted from issue day',
                'quantile_calibration': 'Not applicable to the deterministic global regression head'}
    (out / 'evaluation_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    report = ['# Global pretrained LSTM: Marala comparison', '', conclusion, '', peak_note, '',
              '**These are observed-discharge test scores under noisy future reanalysis weather, not measured operational 10-day forecast skill.**', '',
              'The published Fine Flood Forecasts Caravan model was pretrained on 6,375 basins in 2001-2020. All eight original weight tensors were loaded exactly. The original 256-unit daily rainfall-runoff LSTM was continued into a 10-day weather rollout and then fine-tuned on Marala. Its original global normalization and linear runoff head were retained; this is not a separately pretrained 10-day encoder-decoder.', '',
              f'Local train: {cfg["splits"]["train"]}; validation: {cfg["splits"]["validation"]}; test: {cfg["splits"]["test"]}. Best epoch: {checkpoint["epoch"]}. Test years were excluded from both global/local training and model selection. The earlier global validation period was 1981-1990.', '',
              f'**{len(unique)} unique observed test days**, {len(dataset)} issue windows, {len(observed)} scored issue/lead pairs. {int(table.observed_cumecs.isna().sum())} missing-target pairs were excluded. Overlapping forecast windows are not independent observations.', '',
              markdown(by_year), '', '## Accuracy comparison', '', markdown(selected), '',
              f'Day-10 NSE difference (fine-tuned global minus existing local): {delta:+.6f}. NSE is a skill score, not percentage accuracy.', '',
              '## Comparable inputs and limits', '',
              f'Both models receive the same physical future rain and temperature stand-in, with the same lead-growing Gaussian error (maximum floating-point discrepancy {forcing_error:.8g}). All other 12 inputs of the global model are held at issue-day values throughout the rollout; no future soil moisture, snow, radiation or wind states are used.', '',
              'The comparison uses identical issue dates and observed target values. The global model has 14 dynamic inputs, 51 static attributes, 256 hidden units and a point/MSE objective. The old local LSTM has 8 dynamic inputs, calendar features, 64 hidden units and a log-flow quantile objective; its median is scored. Architecture and input differences mean this comparison alone cannot isolate a causal pretraining benefit.', '',
              'Quantile calibration is not applicable to the global point-regression checkpoint. No synthetic intervals were added. The existing local model has its original quantiles in its separate report.', '',
              'Global statistics remain frozen. Missing predictors receive their global mean in normalized space and separate zero-initialized indicator adapters; missing discharge remains NaN and is masked. Static attributes come from area-weighted HydroATLAS intersections and 1981-2020 weather climatology. Marala area is about 28,794 km2, a substantial basin-size domain shift. UTC daily weather differs from the parent Caravan local-day extraction.', '',
              'Only five local training years and one validation year are used for comparability. Regulation, diversions, few independent flood events, future weather stand-in bias and publication/observation latency remain limits. The 2022-2024 period was inspected in earlier project experiments; it is held out of this training run, not an untouched project-wide research holdout.', '',
              f'Peak and default flood thresholds use training-period Q95 = {peak:.3f} m3/s. This is not an official flood warning threshold. Peak error is mean absolute percentage error on observed exceedance days. PBIAS is positive for overprediction; KGE uses the original correlation/variability/bias definition. False-alarm rate is false alerts divided by observed non-exceedances, and false-alarm ratio is false alerts divided by predicted exceedances.', '',
              '## Every lead day', '', markdown(overall), '', '## Seasonal verification', '', markdown(seasonal), '',
              '![Skill by lead](skill_by_lead.png)', '',
              'Sources: [authors\' model](https://huggingface.co/EmilRyd/caravan_model), [Fine Flood Forecasts](https://github.com/EmilRyd/Fine-Flood-Forecasts). The pinned revision and downloaded hashes are saved in ../../pretrained/download_receipt.json.']
    (out / 'comparison_report.md').write_text('\n'.join(report) + '\n')
    root = Path(cfg['_root']); readme = root / 'README.md'
    if readme.exists():
        body = readme.read_text().split('<!-- REAL_RESULTS -->')[0]
        readme.write_text(body + '<!-- REAL_RESULTS -->\n\n## Real Marala results\n\n' + conclusion + '\n\n' + peak_note + '\n\n'
                          + markdown(selected) + f'\n\nTest: 2022-2024; {len(unique)} observed days; {len(observed)} observed issue/lead pairs. '
                          + 'No missing discharge was filled or scored. These are noisy-reanalysis experiments, not operational forecast accuracy.\n\n'
                          + '[Full observed-only comparison](reports/initial/comparison_report.md)\n')
    print(selected.to_string(index=False), flush=True)
    print(conclusion, flush=True)
    print('Report:', out / 'comparison_report.md', flush=True)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    parser.add_argument('--checkpoint')
    args = parser.parse_args()
    run_evaluation(load_config(args.config), args.checkpoint)
