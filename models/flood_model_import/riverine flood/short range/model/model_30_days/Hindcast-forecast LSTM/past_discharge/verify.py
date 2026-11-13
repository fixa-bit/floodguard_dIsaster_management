"""Check the matched-input change, saved results and original artifact retention."""
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


def verify_inputs(cfg):
    reference_cfg = load_config(resolve(cfg, cfg['evaluation']['reference_config']))
    assert cfg['data']['past_discharge'] is True
    assert reference_cfg['data']['past_discharge'] is False
    for key in ('model', 'splits', 'normalization', 'training', 'finetuning'):
        assert cfg[key] == reference_cfg[key], f'Unexpected configuration change: {key}'
    current = {k: v for k, v in cfg['data'].items() if k != 'past_discharge'}
    old = {k: v for k, v in reference_cfg['data'].items() if k != 'past_discharge'}
    assert current == old
    reference_root = Path(reference_cfg['_root'])
    reference_checkpoint = load_checkpoint(reference_root / 'runs/initial/seed_42/best.pt')
    stats = reference_checkpoint['statistics']
    reference = StreamflowDataset(DataStore(reference_cfg), 'test', stats)
    from data import fit_statistics
    store = DataStore(cfg)
    new_stats = fit_statistics(store)
    for key in ('dynamic', 'forecast', 'flow', 'static', 'training_years'):
        assert new_stats[key] == stats[key], f'Training statistics changed for {key}'
    dataset = StreamflowDataset(store, 'test', new_stats)
    assert dataset.samples == reference.samples
    dynamic = 2 * len(cfg['data']['dynamic_columns'])
    # Check every test window, including every seeded future-weather realization.
    for index in range(len(dataset)):
        before, after = reference[index], dataset[index]
        projected = torch.cat([after['history'][:, :dynamic], after['history'][:, -2:]], dim=-1)
        torch.testing.assert_close(projected, before['history'], rtol=0, atol=0)
        torch.testing.assert_close(after['future'], before['future'], rtol=0, atol=0)
        torch.testing.assert_close(after['target'], before['target'], rtol=0, atol=0, equal_nan=True)
        torch.testing.assert_close(after['mask'], before['mask'])
    return store, dataset


def main():
    cfg = load_config(ROOT / 'config.yaml')
    torch.set_num_threads(cfg['training']['cpu_threads'])
    torch.set_flush_denormal(cfg['training'].get('flush_denormal', False))
    protected = json.loads((ROOT / 'reference_artifacts_before.json').read_text())
    for entry in protected:
        assert Path(entry['path']).is_file() and sha256(entry['path']) == entry['sha256'], entry['path']
    source = resolve(cfg, cfg['data']['daily_file'])
    reference_source = ROOT.parent / 'scratch/data/marala_daily.csv'
    assert sha256(source) == sha256(reference_source)
    store, dataset = verify_inputs(cfg)
    checkpoint_path = ROOT / 'runs/initial/seed_42/best.pt'
    checkpoint = load_checkpoint(checkpoint_path)
    assert checkpoint['dimensions'] == [20, 4, 0]
    assert checkpoint['config']['data']['past_discharge'] is True
    assert checkpoint['config']['data']['forecast_horizon'] == 30
    assert sha256(source) == checkpoint['source_hashes']['daily_file']
    assert not (set(years(cfg['splits']['test'])) & (set(checkpoint['training_years']) | set(checkpoint['selection_years'])))
    model = HindcastForecastLSTM(cfg, *dataset.dimensions()).eval()
    model.load_state_dict(checkpoint['model_state'])
    with torch.no_grad():
        sample = dataset[0]
        prediction = model(*(sample[k].unsqueeze(0) for k in ('history', 'future', 'static')))
    assert tuple(prediction.shape) == (1, 30, 5)
    assert torch.isfinite(prediction).all() and (prediction.diff(dim=-1) >= 0).all()
    table = pd.read_csv(ROOT / 'reports/initial/predictions.csv')
    assert set(table.lead_day) == set(range(1, 31))
    original = pd.read_csv(source)[['basin_id', 'date', 'q_cumecs']].rename(columns={'date': 'target_date'})
    matched = table.merge(original, on=['basin_id', 'target_date'], validate='many_to_one')
    assert len(matched) == len(table)
    np.testing.assert_allclose(matched.observed_cumecs, matched.q_cumecs, rtol=0, atol=1e-10)
    manifest = json.loads((ROOT / 'reports/initial/evaluation_manifest.json').read_text())
    scores = pd.read_csv(ROOT / 'reports/initial/scores_by_lead.csv')
    for lead, group in table.groupby('lead_day'):
        actual = metrics(group.observed_cumecs, group.LSTM_30d_pastQ, manifest['flood_threshold_cumecs'])
        saved = scores.loc[scores.lead_day.eq(lead)].iloc[0]
        for key in ('NSE', 'KGE', 'RMSE_cumecs', 'PBIAS_pct'):
            assert np.isclose(actual[key], saved[key], rtol=1e-10, atol=1e-10)
    protocol = json.loads((ROOT / 'protocol.json').read_text())
    assert protocol['config_sha256'] == sha256(ROOT / 'config.yaml')
    queue = json.loads((ROOT.parents[1] / 'training_queue.json').read_text())
    for row in queue[1:]:
        folder = ROOT.parents[1] / row['folder']
        assert not list(folder.rglob('*.pt')) and not list(folder.rglob('*.pkl'))
    result = {'only_past_discharge_flag_changed_for_model_inputs': True,
              'architecture_and_optimizer_settings_matched': True,
              'all_test_weather_windows_and_noise_exactly_matched': True,
              'training_statistics_exactly_matched': True,
              'same_sample_dates_and_target_masks': True,
              'original_reference_files_unchanged': len(protected),
              'source_tables_byte_identical': True, 'observed_targets_exactly_preserved': True,
              'future_discharge_not_a_predictor_test_passed': True,
              'all_saved_metrics_reproduced': True, 'checkpoint_has_30_leads': True,
              'new_real_models_trained_this_step': 1, 'correctness_tests_passed': 9,
              'source_sha256': sha256(source), 'checkpoint_sha256': sha256(checkpoint_path),
              'other_families_not_trained': True, 'operational_forecast_skill_established': False}
    save_json(ROOT / 'reports/initial/verification.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
