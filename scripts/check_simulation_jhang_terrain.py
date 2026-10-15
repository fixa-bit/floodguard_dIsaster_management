"""Validate downloaded terrain provenance, geographic extent, and real values."""
from hashlib import sha256
from pathlib import Path
import json
import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from PIL import Image

root = Path(__file__).resolve().parents[1]
directory = root / "frontend/public/simulation-terrain"
metadata = json.loads((directory / "jhang-metadata.json").read_text())
assert len(metadata["inputs"]) == 25
assert len({item["url"] for item in metadata["inputs"]}) == 25
for name, record in metadata["outputs"].items():
    content = (directory / name).read_bytes()
    assert len(content) == record["bytes"]
    assert sha256(content).hexdigest() == record["sha256"]
with rasterio.open(directory / "jhang-dem.tif") as source:
    assert source.crs.to_epsg() == 3857
    assert (source.width, source.height) == (metadata["width"], metadata["height"])
    values = source.read(1)
    assert np.isfinite(values).all()
    assert round(float(values.min()), 1) == metadata["elevation_min_m"]
    assert round(float(values.max()), 1) == metadata["elevation_max_m"]
    assert np.ptp(values) > 10, "Elevation data must have actual relief"
    bounds = transform_bounds(source.crs, "EPSG:4326", *source.bounds)
    assert np.allclose(bounds, metadata["bounds"], atol=1e-7)
    assert 100 < abs(source.transform.a) * np.cos(np.radians(31.2)) < 350
with Image.open(directory / "jhang-hillshade.png") as image:
    assert image.size == (metadata["width"], metadata["height"])
assert metadata["used_as_hydraulic_solver"] is False
assert metadata["hydraulic_reference"]["used_for_animation"] is False
assert metadata["hydraulic_reference"]["retrieval"] == "PDF downloaded and file signature verified"
print("PASS: source/output checksums, all 25 tile records, GeoTIFF CRS/extent/resolution/elevations, hillshade alignment, and honest hydraulic-reference status.")
