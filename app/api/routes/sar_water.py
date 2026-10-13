"""Prototype satellite water-extent inference for the map."""

from fastapi import APIRouter, File, HTTPException, UploadFile
from rasterio.errors import RasterioIOError
from starlette.concurrency import run_in_threadpool

from app.services.sar_water_service import ROLES, infer_water_extent
from app.services.sar_catalog_service import infer_at_location
import httpx


router = APIRouter(prefix="/flood/water-extent", tags=["Flood Mapping"])
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


@router.get("/location")
async def water_extent_at_location(latitude: float, longitude: float):
    try:
        return await run_in_threadpool(infer_at_location, latitude, longitude)
    except (ValueError, RasterioIOError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc)) from exc
    except (httpx.HTTPError, OSError) as exc:
        raise HTTPException(502, "Satellite imagery provider is unavailable") from exc


@router.post("")
async def water_extent(
    during_sar: UploadFile = File(...),
    pre_sar: UploadFile = File(...),
    elevation: UploadFile = File(...),
    slope: UploadFile = File(...),
    permanent_water: UploadFile = File(...),
):
    uploads = {
        "during_sar": during_sar, "pre_sar": pre_sar, "elevation": elevation,
        "slope": slope, "permanent_water": permanent_water,
    }
    files = {}
    for role in ROLES:
        content = await uploads[role].read(MAX_UPLOAD_BYTES + 1)
        if not content or len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(422, f"{role} must be a nonempty GeoTIFF smaller than 32 MB")
        files[role] = content
    try:
        return await run_in_threadpool(infer_water_extent, files)
    except (ValueError, RasterioIOError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc)) from exc
