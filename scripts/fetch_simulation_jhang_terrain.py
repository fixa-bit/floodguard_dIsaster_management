"""Download a small real terrain window for the Jhang replay; never simulate floods."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import math
import tempfile

import httpx
import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_bounds

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend/public/simulation-terrain"
ZOOM = 10
SOURCE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
FFC = "https://ffc.gov.pk/wp-content/uploads/2019/02/Sheet8_flood.pdf"


def main():
    district = json.loads((ROOT / "frontend/src/data/outlook-exposure/jhang.geojson").read_text())
    west, south, east, north = district["bounds"]
    size = 256 * 2 ** ZOOM
    def pixel(lon, lat):
        return (lon + 180) / 360 * size, (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * size
    left, top = pixel(west, north)
    right, bottom = pixel(east, south)
    x0, y0, x1, y1 = math.floor(left / 256), math.floor(top / 256), math.floor(right / 256), math.floor(bottom / 256)
    mosaic = np.full(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256), np.nan, dtype=np.float32)
    cache = Path(tempfile.gettempdir()) / "floodguard-jhang-terrain"
    cache.mkdir(exist_ok=True)
    def fetch(tile):
        x, y = tile
        url = SOURCE.format(z=ZOOM, x=x, y=y)
        path = cache / f"{ZOOM}-{x}-{y}.png"
        if not path.exists():
            response = httpx.get(url, timeout=45, follow_redirects=True)
            response.raise_for_status()
            path.write_bytes(response.content)
        content = path.read_bytes()
        rgb = np.asarray(Image.open(BytesIO(content)).convert("RGB"), dtype=np.float32)
        height = rgb[:, :, 0] * 256 + rgb[:, :, 1] + rgb[:, :, 2] / 256 - 32768
        return x, y, height, {"url": url, "sha256": sha256(content).hexdigest(), "bytes": len(content)}
    tiles = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    inputs = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for x, y, height, record in pool.map(fetch, tiles):
            mosaic[(y-y0)*256:(y-y0+1)*256, (x-x0)*256:(x-x0+1)*256] = height
            inputs.append(record)
    # Integer pixel crop, then area-average to at most ~600 pixels per side.
    l, t, r, b = math.floor(left), math.floor(top), math.ceil(right), math.ceil(bottom)
    window = mosaic[t-y0*256:b-y0*256, l-x0*256:r-x0*256]
    downsample = max(1, math.ceil(max(window.shape) / 600))
    width, height = math.ceil(window.shape[1] / downsample), math.ceil(window.shape[0] / downsample)
    dem = np.asarray(Image.fromarray(window).resize((width, height), Image.Resampling.BOX), dtype=np.float32)
    earth_circumference = 40075016.68557849
    mercator_pixel = earth_circumference / size
    minx, maxy = l * mercator_pixel - earth_circumference/2, earth_circumference/2 - t * mercator_pixel
    maxx, miny = r * mercator_pixel - earth_circumference/2, earth_circumference/2 - b * mercator_pixel
    transform = from_bounds(minx, miny, maxx, maxy, width, height)
    OUT.mkdir(parents=True, exist_ok=True)
    dem_path = OUT / "jhang-dem.tif"
    with rasterio.open(dem_path, "w", driver="GTiff", width=width, height=height, count=1, dtype="float32", crs="EPSG:3857", transform=transform, compress="deflate", predictor=3) as target:
        target.write(dem, 1)
        target.set_band_description(1, "Elevation, metres; mixed-source Mapzen Terrain Tiles")
    spacing = abs(transform.a) * math.cos(math.radians((south+north)/2))
    # Conventional hillshade; 6x lighting exaggeration makes flat plain relief visible.
    gy, gx = np.gradient(dem, spacing)
    slope = np.arctan(6 * np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    altitude, azimuth = math.radians(45), math.radians(315)
    shade = np.clip(np.sin(altitude) * np.cos(slope) + np.cos(altitude) * np.sin(slope) * np.cos(azimuth-aspect), 0, 1)
    grey = np.uint8(shade * 255)
    shade_path = OUT / "jhang-hillshade.png"
    Image.fromarray(grey).save(shade_path, optimize=True)
    def lon(x): return x / earth_circumference * 360
    def lat(y): return math.degrees(math.atan(math.sinh(y / (earth_circumference/(2*math.pi)))))
    extent = [lon(minx), lat(miny), lon(maxx), lat(maxy)]
    reference = {"title": "Federal Flood Commission: Jhang and Bhakkar floodplain map, Sheet 8", "url": FFC, "status": "Reference located; not a current calibration or machine-readable hydraulic grid", "used_for_animation": False}
    try:
        response = httpx.get(FFC, timeout=40, follow_redirects=True)
        response.raise_for_status()
        if response.content.startswith(b"%PDF"):
            (cache / "ffc-sheet8.pdf").write_bytes(response.content)
            reference.update({"retrieval": "PDF downloaded and file signature verified", "bytes": len(response.content), "sha256": sha256(response.content).hexdigest()})
        else:
            reference["retrieval"] = "Server returned a non-PDF response; link retained for manual review"
    except httpx.HTTPError as error:
        reference["retrieval"] = f"Direct PDF retrieval unavailable: {type(error).__name__}; official indexed reference retained"
    retrieved = datetime.now(timezone.utc)
    manifest = {"id": "jhang", "accessed_on": retrieved.astimezone(timezone(timedelta(hours=5))).date().isoformat(), "retrieved_at_utc": retrieved.isoformat(), "bounds": extent, "width": width, "height": height, "sample_spacing_m_approx": round(spacing), "elevation_min_m": round(float(np.nanmin(dem)), 1), "elevation_max_m": round(float(np.nanmax(dem)), 1), "source": "Mapzen Terrain Tiles / AWS Open Data, mixed-source global elevation", "attribution": "Terrain: Mapzen / USGS SRTM and GMTED2010", "source_url": "https://registry.opendata.aws/terrain-tiles/", "license_url": "https://github.com/tilezen/joerd/blob/master/docs/attribution.md", "tile_encoding": "Terrarium: R*256 + G + B/256 - 32768", "source_zoom": ZOOM, "resampling": "Area average of cropped Terrarium source pixels; EPSG:3857", "vertical_reference": "Mixed-source provider elevations; not aligned to station gauge datum", "hillshade_exaggeration": 6, "used_as_hydraulic_solver": False, "inputs": inputs, "hydraulic_reference": reference, "outputs": {p.name: {"bytes": p.stat().st_size, "sha256": sha256(p.read_bytes()).hexdigest()} for p in [dem_path, shade_path]}}
    (OUT / "jhang-metadata.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ["width", "height", "sample_spacing_m_approx", "elevation_min_m", "elevation_max_m", "hydraulic_reference", "outputs"]}, indent=2))


if __name__ == "__main__":
    main()
