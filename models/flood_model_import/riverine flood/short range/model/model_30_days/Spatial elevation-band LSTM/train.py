"""Train the 30-lead elevation-band LSTM and matched catchment-mean control."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

from data import DataStore, resolve
from spatial_data import SpatialDataset, load_spatial_config
from spatial_model import build_model
from lstm.train import run_training

ROOT = Path(__file__).resolve().parent


def main():
    cfg = load_spatial_config(ROOT / 'config.yaml')
    run_manifest = resolve(cfg, cfg['spatial']['run_manifest'])
    if run_manifest.exists():
        raise FileExistsError(f'Existing run manifest: {run_manifest}')
    # Fit the spatial model from four bands, then a matched model from their area means.
    store = DataStore(cfg)
    spatial_path = run_training(cfg, cfg['training']['seeds'][0], model_factory=build_model,
                                dataset_factory=SpatialDataset)

    control = deepcopy(cfg)
    control['data']['dynamic_columns'] = cfg['control']['dynamic_columns']
    control['data']['forecast_columns'] = cfg['control']['forecast_columns']
    control['data']['reanalysis_columns'] = cfg['control']['forecast_columns']
    control['spatial']['mode'] = 'catchment_mean'
    control['model']['hidden_size'] = 64
    control['training']['output_dir'] = cfg['control']['output_dir']
    control['model_family'] = 'matched_catchment_mean_control'
    control_path = run_training(control, cfg['training']['seeds'][0], dataset_factory=SpatialDataset)

    run_manifest.parent.mkdir(parents=True, exist_ok=True)
    run_manifest.write_text(json.dumps({
        'spatial': str(spatial_path), 'control': str(control_path),
        'seed': cfg['training']['seeds'][0], 'train_years': list(range(2016, 2021)),
        'validation_years': [2021], 'test_years': [2022, 2023, 2024],
    }, indent=2) + '\n', encoding='utf-8')
    print('Spatial checkpoint:', spatial_path, flush=True)
    print('Mean-control checkpoint:', control_path, flush=True)
    spec = importlib.util.spec_from_file_location('spatial_30day_evaluation', ROOT / 'evaluate.py')
    evaluation = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluation)
    evaluation.main()


if __name__ == '__main__':
    main()
