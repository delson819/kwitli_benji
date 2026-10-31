from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.core.time import market_datetime_as_utc, market_today, utc_now
from backend.app.schemas.availabilities import AvailabilityResponse
from backend.app.core.currencies import amount_storage_units

MAX_DISH_PRICE_COP = Decimal("2000000.00")


class DishCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    price: Decimal = Field(gt=0, le=MAX_DISH_PRICE_COP, max_digits=10, decimal_places=2)
    currency: str = Field(default="COP", pattern="^(COP|XOF)$")
    category: str | None = Field(default=None, max_length=80)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_currency_precision(self):
        amount_storage_units(self.price, self.currency)
        return self

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("value is too short after trimming")
        return normalized

    @field_validator("description")
    @classmethod
    def trim_description(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("category")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DishUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=3, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    price: Decimal | None = Field(default=None, gt=0, le=MAX_DISH_PRICE_COP, max_digits=10, decimal_places=2)
    category: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("value is too short after trimming")
        return normalized

    @field_validator("description")
    @classmethod
    def trim_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("category")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DishResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    cook_id: UUID
    name: str
    description: str
    price: Decimal
    currency: str
    photo_url: str | None
    category: str | None
    is_active: bool
    created_at: datetime


class DishPublicationCreateRequest(DishCreateRequest):
    available_date: date
    start_time: time
    end_time: time
    total_portions: int = Field(gt=0, le=500)

    @model_validator(mode="after")
    def validate_time_window(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        if self.available_date < market_today():
            raise ValueError("available_date must not be in the past in the market timezone")
        if market_datetime_as_utc(self.available_date, self.end_time) <= utc_now():
            raise ValueError("availability end must be in the future in the market timezone")
        return self


class DishPublicationResponse(BaseModel):
    dish: DishResponse
    availability: AvailabilityResponse
