from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.dependencies import get_current_user, get_marketplace_service
from backend.app.persistence.models import User
from backend.app.schemas.favorites import FavoriteCookResponse, FavoriteCookStatusResponse
from backend.app.services.marketplace import ConflictError, MarketplaceService, NotFoundError

router = APIRouter(prefix="/favorites/cooks", tags=["favorites"])


@router.post("/{cook_id}", response_model=FavoriteCookStatusResponse, status_code=status.HTTP_201_CREATED)
def add_favorite(cook_id: str, current_user: User = Depends(get_current_user), service: MarketplaceService = Depends(get_marketplace_service)) -> FavoriteCookStatusResponse:
    try:
        service.add_favorite_cook(cook_id, current_user)
        return {"cook_id": cook_id, "is_favorite": True}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{cook_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(cook_id: str, current_user: User = Depends(get_current_user), service: MarketplaceService = Depends(get_marketplace_service)) -> None:
    try:
        service.remove_favorite_cook(cook_id, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", response_model=list[FavoriteCookResponse])
def list_favorites(current_user: User = Depends(get_current_user), service: MarketplaceService = Depends(get_marketplace_service)) -> list[FavoriteCookResponse]:
    return service.list_favorite_cooks(current_user)


@router.get("/{cook_id}/status", response_model=FavoriteCookStatusResponse)
def favorite_status(cook_id: str, current_user: User = Depends(get_current_user), service: MarketplaceService = Depends(get_marketplace_service)) -> FavoriteCookStatusResponse:
    try:
        return {"cook_id": cook_id, "is_favorite": service.favorite_cook_status(cook_id, current_user)}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
