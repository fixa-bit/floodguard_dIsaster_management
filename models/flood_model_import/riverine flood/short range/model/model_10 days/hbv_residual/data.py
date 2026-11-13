"""Causal state features and branched future forcing; no target imputation."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .physical import STATE_NAMES, FLUX_NAMES, branches, initial_state, simulate
from .forcing import QuantileMapper, validate_archive


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, obj):
    def clean(value):
        if isinstance(value, dict):
            return {str(k): clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, np.ndarray)):
            return [clean(v) for v in value]
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (float, np.floating)):
            return float(value) if np.isfinite(value) else None
        if isinstance(value, (np.bool_,)):
            return bool(value)
        return value
    Path(path).write_text(json.dumps(clean(obj), indent=2, allow_nan=False), encoding="utf-8")


def load_data(config, base):
    path = (base / config["daily_file"]).resolve()
    paths = [path]
    frame = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    if frame.index.duplicated().any():
        raise ValueError("Duplicate daily dates; this module supports one basin")
    frame = frame.loc[config["simulation_start"]:config["simulation_end"]].copy()
    expected = pd.date_range(config["simulation_start"], config["simulation_end"])
    if not frame.index.equals(expected):
        raise ValueError("Daily input must have a complete consecutive calendar")
    weather = ["rain_chirps_mm", "rain_era5_mm", "temperature_c", "pet_mm"]
    if not np.isfinite(frame[weather]).all().all():
        raise ValueError("Missing physical weather: shorten simulation to a complete period")
    if (frame[["rain_chirps_mm", "rain_era5_mm", "pet_mm"]] < 0).any().any():
        raise ValueError("Negative precipitation/PET")
    q = frame.q_cumecs.to_numpy()
    if np.isinf(q).any() or np.any(q[np.isfinite(q)] < 0):
        raise ValueError("Invalid observed discharge")
    modis_files = sorted((base / config["modis_dir"]).glob("[12][0-9][0-9][0-9].csv"))
    if modis_files:
        snow = pd.concat([pd.read_csv(p, parse_dates=["date"]) for p in modis_files]).set_index("date")
        if snow.index.duplicated().any():
            raise ValueError("Duplicate MODIS dates")
        paths.extend(modis_files)
        frame = frame.join(snow[["snow_cover_pct", "valid_frac"]])
    else:
        frame["snow_cover_pct"], frame["valid_frac"] = np.nan, np.nan
    meta_path = (base / config["catchment_metadata"]).resolve()
    paths.append(meta_path)
    area = json.loads(meta_path.read_text())["catchment_area_km2"]
    archive = None
    if config.get("forecast_file"):
        forecast_path = (base / config["forecast_file"]).resolve()
        paths.append(forecast_path)
        archive = validate_archive(pd.read_csv(forecast_path), config["horizon"])
    manifest = {str(p.resolve()): digest(p) for p in paths}
    return frame, float(area), archive, manifest


def historical_features(frame, states, fluxes, area, config):
    features = pd.DataFrame(states, index=frame.index, columns=STATE_NAMES)
    features["hbv_flow_cumecs"] = fluxes[:, 3] * area / 86.4
    features["melt_mm"] = fluxes[:, 0]
    features["actual_evaporation_mm"] = fluxes[:, 2]
    features["rainfall_mm"] = frame.rain_chirps_mm
    features["temperature_c"] = frame.temperature_c
    features["pet_mm"] = frame.pet_mm
    features["modeled_snow_fraction"] = 1 - np.exp(-states[:, 0] / config["snow_cover_scale_mm"])
    doy = frame.index.day_of_year.to_numpy()
    features["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    features["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    # Index, not observed fractional snow cover. Use only sufficiently clear, delayed acquisitions.
    quality = (frame.valid_frac >= config["modis_min_valid_fraction"]) & frame.snow_cover_pct.between(0, 100)
    latency = config["modis_latency_days"]
    ndsi = frame.snow_cover_pct.where(quality).shift(latency)
    coverage = frame.valid_frac.where(quality).shift(latency)
    features["modis_ndsi_index"] = ndsi.ffill(limit=config["modis_max_age_days"])
    features["modis_valid_fraction"] = coverage.ffill(limit=config["modis_max_age_days"])
    residual = frame.q_cumecs - features.hbv_flow_cumecs
    for lag in [0, 1, 2, 3, 7, 14, 30]:
        features[f"observed_q_lag{lag}"] = frame.q_cumecs.shift(lag)
        features[f"residual_lag{lag}"] = residual.shift(lag)
    observed = frame.q_cumecs.notna()
    last_date = pd.Series(frame.index.where(observed), index=frame.index).ffill()
    features["q_observation_age_days"] = (pd.Series(frame.index, index=frame.index) - last_date).dt.days
    features["q_asof"] = frame.q_cumecs.ffill(limit=7)
    return features


def pet_climatology(frame, train_mask):
    # Month/day climatology has consistent leap-day behavior; no realized future PET used.
    values = frame.loc[train_mask, "pet_mm"]
    grouped = values.groupby(values.index.strftime("%m-%d")).mean()
    return {str(k): float(v) for k, v in grouped.items()}


def forecast_rows(frame, config, mapper, pet_climate, archive=None):
    horizon, history = config["horizon"], config["history_days"]
    lookup = {d: i for i, d in enumerate(frame.index)}
    origins, members, ps, ts, pets = [], [], [], [], []
    if archive is None:
        for origin in range(history - 1, len(frame) - horizon):
            valid = frame.index[origin+1:origin+1+horizon]
            origins.append(origin)
            members.append("reanalysis_0")
            ps.append(mapper.transform(frame.rain_era5_mm.iloc[origin+1:origin+1+horizon], valid.month, "rain"))
            ts.append(mapper.transform(frame.temperature_c.iloc[origin+1:origin+1+horizon], valid.month, "temperature"))
            pets.append([pet_climate.get(d.strftime("%m-%d"), pet_climate["02-28"]) for d in valid])
    else:
        for (date, member), rows in archive.groupby(["issue_date", "member"], sort=True):
            date = date.tz_localize(None)
            if date not in lookup:
                continue
            origin = lookup[date]
            if origin < history - 1 or origin + horizon >= len(frame):
                continue
            rows = rows.sort_values("lead_day")
            valid = pd.DatetimeIndex(rows.valid_date).tz_localize(None)
            origins.append(origin)
            members.append(str(member))
            ps.append([mapper.transform(np.array([p]), np.array([d.month]), "rain", lead=j+1)[0]
                       for j, (p, d) in enumerate(zip(rows.precipitation_mm, valid))])
            ts.append([mapper.transform(np.array([t]), np.array([d.month]), "temperature", lead=j+1)[0]
                       for j, (t, d) in enumerate(zip(rows.temperature_c, valid))])
            pets.append([pet_climate.get(d.strftime("%m-%d"), pet_climate["02-28"]) for d in valid])
    if not origins:
        raise ValueError("No complete forecast issue/member trajectories")
    return (np.array(origins), np.array(members), np.array(ps), np.array(ts), np.array(pets))


def make_samples(frame, par, area, config, train_end, archive=None, mapper=None, pet_climate=None):
    train_mask = (frame.index.year >= config["first_training_year"]) & (frame.index <= pd.Timestamp(train_end))
    if mapper is None:
        mapper = QuantileMapper()
        if archive is None:
            mapper.fit(frame, train_mask)
        else:
            mapper.fit_archive(archive, frame, train_end, config["first_training_year"])
    if pet_climate is None:
        pet_climate = pet_climatology(frame, train_mask)
    states, fluxes = simulate(frame.rain_chirps_mm.to_numpy(), frame.temperature_c.to_numpy(),
                             frame.pet_mm.to_numpy(), par, initial_state(par))
    features = historical_features(frame, states, fluxes, area, config)
    origins, members, ps, ts, pets = forecast_rows(frame, config, mapper, pet_climate, archive)
    future_states, future_flux = branches(ps, ts, pets, par, states[origins])
    hbv = future_flux[:, :, 3] * area / 86.4
    horizon = config["horizon"]
    target_indices = origins[:, None] + np.arange(1, horizon + 1)
    valid = frame.index.to_numpy()[target_indices]
    doys = pd.DatetimeIndex(valid.ravel()).day_of_year.to_numpy().reshape(valid.shape)
    future = np.concatenate([
        hbv[..., None], future_states, future_flux[..., :3], ps[..., None], ts[..., None],
        pets[..., None], np.cumsum(ps, axis=1)[..., None],
        np.sin(2*np.pi*doys/365.25)[..., None], np.cos(2*np.pi*doys/365.25)[..., None],
        (1 - np.exp(-future_states[..., 0] / config["snow_cover_scale_mm"]))[..., None],
        np.broadcast_to(np.arange(1, horizon + 1)[None, :, None], (len(origins), horizon, 1))], -1)
    future_names = (["forecast_hbv_cumecs"] + ["forecast_" + s for s in STATE_NAMES] +
                    ["forecast_melt_mm", "forecast_refreeze_mm", "forecast_aet_mm", "forecast_rain_mm",
                     "forecast_temperature_c", "forecast_pet_mm", "forecast_cumulative_rain_mm",
                     "forecast_doy_sin", "forecast_doy_cos", "forecast_modeled_snow_fraction", "lead_day"])
    historical = features.to_numpy(dtype=float)
    history = np.stack([historical[i-config["history_days"]+1:i+1] for i in origins])
    tabs = [historical[origins]]
    tab_names = list(features.columns)
    for window in [3, 7, 14, 30, 60]:
        columns = ["rainfall_mm", "temperature_c", "observed_q_lag0", "residual_lag0", "melt_mm"]
        for kind in ["mean", "max"]:
            rolled = getattr(features[columns].rolling(window, min_periods=1), kind)()
            tabs.append(rolled.to_numpy()[origins])
            tab_names.extend([f"{c}_{kind}_{window}d" for c in columns])
    tab_base = np.concatenate(tabs, -1)
    tabular = np.concatenate([np.broadcast_to(tab_base[:, None, :], (len(origins), horizon, tab_base.shape[-1])), future], -1)
    labels = frame.q_cumecs.to_numpy()[target_indices]
    return {"origins": origins, "members": members, "valid": valid, "history": history,
            "future": future.astype(np.float32), "tabular": tabular, "labels": labels,
            "residual": labels - hbv, "hbv": hbv, "states": states, "fluxes": fluxes,
            "future_states": future_states, "future_fluxes": future_flux,
            "forecast_rain": ps, "forecast_temperature": ts, "forecast_pet": pets,
            "persistence": features.q_asof.to_numpy()[origins], "mapper": mapper,
            "pet_climatology": pet_climate, "history_features": list(features.columns),
            "future_features": future_names, "tabular_features": tab_names + future_names}


def masks(samples, frame, config, test_year):
    dates = samples["valid"]
    start_year = config["first_training_year"]
    train_end = np.datetime64(f"{test_year-2}-12-31")
    train = (dates[:, 0] >= np.datetime64(f"{start_year}-01-01")) & (dates[:, -1] <= train_end)
    val = (dates[:, 0] >= np.datetime64(f"{test_year-1}-01-01")) & (dates[:, -1] <= np.datetime64(f"{test_year-1}-12-31"))
    years = pd.DatetimeIndex(dates.ravel()).year.to_numpy().reshape(dates.shape)
    months = pd.DatetimeIndex(dates.ravel()).month.to_numpy().reshape(dates.shape)
    test = (years == test_year).all(1) & np.isin(months, config["monsoon_months"]).all(1)
    warm = samples["origins"] >= config["warmup_days"]
    return train & warm, val & warm, test & warm
