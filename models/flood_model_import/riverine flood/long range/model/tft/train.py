"""Train and evaluate the Marala long-range Temporal Fusion Transformer.

Per mode (forecast, climate_conditioned) and seed:
  1. pretrain on simulated GloFAS v5 discharge (1980-2015),
  2. fine-tune on observed Marala inflow (train 2016-2021, early-stop 2022-2023),
  3. ablation: same network trained on observed data only (no pretraining).
Seed ensembles are averaged in normalised log space. Test = issues from 2024 on.

    ../../.venv/Scripts/python.exe train.py            # everything
    ../../.venv/Scripts/python.exe train.py --smoke    # 1 seed, 2 epochs
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import common  # noqa: E402
from tft import TemporalFusionTransformer, quantile_loss  # noqa: E402

LOG_VARS = {"precip_era5land_mm", "snowmelt_mm"}
GLOFAS, OBSERVED = 0, 1


# ------------------------------------------------------------------ data
def prepare(frame: pd.DataFrame, cfg: dict) -> dict:
    """Normalised arrays on the full daily calendar. Statistics come from pretrain-train years only."""
    stat_end = pd.Timestamp(cfg["pretrain"]["train"]["targets"][1])
    forcing = frame[common.FORCING].copy()
    for c in LOG_VARS:
        forcing[c] = np.log1p(forcing[c].clip(lower=0))
    ref = forcing.loc[:stat_end]
    mu, sd = ref.mean(), ref.std()
    forcing_z = ((forcing - mu) / sd)

    q_ref = np.log1p(frame.loc[:stat_end, "q_glofas"])
    q_mu, q_sd = float(q_ref.mean()), float(q_ref.std())
    doy = frame.index.day_of_year.to_numpy()
    return {
        "dates": frame.index,
        "forcing": forcing_z.to_numpy(np.float32),
        "forcing_valid": forcing_z.notna().all(axis=1).to_numpy(),
        "doy": np.stack([np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)], 1).astype(np.float32),
        "q": {"glofas": ((np.log1p(frame["q_glofas"]) - q_mu) / q_sd).to_numpy(np.float32),
              "observed": ((np.log1p(frame["q_obs"]) - q_mu) / q_sd).to_numpy(np.float32)},
        "obs_source": frame["q_obs_source"].to_numpy(object),
        "q_obs_m3s": frame["q_obs"].to_numpy(np.float64),
        "norm": {"forcing_mean": mu.to_dict(), "forcing_std": sd.to_dict(), "q_log_mean": q_mu, "q_log_std": q_sd,
                 "log1p_vars": sorted(LOG_VARS), "statistics_period_end": str(stat_end.date())},
    }


def issue_indices(arr, cfg, split, target_key, mode_cfg, stride=1, require_past_obs=False):
    Te, Td = cfg["encoder_days"], cfg["horizon_days"]
    dates = arr["dates"]
    i0 = int(dates.searchsorted(pd.Timestamp(split["issues"][0])))
    i1 = min(int(dates.searchsorted(pd.Timestamp(split["issues"][1]), side="right")) - 1, len(dates) - 1)
    t0, t1 = pd.Timestamp(split["targets"][0]), pd.Timestamp(split["targets"][1])
    q = arr["q"][target_key]
    past_ok = np.isfinite(arr["forcing"][:, past_cols(mode_cfg)]).all(1)
    fut_ok = np.isfinite(arr["forcing"][:, [common.FORCING.index(c) for c in mode_cfg["future_forcing"]]]).all(1)
    require_past_obs = require_past_obs and mode_cfg.get("past_discharge", True)
    out = []
    for i in range(max(i0, Te - 1), i1 + 1, stride):
        if not past_ok[i - Te + 1:i + 1].all():
            continue
        if mode_cfg["future_forcing"]:
            if i + Td >= len(dates) or not fut_ok[i + 1:i + Td + 1].all():
                continue
        fut = slice(i + 1, min(i + Td + 1, len(dates)))
        fdates = dates[fut]
        valid = np.isfinite(q[fut]) & (fdates >= t0) & (fdates <= t1)
        if valid.sum() < cfg["min_valid_targets"]:
            continue
        if require_past_obs and np.isfinite(q[i - 89:i + 1]).mean() < cfg["min_past_obs_coverage_90d"]:
            continue
        out.append(i)
    return np.asarray(out, dtype=np.int64)


def past_cols(mode_cfg):
    return [common.FORCING.index(c) for c in mode_cfg.get("past_forcing", common.FORCING)]


def past_names(mode_cfg):
    names = list(mode_cfg.get("past_forcing", common.FORCING)) + ["doy_sin", "doy_cos"]
    if mode_cfg.get("past_discharge", True):
        names += ["past_discharge", "discharge_available"]
    return names + ["relative_time"]


class Batcher:
    """Builds (past, future, static, target, mask) tensors on the device by index gathering."""

    def __init__(self, arr, cfg, mode_cfg, target_key, static_id, target_window, device):
        self.Te, self.Td = cfg["encoder_days"], cfg["horizon_days"]
        n = len(arr["dates"])
        pad = self.Td  # zero padding after the series end; padded steps are masked out of the loss
        future_cols = [common.FORCING.index(c) for c in mode_cfg["future_forcing"]]
        q = arr["q"][target_key]
        q_avail = np.isfinite(q).astype(np.float32)
        q_val = np.nan_to_num(q, nan=0.0).astype(np.float32)
        parts = [arr["forcing"][:, past_cols(mode_cfg)], arr["doy"]]
        if mode_cfg.get("past_discharge", True):
            parts += [q_val[:, None], q_avail[:, None]]
        past = np.concatenate(parts, 1)
        fut = np.concatenate([arr["forcing"][:, future_cols], arr["doy"]], 1)
        dates = arr["dates"]
        in_window = (dates >= pd.Timestamp(target_window[0])) & (dates <= pd.Timestamp(target_window[1]))
        tgt_mask = (np.isfinite(q) & in_window).astype(np.float32)
        P = lambda a: np.concatenate([a, np.zeros((pad,) + a.shape[1:], a.dtype)])  # noqa: E731
        t = lambda a: torch.from_numpy(np.nan_to_num(P(a), nan=0.0)).to(device)  # noqa: E731
        self.past, self.fut, self.q, self.mask = t(past), t(fut), t(q_val), t(tgt_mask)
        self.static_id, self.device = static_id, device
        self.n_past, self.n_future = past.shape[1] + 1, fut.shape[1] + 1  # +1 relative-position channel
        self.rel_past = torch.linspace(-1, 0, self.Te, device=device).view(1, -1, 1)
        self.rel_fut = (torch.arange(1, self.Td + 1, device=device) / self.Td).view(1, -1, 1)

    def __call__(self, idx: np.ndarray):
        i = torch.as_tensor(idx, device=self.device).view(-1, 1)
        pi = i + torch.arange(-self.Te + 1, 1, device=self.device).view(1, -1)
        fi = i + torch.arange(1, self.Td + 1, device=self.device).view(1, -1)
        B = len(idx)
        past = torch.cat([self.past[pi], self.rel_past.expand(B, -1, -1)], -1)
        fut = torch.cat([self.fut[fi], self.rel_fut.expand(B, -1, -1)], -1)
        static = torch.full((B,), self.static_id, device=self.device, dtype=torch.long)
        return past, fut, static, self.q[fi], self.mask[fi]


# ------------------------------------------------------------------ training
def run_epoch(model, batcher, idx, quantiles, bs, opt=None, rng=None):
    model.train(opt is not None)
    order = rng.permutation(idx) if rng is not None else idx
    total, weight = 0.0, 0.0
    with torch.set_grad_enabled(opt is not None):
        for k in range(0, len(order), bs):
            past, fut, static, y, m = batcher(order[k:k + bs])
            pred, _ = model(past, fut, static)
            loss = quantile_loss(pred, y, m, quantiles)
            if opt is not None:
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
            w = float(m.sum())
            total += float(loss.detach()) * w
            weight += w
    return total / max(weight, 1.0)


def fit(model, train_b, train_idx, val_b, val_idx, quantiles, tcfg, bs, seed, log):
    opt = torch.optim.AdamW(model.parameters(), lr=tcfg["lr"], weight_decay=1e-4)
    rng = np.random.default_rng(seed)
    best, best_state, bad, history = float("inf"), None, 0, []
    for epoch in range(tcfg["max_epochs"]):
        t0 = time.time()
        tr = run_epoch(model, train_b, train_idx, quantiles, bs, opt, rng)
        va = run_epoch(model, val_b, val_idx, quantiles, bs)
        history.append({"epoch": epoch + 1, "train_loss": tr, "val_loss": va, "seconds": round(time.time() - t0, 1)})
        log(f"    epoch {epoch + 1:3d} train {tr:.4f} val {va:.4f} ({time.time() - t0:.0f}s)")
        if va < best - 1e-5:
            best, best_state, bad = va, copy.deepcopy(model.state_dict()), 0
        else:
            bad += 1
            if bad >= tcfg["patience"]:
                break
    model.load_state_dict(best_state)
    return {"best_val_loss": best, "epochs_run": len(history), "history": history}


@torch.no_grad()
def predict(model, batcher, idx, bs):
    model.eval()
    preds, weights = [], []
    for k in range(0, len(idx), bs):
        past, fut, static, _, _ = batcher(idx[k:k + bs])
        p, interp = model(past, fut, static)
        preds.append(p.cpu())
        weights.append((interp["past_weights"].mean((0, 1)).cpu() * len(past), interp["future_weights"].mean((0, 1)).cpu() * len(past)))
    pw = sum(w[0] for w in weights) / len(idx)
    fw = sum(w[1] for w in weights) / len(idx)
    return torch.cat(preds).numpy(), pw.numpy(), fw.numpy()


def to_table(arr, cfg, idx, z_pred, model_name, mode, split):
    """Long table: one row per (issue, lead). Quantiles back-transformed to m3/s."""
    Td, n = cfg["horizon_days"], len(arr["dates"])
    mu, sd = arr["norm"]["q_log_mean"], arr["norm"]["q_log_std"]
    z_pred = np.sort(z_pred, axis=-1)  # no quantile crossing
    q = np.expm1(z_pred * sd + mu)
    rows = []
    t0, t1 = (pd.Timestamp(d) for d in cfg["finetune"][split]["targets"])
    for k, i in enumerate(idx):
        fi = np.arange(i + 1, min(i + Td + 1, n))
        fdates = arr["dates"][fi]
        keep = (fdates >= t0) & (fdates <= t1)
        lead = np.arange(1, len(fi) + 1)[keep]
        rows.append(pd.DataFrame({
            "model": model_name, "mode": mode, "split": split, "issue_date": arr["dates"][i].date().isoformat(),
            "target_date": fdates[keep].strftime("%Y-%m-%d"), "lead_days": lead,
            "obs_m3s": arr["q_obs_m3s"][fi][keep], "obs_source": arr["obs_source"][fi][keep],
            "p10_m3s": q[k, lead - 1, 0], "p50_m3s": q[k, lead - 1, 1], "p90_m3s": q[k, lead - 1, 2]}))
    return pd.concat(rows, ignore_index=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--modes", nargs="*")
    args = parser.parse_args()
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    if args.smoke:
        cfg["training"]["seeds"] = cfg["training"]["seeds"][:1]
        for k in ("pretrain", "finetune", "scratch"):
            cfg["training"][k]["max_epochs"] = 2
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    runs, reports = HERE / ("runs_smoke" if args.smoke else "runs"), HERE / ("reports_smoke" if args.smoke else "reports")
    runs.mkdir(exist_ok=True)
    reports.mkdir(exist_ok=True)
    modes = args.modes or list(cfg["modes"])
    log_file = (reports / f"training_log_{'+'.join(modes)}.txt").open("w", encoding="utf-8")

    def log(msg):
        print(msg, flush=True)
        log_file.write(msg + "\n")

    frame = common.load_all()
    arr = prepare(frame, cfg)
    q_set = cfg["quantiles"]
    bs = cfg["training"]["batch_size"]
    log(f"device {device}; calendar {frame.index[0].date()}..{frame.index[-1].date()}; "
        f"observed days {int(frame.q_obs.notna().sum())}; GloFAS days {int(frame.q_glofas.notna().sum())}")
    summary = {"config": cfg, "device": str(device), "torch": torch.__version__, "normalisation": arr["norm"],
               "data_provenance": common.provenance(), "runs": {}}
    tables, importance = [], {}

    for mode in modes:
        mcfg = cfg["modes"][mode]
        tr = cfg["training"]
        pre_tr = issue_indices(arr, cfg, cfg["pretrain"]["train"], "glofas", mcfg, tr["pretrain"]["issue_stride"])
        pre_va = issue_indices(arr, cfg, cfg["pretrain"]["val"], "glofas", mcfg)
        ft = {s: issue_indices(arr, cfg, cfg["finetune"][s], "observed", mcfg,
                               tr["finetune"]["issue_stride"] if s == "train" else 1, require_past_obs=True)
              for s in ("train", "val", "test")}
        log(f"\n=== mode {mode}: pretrain issues {len(pre_tr)}/{len(pre_va)}; observed issues "
            f"train {len(ft['train'])} val {len(ft['val'])} test {len(ft['test'])}")
        B = lambda key, sid, split, block: Batcher(arr, cfg, mcfg, key, sid, cfg[block][split]["targets"], device)  # noqa: E731
        b_pre_tr, b_pre_va = B("glofas", GLOFAS, "train", "pretrain"), B("glofas", GLOFAS, "val", "pretrain")
        b_obs = {s: B("observed", OBSERVED, s, "finetune") for s in ("train", "val", "test")}
        b_obs_as_glofas = B("observed", GLOFAS, "test", "finetune")
        ens = {"pretrained_only": [], "finetuned": [], "scratch": []}
        ens_val = {"finetuned": [], "scratch": []}
        weights = []
        for seed in tr["seeds"]:
            torch.manual_seed(seed)
            np.random.seed(seed)
            make = lambda: TemporalFusionTransformer(b_pre_tr.n_past, b_pre_tr.n_future, 2, quantiles=q_set, **cfg["model"]).to(device)  # noqa: E731
            key = f"{mode}/seed{seed}"
            summary["runs"][key] = {}

            log(f"  [{key}] pretrain on GloFAS")
            model = make()
            summary["runs"][key]["pretrain"] = fit(model, b_pre_tr, pre_tr, b_pre_va, pre_va, q_set, tr["pretrain"], bs, seed, log)
            torch.save(model.state_dict(), runs / f"{mode}_seed{seed}_pretrained.pt")
            ens["pretrained_only"].append(predict(model, b_obs_as_glofas, ft["test"], bs)[0])

            log(f"  [{key}] fine-tune on observed")
            summary["runs"][key]["finetune"] = fit(model, b_obs["train"], ft["train"], b_obs["val"], ft["val"], q_set, tr["finetune"], bs, seed, log)
            torch.save(model.state_dict(), runs / f"{mode}_seed{seed}_finetuned.pt")
            p, pw, fw = predict(model, b_obs["test"], ft["test"], bs)
            ens["finetuned"].append(p)
            ens_val["finetuned"].append(predict(model, b_obs["val"], ft["val"], bs)[0])
            weights.append((pw, fw))

            log(f"  [{key}] observed-only (no pretraining)")
            torch.manual_seed(seed)
            scratch = make()
            summary["runs"][key]["scratch"] = fit(scratch, b_obs["train"], ft["train"], b_obs["val"], ft["val"], q_set, tr["scratch"], bs, seed, log)
            torch.save(scratch.state_dict(), runs / f"{mode}_seed{seed}_scratch.pt")
            ens["scratch"].append(predict(scratch, b_obs["test"], ft["test"], bs)[0])
            ens_val["scratch"].append(predict(scratch, b_obs["val"], ft["val"], bs)[0])

        for variant, preds in ens.items():
            tables.append(to_table(arr, cfg, ft["test"], np.mean(preds, 0), f"tft_{variant}", mode, "test"))
        for variant, preds in ens_val.items():
            tables.append(to_table(arr, cfg, ft["val"], np.mean(preds, 0), f"tft_{variant}", mode, "val"))
        future_names = mcfg["future_forcing"] + ["doy_sin", "doy_cos", "relative_time"]
        importance[mode] = {
            "encoder": dict(zip(past_names(mcfg), np.mean([w[0] for w in weights], 0).round(4).tolist())),
            "decoder": dict(zip(future_names, np.mean([w[1] for w in weights], 0).round(4).tolist()))}

    allp = pd.concat(tables, ignore_index=True)
    for mode in modes:  # one file per mode so modes can be retrained independently
        allp.loc[allp["mode"].eq(mode)].to_csv(reports / f"predictions_{mode}.csv.gz", index=False, compression="gzip")
        (reports / f"variable_importance_{mode}.json").write_text(json.dumps(importance[mode], indent=2) + "\n", encoding="utf-8")
        mode_summary = {**summary, "runs": {k: v for k, v in summary["runs"].items() if k.startswith(mode + "/")}}
        (reports / f"run_report_{mode}.json").write_text(json.dumps(mode_summary, indent=2, default=str) + "\n", encoding="utf-8")
    (runs / "normalisation.json").write_text(json.dumps(arr["norm"], indent=2) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
