"""Train observed-only hybrid forecasts using the shared seeded training loop."""
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
from data import load_config, resolve
from lstm.train import run_training
from hybrid_physics_ml.model import build_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    parser.add_argument('--checkpoint', help='Optional hybrid checkpoint for fine-tuning')
    args = parser.parse_args()
    cfg = load_config(args.config)
    count = cfg['training']['ensemble_size']
    seeds = cfg['training']['seeds'][:count]
    if count < 1 or len(seeds) != count or len(set(seeds)) != count:
        raise ValueError('Provide enough unique ensemble seeds')
    output = resolve(cfg, cfg['finetuning']['output_dir'] if args.checkpoint else cfg['training']['output_dir'])
    if any((output / f'seed_{seed}' / 'best.pt').exists() for seed in seeds):
        raise FileExistsError('Use a new output_dir to preserve earlier model runs')
    checkpoints = [str(run_training(cfg, seed, initial_checkpoint=args.checkpoint, model_factory=build_model)) for seed in seeds]
    output.mkdir(parents=True, exist_ok=True)
    (output / 'ensemble.json').write_text(json.dumps({'checkpoints': checkpoints, 'seeds': seeds}, indent=2) + '\n')
    print('Saved hybrid checkpoint(s):', *checkpoints, sep='\n', flush=True)


if __name__ == '__main__':
    main()
