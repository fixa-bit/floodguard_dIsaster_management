"""Sequential three-seed fitting with all choices fixed before test evaluation."""
import argparse
import json
import os
import random
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader
import yaml

from data import DataStore, ResidualDataset, fit_statistics, load_config, public_config, resolve, years
from metrics import save_json, sha
from model import ResidualLSTM, objective
from postprocess import fit_postprocessing

ROOT = Path(__file__).resolve().parent


class Tee:
    def __init__(self, stream, file):
        self.stream, self.file = stream, file

    def write(self, text):
        self.stream.write(text)
        self.file.write(text)
        self.file.flush()
        return len(text)

    def flush(self):
        self.stream.flush()
        self.file.flush()


def seed_everything(seed, threads):
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(threads)
    torch.set_flush_denormal(True)
    torch.use_deterministic_algorithms(True)


def move_batch(batch, device):
    return {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in batch.items()}


def predict(model, dataset, cfg):
    device = torch.device(cfg['training']['device'])
    model.eval()
    outputs = {k: [] for k in ('mean', 'quantiles', 'baseline', 'smooth', 'targets', 'mask')}
    with torch.no_grad():
        for batch in DataLoader(dataset, batch_size=cfg['training']['batch_size'], shuffle=False):
            batch = move_batch(batch, device)
            mean, q = model(batch['history'], batch['future'], batch['smooth_climatology'])
            outputs['mean'].append(mean.cpu().numpy())
            outputs['quantiles'].append(q.cpu().numpy())
            for name, key in [('baseline', 'climatology'), ('smooth', 'smooth_climatology'), ('targets', 'target_q'), ('mask', 'mask')]:
                outputs[name].append(batch[key].cpu().numpy())
    return {k: np.concatenate(v) for k, v in outputs.items()}


def selection_mse(model, loader, cfg, scale):
    low, high = cfg['training']['selection_leads']
    total, count = 0., 0
    model.eval()
    with torch.no_grad():
        for batch in loader:
            batch = move_batch(batch, torch.device(cfg['training']['device']))
            mean, _ = model(batch['history'], batch['future'], batch['smooth_climatology'])
            valid = batch['mask'][:, low - 1:high]
            error = (mean[:, low - 1:high] - batch['target_q'][:, low - 1:high])[valid] / scale
            total += float(error.square().sum())
            count += int(valid.sum())
    return total / count


