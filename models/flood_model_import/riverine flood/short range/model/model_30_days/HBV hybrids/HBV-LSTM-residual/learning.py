"""Quantile LightGBM per lead and state-initialized LSTM encoder/decoder."""
import json
from pathlib import Path
import numpy as np
import lightgbm as lgb
import torch
from torch import nn


def fit_boosters(x, residual, train, validation, config, out, feature_names, fixed_rounds=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    models, rounds, importance = [], [], []
    for lead in range(config["horizon"]):
        models.append([])
        rounds.append([])
        for qi, quantile in enumerate(config["quantiles"]):
            fit = train & np.isfinite(residual[:, lead])
            val = validation & np.isfinite(residual[:, lead])
            n = config["lgbm_estimators"] if fixed_rounds is None else fixed_rounds[lead][qi]
            model = lgb.LGBMRegressor(
                objective="quantile", alpha=quantile, n_estimators=int(n),
                learning_rate=0.035, num_leaves=15, max_depth=-1,
                min_child_samples=35, reg_lambda=2., verbosity=-1,
                random_state=config["seed"], n_jobs=config["threads"],
                deterministic=True, force_col_wise=True)
            kwargs = {}
            if fixed_rounds is None:
                if val.sum() == 0:
                    raise ValueError("No validation targets for LightGBM")
                kwargs = {"eval_X": x[val, lead], "eval_y": residual[val, lead],
                          "callbacks": [lgb.early_stopping(config["lgbm_patience"], verbose=False)]}
            model.fit(x[fit, lead], residual[fit, lead], feature_name=feature_names, **kwargs)
            model.booster_.save_model(str(out / f"lead_{lead+1:02d}_q{int(quantile*100):02d}.txt"))
            rounds[lead].append(int(model.best_iteration_ or n))
            importance.extend({"lead_day": lead + 1, "quantile": quantile,
                               "feature": name, "gain": float(gain)}
                              for name, gain in zip(feature_names, model.booster_.feature_importance("gain")))
            models[-1].append(model.booster_)
    (out / "metadata.json").write_text(json.dumps({"features": feature_names, "rounds": rounds,
                                                  "quantiles": config["quantiles"]}, indent=2))
    return models, rounds, importance


def predict_boosters(models, x):
    prediction = np.stack([np.stack([model.predict(x[:, lead]) for model in row], -1)
                           for lead, row in enumerate(models)], 1)
    # Rearrangement is explicit because separately trained quantiles can cross.
    return np.sort(prediction, axis=-1)


class Normalizer:
    def fit(self, x):
        self.mean = np.nanmean(x, axis=tuple(range(x.ndim - 1)))
        self.mean = np.nan_to_num(self.mean)
        self.scale = np.nanstd(x, axis=tuple(range(x.ndim - 1)))
        self.scale = np.where(np.isfinite(self.scale) & (self.scale > 1e-6), self.scale, 1.)
        return self

    def transform(self, x):
        finite = np.isfinite(x)
        values = np.where(finite, (x - self.mean) / self.scale, 0.)
        return np.concatenate([values, (~finite).astype(float)], -1).astype(np.float32)

    def to_dict(self):
        return {"mean": self.mean.tolist(), "scale": self.scale.tolist()}

    @classmethod
    def from_dict(cls, obj):
        norm = cls()
        norm.mean, norm.scale = np.array(obj["mean"]), np.array(obj["scale"])
        return norm


class ResidualLSTM(nn.Module):
    def __init__(self, history_size, future_size, hidden_size):
        super().__init__()
        self.encoder = nn.LSTM(history_size, hidden_size, batch_first=True)
        self.decoder = nn.LSTM(future_size, hidden_size, batch_first=True)
        self.head = nn.Sequential(nn.Linear(hidden_size, hidden_size), nn.ReLU(),
                                  nn.Linear(hidden_size, 3))

    def forward(self, past, future):
        _, state = self.encoder(past)
        hidden, _ = self.decoder(future, state)
        raw = self.head(hidden)
        center = raw[..., 1]
        return torch.stack([center - nn.functional.softplus(raw[..., 0]), center,
                            center + nn.functional.softplus(raw[..., 2])], -1)


def pinball(prediction, target):
    mask = torch.isfinite(target)
    error = torch.nan_to_num(target)[..., None] - prediction
    levels = prediction.new_tensor([0.1, 0.5, 0.9])
    losses = torch.maximum(levels * error, (levels - 1) * error)
    return (losses * mask[..., None]).sum() / (mask.sum().clamp_min(1) * 3)


def fit_lstm(history, future, residual, train, validation, config, out, fixed_epochs=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    torch.manual_seed(config["seed"])
    np.random.seed(config["seed"])
    torch.set_num_threads(config["threads"])
    torch.set_flush_denormal(True)
    torch.use_deterministic_algorithms(True)
    hnorm = Normalizer().fit(history[train])
    fnorm = Normalizer().fit(future[train])
    hs, fs = hnorm.transform(history), fnorm.transform(future)
    target_scale = max(float(np.nanstd(residual[train])), 1.)
    ys = (residual / target_scale).astype(np.float32)
    model = ResidualLSTM(hs.shape[-1], fs.shape[-1], config["lstm_hidden_size"])
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["lstm_learning_rate"], weight_decay=1e-4)
    rng = np.random.default_rng(config["seed"])
    indices = np.where(train & np.isfinite(ys).any(axis=1))[0]
    val_indices = np.where(validation & np.isfinite(ys).any(axis=1))[0]
    if fixed_epochs is None and len(val_indices) == 0:
        raise ValueError("No validation sequences for LSTM")
    best, best_epoch, stale, log = float("inf"), 0, 0, []
    epochs = config["lstm_epochs"] if fixed_epochs is None else int(fixed_epochs)
    for epoch in range(1, epochs + 1):
        model.train()
        total, count = 0., 0
        for batch in np.array_split(rng.permutation(indices), max(1, int(np.ceil(len(indices) / config["lstm_batch_size"])))):
            optimizer.zero_grad()
            prediction = model(torch.from_numpy(hs[batch]), torch.from_numpy(fs[batch]))
            loss = pinball(prediction, torch.from_numpy(ys[batch]))
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.)
            optimizer.step()
            total += float(loss.detach()) * len(batch)
            count += len(batch)
        model.eval()
        with torch.no_grad():
            val_losses, val_weights = [], []
            for batch in np.array_split(val_indices, max(1, int(np.ceil(len(val_indices) / 256)))):
                if not len(batch):
                    continue
                prediction = model(torch.from_numpy(hs[batch]), torch.from_numpy(fs[batch]))
                val_losses.append(float(pinball(prediction, torch.from_numpy(ys[batch]))))
                val_weights.append(int(np.isfinite(ys[batch]).sum()))
            vloss = float(np.average(val_losses, weights=val_weights)) if val_losses else None
        log.append({"epoch": epoch, "train_pinball_scaled": total / count,
                    "validation_pinball_scaled": vloss})
        if epoch == 1 or epoch % 10 == 0:
            print(f"  LSTM epoch {epoch}/{epochs}, validation loss {vloss}", flush=True)
        improved = fixed_epochs is not None or vloss < best - 1e-5
        if improved:
            best = vloss if vloss is not None else float("inf")
            best_epoch, stale = epoch, 0
            torch.save({"state_dict": model.state_dict(), "history_size": hs.shape[-1],
                        "future_size": fs.shape[-1], "hidden_size": config["lstm_hidden_size"],
                        "history_normalizer": hnorm.to_dict(), "future_normalizer": fnorm.to_dict(),
                        "residual_scale": target_scale, "epoch": epoch}, out / "best.pt")
        else:
            stale += 1
        if fixed_epochs is None and stale >= config["lstm_patience"]:
            break
    (out / "history.json").write_text(json.dumps(log, indent=2))
    checkpoint = torch.load(out / "best.pt", map_location="cpu", weights_only=False)
    model.load_state_dict(checkpoint["state_dict"])
    return model, hnorm, fnorm, target_scale, best_epoch


def predict_lstm(bundle, history, future):
    model, hnorm, fnorm, scale = bundle[:4]
    hs, fs = hnorm.transform(history), fnorm.transform(future)
    result = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(hs), 256):
            result.append(model(torch.from_numpy(hs[start:start+256]),
                                torch.from_numpy(fs[start:start+256])).numpy() * scale)
    return np.concatenate(result)


def load_lstm(path):
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    model = ResidualLSTM(ckpt["history_size"], ckpt["future_size"], ckpt["hidden_size"])
    model.load_state_dict(ckpt["state_dict"])
    return (model, Normalizer.from_dict(ckpt["history_normalizer"]),
            Normalizer.from_dict(ckpt["future_normalizer"]), ckpt["residual_scale"])
