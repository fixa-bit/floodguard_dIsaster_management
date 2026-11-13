"""Train each basis model using the existing masked, chronological training loop."""
import argparse
import hashlib
import json
from pathlib import Path

from .core.data import load_config, resolve
from .core.training import run_training
from _nhits.data import BasisDataset
from _nhits.model import build_model


def train_config(config_path, checkpoint=None):
    cfg = load_config(config_path)
    t = cfg['training']; seeds = t['seeds'][:t['ensemble_size']]
    if len(seeds) != t['ensemble_size'] or not seeds or len(set(seeds)) != len(seeds):
        raise ValueError('Provide unique seeds for each requested ensemble member')
    if checkpoint and cfg['finetuning']['freeze_hindcast'] and cfg['architecture']['name'] != 'lstm_control':
        raise ValueError('Residual MLPs have no hindcast LSTM to freeze')
    output = resolve(cfg, cfg['finetuning']['output_dir'] if checkpoint else t['output_dir'])
    for seed in seeds:
        if (output / f'seed_{seed}' / 'best.pt').exists():
            raise FileExistsError('Choose a new output_dir; saved models are not overwritten')
    paths = [str(run_training(cfg, seed, initial_checkpoint=checkpoint,
                              model_factory=build_model, dataset_factory=BasisDataset)) for seed in seeds]
    output.mkdir(parents=True, exist_ok=True)
    (output / 'ensemble.json').write_text(json.dumps({'checkpoints': paths, 'seeds': seeds}, indent=2) + '\n')
    source = resolve(cfg, cfg['data']['daily_file'])
    (output / 'input_manifest.json').write_text(json.dumps({'daily_file': str(source),
        'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'no_discharge_filling': True,
        'forecast_mode': cfg['data']['forecast_mode'], 'past_discharge_as_input': cfg['data']['past_discharge']}, indent=2) + '\n')
    print('Completed', cfg['model_family'], paths, flush=True)
    return paths


def main(default_config):
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(default_config))
    parser.add_argument('--checkpoint', help='Optional same-architecture checkpoint for fine-tuning')
    args = parser.parse_args()
    train_config(args.config, args.checkpoint)
