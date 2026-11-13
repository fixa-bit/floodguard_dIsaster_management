"""Load the flash-flood grid inputs and labels, and build features at training time.

Every source stays in its own file under ../dataset; they are combined only here, in memory.

Label (one value per cell and Pakistan-local day):
    1  a Groundsource flood report STARTS in the cell that day, lasting at most MAX_DURATION_DAYS and
       located to at most MAX_AREA_KM2, and no report started in the same cell in the previous
       ONSET_GAP_DAYS days (a new onset, not continued coverage of the same flood);
    0  no report starts in the cell that day;
    masked (excluded from training and scoring): days of an ongoing reported flood in the cell, and the
       ONSET_GAP_DAYS days after an onset, so continued coverage is not counted as new floods or as misses.
A report labels every cell holding at least MIN_EVENT_SHARE of its area, and always its centroid cell.
"""
from __future__ import annotations

import csv
import glob
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DATASET = ROOT.parent / "dataset"
GEE = DATASET / "raw" / "gee"
EVENTS = DATASET / "processed" / "groundsource_pakistan_events.csv"

MAX_DURATION_DAYS = 3
MAX_AREA_KM2 = 2000.0
MIN_EVENT_SHARE = 0.25
ONSET_GAP_DAYS = 3


@dataclass
class Grid:
    cells: list            # rows of cells.csv
    static: dict           # name -> (cells,)
    dates: np.ndarray      # datetime64[D], shape (days,)
    dynamic: dict          # name -> (days, cells) float32, NaN where missing
    label: np.ndarray      # (days, cells) int8: 1 onset, 0 none, -1 masked
    events_used: int
    events_dropped: dict


