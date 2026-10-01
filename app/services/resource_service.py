from app.schemas.resource import ResourceResponse


# No placeholder facilities are exposed in real deployments. Populate this list
# only from an approved authority source or replace it with a persistent provider.
RESOURCES: list[ResourceResponse] = []


def list_resources(resource_type: str, location_id: str | None = None) -> list[ResourceResponse]:
    return [resource for resource in RESOURCES if resource.resource_type == resource_type and (location_id is None or resource.location_id == location_id)]
