"""Check that app preprocessing matches the trained dataset contract."""

import json
import base64
from pathlib import Path

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient

from app.main import app
from app.services.sar_water_service import ROLES, prepare_inputs


def test_selected_ensemble_policy_blends_probabilities(tmp_path, monkeypatch):
    import torch
    from app.services import sar_water_service as service

    (tmp_path / "inference.json").write_text(json.dumps({"hybrid_weight": .75}))
    class Model:
        def __call__(self, x):
            return torch.zeros(1, 1, 2, 3)
    class Booster:
        def inplace_predict(self, features):
            assert features.shape == (6, 11)
            return np.full(6, .9, dtype=np.float32)
    monkeypatch.setattr(service, "_hybrid_booster", lambda checkpoint: Booster())
    scalers = {"channels": [{"mean": 0, "std": 1}] * 7}
    result = service.predict_probabilities(Model(), np.zeros((7, 2, 3), dtype=np.float32), tmp_path / "best.pt", scalers)
    np.testing.assert_allclose(result, .8)


def test_area_summary_uses_ground_area_and_excludes_missing_pixels():
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    from app.services.sar_water_service import _area_summary

    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=3, height=2, count=2, dtype="float32",
                         crs="EPSG:6933", transform=from_origin(1000, 1000, 30, 30)) as dst:
            dst.write(np.zeros((2, 2, 3), dtype=np.float32))
        content = memory.read()
    valid = np.array([[True, True, True], [True, True, False]])
    water = np.array([[True, True, False], [False, False, False]])
    flood = np.array([[False, True, False], [False, False, False]])
    result = _area_summary({"during_sar": content}, valid, water, flood)
    assert result["analysis_area_km2"] == 0.0054
    assert result["valid_area_km2"] == 0.0045
    assert result["water_area_km2"] == 0.0018
    assert result["potential_flood_area_km2"] == 0.0009
    assert result["excluded_permanent_water_area_km2"] == 0.0009
    assert result["valid_coverage_percent"] == 83.33


@pytest.mark.parametrize("reference,logit,expected_water,expected_flood,expected_excluded", [
    ([1, 0, 0, 1, -1, 0], 5.0, 5, 3, 2),
    ([1, 1, 1, 1, 1, 1], 5.0, 6, 0, 6),
    ([0, 0, 0, 0, 0, 0], 5.0, 6, 6, 0),
    ([1, 0, 0, 1, -1, 0], -5.0, 0, 0, 0),
])
def test_permanent_water_filter(reference, logit, expected_water, expected_flood, expected_excluded, monkeypatch):
    from io import BytesIO
    from PIL import Image
    from rasterio.io import MemoryFile
    from rasterio.transform import from_origin
    import torch
    from app.services import sar_water_service as service

    class ConstantModel:
        def __call__(self, inputs):
            return torch.full((1, 1, 2, 3), logit)

    scalers = {"channels": [
        {"name": name, "method": "binary_passthrough" if index == 6 else "train_zscore",
         "clip": None, "mean": 0, "std": 1}
        for index, name in enumerate(service.CHANNELS)
    ]}
    monkeypatch.setattr(service, "_model_and_scalers", lambda: (
        ConstantModel(), scalers, Path("bundled/test/best.pt")))
    files = {}
    for role in ROLES:
        bands = 2 if role in ("during_sar", "pre_sar") else 1
        data = np.zeros((bands, 2, 3), dtype=np.float32)
        if role == "permanent_water":
            data[0] = np.array(reference).reshape(2, 3)
        with MemoryFile() as memory:
            with memory.open(driver="GTiff", width=3, height=2, count=bands,
                             dtype="float32", crs="EPSG:4326",
                             transform=from_origin(70, 30, 0.001, 0.001), nodata=-1) as dst:
                dst.write(data)
            files[role] = memory.read()
    result = service.infer_water_extent(files)
    assert result["water_pixels"] == expected_water
    assert result["potential_flood_pixels"] == expected_flood
    assert result["excluded_permanent_water_pixels"] == expected_excluded
    valid = np.array(reference).reshape(2, 3) != -1
    assert result["valid_pixels"] == int(valid.sum())
    assert result["potential_flood_percent"] == round(100 * expected_flood / valid.sum(), 2)
    assert result["response_version"] == 2
    assert result["analysis_area_km2"] > 0
    assert result["valid_coverage_percent"] == round(100 * valid.mean(), 2)
    assert result["potential_flood_area_km2"] <= result["water_area_km2"] <= result["valid_area_km2"] <= result["analysis_area_km2"]
    assert result["status"] == ("potential_flooding_detected" if expected_flood else "permanent_water_only" if expected_water else "no_water_detected")
    png = Image.open(BytesIO(base64.b64decode(result["image_data_url"].split(",", 1)[1])))
    displayed = np.array(png)[:, :, 3] > 0
    expected = (np.array(reference).reshape(2, 3) == 0) & (logit > 0)
    np.testing.assert_array_equal(displayed, expected)
    original = Image.open(BytesIO(base64.b64decode(result["all_water_image_data_url"].split(",", 1)[1])))
    np.testing.assert_array_equal(np.array(original)[:, :, 3] > 0, valid & (logit > 0))


