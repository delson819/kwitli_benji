from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID
from pydantic import BaseModel

class DiscoverResponse(BaseModel):
    availability_id: UUID | None = None
    dish_id: UUID
    dish_name: str
    description: str
    cook_id: UUID
    cook_display_name: str
    profile_photo_url: str | None
    business_vertical: str
    cook_rating: Decimal
    rating_average: Decimal | None
    review_count: int
    photo_url: str | None
    price: Decimal
    currency: str
    remaining_portions: int | None = None
    available_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    ready_at: datetime | None = None
    featured_type: str | None
    distance_km: float
    is_open: bool
