"""Riverine forecast APIs: live extended GloFAS series and the saved model outlook."""
from fastapi import APIRouter, HTTPException
import httpx

from app.services.riverine_extended_forecast import get_riverine_extended_forecast
from app.services.riverine_outlook import get_riverine_outlook

router = APIRouter(prefix="/predictive", tags=["Predictive models"])


@router.get("/riverine-extended-forecast")
async def riverine_extended_forecast():
    try:
        return await get_riverine_extended_forecast()
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=503, detail=f"Extended Marala forecast unavailable: {exc}") from exc


@router.get("/riverine-outlook/{station_id}")
def riverine_outlook(station_id: str):
    """Seasonal (180-day), seasonal-mean and 2026–2040 climate outlook from the trained riverine models."""
    return get_riverine_outlook(station_id)
