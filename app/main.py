from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError, app_error_handler
from app.core.logging import configure_logging
from app.db.init_db import init_db

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


@app.on_event("startup")
def startup() -> None:
    init_db()
