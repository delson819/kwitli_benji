from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.admin_page import router as admin_page_router
from backend.app.api.router import api_router
from backend.app.core.config import get_settings
from backend.app.database import init_database
from backend.app.rate_limit import InMemoryRateLimiter, UploadSecurityMiddleware


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_database()
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=settings.app_description,
        lifespan=lifespan,
    )
    limiter = InMemoryRateLimiter(max_buckets=settings.rate_limit_max_buckets)
    app.state.rate_limiter = limiter
    app.add_middleware(UploadSecurityMiddleware, limiter=limiter, settings=settings)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(admin_page_router)
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

    @app.get("/", tags=["meta"])
    def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "docs_url": "/docs",
            "launch_country": settings.launch_country,
            "ui_locale": settings.ui_locale,
        }

    return app


app = create_app()
