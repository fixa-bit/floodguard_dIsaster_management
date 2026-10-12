from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.schemas.exposure import ExposureRequest
from app.services.exposure_service import ExposureService

router = APIRouter(prefix="/exposure", tags=["GIS Flood Exposure"])


@router.get("/regions")
def regions():
    return ExposureService().regions()


@router.get("/regions/{region}/audit")
def dataset_audit(region: str, include_reference_buildings: bool = True, refresh: bool = False):
    return ExposureService().audit(region, include_reference_buildings, refresh)


@router.post("/analyses", status_code=201)
def analyze(request: ExposureRequest):
    return ExposureService().analyze(request)


@router.get("/analyses/{region}/{analysis_id}")
def summary(region: str, analysis_id: str):
    return FileResponse(ExposureService().artifact(region, analysis_id), media_type="application/json")


@router.get("/analyses/{region}/{analysis_id}/layers/{layer}")
def layer(region: str, analysis_id: str, layer: str):
    return FileResponse(ExposureService().artifact(region, analysis_id, layer), media_type="application/geo+json")
