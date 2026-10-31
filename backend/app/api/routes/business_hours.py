from fastapi import APIRouter, Depends, HTTPException

from backend.app.dependencies import get_current_user, get_marketplace_service
from backend.app.persistence.models import User
from backend.app.schemas.business_hours import BusinessHourResponse, BusinessHoursSave
from backend.app.services.marketplace import AuthorizationError, MarketplaceService

router = APIRouter(prefix="/cooks/me/hours", tags=["business hours"])


@router.get("", response_model=list[BusinessHourResponse])
def get_my_business_hours(
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
):
    try:
        return service.get_cook_business_hours(current_user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.put("", response_model=list[BusinessHourResponse])
def save_my_business_hours(
    payload: BusinessHoursSave,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
):
    try:
        return service.save_cook_business_hours(payload, current_user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
