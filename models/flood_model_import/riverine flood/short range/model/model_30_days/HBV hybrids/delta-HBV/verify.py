"""Recheck saved predictions against source observations and saved score tables."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from data import load_config, resolve, sha256
from evaluate import metrics


ROOT = Path(__file__).resolve().parent


def main():
    cfg = load_config(ROOT / 'config.yaml')
    source = ROOT.parents[3] / 'evaluation comparison' / 'common' / 'data' / 'marala_daily.csv'
    daily = resolve(cfg, cfg['data']['daily_file'])
    if sha256(source) != sha256(daily):
        raise AssertionError('Local daily table differs from the original observed source')
    predictions_path = resolve(cfg, cfg['evaluation']['output_dir']) / 'predictions.csv'
    predictions = pd.read_csv(predictions_path, parse_dates=['target_date'])
    original = pd.read_csv(source, parse_dates=['date'])[['date', 'q_cumecs']]
    joined = predictions.merge(original, left_on='target_date', right_on='date', validate='many_to_one')
    if len(joined) != len(predictions) or not np.allclose(joined.observed_cumecs, joined.q_cumecs, rtol=0, atol=1e-10):
        raise AssertionError('A saved prediction does not match its original observed target')
    if predictions.lead_day.max() != 30 or predictions.lead_day.min() != 1:
        raise AssertionError('Saved forecasts do not span lead days 1 through 30')
    scores = pd.read_csv(resolve(cfg, cfg['evaluation']['output_dir']) / 'scores_by_lead.csv')
    normalization = json.loads((resolve(cfg, cfg['training']['output_dir']) / 'normalization.json').read_text())
    threshold = normalization['flood_threshold_cumecs']
    for lead, frame in predictions.groupby('lead_day'):
        recalculated = metrics(frame.observed_cumecs, frame.delta_HBV, threshold)
        saved = scores.loc[scores.lead_day.eq(lead)].iloc[0]
        for name in ('NSE', 'KGE', 'RMSE_cumecs', 'MAE_cumecs', 'PBIAS_pct'):
            if not np.isclose(recalculated[name], saved[name], rtol=1e-9, atol=1e-9, equal_nan=True):
                raise AssertionError(f'Saved {name} differs at lead {lead}')
    comparison = resolve(cfg, cfg['evaluation']['comparison_dir']) / 'matched_predictions.csv'
    matched = pd.read_csv(comparison)
    if len(matched) != len(predictions) or not np.allclose(matched.observed_cumecs, predictions.observed_cumecs, rtol=0, atol=1e-10):
        raise AssertionError('Comparison does not use the same observed records')
    report = {
        'observed_source_sha256': sha256(source), 'local_table_byte_identical': True,
        'all_prediction_targets_match_original_observations': True,
        'all_30_lead_days_present': sorted(predictions.lead_day.unique().tolist()) == list(range(1, 31)),
        'saved_metrics_recomputed': True,
        'comparison_records_match': True, 'prediction_rows': len(predictions),
        'lead_30_observed_targets': int(predictions.loc[predictions.lead_day.eq(30), 'observed_cumecs'].notna().sum()),
        'discharge_values_filled_or_modified': False,
    }
    out = resolve(cfg, cfg['evaluation']['output_dir']) / 'verification.json'
    out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
