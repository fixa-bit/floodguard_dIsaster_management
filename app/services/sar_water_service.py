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
        Path(__file__).resolve().parents[3] / "NDMA_tasks" / "NDMA_tasks" / "model" / "unet"
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


def infer_water_extent(files: dict[str, bytes], threshold: float = 0.5) -> dict:
    model, scalers, checkpoint = _model_and_scalers()
    inputs, valid, coordinates = prepare_inputs(files, scalers)
    import torch

    with torch.inference_mode():
        probabilities = model(torch.from_numpy(inputs)[None]).sigmoid()[0, 0].numpy()
    water = (probabilities >= threshold) & valid
    overlay = np.zeros((*water.shape, 4), dtype=np.uint8)
    overlay[water] = (0, 202, 225, 185)
    buffer = BytesIO()
    Image.fromarray(overlay, "RGBA").save(buffer, format="PNG")
    return {
        "model": checkpoint.parent.name,
        "label": "Water extent (includes permanent water)",
        "threshold": threshold,
        "water_pixels": int(water.sum()),
        "valid_pixels": int(valid.sum()),
        "water_percent": round(100 * float(water.sum()) / float(valid.sum()), 2),
        "coordinates": coordinates,
        "image_data_url": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
    }
