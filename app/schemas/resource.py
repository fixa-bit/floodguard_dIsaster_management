from pydantic import BaseModel


class ResourceResponse(BaseModel):
    id: str
    name: str
    location_id: str
    latitude: float
    longitude: float
    address: str
    phone: str | None = None
    capacity: int | None = None
    resource_type: str