def load_cells():
    with (GEE / "grid" / "cells.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_static():
    data = np.load(GEE / "static" / "static_features.npz")
    values = {name: data[name].astype(np.float32) for name in data.files if name not in ("rows", "cols")}
    return {name: np.where(np.isfinite(array), array, np.nan) for name, array in values.items()}   # masked pixels arrive as -inf


def load_source(folder, start, end):
    """Concatenate monthly arrays of one source between two ISO dates (inclusive)."""
    files = sorted(glob.glob(str(GEE / folder / "*.npz")))
    parts, dates = {}, []
    for path in files:
        month = Path(path).stem
        if month < start[:7] or month > end[:7]:
            continue
        data = np.load(path)
        dates.append(data["dates"].astype("datetime64[D]"))
        for name in data.files:
            if name != "dates":
                parts.setdefault(name, []).append(data[name])
    if not dates:
        raise FileNotFoundError(f"No {folder} months between {start} and {end}")
    all_dates = np.concatenate(dates)
    return all_dates, {name: np.concatenate(values).astype(np.float32) for name, values in parts.items()}


def align(dates, source_dates, arrays):
    """Place a source on the common date axis; days the source lacks stay NaN."""
    index = {d: i for i, d in enumerate(source_dates)}
    rows = np.array([index.get(d, -1) for d in dates])
    out = {}
    for name, values in arrays.items():
        aligned = np.full((len(dates), values.shape[1]), np.nan, dtype=np.float32)
        aligned[rows >= 0] = values[rows[rows >= 0]]
        out[name] = aligned
    return out


def build_labels(dates, n_cells):
    label = np.zeros((len(dates), n_cells), dtype=np.int8)
    first = dates[0].astype(object)
    position = lambda day: (day - first).days
    dropped = {"too_long": 0, "too_large_or_unlocated": 0, "outside_period": 0}
    onsets = []
    with EVENTS.open(encoding="utf-8") as handle:
        for event in csv.DictReader(handle):
            start, end = date.fromisoformat(event["start_date"]), date.fromisoformat(event["end_date"])
            duration = (end - start).days + 1
            area = float(event["area_km2"] or "nan")
            if duration > MAX_DURATION_DAYS:
                dropped["too_long"] += 1
                continue
            if not np.isfinite(area) or area > MAX_AREA_KM2 or not event["cells"]:
                dropped["too_large_or_unlocated"] += 1
                continue
            cells = set()
            for item in event["cells"].split(";"):
                cell_id, share_of_event, _ = item.split(":")
                if float(share_of_event) >= MIN_EVENT_SHARE:
                    cells.add(int(cell_id))
            if event["centroid_cell"] != "":
                cells.add(int(event["centroid_cell"]))
            i0, i1 = position(start), position(end)
            if i0 < 0 or i0 >= len(dates):
                dropped["outside_period"] += 1
                continue
            onsets.append((i0, min(i1, len(dates) - 1), sorted(cells)))
    onsets.sort()
    for i0, i1, cells in onsets:
        for cell in cells:
            if label[i0, cell] == 0:
                label[i0, cell] = 1          # a new onset; a report inside a masked window stays masked
            stop = min(len(dates) - 1, max(i1, i0 + ONSET_GAP_DAYS))
            window = label[i0 + 1:stop + 1, cell]
            window[window != 1] = -1
    return label, len(onsets), dropped


def load(start="2009-12-01", end="2026-01-31"):
    cells = load_cells()
    static = load_static()
    first, last = np.datetime64(start), np.datetime64(end)
    dates = np.arange(first, last + 1, dtype="datetime64[D]")
    imerg_dates, imerg = load_source("imerg_v07", start, end)
    era5_dates, era5 = load_source("era5land_daily", start, end)
    dynamic = {**align(dates, imerg_dates, imerg), **align(dates, era5_dates, era5)}
    label, used, dropped = build_labels(dates, len(cells))
    return Grid(cells=cells, static=static, dates=dates, dynamic=dynamic, label=label, events_used=used, events_dropped=dropped)


def lagged_sum(values, start_lag, window):
    """Sum over days [t-start_lag-window+1, t-start_lag] for each day t; NaN if any of those days is missing."""
    days = values.shape[0]
    zeros = np.zeros((1, values.shape[1]))
    total = np.vstack([zeros, np.cumsum(np.nan_to_num(values, nan=0.0), axis=0, dtype=np.float64)])
    missing = np.vstack([zeros, np.cumsum(np.isnan(values), axis=0)])
    hi = np.arange(days) - start_lag + 1
    lo = hi - window
    ok = lo >= 0
    out = np.full(values.shape, np.nan, dtype=np.float32)
    sums = total[hi[ok]] - total[lo[ok]]
    gaps = missing[hi[ok]] - missing[lo[ok]]
    out[ok] = np.where(gaps > 0, np.nan, sums)
    return out


def shift(values, lag):
    out = np.full(values.shape, np.nan, dtype=np.float32)
    out[lag:] = values[:-lag]
    return out


def neighbourhood_max(values, cells):
    """Maximum over the 3x3 block of grid cells around each cell (cells outside the grid ignored)."""
    rows = np.array([int(c["row"]) for c in cells])
    cols = np.array([int(c["col"]) for c in cells])
    lookup = {(r, c): i for i, (r, c) in enumerate(zip(rows, cols))}
    neighbours = [[lookup[(r + dr, c + dc)] for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (r + dr, c + dc) in lookup] for r, c in zip(rows, cols)]
    out = np.full(values.shape, np.nan, dtype=np.float32)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for i, group in enumerate(neighbours):
                out[:, i] = np.nanmax(values[:, group], axis=1)
    return out


def features(grid: Grid, mode: str):
    """Return (dynamic, static): dynamic name -> (days, cells), static name -> (cells,).

    mode 'forecast' adds the target day's rain as a perfect-forecast stand-in (realised IMERG; no archived
    rainfall forecasts exist for Pakistan); mode 'observed' uses only information available before the day.
    """
    p, p3 = grid.dynamic["precip_total_mm"], grid.dynamic["precip_max3h_mm"]
    dynamic = {}
    if mode == "forecast":
        dynamic["rain_day"] = p
        dynamic["rain_max3h_day"] = p3
        dynamic["rain_day_nbr_max"] = neighbourhood_max(p, grid.cells)
        dynamic["rain_max3h_nbr_max"] = neighbourhood_max(p3, grid.cells)
    dynamic["rain_prev1"] = shift(p, 1)
    dynamic["rain_max3h_prev1"] = shift(p3, 1)
    dynamic["rain_prev3"] = lagged_sum(p, 1, 3)
    dynamic["rain_prev7"] = lagged_sum(p, 1, 7)
    dynamic["rain_prev30"] = lagged_sum(p, 1, 30)
    dynamic["soil_moisture_prev1"] = shift(grid.dynamic["soil_moisture_m3m3"], 1)
    dynamic["t2m_max_prev1"] = shift(grid.dynamic["t2m_max_c"], 1)
    dynamic["snowmelt_prev7"] = lagged_sum(grid.dynamic["snowmelt_mm"], 1, 7)
    reported = (grid.label == 1).astype(np.float32)
    national = reported.sum(axis=1, keepdims=True)
    # Reporting inputs are relative, so they mean the same thing as news coverage grows over the years
    # (the absolute reporting level is carried by the climatology baseline the trees start from).
    national_week = lagged_sum(national, 1, 7)
    national_year = lagged_sum(national, 1, 365)
    with np.errstate(divide="ignore", invalid="ignore"):
        dynamic["reports_national_week_vs_year"] = np.repeat(np.where(national_year > 0, national_week / (national_year / 52.0), np.nan), len(grid.cells), axis=1)
        dynamic["reports_cell_share_prev365"] = lagged_sum(reported, 1, 365) / np.where(national_year > 0, national_year, np.nan)
    doy = np.array([d.astype(object).timetuple().tm_yday for d in grid.dates], dtype=np.float32)[:, None]
    dynamic["season_sin"] = np.repeat(np.sin(2 * np.pi * doy / 365.25), len(grid.cells), axis=1)
    dynamic["season_cos"] = np.repeat(np.cos(2 * np.pi * doy / 365.25), len(grid.cells), axis=1)
    s = grid.static
    static = {"elev_mean_m": s["elev_mean_m"], "relief_m": s["elev_max_m"] - s["elev_min_m"], "elev_std_m": s["elev_std_m"],
              "slope_mean_deg": s["slope_mean_deg"], "steep_fraction": s["steep_fraction"],
              "log_upstream_area_km2": np.log10(np.maximum(s["upstream_area_max_km2"], 1)),
              "built_fraction": s["built_fraction"], "cropland_fraction": s["cropland_fraction"], "bare_fraction": s["bare_fraction"],
              "snow_ice_fraction": s["snow_ice_fraction"], "tree_fraction": s["tree_fraction"],
              "log_population_per_km2": np.log10(np.maximum(s["population_per_km2"], 0.1)),
              "lon": np.array([float(c["lon"]) for c in grid.cells], dtype=np.float32),
              "lat": np.array([float(c["lat"]) for c in grid.cells], dtype=np.float32)}
    return dynamic, {name: np.asarray(values, dtype=np.float32) for name, values in static.items()}


def assemble(dynamic, static, day_index, cell_index, names):
    """Rows for the given (day, cell) pairs, columns in ``names`` order."""
    out = np.empty((len(day_index), len(names)), dtype=np.float32)
    for j, name in enumerate(names):
        out[:, j] = dynamic[name][day_index, cell_index] if name in dynamic else static[name][cell_index]
    return out
