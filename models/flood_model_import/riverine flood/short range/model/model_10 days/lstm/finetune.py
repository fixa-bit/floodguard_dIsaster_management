"""Continue fitting with new config-selected years/basins/forecast products."""
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
from pathlib import Path

from data import load_config
from train import load_checkpoint, run_training


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    parser.add_argument('--checkpoint', required=True)
    args = parser.parse_args()
    cfg = load_config(args.config)
    original = load_checkpoint(args.checkpoint)
    # Old normalization is the default: new stats change the meaning of old weights.
    output = run_training(cfg, original['seed'], initial_checkpoint=args.checkpoint)
    print(f'Fine-tuned checkpoint: {output}')


if __name__ == '__main__':
    main()
