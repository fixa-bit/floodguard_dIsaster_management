"""Train one frozen-config Marala experiment; select on validation loss only."""
import argparse
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Subset
import yaml

from data import (DataStore, DeltaDataset, fit_statistics, load_config, public_config,
                  resolve, save_json, sha256, years)
from model import DeltaHBV, masked_loss


def validation_loss(model, loader, stats, options, device):
    total, count = 0., 0
    model.eval()
    with torch.no_grad():
        for batch in loader:
            pred = model(batch['neural'].to(device), batch['forcing'].to(device))
            loss = masked_loss(pred, batch['target'].to(device), batch['mask'].to(device), stats, options)
            n = int(batch['mask'].sum())
            total += float(loss) * n
            count += n
    return total / count


def train(config_path):
    cfg = load_config(config_path)
    options = cfg['training']
    output = resolve(cfg, options['output_dir'])
    if (output / 'best.pt').exists():
        raise FileExistsError('Choose a new output_dir to preserve the trained checkpoint')
    random.seed(options['seed'])
    np.random.seed(options['seed'])
    torch.manual_seed(options['seed'])
    torch.set_num_threads(options['cpu_threads'])
    device = torch.device(options['device'])
    source = resolve(cfg, cfg['data']['daily_file'])
    before = sha256(source)
    store = DataStore(cfg)
    stats = fit_statistics(store)
    train_data = DeltaDataset(store, 'train', stats, training_noise=True, seed=options['seed'])
    validation = DeltaDataset(store, 'validation', stats)
    # Keep all dates available; evenly subsample issue dates only during fitting.
    selected = list(range(0, len(train_data), options['sample_stride']))
    generator = torch.Generator().manual_seed(options['seed'])
    loader = DataLoader(Subset(train_data, selected), batch_size=options['batch_size'], shuffle=True, generator=generator)
    valid_loader = DataLoader(validation, batch_size=options['batch_size'], shuffle=False)
    model = DeltaHBV(cfg).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=options['learning_rate'], weight_decay=options['weight_decay'])
    output.mkdir(parents=True, exist_ok=True)
    (output / 'config.yaml').write_text(yaml.safe_dump(public_config(cfg), sort_keys=False), encoding='utf-8')
    save_json(output / 'normalization.json', stats)
    history, best, stale = [], float('inf'), 0
    started = time.perf_counter()
    print(f'Train issues: {len(selected)}/{len(train_data)}; validation: {len(validation)}; parameters: {sum(p.numel() for p in model.parameters())}', flush=True)
    for epoch in range(options['epochs']):
        epoch_start = time.perf_counter()
        train_data.epoch = epoch
        model.train()
        total, count = 0., 0
        for batch in loader:
            optimizer.zero_grad(set_to_none=True)
            pred = model(batch['neural'].to(device), batch['forcing'].to(device))
            loss = masked_loss(pred, batch['target'].to(device), batch['mask'].to(device), stats, options)
            if not torch.isfinite(loss):
                raise FloatingPointError('Nonfinite training loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), options['gradient_clip'], error_if_nonfinite=True)
            optimizer.step()
            n = int(batch['mask'].sum())
            total += float(loss.detach()) * n
            count += n
        valid_loss = validation_loss(model, valid_loader, stats, options, device)
        row = {'epoch': epoch + 1, 'training_loss': total / count, 'validation_loss': valid_loss,
               'seconds': time.perf_counter() - epoch_start}
        history.append(row)
        print(f"Epoch {epoch + 1}: train={row['training_loss']:.5f} validation={valid_loss:.5f} time={row['seconds']:.1f}s", flush=True)
        if valid_loss < best - options['min_delta']:
            best, stale = valid_loss, 0
            torch.save({'model_state': model.state_dict(), 'statistics': stats,
                        'config': public_config(cfg), 'training_years': years(cfg['splits']['train']),
                        'selection_years': years(cfg['splits']['validation']), 'epoch': epoch + 1,
                        'validation_loss': best, 'source_sha256': before,
                        'model_name': 'delta_HBV_1.0_Marala',
                        'upstream_revision': 'b163a3c0125c5188f730f379643437d83b4e5d35'}, output / 'best.pt')
        else:
            stale += 1
        pd.DataFrame(history).to_csv(output / 'history.csv', index=False)
        if stale >= options['patience']:
            break
    if sha256(source) != before:
        raise RuntimeError('Input table changed during training')
    summary = {'seconds': time.perf_counter() - started, 'epochs': len(history),
               'best_validation_loss': best, 'parameters': sum(p.numel() for p in model.parameters()),
               'train_samples_available': len(train_data), 'train_samples_per_epoch': len(selected),
               'validation_samples': len(validation), 'seed': options['seed'],
               'training_years': years(cfg['splits']['train']), 'selection_years': years(cfg['splits']['validation']),
               'source_sha256_unchanged': before, 'hpo_trials': 1}
    save_json(output / 'training_summary.json', summary)
    print(f'Saved {output / "best.pt"}; total {summary["seconds"]:.1f}s', flush=True)
    return cfg


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    cfg = train(parser.parse_args().config)
    from evaluate import evaluate
    evaluate(cfg)
