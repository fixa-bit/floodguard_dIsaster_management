"""Figures and a written summary from train.py outputs.  Run: ../../.venv/Scripts/python.exe report.py"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pyproj
from shapely import union_all
from shapely.geometry import shape
from shapely.ops import transform

import data

ROOT = Path(__file__).resolve().parent
REPORTS, RUNS = ROOT / "reports", ROOT / "runs"
NAMES = {"lightgbm_forecast": "LightGBM, with day's rain (forecast stand-in)", "lightgbm_observed": "LightGBM, rain before the day only",
         "lightgbm_weather_only": "LightGBM, weather and terrain only (no reporting inputs)",
         "rain_trigger": "Climatology + rain trigger", "climatology": "Climatology (reporting-adjusted)"}
COLORS = {"lightgbm_forecast": "#2a78d6", "lightgbm_observed": "#1baf7a", "lightgbm_weather_only": "#6250d6", "rain_trigger": "#eb6834", "climatology": "#898781"}
# Two of the busiest test days for reported onsets, both dominated by hill and mountain flash floods.
CASES = [("2025-08-14", "KP, Gilgit-Baltistan and AJK cloudbursts (Buner floods began 15 Aug)"), ("2022-08-27", "KP floods, Swat valley")]
TO_GRID = pyproj.Transformer.from_crs(4326, 6933, always_xy=True)


def boundaries():
    out = {}
    for name in ("pakistan_lsib", "chenab_districts"):
        features = json.loads((data.GEE / "grid" / f"{name}.geojson").read_text(encoding="utf-8"))["features"]
        out[name] = transform(TO_GRID.transform, union_all([shape(f["geometry"]) for f in features]))
    return out


def draw_outline(axis, geometry, color, width):
    for polygon in getattr(geometry, "geoms", [geometry]):
        x, y = polygon.exterior.xy
        axis.plot(np.array(x) / 1000, np.array(y) / 1000, color=color, linewidth=width)


def cell_image(values, cells, grid):
    image = np.full((grid["height"], grid["width"]), np.nan)
    for value, cell in zip(values, cells):
        image[int(cell["row"]), int(cell["col"])] = value
    return image


def fmt(value, digits=3):
    return "—" if value is None or (isinstance(value, float) and not np.isfinite(value)) else f"{value:.{digits}f}"


def main():
    metrics = json.loads((REPORTS / "metrics.json").read_text(encoding="utf-8"))
    predictions = np.load(RUNS / "test_predictions.npz")
    cells = data.load_cells()
    grid = json.loads((data.GEE / "grid" / "grid_definition.json").read_text(encoding="utf-8"))
    extent = [grid["x0"] / 1000, (grid["x0"] + grid["width"] * grid["cell_m"]) / 1000, (grid["y1"] - grid["height"] * grid["cell_m"]) / 1000, grid["y1"] / 1000]
    outlines = boundaries()
    day, cell, y = predictions["day"], predictions["cell"], predictions["y"]
    dates = predictions["dates"]
    models = [name for name in NAMES if name in predictions.files]

    # Reliability
    figure, axis = plt.subplots(figsize=(6, 5))
    for name in models:
        rows = metrics["test"][name]["reliability_pakistan"]
        axis.plot([r["p_mean"] for r in rows], [r["observed_rate"] for r in rows], marker="o", color=COLORS[name], linewidth=2, label=NAMES[name])
    top = max(max(r["observed_rate"] for r in metrics["test"][name]["reliability_pakistan"]) for name in models)
    axis.plot([0, top], [0, top], color="#c3c2b7", linewidth=1, label="Perfectly calibrated")
    axis.set(xscale="log", yscale="log", xlabel="Predicted chance of a reported onset (decile mean)", ylabel="Observed onset rate", title="Reliability, test 2022–Jan 2026, all Pakistan")
    axis.legend(fontsize=8)
    figure.tight_layout()
    figure.savefig(REPORTS / "reliability.png", dpi=150)
    plt.close(figure)

    # Test-period maps: observed onsets per cell vs mean predicted probability
    best = "lightgbm_forecast"
    counts = np.bincount(cell, weights=y, minlength=len(cells))
    scored = np.bincount(cell, minlength=len(cells))
    mean_p = np.bincount(cell, weights=predictions[best], minlength=len(cells)) / np.maximum(scored, 1)
    figure, axes = plt.subplots(1, 2, figsize=(13, 6))
    for axis, values, title, cmap in ((axes[0], np.where(counts > 0, counts, np.nan), "Reported flash-flood onsets per cell, 2022–Jan 2026", "Oranges"),
                                      (axes[1], mean_p * 365, f"Expected onsets per year from {NAMES[best]}", "Blues")):
        image = axis.imshow(cell_image(values, cells, grid), extent=extent, cmap=cmap, norm=matplotlib.colors.LogNorm(), origin="upper")
        draw_outline(axis, outlines["pakistan_lsib"], "#52514e", 0.8)
        draw_outline(axis, outlines["chenab_districts"], "#d03b3b", 1.0)
        axis.set_title(title, fontsize=10)
        axis.set_xticks([]); axis.set_yticks([])
        figure.colorbar(image, ax=axis, shrink=0.75)
    figure.text(0.5, 0.02, "Red outline: Chenab districts (Sialkot to Jhang). 20 km EASE-Grid 2.0 cells.", ha="center", fontsize=9)
    figure.savefig(REPORTS / "test_period_maps.png", dpi=150, bbox_inches="tight")
    plt.close(figure)

    # Case days
    date_index = {str(d): i for i, d in enumerate(dates)}
    figure, axes = plt.subplots(1, len(CASES), figsize=(13, 6))
    case_notes = []
    for axis, (when, title) in zip(np.atleast_1d(axes), CASES):
        index = date_index.get(when)
        mask = day == index
        values = np.full(len(cells), np.nan)
        values[cell[mask]] = predictions[best][mask]
        image = axis.imshow(cell_image(values, cells, grid), extent=extent, cmap="Blues", norm=matplotlib.colors.LogNorm(vmin=1e-4, vmax=1), origin="upper")
        hit = cell[mask][y[mask] == 1]
        axis.scatter([float(cells[c]["x_center_m"]) / 1000 for c in hit], [float(cells[c]["y_center_m"]) / 1000 for c in hit],
                     s=30, facecolors="none", edgecolors="#d95926", linewidths=1.5, label="Reported onset")
        draw_outline(axis, outlines["pakistan_lsib"], "#52514e", 0.8)
        axis.set_title(f"{when}: {title}", fontsize=10)
        axis.set_xticks([]); axis.set_yticks([])
        axis.legend(loc="lower right", fontsize=8)
        figure.colorbar(image, ax=axis, shrink=0.75, label="Predicted chance")
        p_day = predictions[best][mask]
        ranked = np.argsort(-p_day)
        top = set(cell[mask][ranked[:max(1, int(np.ceil(0.05 * mask.sum())))]])
        case_notes.append((when, title, int(len(hit)), int(sum(c in top for c in hit))))
    figure.savefig(REPORTS / "case_days.png", dpi=150, bbox_inches="tight")
    plt.close(figure)

    # Written summary
    test = metrics["test"]
    lines = ["# Flash-flood model: test results", "",
             f"Generated from `metrics.json` ({metrics['created_utc']}). Target: a reported flood onset in a 20 km cell on a Pakistan-local day. "
             f"Test: {metrics['splits']['test'][0]} to {metrics['splits']['test'][1]}, every cell-day not masked as ongoing coverage.", "",
             "| Model | Area | Onsets | Base rate | PR-AUC | ROC-AUC | Brier skill vs climatology | Onsets in daily top 1 % / 5 % of cells | Hit rate | False-alarm ratio | CSI |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name in models:
        for key, label in (("pakistan|all", "Pakistan"), ("chenab_districts|all", "Chenab districts")):
            r = test[name][key]
            lines.append(f"| {NAMES[name]} | {label} | {r.get('onsets', 0):,} | {fmt(r.get('base_rate'), 5)} | {fmt(r.get('pr_auc'))} | {fmt(r.get('roc_auc'))} | "
                         f"{fmt(r.get('brier_skill_vs_climatology'))} | {fmt(r.get('onsets_in_daily_top_1pct'), 2)} / {fmt(r.get('onsets_in_daily_top_5pct'), 2)} | "
                         f"{fmt(r.get('hit_rate'), 2)} | {fmt(r.get('false_alarm_ratio'), 2)} | {fmt(r.get('csi'), 3)} |")
    lines += ["", "Alarm thresholds were chosen on 2020–2021 to maximise CSI. PR-AUC should be read against the base rate (a no-skill model scores the base rate).", "",
              "## By year and season (Pakistan, LightGBM with the day's rain)", "", "| Slice | Onsets | PR-AUC | ROC-AUC | Brier skill | Top 5 % |", "|---|---:|---:|---:|---:|---:|"]
    for key, r in test["lightgbm_forecast"].items():
        if key.startswith("pakistan|") and key != "pakistan|all":
            lines.append(f"| {key.split('|')[1]} | {r.get('onsets', 0):,} | {fmt(r.get('pr_auc'))} | {fmt(r.get('roc_auc'))} | {fmt(r.get('brier_skill_vs_climatology'))} | {fmt(r.get('onsets_in_daily_top_5pct'), 2)} |")
    lines += ["", "## By province (LightGBM with the day's rain)", "", "| Area | Onsets | PR-AUC | ROC-AUC | Brier skill | Top 5 % |", "|---|---:|---:|---:|---:|---:|"]
    for key, r in test["lightgbm_forecast"].items():
        if key.startswith("province:") and key.endswith("|all"):
            lines.append(f"| {key.split('|')[0].split(':')[1]} | {r.get('onsets', 0):,} | {fmt(r.get('pr_auc'))} | {fmt(r.get('roc_auc'))} | {fmt(r.get('brier_skill_vs_climatology'))} | {fmt(r.get('onsets_in_daily_top_5pct'), 2)} |")
    lines += ["", "## Case days", ""]
    for when, title, onsets, caught in case_notes:
        lines.append(f"- {when}, {title}: {onsets} cells reported an onset; {caught} of them were among the 5 % highest-risk cells that day.")
    lines += ["", "## What the model relies on (share of total gain)", ""]
    for mode in ("lightgbm_forecast", "lightgbm_observed", "lightgbm_weather_only"):
        top = metrics["models"][mode]["importance"][:8]
        lines.append(f"- {NAMES[mode]}: " + ", ".join(f"{item['feature']} {item['gain_share']:.0%}" for item in top))
    lines += ["", "Figures: `reliability.png`, `test_period_maps.png`, `case_days.png`."]
    (REPORTS / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
