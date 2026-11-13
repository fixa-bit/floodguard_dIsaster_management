"""Fine-tune the genuine global checkpoint using masked local runoff targets."""
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
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fine_tuned_global_pretrained_lstm.data import GlobalDataset, load_config, resolve, schema
from fine_tuned_global_pretrained_lstm.model import GlobalPretrainedLSTM, masked_mse
from lstm.train import load_checkpoint


KEYS = ['history', 'future', 'static', 'history_missing', 'future_missing', 'static_missing']


def years(bounds):
    return list(range(int(bounds[0]), int(bounds[1]) + 1))


def check_years(cfg, original):
    trained = list(range(int(original['train_start_date'][-4:]), int(original['train_end_date'][-4:]) + 1))
    selected = list(range(int(original['validation_start_date'][-4:]), int(original['validation_end_date'][-4:]) + 1))
    if set(years(cfg['splits']['validation']) + years(cfg['splits']['test'])) & set(trained):
        raise ValueError('Validation/test years overlap global pretraining; choose years after its cutoff')
    if set(years(cfg['splits']['test'])) & set(years(cfg['splits']['train']) + selected + years(cfg['splits']['validation'])):
        raise ValueError('Test years overlap training or model selection')
    return trained, selected


def configure_seed(cfg):
    t = cfg['training']; random.seed(t['seed']); np.random.seed(t['seed']); torch.manual_seed(t['seed'])
    torch.set_num_threads(t['cpu_threads']); torch.use_deterministic_algorithms(True)
    torch.set_flush_denormal(t['flush_denormal'])


