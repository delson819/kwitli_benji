from datetime import datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.app.discovery import BusinessVertical, DEFAULT_BUSINESS_VERTICAL


class CookCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=2, max_length=120)
    bio: str | None = Field(default=None, max_length=1000)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    business_vertical: BusinessVertical = DEFAULT_BUSINESS_VERTICAL

    @field_validator("display_name")
    @classmethod
    def trim_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("display_name must contain at least two characters")
        return normalized


class CookUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=2, max_length=120)
    bio: str | None = Field(default=None, max_length=1000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    business_vertical: BusinessVertical | None = None

    @field_validator("display_name")
    @classmethod
    def trim_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("display_name must contain at least two characters")
        return normalized


class CookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    display_name: str
    bio: str | None
    profile_photo_url: str | None
    rating: Decimal
    orders_completed: int
    latitude: float
    longitude: float
    business_vertical: str = DEFAULT_BUSINESS_VERTICAL
    is_verified: bool
    created_at: datetime


class PublicReviewResponse(BaseModel):
    id: UUID
    rating: int
    comment: str | None
    created_at: datetime


class PublicCookDishResponse(BaseModel):
    dish_id: UUID
    availability_id: UUID | None = None
    name: str
    description: str
    photo_url: str | None
    price: Decimal
    currency: str
    remaining_portions: int | None = None
    start_time: time | None = None
    end_time: time | None = None


class PublicCookProfileResponse(BaseModel):
    cook_id: UUID
    display_name: str
    bio: str | None
    profile_photo_url: str | None
    rating_average: Decimal | None
    rating_count: int
    orders_completed: int
    is_verified: bool
    is_open: bool
    business_vertical: str = DEFAULT_BUSINESS_VERTICAL
    active_dishes_count: int
    member_since: datetime
    available_dishes: list[PublicCookDishResponse]
    recent_reviews: list[PublicReviewResponse]
