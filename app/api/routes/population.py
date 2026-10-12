from fastapi import APIRouter
from fastapi.responses import FileResponse
from app.schemas.population import PopulationRequest
from app.services.population_service import PopulationService

router = APIRouter(prefix='/population', tags=['Flood-Affected Population'])


@router.post('/analyses', status_code=202)
def analyze(request: PopulationRequest):
    return PopulationService().start(request)


@router.get('/regions/{region}/latest')
def latest(region: str):
    return PopulationService().latest(region)


@router.get('/analyses/{region}/{ident}/status')
def status(region: str, ident: str):
    return PopulationService().status(region,ident)


@router.get('/analyses/{region}/{ident}')
def summary(region: str, ident: str):
    return FileResponse(PopulationService().artifact(region,ident),media_type='application/json')


@router.get('/analyses/{region}/{ident}/layers/{layer}')
def layer(region: str, ident: str, layer: str):
    return FileResponse(PopulationService().artifact(region,ident,layer),media_type='application/geo+json')
