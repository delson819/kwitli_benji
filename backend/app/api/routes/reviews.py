from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from backend.app.core.config import get_settings
from backend.app.dependencies import get_current_user, get_marketplace_service
from backend.app.persistence.models import User
from backend.app.rate_limit import enforce_rate_limit
from backend.app.schemas.reviews import ReviewCreateRequest, ReviewPageResponse, ReviewResponse
from backend.app.services.marketplace import AuthorizationError, ConflictError, MarketplaceService, NotFoundError

router = APIRouter(prefix="/reviews", tags=["reviews"])

@router.post("", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
def create_review(
    payload: ReviewCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> ReviewResponse:
    enforce_rate_limit(
        request,
        scope="reviews-create",
        limit=get_settings().rate_limit_review_requests,
        user_id=current_user.id,
    )
    try:
        return service.create_review(payload, current_user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/cooks/{cook_id}", response_model=ReviewPageResponse)
def list_cook_reviews(
    cook_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> ReviewPageResponse:
    try:
        return {"items": service.list_reviews_for_cook(cook_id, limit, offset), "limit": limit, "offset": offset}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
