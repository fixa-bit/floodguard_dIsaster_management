"""Bundled project implementation with local imports; see source_reference."""
import argparse
import hashlib
import json
import os
import random
import time
import warnings
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
import yaml

from data import DataStore, StreamflowDataset, fit_statistics, load_config, public_config, resolve, years
from model import HindcastForecastLSTM, masked_pinball


def seed_everything(seed, threads):
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(True)


def device_for(cfg):
    requested = cfg['training']['device']
    return torch.device('cuda' if requested == 'auto' and torch.cuda.is_available() else 'cpu' if requested == 'auto' else requested)


def load_checkpoint(path):
    # Only load checkpoints produced by this project or another trusted source.
    return torch.load(path, map_location='cpu', weights_only=True)


def check_evaluation_years(cfg, checkpoint):
    test = set(years(cfg['splits']['test']))
    used = set(checkpoint['training_years']) | set(checkpoint['selection_years'])
    if test & used:
        raise ValueError(f'Test years previously used for fitting/selection: {sorted(test & used)}')


def run_training(cfg, seed, initial_checkpoint=None, model_factory=None, dataset_factory=None):
    training = cfg['training']
    seed_everything(seed, training['cpu_threads'])
    torch.set_flush_denormal(training.get('flush_denormal', False))
    initial = load_checkpoint(initial_checkpoint) if initial_checkpoint else None
    if initial:
        check_evaluation_years(cfg, initial)
        if set(years(cfg['splits']['validation'])) & set(initial['training_years']):
            raise ValueError('Validation years were used for training the original checkpoint')
    store = DataStore(cfg)
    recompute = initial is None or cfg['finetuning']['recompute_normalization']
    if initial and recompute:
        warnings.warn('Recomputing normalization changes the coordinates seen by pretrained weights; fine-tuning must readapt. Keep old statistics for a direct continuation.')
    stats = fit_statistics(store) if recompute else initial['statistics']
    dataset_class = dataset_factory or StreamflowDataset
    train = dataset_class(store, 'train', stats, training_noise=True, seed=seed)
    validation = dataset_class(store, 'validation', stats)
    dimensions = train.dimensions()
    model = model_factory(cfg, dimensions, stats) if model_factory else HindcastForecastLSTM(cfg, *dimensions)
    if initial:
        if dimensions != tuple(initial['dimensions']) or cfg['model']['quantiles'] != initial['config']['model']['quantiles']:
            raise ValueError('Fine-tuning requires the same feature schema and quantiles')
        model.load_state_dict(initial['model_state'])
        if hasattr(model, 'set_input_statistics'):
            model.set_input_statistics(stats)
        if cfg['finetuning']['freeze_hindcast']:
            for parameter in model.hindcast.parameters():
                parameter.requires_grad = False
    device = device_for(cfg)
    model.to(device)
    output = resolve(cfg, cfg['finetuning']['output_dir'] if initial else training['output_dir']) / f'seed_{seed}'
    output.mkdir(parents=True, exist_ok=True)
    learning_rate = cfg['finetuning']['learning_rate'] if initial else training['learning_rate']
    epochs = cfg['finetuning']['epochs'] if initial else training['epochs']
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=learning_rate, weight_decay=training['weight_decay'])
    generator = torch.Generator().manual_seed(seed)
    train_loader = DataLoader(train, batch_size=training['batch_size'], shuffle=True, generator=generator, num_workers=0)
    val_loader = DataLoader(validation, batch_size=training['batch_size'], shuffle=False, num_workers=0)
    inherited_train = initial['training_years'] if initial else []
    inherited_selection = initial['selection_years'] if initial else []
    metadata = {'training_years': sorted(set(inherited_train + years(cfg['splits']['train']))),
                'selection_years': sorted(set(inherited_selection + years(cfg['splits']['validation']))),
                'configured_test_years': years(cfg['splits']['test'])}
    if initial and recompute:
        metadata['normalization_recomputed'] = True
    check_evaluation_years(cfg, metadata)
    source_hashes = {key: hashlib.sha256(resolve(cfg, cfg['data'][key]).read_bytes()).hexdigest()
                     for key in ('daily_file', 'static_file', 'forecast_file') if cfg['data'].get(key)}
    best, bad_epochs, history = float('inf'), 0, []
    start = time.perf_counter()
    for epoch in range(1, epochs + 1):
        train.epoch = epoch
        model.train()
        train_sum, train_n = 0.0, 0
        for batch in train_loader:
            optimizer.zero_grad()
            prediction = model(*(batch[k].to(device) for k in ('history', 'future', 'static')))
            loss = masked_pinball(prediction, batch['target'].to(device), batch['mask'].to(device), model.quantiles)
            if not torch.isfinite(loss):
                raise FloatingPointError('Nonfinite training loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), training['gradient_clip'])
            optimizer.step()
            n = int(batch['mask'].sum())
            train_sum += float(loss.detach()) * n
            train_n += n
        model.eval()
        val_sum, val_n = 0.0, 0
        with torch.no_grad():
            for batch in val_loader:
                prediction = model(*(batch[k].to(device) for k in ('history', 'future', 'static')))
                loss = masked_pinball(prediction, batch['target'].to(device), batch['mask'].to(device), model.quantiles)
                n = int(batch['mask'].sum())
                val_sum += float(loss) * n
                val_n += n
        val_loss = val_sum / val_n
        history.append({'epoch': epoch, 'train_pinball': train_sum / train_n, 'validation_pinball': val_loss})
        print(f'Seed {seed} epoch {epoch}/{epochs}: train={train_sum / train_n:.5f}, validation={val_loss:.5f}', flush=True)
        if val_loss < best - training['min_delta']:
            best, bad_epochs = val_loss, 0
            checkpoint = {'model_state': {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
                          'optimizer_state': optimizer.state_dict(), 'statistics': stats, 'config': public_config(cfg),
                          'dimensions': list(dimensions), 'epoch': epoch, 'validation_pinball': val_loss,
                          'seed': seed, 'source_hashes': source_hashes, 'train_samples': len(train),
                          'validation_samples': len(validation), 'parent_checkpoint': str(initial_checkpoint) if initial else None,
                          'torch_version': str(torch.__version__),
                          'model_family': cfg.get('model_family', 'hindcast_forecast_lstm'), **metadata}
            torch.save(checkpoint, output / 'best.pt')
        else:
            bad_epochs += 1
        if bad_epochs >= training['patience']:
            break
    for key, digest in source_hashes.items():
        if hashlib.sha256(resolve(cfg, cfg['data'][key]).read_bytes()).hexdigest() != digest:
            raise RuntimeError('An input file changed during training')
    (output / 'config.yaml').write_text(yaml.safe_dump(public_config(cfg), sort_keys=False))
    (output / 'normalization.json').write_text(json.dumps(stats, indent=2) + '\n')
    (output / 'years.json').write_text(json.dumps(metadata, indent=2) + '\n')
    (output / 'history.json').write_text(json.dumps({'epochs': history, 'elapsed_seconds': time.perf_counter() - start,
                                                   'learning_rate': learning_rate, 'source_hashes_unchanged': True}, indent=2) + '\n')
    return output / 'best.pt'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    args = parser.parse_args()
    cfg = load_config(args.config)
    n = cfg['training']['ensemble_size']
    seeds = cfg['training']['seeds'][:n]
    if len(seeds) != n or len(set(seeds)) != n or n < 1:
        raise ValueError('Provide enough unique seeds for ensemble_size')
    checkpoints = [str(run_training(cfg, seed)) for seed in seeds]
    out = resolve(cfg, cfg['training']['output_dir'])
    (out / 'ensemble.json').write_text(json.dumps({'checkpoints': checkpoints, 'seeds': seeds}, indent=2) + '\n')
    print('Saved:', *checkpoints, sep='\n')


if __name__ == '__main__':
    main()
