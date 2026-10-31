from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from backend.app.core.config import get_settings
from backend.app.dependencies import get_marketplace_service
from backend.app.discovery import BusinessVertical, DiscoveryFilter
from backend.app.rate_limit import enforce_rate_limit
from backend.app.schemas.discover import DiscoverResponse
from backend.app.services.marketplace import MarketplaceService

router = APIRouter(prefix="/discover", tags=["discover"])

@router.get("", response_model=list[DiscoverResponse])
def discover(
    request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius_km: float = Query(ge=0.1, le=30),
    discovery_filter: DiscoveryFilter | None = Query(default=None, alias="filter"),
    vertical: BusinessVertical | None = Query(default=None),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> list[DiscoverResponse]:
    enforce_rate_limit(
        request,
        scope="discover",
        limit=get_settings().rate_limit_discover_requests,
    )
    results = service.discover(latitude, longitude, radius_km, discovery_filter, vertical)
    cook_ids = {cook.id for _availability, _dish, cook, _distance, _stock in results}
    review_stats = service.review_stats_for_cooks(cook_ids)
    open_status = service.cook_open_status(cook_ids)
    return [
        DiscoverResponse(
            availability_id=availability.id if availability else None,
            dish_id=dish.id,
            dish_name=dish.name,
            description=dish.description,
            cook_id=cook.id,
            cook_display_name=cook.display_name,
            profile_photo_url=cook.profile_photo_url,
            business_vertical=cook.business_vertical,
            cook_rating=review_stats.get(cook.id, (Decimal("0"), 0))[0],
            rating_average=review_stats.get(cook.id, (None, 0))[0],
            review_count=review_stats.get(cook.id, (None, 0))[1],
            photo_url=dish.photo_url,
            price=dish.price,
            currency=dish.currency,
            remaining_portions=remaining_portions,
            available_date=None,
            start_time=None,
            end_time=None,
            ready_at=availability.ready_at if availability else None,
            featured_type=dish.featured_type,
            distance_km=distance_km,
            is_open=open_status.get(cook.id, False),
        )
        for availability, dish, cook, distance_km, remaining_portions in results
    ]
