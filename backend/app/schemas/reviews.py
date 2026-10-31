from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    customer_id: UUID
    cook_id: UUID
    rating: int
    comment: str | None
    created_at: datetime


class PublicReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    rating: int
    comment: str | None
    created_at: datetime


class ReviewPageResponse(BaseModel):
    items: list[PublicReviewResponse]
    limit: int
    offset: int
