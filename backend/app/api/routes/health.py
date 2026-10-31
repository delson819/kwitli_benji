from fastapi import APIRouter

from backend.app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def healthcheck() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "storage_backend": "sqlite" if settings.database_url.startswith("sqlite") else "postgresql",
    }
