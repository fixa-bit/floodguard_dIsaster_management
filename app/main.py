from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.api.router import api_router
from app.api.routes.station_hydrograph import router as station_hydrograph_router
from app.core.config import get_settings
from app.core.exceptions import AppError, app_error_handler
from app.core.logging import configure_logging
from app.db.init_db import init_db
from app.services.upstream_forecast_cache_service import upstream_forecast_cache
from app.services.river_monitoring_service import river_monitoring_cache

configure_logging()
settings = get_settings()

app = FastAPI(
    title="FloodGuard AI Backend",
    description="Backend foundation for flood early warning, verification, and emergency response workflows.",
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_exception_handler(AppError, app_error_handler)
app.include_router(api_router)
app.include_router(station_hydrograph_router, prefix="/api")


@app.on_event("startup")
async def startup() -> None:
    init_db()
    upstream_forecast_cache.start()
    river_monitoring_cache.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await upstream_forecast_cache.stop()
    await river_monitoring_cache.stop()
