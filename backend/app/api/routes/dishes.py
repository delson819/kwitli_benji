from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from backend.app.dependencies import get_current_user, get_marketplace_service
from backend.app.persistence.models import User
from backend.app.schemas.dishes import DishCreateRequest, DishPublicationCreateRequest, DishPublicationResponse, DishResponse, DishUpdateRequest
from backend.app.rate_limit import enforce_rate_limit
from backend.app.services.marketplace import AuthorizationError, ConflictError, MarketplaceService, NotFoundError
from backend.app.services.storage import LocalImageStorage
from backend.app.core.config import get_settings

router = APIRouter(prefix="/dishes", tags=["dishes"])

@router.post("", response_model=DishResponse, status_code=status.HTTP_201_CREATED)
def create_dish(
    payload: DishCreateRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> DishResponse:
    try:
        return service.create_dish(payload, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/with-availability", response_model=DishPublicationResponse, status_code=status.HTTP_201_CREATED)
def publish_dish_with_availability(
    payload: DishPublicationCreateRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> DishPublicationResponse:
    try:
        dish, availability = service.publish_dish_with_availability(payload, current_user)
        return DishPublicationResponse(dish=dish, availability=availability)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

@router.get("", response_model=list[DishResponse])
def list_dishes(
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> list[DishResponse]:
    try:
        return service.list_dishes_for_user(current_user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

@router.get("/{dish_id}", response_model=DishResponse)
def get_dish(
    dish_id: str,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> DishResponse:
    try:
        return service.get_owned_dish(dish_id, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.patch("/{dish_id}", response_model=DishResponse)
def update_dish(
    dish_id: str,
    payload: DishUpdateRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> DishResponse:
    try:
        return service.update_dish(dish_id, payload, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{dish_id}/photo", response_model=DishResponse)
async def upload_dish_photo(
    dish_id: str,
    request: Request,
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> DishResponse:
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
        dish = service.get_dish(dish_id)
        service.get_owned_dish(dish.id, current_user)
        enforce_rate_limit(
            request,
            scope="uploads",
            limit=settings.rate_limit_upload_requests,
            user_id=current_user.id,
        )
        photo_url = await storage.save_image(image)
        return service.set_dish_photo(dish.id, photo_url, current_user)
    except NotFoundError as exc:
        if photo_url is not None:
            storage.delete_image(photo_url)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