def test_bundled_model_loads_and_predicts_without_training_dataset(monkeypatch):
    from types import SimpleNamespace
    import torch
    from app.services import sar_water_service as service

    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(sar_unet_model_dir=""))
    service._model_and_scalers.cache_clear()
    try:
        model, scalers, checkpoint = service._model_and_scalers()
        assert checkpoint.is_relative_to(Path(__file__).resolve().parents[1] / "app" / "ml")
        assert tuple(channel["name"] for channel in scalers["channels"]) == service.CHANNELS
        with torch.inference_mode():
            output = model(torch.zeros(1, 7, 64, 64))
        assert output.shape == (1, 1, 64, 64)
        assert torch.isfinite(output).all()
    finally:
        service._model_and_scalers.cache_clear()


def sample_inputs():
    project = Path(__file__).resolve().parents[2] / "NDMA_tasks" / "NDMA_tasks"
    dataset = project / "dataset" / "sen1floods11_sar_handlabeled_v1_1"
    prepared = dataset / "processed" / "training_ready" / "multifeature" / "a963ebd076af3f8f"
    sample = prepared / "images" / "Ghana_103272_inputs.tif"
    metadata = prepared / "metadata" / "Ghana_103272.json"
    if not sample.exists() or not metadata.exists():
        pytest.skip("Sibling NDMA training dataset is not installed")
    source_paths = json.loads(metadata.read_text(encoding="utf-8"))["source_paths"]
    source_root = Path("D:/NDMA_tasks/dataset/sen1floods11_sar_handlabeled_v1_1")
    files = {
        role: (dataset / Path(source_paths[role]).relative_to(source_root)).read_bytes()
        for role in ROLES
    }
    scalers = json.loads((prepared / "scalers.json").read_text(encoding="utf-8"))
    return files, scalers, sample


def test_preprocessing_matches_prepared_training_chip():
    files, scalers, sample = sample_inputs()
    actual, valid, coordinates = prepare_inputs(files, scalers)
    with rasterio.open(sample) as expected:
        assert np.array_equal(valid, expected.dataset_mask() != 0)
        np.testing.assert_allclose(actual, expected.read(), rtol=1e-5, atol=1e-5)
        assert len(coordinates) == 4


def test_api_returns_georeferenced_water_overlay():
    files, _, _ = sample_inputs()
    client = TestClient(app)
    try:
        response = client.post("/api/v1/flood/water-extent", files={
            role: (f"{role}.tif", content, "image/tiff") for role, content in files.items()
        })
    finally:
        client.close()
    assert response.status_code == 200, response.text
    overlay = response.json()
    assert overlay["label"] == "Potential flooding (permanent water excluded)"
    assert overlay["potential_flood_pixels"] + overlay["excluded_permanent_water_pixels"] == overlay["water_pixels"]
    assert overlay["valid_pixels"] > 0
    assert 0 <= overlay["water_pixels"] <= overlay["valid_pixels"]
    assert len(overlay["coordinates"]) == 4
    assert base64.b64decode(overlay["image_data_url"].split(",", 1)[1]).startswith(b"\x89PNG")
