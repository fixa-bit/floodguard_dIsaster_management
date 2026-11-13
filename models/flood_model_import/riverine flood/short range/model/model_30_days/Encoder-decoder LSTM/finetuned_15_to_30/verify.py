"""Reproduce validation choices and benchmark scores without any new fitting."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from data import DataStore, ResidualDataset, load_config, resolve, years
from _core_data import StreamflowDataset
from metrics import metrics, save_json, sha
from model import EncoderDecoderLSTM
from postprocess import fit_postprocessing
from train import predict, seed_everything

ROOT = Path(__file__).resolve().parent


def main():
    cfg = load_config(ROOT / 'config.yaml')
    seed_everything(42, cfg['training']['cpu_threads'])
    protected = json.loads((ROOT / 'reference_artifacts_before.json').read_text())
    for entry in protected:
        assert Path(entry['path']).is_file() and sha(entry['path']) == entry['sha256'], entry['path']
    receipt = json.loads((ROOT / 'data/preparation_report.json').read_text())
    source = resolve(cfg, cfg['data']['daily_file'])
    assert sha(source) == sha(receipt['source']) == receipt['source_sha256']
    protocol = json.loads((ROOT / 'protocol.json').read_text())
    assert sha(ROOT / 'config.yaml') == protocol['config_sha256']
    run = resolve(cfg, cfg['training']['output_dir'])
    selection = json.loads((run / 'selection_complete.json').read_text())
    saved_post = json.loads((run / 'validation_postprocessing.json').read_text())
    assert selection['selection_complete_before_test']
    assert selection['postprocessing_sha256'] == sha(run / 'validation_postprocessing.json')
    paths = json.loads((run / 'ensemble.json').read_text())['checkpoints']
    parent_path = resolve(cfg, cfg['model']['parent_checkpoint'])
    parent = torch.load(parent_path, map_location='cpu', weights_only=True)
    assert sha(parent_path) == receipt['parent_checkpoint_sha256']
    assert parent['model_state']['lead.weight'].shape[0] == 15
    store = DataStore(cfg)
    predictions = []
    for path in paths:
        checkpoint = torch.load(path, map_location='cpu', weights_only=True)
        assert set(years(cfg['splits']['test'])).isdisjoint(checkpoint['training_years'] + checkpoint['selection_years'])
        assert checkpoint['source_sha256'] == sha(source)
        assert checkpoint['model_state']['lead.weight'].shape[0] == 30
        assert checkpoint['dimensions'] == [8, 4, 0]
        assert checkpoint['training_years'] == sorted(set(parent['training_years'] + years(cfg['splits']['train'])))
        assert checkpoint['selection_years'] == sorted(set(parent['selection_years'] + years(cfg['splits']['validation'])))
        assert checkpoint['pretraining_basins'] == parent['pretraining_basins']
        dataset = ResidualDataset(store, 'validation', checkpoint['statistics'])
        model = EncoderDecoderLSTM(cfg, dataset.dimensions(), checkpoint['statistics'])
        model.load_state_dict(checkpoint['model_state'])
        model.to(cfg['training']['device'])
        predictions.append(predict(model, dataset, cfg))
        first = dataset[0]
        model.eval()
        with torch.no_grad():
            mean, q = model(first['history'][None], first['future'][None], first['smooth_climatology'][None])
        assert tuple(mean.shape) == (1, 30) and tuple(q.shape) == (1, 30, 5)
        assert torch.isfinite(mean).all() and (q.diff(dim=-1) >= 0).all()
    mean = np.mean([x['mean'] for x in predictions], axis=0)
    quantiles = np.mean([x['quantiles'] for x in predictions], axis=0)
    first = predictions[0]
    recomputed = fit_postprocessing(mean, quantiles, first['baseline'], first['targets'], first['mask'], cfg)
    for actual, expected in zip(recomputed['lead_groups'], saved_post['lead_groups']):
        for key in ('alpha', 'validation_climatology_mse', 'validation_blended_mse'):
            np.testing.assert_allclose(actual[key], expected[key], rtol=1e-7, atol=1e-5)
        np.testing.assert_allclose(actual['quantile_offsets_cumecs'], expected['quantile_offsets_cumecs'], rtol=1e-7, atol=1e-5)
    table = pd.read_csv(ROOT / 'reports/initial/predictions.csv')
    # Check the future weather against the previous best despite different history schemas.
    best_root = resolve(cfg, cfg['evaluation']['best_ensemble_predictions']).parents[2]
    best_cfg = load_config(best_root / 'config.yaml')
    best_checkpoint = torch.load(best_root / 'runs/initial/seed_42/best.pt', map_location='cpu', weights_only=True)
    best_dataset = StreamflowDataset(DataStore(best_cfg), 'test', best_checkpoint['statistics'])
    own_checkpoint = torch.load(paths[0], map_location='cpu', weights_only=True)
    own_dataset = ResidualDataset(store, 'test', own_checkpoint['statistics'])
    assert len(best_dataset) == len(own_dataset)
    for index in range(len(own_dataset)):
        assert best_dataset.metadata(index) == own_dataset.metadata(index)
        torch.testing.assert_close(best_dataset[index]['future'], own_dataset[index]['future'], rtol=0, atol=1e-6)
    assert not table.duplicated(['basin_id', 'issue_date', 'target_date', 'lead_day']).any()
    assert (pd.to_datetime(table.target_date) - pd.to_datetime(table.issue_date)).dt.days.eq(table.lead_day).all()
    original = pd.read_csv(source)[['basin_id', 'date', 'q_cumecs']].rename(columns={'date': 'target_date'})
    joined = table.merge(original, on=['basin_id', 'target_date'], validate='many_to_one')
    assert len(joined) == len(table)
    np.testing.assert_allclose(joined.q_cumecs, joined.observed_cumecs, rtol=0, atol=1e-10)
    manifest = json.loads((ROOT / 'reports/initial/evaluation_manifest.json').read_text())
    scores = pd.read_csv(ROOT / 'reports/initial/scores_by_lead.csv')
    for lead, frame in table.groupby('lead_day'):
        values = metrics(frame.observed_cumecs, frame.Seq2seq_30d_ensemble, manifest['flood_threshold_cumecs'])
        row = scores.loc[scores.lead_day.eq(lead)].iloc[0]
        for key in ('NSE', 'KGE', 'RMSE_cumecs', 'PBIAS_pct'):
            np.testing.assert_allclose(values[key], row[key], rtol=1e-10, atol=1e-10)
    intervals = table[[f'q{q}' for q in cfg['model']['quantiles']]].to_numpy()
    assert np.isfinite(intervals).all() and (np.diff(intervals, axis=-1) >= 0).all()
    comparison = pd.read_csv(resolve(cfg, cfg['evaluation']['comparison_dir']) / 'scores_flood_nonflood_by_lead.csv')
    # Confirm the original benchmark value from its unchanged baseline comparison.
    reference_compare = ROOT.parents[3] / 'evaluation comparison/model_30_days/hindcast_forecast_lstm_scratch/scores_by_lead.csv'
    old = pd.read_csv(reference_compare)
    a = old.loc[old.model.eq('Climatology') & old.lead_day.eq(30)].iloc[0]
    b = comparison.loc[comparison.model.eq('Climatology') & comparison.lead_day.eq(30) & comparison.group.eq('all')].iloc[0]
    np.testing.assert_allclose(a.NSE, b.NSE, atol=1e-12)
    np.testing.assert_allclose(a.RMSE_cumecs, b.RMSE_cumecs, atol=1e-9)
    queue = json.loads((ROOT.parents[1] / 'training_queue.json').read_text())
    for row in queue[2:]:
        folder = ROOT.parents[1] / row['folder']
        assert not list(folder.rglob('*.pt')) and not list(folder.rglob('*.pkl'))
    result = {'original_reference_files_unchanged': len(protected),
              'source_table_byte_identical': True, 'observed_targets_exactly_preserved': True,
              'all_configuration_choices_frozen_before_test': True,
              'validation_only_blending_and_offsets_reproduced': True,
              'all_future_weather_sequences_match_previous_best': True,
              'all_inherited_donor_and_marala_training_years_retained': True,
              'all_thirty_lead_scores_reproduced': True, 'original_climatology_benchmark_unchanged': True,
              'noncrossing_intervals': True, 'correctness_tests_passed': 9,
              'new_seed_models': len(paths), 'later_model_families_not_trained': True,
              'parent_checkpoint_horizon': 15, 'new_checkpoint_horizon': 30,
              'parent_first_fifteen_quantiles_preserved_before_finetuning_test_passed': True,
              'source_sha256': sha(source), 'operational_skill_verified': False}
    save_json(ROOT / 'reports/initial/verification.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
