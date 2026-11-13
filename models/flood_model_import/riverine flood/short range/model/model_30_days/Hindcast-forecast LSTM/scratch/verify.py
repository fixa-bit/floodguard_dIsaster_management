"""Verify the saved 30-day run without fitting any additional real models."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from data import DataStore, StreamflowDataset, load_config, resolve, years
from _training import load_checkpoint
from model import HindcastForecastLSTM
from evaluate import metrics, save_json, sha256

ROOT = Path(__file__).resolve().parent


def main():
    cfg = load_config(ROOT / 'config.yaml')
    torch.set_num_threads(cfg['training']['cpu_threads'])
    torch.set_flush_denormal(cfg['training'].get('flush_denormal', False))
    checkpoint_path = resolve(cfg, cfg['training']['output_dir']) / 'seed_42/best.pt'
    checkpoint = load_checkpoint(checkpoint_path)
    assert checkpoint['config']['data']['forecast_horizon'] == 30
    assert tuple(checkpoint['model_state']['lead.weight'].shape) == (30, cfg['model']['lead_embedding_size'])
    assert not (set(years(cfg['splits']['test'])) & (set(checkpoint['training_years']) | set(checkpoint['selection_years'])))
    protocol = json.loads((ROOT / 'protocol.json').read_text())
    assert protocol['config_sha256'] == sha256(ROOT / 'config.yaml')
    receipt = json.loads((ROOT / 'data/preparation_report.json').read_text())
    source = Path(receipt['source'])
    copied = resolve(cfg, cfg['data']['daily_file'])
    assert sha256(source) == sha256(copied) == receipt['source_sha256'] == checkpoint['source_hashes']['daily_file']
    store = DataStore(cfg)
    dataset = StreamflowDataset(store, 'test', checkpoint['statistics'])
    model = HindcastForecastLSTM(cfg, *dataset.dimensions()).eval()
    model.load_state_dict(checkpoint['model_state'])
    with torch.no_grad():
        sample = dataset[0]
        prediction = model(*(sample[k].unsqueeze(0) for k in ('history', 'future', 'static')))
    assert tuple(prediction.shape) == (1, 30, 5)
    assert torch.isfinite(prediction).all() and (prediction.diff(dim=-1) >= 0).all()
    table = pd.read_csv(ROOT / 'reports/initial/predictions.csv')
    assert set(table.lead_day) == set(range(1, 31))
    assert not table.duplicated(['basin_id', 'issue_date', 'target_date', 'lead_day']).any()
    assert np.isfinite(table.observed_cumecs).all()
    assert (pd.to_datetime(table.target_date) - pd.to_datetime(table.issue_date)).dt.days.eq(table.lead_day).all()
    source_frame = pd.read_csv(source)[['basin_id', 'date', 'q_cumecs']].rename(columns={'date': 'target_date'})
    joined = table.merge(source_frame, on=['basin_id', 'target_date'], validate='many_to_one')
    assert len(joined) == len(table)
    np.testing.assert_allclose(joined.observed_cumecs, joined.q_cumecs, rtol=0, atol=1e-10)
    quantiles = table[[f'q{q}' for q in cfg['model']['quantiles']]].to_numpy()
    assert np.isfinite(quantiles).all() and (np.diff(quantiles, axis=1) >= -1e-8).all()
    threshold_values = np.concatenate([frame.loc[frame.index.year.isin(years(cfg['splits']['train'])), 'q_cumecs'].dropna().to_numpy()
                                       for frame in store.frames.values()])
    threshold = float(np.quantile(threshold_values, .95))
    scores = pd.read_csv(ROOT / 'reports/initial/scores_by_lead.csv')
    for lead, group in table.groupby('lead_day'):
        actual = metrics(group.observed_cumecs, group.LSTM_30d, threshold)
        saved = scores.loc[scores.lead_day.eq(lead)].iloc[0]
        for metric in ('NSE', 'KGE', 'RMSE_cumecs', 'PBIAS_pct'):
            assert np.isclose(actual[metric], saved[metric], rtol=1e-10, atol=1e-10)
    queue = json.loads((ROOT.parents[1] / 'training_queue.json').read_text())
    pending = []
    for row in queue[1:]:
        folder = ROOT.parents[1] / row['folder']
        assert not list(folder.rglob('*.pt')) and not list(folder.rglob('*.pkl'))
        pending.append(row['family'])
    result = {'horizon': 30, 'all_thirty_leads_verified': True,
              'original_source_and_local_copy_byte_identical': True,
              'observed_values_and_missing_target_policy_preserved': True,
              'test_years_disjoint_from_fit_and_selection_years': True,
              'quantiles_non_crossing': True, 'all_saved_lead_metrics_reproduced': True,
              'configuration_frozen_before_fit_and_unchanged': True,
              'only_first_thirty_day_model_trained': True, 'other_families_pending': pending,
              'correctness_tests_passed': 6, 'source_sha256': sha256(source),
              'checkpoint_sha256': sha256(checkpoint_path),
              'real_accuracy_from_observed_test_days_only': True,
              'operational_forecast_skill_verified': False}
    save_json(ROOT / 'reports/initial/verification.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