def run_finetuning(cfg):
    configure_seed(cfg)
    settings = cfg['training']; norm = schema(cfg)
    trained, selected = check_years(cfg, norm['source_config'])
    initial = settings.get('initial_checkpoint')
    previous = load_checkpoint(resolve(cfg, initial)) if initial else None
    if previous:
        if previous['normalization'] != norm:
            raise ValueError('Keep the same global normalization and feature schema when continuing')
        if set(years(cfg['splits']['validation']) + years(cfg['splits']['test'])) & set(previous['training_years']):
            raise ValueError('New validation/test years were used by the earlier checkpoint for training')
        if set(years(cfg['splits']['test'])) & set(previous['selection_years']):
            raise ValueError('New test years were used by the earlier checkpoint for model selection')
    reference = load_checkpoint(resolve(cfg, cfg['reference']['checkpoint']))
    train = GlobalDataset(cfg, 'train', norm, reference['statistics'], training_noise=True, seed=settings['seed'])
    validation = GlobalDataset(cfg, 'validation', norm, reference['statistics'])
    model = GlobalPretrainedLSTM(norm['source_config'], settings['gradient_history_days'])
    parent_path = resolve(cfg, cfg['pretrained']['checkpoint'])
    parent = torch.load(parent_path, map_location='cpu', weights_only=True)
    model.load_published_weights(parent)
    if previous:
        model.load_state_dict(previous['model_state'])
    if settings['freeze_recurrent']:
        for parameter in model.lstm.parameters():
            parameter.requires_grad = False
    if settings['freeze_static_embedding']:
        for parameter in model.embedding_net.parameters():
            parameter.requires_grad = False
    groups = [{'params': [p for p in model.lstm.parameters() if p.requires_grad], 'lr': settings['recurrent_learning_rate']},
              {'params': [p for name, p in model.named_parameters() if not name.startswith('lstm.') and p.requires_grad],
               'lr': settings['embedding_head_learning_rate']}]
    optimizer = torch.optim.AdamW(groups, weight_decay=settings['weight_decay'])
    output = resolve(cfg, settings['output_dir'])
    if (output / 'best.pt').exists():
        raise FileExistsError('Choose a new output_dir; trained checkpoints are not overwritten')
    output.mkdir(parents=True, exist_ok=True)
    generator = torch.Generator().manual_seed(settings['seed'])
    loader = DataLoader(train, batch_size=settings['batch_size'], shuffle=True, generator=generator)
    valid_loader = DataLoader(validation, batch_size=settings['batch_size'], shuffle=False)
    hashes = {name: hashlib.sha256(resolve(cfg, path).read_bytes()).hexdigest() for name, path in {
        'daily': cfg['data']['daily_file'], 'static': cfg['data']['static_file'], 'parent': cfg['pretrained']['checkpoint'],
        'global_scaler': cfg['pretrained']['scaler']}.items()}
    history, best, stale = [], float('inf'), 0
    start = time.perf_counter()
    for epoch in range(1, settings['epochs'] + 1):
        model.train(); train.epoch = epoch; total, count = 0., 0
        for batch in loader:
            optimizer.zero_grad()
            prediction = model(*(batch[key] for key in KEYS))
            loss = masked_mse(prediction, batch['target'], batch['mask'])
            if not torch.isfinite(loss):
                raise FloatingPointError('Nonfinite masked training loss')
            loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(), settings['gradient_clip']); optimizer.step()
            n = int(batch['mask'].sum()); total += float(loss.detach()) * n; count += n
        model.eval(); valid_total, valid_count = 0., 0
        with torch.no_grad():
            for batch in valid_loader:
                prediction = model(*(batch[key] for key in KEYS))
                loss = masked_mse(prediction, batch['target'], batch['mask'])
                n = int(batch['mask'].sum()); valid_total += float(loss) * n; valid_count += n
        valid_loss = valid_total / valid_count
        if not np.isfinite(valid_loss):
            raise FloatingPointError('Nonfinite validation loss')
        history.append({'epoch': epoch, 'train_mse': total / count, 'validation_mse': valid_loss})
        print(f'Global fine-tune {epoch}/{settings["epochs"]}: train={total / count:.6f}, validation={valid_loss:.6f}', flush=True)
        if valid_loss < best - settings['min_delta']:
            best, stale = valid_loss, 0
            checkpoint = {'model_state': model.state_dict(), 'normalization': norm,
                          'config': {k: v for k, v in cfg.items() if not k.startswith('_')},
                          'epoch': epoch, 'validation_mse': valid_loss, 'parent_sha256': hashes['parent'], 'source_hashes': hashes,
                          'pretrained_model_repository': 'EmilRyd/caravan_model', 'pretrained_basin_count': norm['source_config']['number_of_basins'],
                          'global_training_years': trained, 'global_selection_years': selected,
                          'local_training_years': sorted(set(years(cfg['splits']['train']) + (previous['local_training_years'] if previous else []))),
                          'local_selection_years': sorted(set(years(cfg['splits']['validation']) + (previous['local_selection_years'] if previous else []))),
                          'training_years': sorted(set(trained + years(cfg['splits']['train']) + (previous['training_years'] if previous else []))),
                          'selection_years': sorted(set(selected + years(cfg['splits']['validation']) + (previous['selection_years'] if previous else []))),
                          'initial_local_checkpoint': str(resolve(cfg, initial)) if initial else None,
                          'train_samples': len(train), 'validation_samples': len(validation),
                          'area_km2': train.area_km2, 'all_published_tensors_loaded_exactly': True}
            torch.save(checkpoint, output / 'best.pt')
        else:
            stale += 1
        if stale >= settings['patience']:
            break
    for key, path in {'daily': cfg['data']['daily_file'], 'static': cfg['data']['static_file'],
                       'parent': cfg['pretrained']['checkpoint'], 'global_scaler': cfg['pretrained']['scaler']}.items():
        if hashlib.sha256(resolve(cfg, path).read_bytes()).hexdigest() != hashes[key]:
            raise AssertionError('A source changed during training')
    selected_checkpoint = load_checkpoint(output / 'best.pt')
    changed = [key for key, value in parent.items() if not torch.equal(value, selected_checkpoint['model_state'][key])]
    (output / 'history.json').write_text(json.dumps({'epochs': history, 'elapsed_seconds': time.perf_counter() - start,
                                                    'source_hashes_unchanged': True, 'published_tensors_changed_by_finetuning': changed}, indent=2) + '\n')
    (output / 'normalization.json').write_text(json.dumps(norm, indent=2) + '\n')
    (output / 'config.yaml').write_text(yaml.safe_dump({k: v for k, v in cfg.items() if not k.startswith('_')}, sort_keys=False))
    (output / 'years.json').write_text(json.dumps({key: selected_checkpoint[key] for key in ['global_training_years', 'global_selection_years', 'local_training_years', 'local_selection_years']}, indent=2) + '\n')
    print('Saved actual global fine-tune:', output / 'best.pt', flush=True)
    return output / 'best.pt'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    parser.add_argument('--checkpoint', help='Optional saved local adaptation to continue with a fresh optimizer')
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.checkpoint:
        cfg['training']['initial_checkpoint'] = str(Path(args.checkpoint).resolve())
    run_finetuning(cfg)
