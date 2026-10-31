from datetime import datetime
from decimal import Decimal
from uuid import UUID

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    availability_id: UUID
    quantity: int = Field(gt=0, le=50)


class OrderItemResponse(BaseModel):
    id: UUID
    dish_id: UUID
    availability_id: UUID | None = None
    dish_name: str
    photo_url: str | None
    quantity: int
    unit_price: Decimal
    line_total: Decimal


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    customer_id: UUID
    availability_id: UUID | None
    quantity: int | None
    unit_price: Decimal | None
    total_price: Decimal
    currency: str
    status: str
    pickup_code: str | None
    confirmed_at: datetime | None
    ready_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    pickup_expires_at: datetime | None
    created_at: datetime
    in_progress_at: datetime | None
    picked_up_at: datetime | None
    cook_id: UUID
    cook_display_name: str
    items: list[OrderItemResponse]


class OrderStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(pattern="^(in_progress|ready)$")


class PickupConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pickup_code: str | None = Field(default=None, pattern=r"^\d{6}$")


class OrderResolutionRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Literal[
        "order_not_received", "incorrect_order", "item_missing", "excessive_delay",
        "quality_issue", "merchant_unavailable", "ingredient_unavailable",
        "item_out_of_stock", "exceptional_closure", "menu_price_error",
        "technical_issue", "other",
    ]
    description: str = Field(min_length=1, max_length=1000)


class OrderResolutionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approved", "rejected", "request_resolution"]
    note: str = Field(min_length=1, max_length=1000)


class OrderResolutionRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    requester_id: UUID
    requester_role: str
    request_type: str
    reason: str
    description: str
    status: Literal["submitted", "approved", "rejected", "resolution_requested"]
    reviewed_by: UUID | None
    reviewed_at: datetime | None
    decision_note: str | None
    created_at: datetime


class OrderHistoryResponse(OrderResponse):
    dish_name: str | None
    dish_photo_url: str | None
    review_id: UUID | None
    review_rating: int | None = None
    review_comment: str | None = None


class OrderMessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=230)

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Le message ne peut pas etre vide.")
        return normalized


class OrderMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order_id: UUID
    sender_id: UUID
    sender_role: Literal["customer", "merchant"]
    body: str
    created_at: datetime
