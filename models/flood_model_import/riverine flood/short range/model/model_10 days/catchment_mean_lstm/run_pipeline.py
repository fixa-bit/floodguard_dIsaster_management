"""Durable sequential extraction, preparation, training and evaluation."""
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
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='spatially_distributed_model/config.yaml')
    parser.add_argument('--extraction-config', default='spatially_distributed_model/extraction.json')
    parser.add_argument('--extraction-python', default=str(root.parent / 'dataset/chenab_marala/raw/marala/rainfall/google_earth_engine/.venv/Scripts/python.exe'))
    args = parser.parse_args()
    steps = [
        ('download', [args.extraction_python, '-u', 'spatially_distributed_model/download_data.py', '--config', args.extraction_config]),
        ('prepare', [sys.executable, '-u', 'spatially_distributed_model/prepare_data.py', '--config', args.config]),
        ('train', [sys.executable, '-u', 'spatially_distributed_model/train.py', '--config', args.config]),
        ('evaluate', [sys.executable, '-u', 'spatially_distributed_model/evaluate.py', '--config', args.config])]
    for label, command in steps:
        print(f'STAGE {label}', flush=True)
        subprocess.run(command, cwd=root, check=True)
    print('PIPELINE COMPLETE', flush=True)


if __name__ == '__main__':
    main()
