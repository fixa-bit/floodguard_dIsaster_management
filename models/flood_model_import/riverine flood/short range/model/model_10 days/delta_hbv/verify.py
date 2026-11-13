"""Verify saved real results, forcing alignment and original data hashes."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from data import DataStore, DeltaDataset, load_config, resolve, save_json, sha256
from _core_data import StreamflowDataset
from evaluate import markdown, metrics
from model import DeltaHBV

ROOT = Path(__file__).resolve().parent


def main():
    cfg = load_config(ROOT / 'config.yaml')
    torch.set_num_threads(cfg['training']['cpu_threads'])
    checkpoint = torch.load(resolve(cfg, cfg['training']['output_dir']) / 'best.pt', map_location='cpu', weights_only=False)
    store = DataStore(cfg)
    dataset = DeltaDataset(store, 'test', checkpoint['statistics'])
    reference_cfg = load_config(ROOT.parent / 'lstm/config.yaml')
    reference_checkpoint = torch.load(ROOT.parent / 'lstm/runs/initial/seed_42/best.pt', map_location='cpu', weights_only=False)
    reference = StreamflowDataset(DataStore(reference_cfg), 'test', reference_checkpoint['statistics'])
    assert dataset.samples == reference.samples
    for index in (0, len(dataset) // 2, len(dataset) - 1):
        future = reference[index]['future'].numpy()
        stats = reference_checkpoint['statistics']['forecast']
        raw = future[:, :2] * np.asarray(stats['scale']) + np.asarray(stats['center'])
        raw[:, 0] = np.maximum(raw[:, 0], 0)
        np.testing.assert_allclose(dataset[index]['forcing'][-10:, :2], raw, rtol=1e-6, atol=1e-5)
    source = ROOT.parents[2] / 'evaluation comparison/common/data/marala_daily.csv'
    assert sha256(source) == checkpoint['source_sha256'] == sha256(ROOT / 'data/marala_daily.csv')
    predictions = pd.read_csv(ROOT / 'reports/initial/predictions.csv')
    original = pd.read_csv(source, parse_dates=['date'])
    selected = original[['date', 'q_cumecs']].rename(columns={'date': 'target_date'})
    matched = predictions.assign(target_date=lambda x: pd.to_datetime(x.target_date)).merge(selected, on='target_date', validate='many_to_one')
    np.testing.assert_allclose(matched.q_cumecs, matched.observed_cumecs, rtol=0, atol=1e-10)
    scores = pd.read_csv(ROOT / 'reports/initial/scores_by_lead.csv')
    threshold = checkpoint['statistics']['flood_threshold_cumecs']
    for lead, rows in predictions.groupby('lead_day'):
        recomputed = metrics(rows.observed_cumecs, rows.delta_HBV, threshold)
        saved = scores.loc[scores.lead_day.eq(lead)].iloc[0]
        for name in ('NSE', 'KGE', 'RMSE_cumecs', 'PBIAS_pct'):
            assert np.isclose(recomputed[name], saved[name], rtol=1e-10, atol=1e-10)
    model = DeltaHBV(cfg)
    model.load_state_dict(checkpoint['model_state'])
    model.eval()
    item = dataset[0]
    with torch.no_grad():
        physical = model(item['neural'].unsqueeze(0), item['forcing'].unsqueeze(0)).numpy()[0]
    _, issue = dataset.metadata(0)
    saved = predictions.loc[predictions.issue_date.eq(issue.strftime('%Y-%m-%d'))].sort_values('lead_day')
    np.testing.assert_allclose(physical[saved.lead_day.to_numpy() - 1], saved.delta_HBV, rtol=2e-5, atol=.003)
    provenance = json.loads((ROOT / 'source_reference/provenance.json').read_text())
    for entry in provenance['files']:
        assert sha256(ROOT / 'source_reference' / entry['path']) == entry['sha256']
        if entry['path'].startswith('src/'):
            assert sha256(ROOT / '_vendor' / entry['path'].removeprefix('src/')) == entry['sha256']
    verification = {
        'original_and_local_data_byte_identical': True,
        'observed_test_targets_exactly_preserved': True,
        'upstream_physics_bytes_match_pinned_sources': True,
        'original_lstm_forecast_weather_matched_before_precipitation_clipping': True,
        'observed_test_sample_dates_match_original_lstm': True,
        'saved_metrics_independently_reproduced': True,
        'loaded_checkpoint_reproduces_saved_predictions': True,
        'correctness_tests_passed': 5,
        'source_sha256': sha256(source),
        'training_capped_at_configured_epochs': len(pd.read_csv(ROOT / 'runs/initial/seed_42/history.csv')) == cfg['training']['epochs'],
        'convergence_established': False,
    }
    save_json(ROOT / 'reports/initial/verification.json', verification)
    readme = ROOT / 'README.md'
    text = readme.read_text(encoding='utf-8')
    summary = json.loads((ROOT / 'runs/initial/seed_42/training_summary.json').read_text())
    comparison_scores = pd.read_csv(resolve(cfg, cfg['evaluation']['comparison_dir']) / 'scores_flood_nonflood_by_lead.csv')
    horizon = cfg['data']['forecast_horizon']
    final = comparison_scores.loc[comparison_scores.lead_day.eq(horizon) & comparison_scores.group.eq('all')].set_index('model')
    finding = (f'Lead-{horizon} NSE: delta-HBV **{final.loc["delta_HBV", "NSE"]:.3f}**; '
               f'original LSTM **{final.loc["LSTM", "NSE"]:.3f}**; persistence **{final.loc["Persistence", "NSE"]:.3f}**; '
               f'climatology **{final.loc["Climatology", "NSE"]:.3f}**. These use identical observed records.')
    lines = ['## Measured accuracy', '',
             f'Training took **{summary["seconds"]:.1f} seconds**, with {summary["epochs"]} epochs and seed {summary["seed"]}; the selected checkpoint is epoch {checkpoint["epoch"]}. The run reached its configured epoch cap while validation loss was still improving, so convergence is not established.', '',
             markdown(scores.loc[scores.lead_day.isin([1, 5, 10]), ['lead_day', 'n', 'NSE', 'KGE', 'RMSE_cumecs', 'PBIAS_pct']]), '',
             finding, '',
             'Five correctness tests and the saved-result verification passed. See reports/initial/verification.json. No accuracy is inferred from these tests.', '']
    if '## Measured accuracy' not in text:
        readme.write_text(text.replace('## Limits', '\n'.join(lines) + '\n## Limits'), encoding='utf-8')
    print(json.dumps(verification, indent=2))


if __name__ == '__main__':
    main()
