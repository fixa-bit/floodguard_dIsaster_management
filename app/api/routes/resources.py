from fastapi import APIRouter, Query

from app.schemas.resource import ResourceResponse
from app.services import relief_facilities
from app.services.resource_service import list_resources

router = APIRouter(prefix="/resources", tags=["Emergency Resources"])


@router.get("/shelters", response_model=list[ResourceResponse])
async def shelters(location_id: str | None = None):
    return list_resources("shelter", location_id)


@router.get("/hospitals", response_model=list[ResourceResponse])
async def hospitals(location_id: str | None = None):
    return list_resources("hospital", location_id)


@router.get("/emergency-contacts", response_model=list[ResourceResponse])
async def emergency_contacts(location_id: str | None = None):
    return list_resources("emergency_contact", location_id)


@router.get("/facilities/nearby")
async def facilities_nearby(latitude: float = Query(ge=23, le=38), longitude: float = Query(ge=60, le=78),
                            radius_km: float = Query(default=25, gt=0, le=200), per_category: int = Query(default=8, ge=1, le=50)):
    """Hospitals, clinics, rescue, police, schools (possible relief camps) and assembly points near a
    point, from OpenStreetMap (GIS Operations' relief assessment)."""
    return relief_facilities.nearby(latitude, longitude, radius_km, per_category)
