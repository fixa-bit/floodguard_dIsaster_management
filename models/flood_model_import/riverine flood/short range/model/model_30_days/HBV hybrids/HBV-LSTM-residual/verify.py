"""Check source observations and the fixed physical-HBV baseline in saved forecasts."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    cfg = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
    original_path = (ROOT / cfg['source_daily_file']).resolve()
    local_path = (ROOT / cfg['daily_file']).resolve()
    if digest(original_path) != digest(local_path):
        raise AssertionError('Bundled observed daily input differs from source')
    source = pd.read_csv(original_path, parse_dates=['date'])[['date', 'q_cumecs']]
    result = pd.read_csv(ROOT / cfg['test_output_dir'] / 'forecast_detail.csv', parse_dates=['target_date'])
    joined = result.merge(source, left_on='target_date', right_on='date', validate='many_to_one')
    if len(joined) != len(result) or not np.allclose(joined.observed_cumecs, joined.q_cumecs, rtol=0, atol=1e-10):
        raise AssertionError('A saved target differs from the original observed discharge')
    physical_path = (ROOT.parents[3] / 'model' / 'model_30_days' / 'HBV hybrids' /
                     'calibrated-physical-HBV' / 'reports' / 'initial' / 'predictions.csv')
    physical = pd.read_csv(physical_path, parse_dates=['target_date'])
    keys = ['basin_id', 'issue_date', 'target_date', 'lead_day']
    matched = result.merge(physical, on=keys, how='inner', validate='one_to_one', suffixes=('_hybrid', '_physical'))
    if len(matched) != len(result):
        raise AssertionError('Hybrid and calibrated physical HBV test keys do not match')
    if not np.allclose(matched.HBV_physical, matched.Calibrated_HBV, rtol=1e-7, atol=1e-6):
        raise AssertionError('Hybrid physical base does not reproduce the calibrated-HBV forecasts')
    if not np.allclose(matched.observed_cumecs_hybrid, matched.observed_cumecs_physical, rtol=0, atol=1e-10):
        raise AssertionError('Physical and hybrid forecast files disagree on observed targets')
    report = {
        'daily_table_byte_identical_to_source': True,
        'all_saved_targets_equal_original_observations': True,
        'physical_base_reproduces_calibrated_hbv_predictions': True,
        'matched_issue_lead_pairs': len(result),
        'lead30_observed_targets': int(result.loc[result.lead_day.eq(cfg['horizon']), 'observed_cumecs'].notna().sum()),
        'discharge_values_filled_or_modified': False,
    }
    out = ROOT / cfg['test_output_dir'] / 'verification.json'
    out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
