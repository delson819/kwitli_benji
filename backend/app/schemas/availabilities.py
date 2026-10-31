from datetime import date, datetime, time
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.core.time import market_datetime_as_utc, market_today, utc_now

class AvailabilityCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dish_id: UUID
    available_date: date
    start_time: time
    end_time: time
    total_portions: int = Field(gt=0, le=500)
    status: Literal["active", "inactive"] = "active"

    @model_validator(mode="after")
    def validate_time_window(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        if self.available_date < market_today():
            raise ValueError("available_date must not be in the past in the market timezone")
        if market_datetime_as_utc(self.available_date, self.end_time) <= utc_now():
            raise ValueError("availability end must be in the future in the market timezone")
        return self


class AvailabilityUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    total_portions: int | None = Field(default=None, gt=0, le=500)
    remaining_portions: int | None = Field(default=None, ge=0, le=500)
    status: Literal["active", "inactive"] | None = None

    @model_validator(mode="after")
    def validate_partial_time_window(self):
        if self.start_time is not None and self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class AvailabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    dish_id: UUID
    available_date: date
    start_time: time
    end_time: time
    total_portions: int
    remaining_portions: int
    status: str
    created_at: datetime
