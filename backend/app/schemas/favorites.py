from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class FavoriteCookResponse(BaseModel):
    id: UUID
    cook_id: UUID
    display_name: str
    profile_photo_url: str | None
    rating_average: Decimal | None
    rating_count: int
    has_active_availability: bool
    created_at: datetime


class FavoriteCookStatusResponse(BaseModel):
    cook_id: UUID
    is_favorite: bool
