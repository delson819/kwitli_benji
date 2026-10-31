from fastapi import APIRouter, Depends, HTTPException, status
from backend.app.dependencies import get_current_user, get_marketplace_service
from backend.app.persistence.models import User
from backend.app.schemas.availabilities import AvailabilityCreateRequest, AvailabilityResponse, AvailabilityUpdateRequest
from backend.app.services.marketplace import AuthorizationError, ConflictError, MarketplaceService, NotFoundError

router = APIRouter(prefix="/availabilities", tags=["availabilities"])

@router.post("", response_model=AvailabilityResponse, status_code=status.HTTP_201_CREATED)
def create_availability(
    payload: AvailabilityCreateRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> AvailabilityResponse:
    try:
        return service.create_availability(payload, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

@router.get("", response_model=list[AvailabilityResponse])
def list_availabilities(
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> list[AvailabilityResponse]:
    try:
        return service.list_availabilities_for_user(current_user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

@router.get("/{availability_id}", response_model=AvailabilityResponse)
def get_availability(
    availability_id: str,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> AvailabilityResponse:
    try:
        return service.get_owned_availability(availability_id, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.patch("/{availability_id}", response_model=AvailabilityResponse)
def update_availability(
    availability_id: str,
    payload: AvailabilityUpdateRequest,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> AvailabilityResponse:
    try:
        return service.update_availability(availability_id, payload, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
