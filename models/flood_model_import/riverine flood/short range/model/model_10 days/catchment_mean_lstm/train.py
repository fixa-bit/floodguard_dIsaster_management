"""Train the elevation-band model and the same-source catchment-mean control."""
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
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import resolve
from lstm.train import run_training
from catchment_mean_lstm.data import load_spatial_config, SpatialDataset
from catchment_mean_lstm.model import build_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    parser.add_argument('--stage', choices=['all', 'spatial', 'mean_control'], default='mean_control')
    args = parser.parse_args()
    main_cfg = load_spatial_config(args.config)
    state_file = resolve(main_cfg, main_cfg['spatial']['run_manifest'])
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    for stage in ['spatial', 'mean_control'] if args.stage == 'all' else [args.stage]:
        cfg = main_cfg if stage == main_cfg.get('variant_stage') else load_spatial_config(resolve(main_cfg, main_cfg['spatial']['control_config']))
        count = cfg['training']['ensemble_size']
        seeds = cfg['training']['seeds'][:count]
        if count < 1 or len(seeds) != count or len(set(seeds)) != count:
            raise ValueError('Provide enough unique seeds')
        out = resolve(cfg, cfg['training']['output_dir'])
        if any((out / f'seed_{seed}' / 'best.pt').exists() for seed in seeds):
            raise FileExistsError('Choose a new stage output_dir to preserve existing checkpoints')
        state[stage] = [str(run_training(cfg, seed, model_factory=build_model if stage == 'spatial' else None,
                                         dataset_factory=SpatialDataset)) for seed in seeds]
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(state, indent=2) + '\n')
        print(stage, 'saved:', *state[stage], flush=True)


if __name__ == '__main__':
    main()
