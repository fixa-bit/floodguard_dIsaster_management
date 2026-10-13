"""Fetch and align public satellite inputs for a selected map location."""

from datetime import datetime, timedelta, timezone

import httpx
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform as transform_coordinates

from app.services.sar_water_service import infer_water_extent


STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
SIGN = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
SIZE = 256
METRES_PER_PIXEL = 30


def _search(client, collection, longitude, latitude, limit=20, since=None):
    query = {
        "collections": [collection],
        "intersects": {"type": "Point", "coordinates": [longitude, latitude]},
        "limit": limit,
    }
    if since:
        query["datetime"] = f"{since.isoformat().replace('+00:00', 'Z')}/.."
    response = client.post(STAC, json=query)
    response.raise_for_status()
    return response.json()["features"]


def _signed(client, item, asset):
    response = client.get(SIGN, params={"href": item["assets"][asset]["href"]})
    response.raise_for_status()
    return response.json()["href"]


def _window(url, crs, transform, resampling=Resampling.bilinear):
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.tiff"):
        with rasterio.open(url) as source:
            with WarpedVRT(source, crs=crs, transform=transform, width=SIZE, height=SIZE,
                           resampling=resampling) as aligned:
                return aligned.read(1, masked=True).astype(np.float32).filled(np.nan)


def _tiff(data, crs, transform, descriptions=None):
    buffer = MemoryFile()
    with buffer.open(driver="GTiff", height=SIZE, width=SIZE, count=data.shape[0],
                     dtype="float32", crs=crs, transform=transform, nodata=np.nan) as dst:
        dst.write(data.astype(np.float32))
        if descriptions:
            dst.descriptions = descriptions
    content = buffer.read()
    buffer.close()
    return content


def infer_at_location(latitude: float, longitude: float) -> dict:
    if not (-85 <= latitude <= 85 and -180 <= longitude <= 180):
        raise ValueError("Select a valid map location")
    now = datetime.now(timezone.utc)
    with httpx.Client(timeout=45) as client:
        radar = _search(client, "sentinel-1-rtc", longitude, latitude, since=now - timedelta(days=90))
        radar = [item for item in radar if "vv" in item["assets"] and "vh" in item["assets"]]
        pair = next(((radar[0], old) for old in radar[1:]
                     if old["properties"].get("sat:relative_orbit") == radar[0]["properties"].get("sat:relative_orbit")
                     and old["properties"].get("sat:orbit_state") == radar[0]["properties"].get("sat:orbit_state")), None) if radar else None
        if not pair:
            raise ValueError("No recent matching VV/VH satellite passes are available at this location")
        dem = _search(client, "cop-dem-glo-30", longitude, latitude, limit=1)
        water = _search(client, "jrc-gsw", longitude, latitude, limit=1)
        if not dem or not water:
            raise ValueError("Elevation or historical water data is unavailable at this location")
        zone = min(60, max(1, int((longitude + 180) // 6) + 1))
        crs = f"EPSG:{32600 + zone if latitude >= 0 else 32700 + zone}"
        x, y = transform_coordinates("EPSG:4326", crs, [longitude], [latitude])
        half = SIZE * METRES_PER_PIXEL / 2
        grid = from_origin(x[0] - half, y[0] + half, METRES_PER_PIXEL, METRES_PER_PIXEL)
        scenes = []
        for item in pair:
            bands = []
            for polarization in ("vv", "vh"):
                values = _window(_signed(client, item, polarization), crs, grid)
                values = np.where(values > 0, 10 * np.log10(np.maximum(values, 1e-10)), np.nan)
                bands.append(values)
            scenes.append(np.stack(bands))
        elevation = _window(_signed(client, dem[0], "data"), crs, grid)
        # Slope uses the same degree units as the training features.
        slope = np.degrees(np.arctan(np.hypot(*np.gradient(elevation, METRES_PER_PIXEL))))
        seasonality = _window(_signed(client, water[0], "seasonality"), crs, grid, Resampling.nearest)
        permanent = np.where(np.isfinite(seasonality), (seasonality == 12).astype(np.float32), -1)
        files = {
            "during_sar": _tiff(scenes[0], crs, grid, ("VV", "VH")),
            "pre_sar": _tiff(scenes[1], crs, grid, ("VV", "VH")),
            "elevation": _tiff(elevation[None], crs, grid),
            "slope": _tiff(slope[None], crs, grid),
            "permanent_water": _tiff(permanent[None], crs, grid),
        }
    result = infer_water_extent(files)
    result["during_date"] = pair[0]["properties"]["datetime"]
    result["pre_date"] = pair[1]["properties"]["datetime"]
    result["source"] = "Microsoft Planetary Computer Sentinel-1 RTC, Copernicus DEM, JRC GSW"
    return result
