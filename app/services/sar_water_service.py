"""Prepare seven model channels and render a georeferenced water mask."""

import base64
from contextlib import ExitStack
from functools import lru_cache
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
import json
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer
import rasterio
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.warp import reproject, transform as transform_coordinates

from app.core.config import get_settings


CHANNELS = ("during_vv", "during_vh", "pre_vv", "pre_vh", "elevation", "slope", "permanent_water")
ROLES = ("during_sar", "pre_sar", "elevation", "slope", "permanent_water")
MAX_SIDE = 1024


def model_directory() -> Path:
    configured = get_settings().sar_unet_model_dir
    return Path(configured).expanduser() if configured else (
        Path(__file__).resolve().parents[1] / "ml" / "sar_unet"
    )


def _read_layer(source, role, reference):
    if source.crs is None:
        raise ValueError(f"{role} has no coordinate reference system")
    expected = 2 if role in ("during_sar", "pre_sar") else 1
    if source.count != expected:
        raise ValueError(f"{role} must contain {expected} band(s)")
    data = source.read().astype(np.float32)
    masks = source.read_masks()
    if expected == 2:
        descriptions = [(item or "").upper() for item in source.descriptions]
        if descriptions == ["VH", "VV"]:
            data, masks = data[[1, 0]], masks[[1, 0]]
        elif descriptions not in (["VV", "VH"], ["", ""]):
            raise ValueError(f"{role} must have VV/VH bands")
    if role == "permanent_water":
        valid = np.isin(data, [0, 1]) & (masks != 0)
        data = np.where(valid, data, -1).astype(np.float32)
        nodata, resampling = -1, Resampling.nearest
    else:
        data[(masks == 0) | ~np.isfinite(data)] = np.nan
        nodata, resampling = np.nan, Resampling.bilinear
    if (source.crs == reference.crs and source.transform == reference.transform
            and source.width == reference.width and source.height == reference.height):
        return data
    aligned = np.full((expected, reference.height, reference.width), nodata, dtype=np.float32)
    for index in range(expected):
        reproject(
            data[index], aligned[index], src_transform=source.transform, src_crs=source.crs,
            src_nodata=nodata, dst_transform=reference.transform, dst_crs=reference.crs,
            dst_nodata=nodata, resampling=resampling,
        )
    return aligned


def prepare_inputs(files: dict[str, bytes], scalers: dict):
    if tuple(item["name"] for item in scalers["channels"]) != CHANNELS:
        raise ValueError("Model scaler channel order does not match the seven input bands")
    with ExitStack() as stack:
        sources = {}
        for role in ROLES:
            memory = stack.enter_context(MemoryFile(files[role]))
            sources[role] = stack.enter_context(memory.open())
        reference = sources["during_sar"]
        if reference.crs is None:
            raise ValueError("during_sar has no coordinate reference system")
        if not (1 <= reference.width <= MAX_SIDE and 1 <= reference.height <= MAX_SIDE):
            raise ValueError(f"During-SAR raster must be at most {MAX_SIDE} pixels per side")
        arrays = [_read_layer(sources[role], role, reference) for role in ROLES]
        raw = np.concatenate(arrays, axis=0)
        valid = np.isfinite(raw).all(axis=0) & np.isin(raw[6], [0, 1])
        if not valid.any():
            raise ValueError("The input layers have no jointly valid pixels")
        if scalers["channels"][6]["method"] != "binary_passthrough":
            raise ValueError("Permanent-water channel must remain binary for flood filtering")
        for index, scaler in enumerate(scalers["channels"]):
            if scaler["clip"] is not None:
                raw[index] = np.clip(raw[index], *scaler["clip"])
            if scaler["method"] == "train_zscore":
                raw[index] = (raw[index] - scaler["mean"]) / scaler["std"]
        raw[:, ~valid] = 0
        corners = [(0, 0), (reference.width, 0), (reference.width, reference.height), (0, reference.height)]
        xy = [reference.transform * corner for corner in corners]
        longitude, latitude = transform_coordinates(reference.crs, "EPSG:4326", [p[0] for p in xy], [p[1] for p in xy])
        coordinates = [[float(lon), float(lat)] for lon, lat in zip(longitude, latitude)]
        if any(not (-180 <= lon <= 180 and -85 <= lat <= 85) for lon, lat in coordinates):
            raise ValueError("Input extent is outside the supported map range")
        return np.ascontiguousarray(raw, dtype=np.float32), valid, coordinates


@lru_cache(maxsize=1)
def _model_and_scalers():
    directory = model_directory()
    release = directory / "release.json"
    if release.exists():
        selected = (directory / "runs" / json.loads(release.read_text())["run"] / "best.pt").resolve()
        if not selected.is_relative_to((directory / "runs").resolve()):
            raise ValueError("Selected U-Net release must be inside the bundle runs directory")
        runs = [selected] if selected.is_file() else []
    else:
        runs = sorted((directory / "runs").glob("*/best.pt"), key=lambda path: path.stat().st_mtime)
    if not runs:
        raise FileNotFoundError(f"No U-Net checkpoint found under {directory / 'runs'}")
    checkpoint = runs[-1]
    scalers = json.loads((checkpoint.parent / "dataset_scalers.json").read_text(encoding="utf-8"))
    spec = spec_from_file_location("floodguard_sar_unet_network", directory / "network.py")
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"U-Net network.py not found in {directory}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    import torch

    model = module.FloodUNet(in_channels=7, pretrained=False)
    with torch.serialization.safe_globals([torch.torch_version.TorchVersion]):
        saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(saved["model"])
    model.eval()
    return model, scalers, checkpoint


