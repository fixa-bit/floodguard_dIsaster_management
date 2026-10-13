from fastapi import APIRouter
from app.api.routes import alerts

from app.api.routes import automation, citizen_reports, dashboard, events, exposure, flood, gis, health, incidents, population, resources, river, sar_water, simulation, system, weather

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(alerts.router)
api_router.include_router(system.router)
api_router.include_router(weather.router)
api_router.include_router(river.router)
api_router.include_router(flood.router)
api_router.include_router(sar_water.router)
api_router.include_router(incidents.router)
api_router.include_router(citizen_reports.router)
api_router.include_router(simulation.router)
api_router.include_router(events.router)
api_router.include_router(resources.router)
api_router.include_router(automation.router)
api_router.include_router(dashboard.router)
api_router.include_router(gis.router)
api_router.include_router(exposure.router)
api_router.include_router(population.router)