def fit_seed(cfg, stats, store, parent, seed):
    seed_everything(seed, cfg['training']['cpu_threads'])
    train = ResidualDataset(store, 'train', stats, training_noise=True, seed=seed)
    valid = ResidualDataset(store, 'validation', stats)
    model = ResidualLSTM(cfg, train.dimensions(), stats)
    model.initialize_from_parent(parent)
    model.to(cfg['training']['device'])
    folder = resolve(cfg, cfg['training']['output_dir']) / f'seed_{seed}'
    if folder.exists():
        raise FileExistsError(f'Preserve existing seed run: {folder}')
    folder.mkdir(parents=True)
    options = cfg['training']
    optimizer = torch.optim.AdamW(model.parameters(), lr=options['learning_rate'], weight_decay=options['weight_decay'])
    generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(train, batch_size=options['batch_size'], shuffle=True, generator=generator)
    validation_loader = DataLoader(valid, batch_size=options['batch_size'], shuffle=False)
    best = selection_mse(model, validation_loader, cfg, stats['flow_std_cumecs'])
    initial_mse = best
    best_epoch, stale = 0, 0
    history = []
    source = resolve(cfg, cfg['data']['daily_file'])
    source_hash = sha(source)

    def save(epoch):
        torch.save({'model_state': model.state_dict(), 'statistics': stats, 'config': public_config(cfg),
                    'dimensions': list(train.dimensions()), 'epoch': epoch,
                    'validation_selection_mse': best, 'seed': seed,
                    'training_years': years(cfg['splits']['train']),
                    'selection_years': years(cfg['splits']['validation']),
                    'source_sha256': source_hash, 'parent_checkpoint_sha256': sha(resolve(cfg, cfg['model']['parent_checkpoint'])),
                    'training_samples': len(train), 'validation_samples': len(valid),
                    'point_output': 'conditional mean in cumecs; separate quantile head'}, folder / 'best.pt')
    save(0)
    started = time.perf_counter()
    print(f'Seed {seed}: initial smooth-climatology validation scaled MSE={best:.5f}', flush=True)
    for epoch in range(1, options['epochs'] + 1):
        model.train()
        train.epoch = epoch
        total, count = 0., 0
        for batch in loader:
            batch = move_batch(batch, torch.device(options['device']))
            optimizer.zero_grad(set_to_none=True)
            mean, q = model(batch['history'], batch['future'], batch['smooth_climatology'])
            loss = objective(mean, q, batch, model.flow_scale, cfg)
            if not torch.isfinite(loss):
                raise FloatingPointError('Nonfinite residual training loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), options['gradient_clip'], error_if_nonfinite=True)
            optimizer.step()
            n = int(batch['mask'].sum())
            total += float(loss.detach()) * n
            count += n
        score = selection_mse(model, validation_loader, cfg, stats['flow_std_cumecs'])
        history.append({'epoch': epoch, 'training_loss': total / count, 'validation_scaled_mse_leads21_30': score})
        print(f'Seed {seed} epoch {epoch}: train={total / count:.5f} validation_MSE={score:.5f}', flush=True)
        if score < best - options['min_delta']:
            best, best_epoch, stale = score, epoch, 0
            save(epoch)
        else:
            stale += 1
        pd.DataFrame(history).to_csv(folder / 'history.csv', index=False)
        if stale >= options['patience']:
            break
    if sha(source) != source_hash:
        raise RuntimeError('Source data changed')
    summary = {'seed': seed, 'seconds': time.perf_counter() - started, 'epochs': len(history),
               'selected_epoch': best_epoch, 'selected_validation_mse': best,
               'initial_smooth_climatology_validation_mse': initial_mse,
               'selected_initial_baseline_only': best_epoch == 0,
               'parameters': sum(p.numel() for p in model.parameters()),
               'training_samples': len(train), 'validation_samples': len(valid)}
    save_json(folder / 'training_summary.json', summary)
    (folder / 'config.yaml').write_text(yaml.safe_dump(public_config(cfg), sort_keys=False), encoding='utf-8')
    return folder / 'best.pt', summary


def main(config_path):
    cfg = load_config(config_path)
    output = resolve(cfg, cfg['training']['output_dir'])
    if output.exists():
        raise FileExistsError('Choose a new run directory; existing ensemble is protected')
    source = resolve(cfg, cfg['data']['daily_file'])
    source_hash = sha(source)
    parent_path = resolve(cfg, cfg['model']['parent_checkpoint'])
    parent = torch.load(parent_path, map_location='cpu', weights_only=True)
    if set(parent['training_years'] + parent['selection_years']) & set(years(cfg['splits']['test'])):
        raise ValueError('Parent used a configured benchmark year')
    protocol = {'config_sha256': sha(config_path), 'frozen_before_training': True,
                'seeds': cfg['training']['seeds'], 'sequential_seed_training': True,
                'smoothing_window_chosen_before_test': cfg['model']['smooth_climatology_window'],
                'selection': '2021 scaled point MSE across leads 21-30',
                'postprocessing': '2021 only; three fixed lead groups; no test data',
                'test_evaluation_after_selection_only': True,
                'no_test_driven_retry': True, 'source_sha256': source_hash,
                'parent_sha256': sha(parent_path), 'missing_targets_remain_nan': True}
    save_json(ROOT / 'protocol.json', protocol)
    store = DataStore(cfg)
    stats = fit_statistics(store)
    for key in ('dynamic', 'forecast', 'flow'):
        if stats[key] != parent['statistics'][key]:
            raise ValueError(f'Parent input coordinates differ: {key}')
    with (ROOT / 'training.log').open('x', encoding='utf-8') as log, redirect_stdout(Tee(sys.stdout, log)):
        checkpoints, summaries = [], []
        for seed in cfg['training']['seeds']:
            path, summary = fit_seed(cfg, stats, store, parent, seed)
            checkpoints.append(str(path))
            summaries.append(summary)
        save_json(output / 'ensemble.json', {'checkpoints': checkpoints, 'seeds': cfg['training']['seeds'], 'aggregation': 'uniform mean'})
        validation = ResidualDataset(store, 'validation', stats)
        predictions = []
        for path in checkpoints:
            checkpoint = torch.load(path, map_location='cpu', weights_only=True)
            model = ResidualLSTM(cfg, validation.dimensions(), stats)
            model.load_state_dict(checkpoint['model_state'])
            model.to(cfg['training']['device'])
            predictions.append(predict(model, validation, cfg))
        mean = np.mean([x['mean'] for x in predictions], axis=0)
        quantiles = np.mean([x['quantiles'] for x in predictions], axis=0)
        first = predictions[0]
        post = fit_postprocessing(mean, quantiles, first['baseline'], first['targets'], first['mask'], cfg)
        save_json(output / 'validation_postprocessing.json', post)
        save_json(output / 'selection_complete.json', {'postprocessing_sha256': sha(output / 'validation_postprocessing.json'),
                  'config_sha256': sha(config_path), 'selection_complete_before_test': True,
                  'new_models_fitted': len(checkpoints), 'training_summaries': summaries})
        print('All validation selection and postprocessing frozen. Starting one benchmark evaluation.', flush=True)
        from evaluate import evaluate
        evaluate(cfg)
        if sha(source) != source_hash:
            raise RuntimeError('Source data changed')
        (ROOT / 'requirements-lock.txt').write_text(subprocess.check_output([sys.executable, '-m', 'pip', 'freeze'], text=True), encoding='utf-8')
        queue_path = ROOT.parents[1] / 'training_queue.json'
        queue = json.loads(queue_path.read_text())
        queue[0].update(completed_variants=['scratch', 'past_discharge', 'climatology_residual_ensemble'],
                        completed_variant='climatology_residual_ensemble', status='trained and evaluated; awaiting user feedback')
        save_json(queue_path, queue)
        print('Residual ensemble complete; all other model families remain pending feedback.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(ROOT / 'config.yaml'))
    main(parser.parse_args().config)
