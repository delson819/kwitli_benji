from datetime import time

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BusinessHourInput(BaseModel):
    weekday: int = Field(ge=0, le=6)
    is_closed: bool
    opens_at: time | None = None
    closes_at: time | None = None

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.is_closed:
            if self.opens_at is not None or self.closes_at is not None:
                raise ValueError("Un jour fermé ne doit pas avoir d’horaires.")
        elif self.opens_at is None or self.closes_at is None or self.opens_at >= self.closes_at:
            raise ValueError("Un jour ouvert doit avoir une heure de fermeture après l’ouverture.")
        return self


class BusinessHoursSave(BaseModel):
    days: list[BusinessHourInput] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def validate_week(self):
        if {day.weekday for day in self.days} != set(range(7)):
            raise ValueError("Les horaires doivent contenir une seule entrée pour chacun des 7 jours.")
        return self


class BusinessHourResponse(BusinessHourInput):
    model_config = ConfigDict(from_attributes=True)

    id: str | None
    cook_profile_id: str
