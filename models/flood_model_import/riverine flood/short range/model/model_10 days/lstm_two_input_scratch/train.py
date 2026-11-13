"""Pretrain on real donor basins, fine-tune on Marala, and fit a matched control."""
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
import hashlib
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import DataStore, load_config, resolve, years
from lstm.train import load_checkpoint, run_training
from lstm_two_input_scratch.download_data import workflow


def run_stage(cfg, stage, parent=None):
    key = {'pretrain': 'pretrain_config', 'finetune': 'finetune_config', 'scratch': 'scratch_config'}[stage]
    config = load_config(cfg['_root'] / (cfg['variant_config'] if stage == cfg.get('variant_stage') else cfg['stages'][key]))
    seed = config['training']['seeds'][0]
    output_dir = config['finetuning']['output_dir'] if stage == 'finetune' else config['training']['output_dir']
    if (resolve(config, output_dir) / f'seed_{seed}' / 'best.pt').exists():
        raise FileExistsError('Checkpoint already exists; choose a new stage output_dir to preserve the previous experiment')
    if stage == 'pretrain':
        store = DataStore(config)
        donors = sorted(b for b, frame in store.frames.items()
                        if frame.loc[frame.index.year.isin(years(config['splits']['train'])), store.d['target_column']].notna().any())
        if len(donors) < 2 or 'marala' in donors:
            raise ValueError('Pretraining requires at least two observed donor basins, excluding Marala')
    else:
        donors = []
    if stage == 'finetune':
        if parent is None:
            raise ValueError('Fine-tuning requires the multi-basin parent checkpoint')
        original = load_checkpoint(parent)
        donors = original.get('pretraining_basins', [])
        if len(donors) < 2:
            raise ValueError('Parent is not a verified multi-basin checkpoint')
    output = run_training(config, seed, initial_checkpoint=parent if stage == 'finetune' else None)
    checkpoint = load_checkpoint(output)
    checkpoint['training_stage'] = stage
    checkpoint['pretraining_basins'] = donors
    checkpoint['pretraining_dataset'] = 'CAMELS-US original Zenodo archive' if donors else None
    if stage == 'finetune':
        checkpoint['pretraining_parent_sha256'] = hashlib.sha256(Path(parent).read_bytes()).hexdigest()
    torch.save(checkpoint, output)
    print(f'{stage} checkpoint: {output}', flush=True)
    return str(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    parser.add_argument('--stage', choices=['all', 'pretrain', 'finetune', 'scratch'], default='scratch')
    parser.add_argument('--checkpoint')
    args = parser.parse_args()
    cfg = workflow(args.config)
    manifest = cfg['_root'] / cfg['stages']['manifest']
    state = json.loads(manifest.read_text()) if manifest.exists() else {}
    for stage in ['pretrain', 'finetune', 'scratch'] if args.stage == 'all' else [args.stage]:
        parent = (args.checkpoint or str((cfg['_root'] / cfg['pretrained_checkpoint']).resolve()) or state.get('pretrain')) if stage == 'finetune' else None
        state[stage] = run_stage(cfg, stage, parent)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(state, indent=2) + '\n')


if __name__ == '__main__':
    main()
