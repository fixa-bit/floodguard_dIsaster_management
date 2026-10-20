"""Check that displayed validation overlays agree with the recorded metrics."""
import base64
from io import BytesIO
import json
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image
import pytest


def decode(url):
    return np.array(Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1]))))


@pytest.mark.parametrize("name", ["sar-pakistan.json", "sar-pakistan-permanent.json"])
def test_validation_example_masks_match_metrics(name):
    path = Path(__file__).resolve().parents[1] / "frontend/public/examples" / name
    result = json.loads(path.read_text(encoding="utf-8"))
    validation = result["validation"]
    assert result["during_date"] == "2017-06-28"
    assert result["is_historical_example"]
    bundle = path.parents[3] / "app/ml/sar_unet"
    release = json.loads((bundle / "release.json").read_text())
    checkpoint = bundle / "runs" / release["run"] / "best.pt"
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == result["checkpoint_sha256"]
    assert all(not experiment["accepted"] for experiment in result["evaluation"]["experiments"])
    assert validation["split"] == "test"
    event = decode(validation["event_image_data_url"])
    reference = decode(validation["reference_water_image_data_url"])[..., 3] > 0
    predicted = decode(result["all_water_image_data_url"])[..., 3] > 0
    permanent = decode(result["permanent_water_image_data_url"])[..., 3] > 0
    flood = decode(result["image_data_url"])[..., 3] > 0
    errors = decode(validation["error_image_data_url"])
    valid = ~np.all(errors[..., :3] == [150, 150, 150], axis=2)
    assert event.shape[:2] == reference.shape == predicted.shape == permanent.shape == errors.shape[:2]
    np.testing.assert_array_equal(flood, predicted & ~permanent)
    assert int(permanent.sum()) == result["permanent_water_reference_pixels"]
    assert int(reference.sum()) == validation["reference_water_pixels"]
    assert validation["metrics"]["tp"] == int((predicted & reference & valid).sum())
    assert validation["metrics"]["fp"] == int((predicted & ~reference & valid).sum())
    assert validation["metrics"]["fn"] == int((~predicted & reference & valid).sum())
    assert validation["metrics"]["tn"] == int((~predicted & ~reference & valid).sum())
    assert int(np.all(errors[..., :3] == [241, 111, 178], axis=2).sum()) == validation["metrics"]["fn"]
    assert int(np.all(errors[..., :3] == [255, 158, 75], axis=2).sum()) == validation["metrics"]["fp"]
    if "permanent" in name:
        assert permanent.any()
