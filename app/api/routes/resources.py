from fastapi import APIRouter

from app.schemas.resource import ResourceResponse
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
