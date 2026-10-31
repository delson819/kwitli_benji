from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from backend.app.dependencies import get_current_user, get_marketplace_service
from backend.app.persistence.models import User
from backend.app.core.config import get_settings
from backend.app.schemas.cooks import CookCreateRequest, CookResponse, CookUpdateRequest, PublicCookProfileResponse
from backend.app.rate_limit import enforce_rate_limit
from backend.app.services.marketplace import AuthorizationError, ConflictError, MarketplaceService, NotFoundError
from backend.app.services.storage import LocalImageStorage

router = APIRouter(prefix="/cooks", tags=["cooks"])


@router.post("", response_model=CookResponse, status_code=status.HTTP_201_CREATED)
def create_cook(
    payload: CookCreateRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> CookResponse:
    try:
        return service.create_cook(payload, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/me/photo", response_model=CookResponse)
async def upload_profile_photo(
    request: Request,
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> CookResponse:
    settings = get_settings()
    storage = LocalImageStorage(
        Path(settings.upload_dir),
        settings.upload_max_bytes,
        settings.upload_max_width,
        settings.upload_max_height,
        settings.upload_max_pixels,
    )
    photo_url: str | None = None
    try:
        service.get_owned_cook_profile(current_user)
        enforce_rate_limit(
            request,
            scope="uploads",
            limit=settings.rate_limit_upload_requests,
            user_id=current_user.id,
        )
        photo_url = await storage.save_image(image)
        return service.set_cook_profile_photo(photo_url, current_user)
    except AuthorizationError as exc:
        if photo_url is not None:
            storage.delete_image(photo_url)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception:
        if photo_url is not None:
            storage.delete_image(photo_url)
        raise
    finally:
        await image.close()


@router.patch("/me", response_model=CookResponse)
def update_my_cook_profile(
    payload: CookUpdateRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> CookResponse:
    try:
        return service.update_cook(payload, current_user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/{cook_id}/public", response_model=PublicCookProfileResponse)
def get_public_cook(cook_id: str, service: MarketplaceService = Depends(get_marketplace_service)) -> PublicCookProfileResponse:
    try:
        return service.get_public_cook_profile(cook_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{cook_id}", response_model=PublicCookProfileResponse)
def get_cook(cook_id: str, service: MarketplaceService = Depends(get_marketplace_service)) -> PublicCookProfileResponse:
    return get_public_cook(cook_id, service)
