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
    assert overlay["label"] == "Water extent (includes permanent water)"
    assert overlay["valid_pixels"] > 0
    assert 0 <= overlay["water_pixels"] <= overlay["valid_pixels"]
    assert len(overlay["coordinates"]) == 4
    assert base64.b64decode(overlay["image_data_url"].split(",", 1)[1]).startswith(b"\x89PNG")