def _overlay_url(mask, color=(0, 202, 225, 185)):
    overlay = np.zeros((*mask.shape, 4), dtype=np.uint8)
    overlay[mask] = color
    buffer = BytesIO()
    Image.fromarray(overlay, "RGBA").save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


@lru_cache(maxsize=1)
def _hybrid_booster(checkpoint):
    import xgboost as xgb
    booster = xgb.Booster(params={"nthread": 1})
    booster.load_model(checkpoint.parent / "boost.json")
    return booster


def predict_probabilities(model, inputs, checkpoint, scalers):
    import torch
    policy_path = checkpoint.parent / "inference.json"
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else {}
    weight = float(policy.get("hybrid_weight", 0))
    if not 0 <= weight <= 1:
        raise ValueError("Invalid neural/tree ensemble weight")
    with torch.inference_mode():
        probability = model(torch.from_numpy(inputs)[None]).sigmoid()[0, 0].numpy() if weight < 1 else np.zeros(inputs.shape[1:], dtype=np.float32)
    if weight:
        from app.ml.sar_unet.hybrid_features import pixel_features
        tree = _hybrid_booster(checkpoint).inplace_predict(pixel_features(inputs, scalers)).reshape(probability.shape)
        probability = (1-weight)*probability + weight*tree
    return probability


def _area_summary(files, valid, water, potential_flood, permanent=None):
    """Approximate cell areas from their corners in a global equal-area CRS."""
    with MemoryFile(files["during_sar"]) as memory, memory.open() as source:
        rows, columns = np.indices((source.height + 1, source.width + 1))
        grid = source.transform
        x = grid.a * columns + grid.b * rows + grid.c
        y = grid.d * columns + grid.e * rows + grid.f
        x, y = Transformer.from_crs(source.crs, "EPSG:6933", always_xy=True).transform(x, y)
    # Shift away from large map coordinates before calculating polygon areas.
    x, y = x - x[0, 0], y - y[0, 0]
    corners = [(x[:-1, :-1], y[:-1, :-1]), (x[:-1, 1:], y[:-1, 1:]),
               (x[1:, 1:], y[1:, 1:]), (x[1:, :-1], y[1:, :-1])]
    area = abs(sum(a[0] * b[1] - b[0] * a[1]
                   for a, b in zip(corners, corners[1:] + corners[:1]))) / 2
    if not np.isfinite(area).all() or (area <= 0).any():
        raise ValueError("Input grid cannot be measured reliably")
    return {
        "analysis_area_km2": round(float(area.sum()) / 1e6, 4),
        "valid_area_km2": round(float(area[valid].sum()) / 1e6, 4),
        "water_area_km2": round(float(area[water].sum()) / 1e6, 4),
        "potential_flood_area_km2": round(float(area[potential_flood].sum()) / 1e6, 4),
        "excluded_permanent_water_area_km2": round(float(area[water & ~potential_flood].sum()) / 1e6, 4),
        "permanent_water_reference_area_km2": round(float(area[valid & permanent].sum()) / 1e6, 4) if permanent is not None else None,
        "valid_coverage_percent": round(100 * float(valid.mean()), 2),
        "total_pixels": int(valid.size),
        "area_method": "approximate_equal_area_pixel_corners",
    }


def infer_water_extent(files: dict[str, bytes], threshold: float | None = None) -> dict:
    model, scalers, checkpoint = _model_and_scalers()
    if threshold is None:
        policy = checkpoint.parent / "inference.json"
        threshold = float(json.loads(policy.read_text())["threshold"]) if policy.exists() else .5
    if not 0 < threshold < 1:
        raise ValueError("Probability threshold must be between 0 and 1")
    inputs, valid, coordinates = prepare_inputs(files, scalers)
    probabilities = predict_probabilities(model, inputs, checkpoint, scalers)
    water = (probabilities >= threshold) & valid
    # This channel passes through normalization unchanged and is aligned using
    # nearest-neighbor sampling. Unknown reference pixels are excluded by valid.
    permanent = inputs[6] == 1
    potential_flood = water & ~permanent
    return {
        "response_version": 2,
        "status": "potential_flooding_detected" if potential_flood.any() else (
            "permanent_water_only" if water.any() else "no_water_detected"),
        **_area_summary(files, valid, water, potential_flood, permanent),
        "model": checkpoint.parent.name,
        "label": "Potential flooding (permanent water excluded)",
        "method": "predicted_water_minus_permanent_water",
        "limitation": "Water outside the permanent-water reference is potential flooding; seasonal water and reference gaps can remain. A verified pre-event water map is needed to confirm newly flooded areas.",
        "threshold": threshold,
        "water_pixels": int(water.sum()),
        "valid_pixels": int(valid.sum()),
        "water_percent": round(100 * float(water.sum()) / float(valid.sum()), 2),
        "potential_flood_pixels": int(potential_flood.sum()),
        "potential_flood_percent": round(100 * float(potential_flood.sum()) / float(valid.sum()), 2),
        "excluded_permanent_water_pixels": int((water & permanent).sum()),
        "permanent_water_reference_pixels": int((permanent & valid).sum()),
        "coordinates": coordinates,
        "image_data_url": _overlay_url(potential_flood),
        "all_water_image_data_url": _overlay_url(water),
        "permanent_water_image_data_url": _overlay_url(permanent & valid, (76, 115, 255, 210)),
    }
