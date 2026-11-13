"""Small reproducible CPU LSTM, supervised exclusively on observed targets.

Input discharge is also observed-only. Missing inputs are standardized zero with
an explicit mask. No two-sided interpolation or synthetic discharge enters training.
"""
import csv
import hashlib
import json
import random
from datetime import date
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

HERE = Path(__file__).resolve().parent
LOOKBACK, HORIZON, EPOCHS, SEED = 30, 15, 15, 42


class Forecast(nn.Module):
    def __init__(self):
        super().__init__()
        self.lstm = nn.LSTM(4, 16, batch_first=True)
        self.head = nn.Linear(16, HORIZON)

    def forward(self, x):
        sequence, _ = self.lstm(x)
        return self.head(sequence[:, -1])


def metrics(actual, predicted):
    errors = predicted - actual
    denominator = np.sum((actual - actual.mean()) ** 2)
    return dict(n=len(actual), mae_m3_s=float(np.abs(errors).mean()),
                rmse_m3_s=float(np.sqrt(np.mean(errors ** 2))),
                nse=float(1 - np.sum(errors ** 2) / denominator) if denominator else None)


def main():
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    path = HERE / 'data/daily_observed_priority.csv'
    rows = list(csv.DictReader(path.open(encoding='utf-8', newline='')))
    q = np.array([float(r['observed_discharge_m3_s']) for r in rows], dtype=np.float32)
    observed = np.isfinite(q)
    training = np.array([r['split'] == 'train' for r in rows]) & observed
    mean, std = float(q[training].mean()), float(q[training].std())
    standardized = np.where(observed, (q - mean) / std, 0)
    days = np.array([(date.fromisoformat(r['date']) - date(int(r['date'][:4]), 1, 1)).days for r in rows])
    features = np.stack([standardized, observed.astype(np.float32), np.sin(2 * np.pi * days / 365.25), np.cos(2 * np.pi * days / 365.25)], axis=1).astype(np.float32)
    partitions = {}
    for part in ('train', 'validation', 'test'):
        indexes = [i for i in range(LOOKBACK, len(rows) - HORIZON + 1)
                   if all(r['split'] == part for r in rows[i:i + HORIZON])
                   and observed[i - 1] and observed[i - LOOKBACK:i].sum() >= 15
                   and observed[i:i + HORIZON].any()]
        x = np.stack([features[i - LOOKBACK:i] for i in indexes])
        mask = np.stack([observed[i:i + HORIZON] for i in indexes])
        y = np.stack([np.where(observed[i:i + HORIZON], (q[i:i + HORIZON] - mean) / std, 0) for i in indexes])
        partitions[part] = (indexes, torch.tensor(x), torch.tensor(y), torch.tensor(mask, dtype=torch.float32))
    model = Forecast()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.003)
    _, x, y, mask = partitions['train']
    loader = DataLoader(TensorDataset(x, y, mask), batch_size=64, shuffle=True, generator=torch.Generator().manual_seed(SEED))
    output = HERE / 'observed_only'
    output.mkdir(exist_ok=True)
    history, best = [], float('inf')
    for epoch in range(1, EPOCHS + 1):
        model.train()
        for inputs, targets, valid in loader:
            optimizer.zero_grad()
            loss = (((model(inputs) - targets) ** 2) * valid).sum() / valid.sum()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1)
            optimizer.step()
        model.eval()
        with torch.no_grad():
            _, vx, vy, vm = partitions['validation']
            validation = float((((model(vx) - vy) ** 2) * vm).sum() / vm.sum())
        history.append(dict(epoch=epoch, validation_mse_standardized=validation))
        if validation < best:
            best = validation
            torch.save(model.state_dict(), output / 'model.pt')
        print(f'Epoch {epoch}/{EPOCHS}, validation MSE {validation:.5f}', flush=True)
    model.load_state_dict(torch.load(output / 'model.pt', weights_only=True))
    model.eval()
    report = dict(seed=SEED, lookback=LOOKBACK, horizon=HORIZON, epochs=EPOCHS,
                  selected_epoch=min(history, key=lambda r: r['validation_mse_standardized'])['epoch'],
                  dataset_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  torch_version=torch.__version__, numpy_version=np.__version__,
                  train_mean_m3_s=mean, train_std_m3_s=std,
                  predictors=['past observed discharge', 'past observation mask', 'day-of-year sine', 'day-of-year cosine'],
                  target_policy='Observed only, masked MSE. No interpolated or modeled targets.',
                  input_policy='Past observations only, standardized zero + mask for missing inputs; require last input observed and >=15 observed days in 30-day window.',
                  limitations=['Retrospective date-level experiment; historical issue-time availability is unconfirmed.', 'IRSA daily means differ from point observations; source and basis preserved in predictions.', 'Overlapping forecast windows are not independent events.'],
                  split_windows={p: len(v[0]) for p, v in partitions.items()}, history=history, scores={})
    predictions = []
    for part in ('validation', 'test'):
        indexes, x, _, mask = partitions[part]
        with torch.no_grad():
            pred = np.maximum(0, model(x).numpy() * std + mean)
        report['scores'][part] = {}
        for lead in range(HORIZON):
            valid = mask[:, lead].numpy().astype(bool)
            indices = np.array(indexes)[valid]
            actual = q[indices + lead]
            forecast = pred[valid, lead]
            persistence = q[indices - 1]
            report['scores'][part][str(lead + 1)] = dict(lstm=metrics(actual, forecast), persistence=metrics(actual, persistence))
            for i, a, f, baseline in zip(indices, actual, forecast, persistence):
                target = rows[i + lead]
                predictions.append(dict(split=part, issue_after_date=rows[i - 1]['date'], target_date=target['date'], lead_days=lead + 1,
                                        observed_m3_s=float(a), lstm_m3_s=float(f), persistence_m3_s=float(baseline),
                                        target_source=target['source'], measurement_basis=target['measurement_basis']))
    with (output / 'predictions_observed_days.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    (output / 'training_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({p: {lead: report['scores'][p][lead] for lead in ('1', '3', '7', '15')} for p in ('validation', 'test')}, indent=2))


if __name__ == '__main__':
    main()
