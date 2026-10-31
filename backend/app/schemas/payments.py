from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PaymentLineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    availability_id: UUID | None = None
    dish_id: UUID | None = None
    quantity: int = Field(gt=0, le=50)

    @model_validator(mode="after")
    def require_one_item_reference(self):
        if (self.availability_id is None) == (self.dish_id is None):
            raise ValueError("Chaque ligne doit identifier un article ou une disponibilite, pas les deux.")
        return self


class PaymentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    availability_id: UUID | None = None
    quantity: int | None = Field(default=None, gt=0, le=50)
    items: list[PaymentLineRequest] | None = Field(default=None, min_length=1, max_length=20)
    network: Literal["WAVE", "ORANGEMONEY"] | None = None
    phone_number: str | None = Field(default=None, pattern=r"^\+?[0-9]{9,15}$")
    return_url: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def validate_lines(self):
        if self.items is not None:
            if self.availability_id is not None or self.quantity is not None:
                raise ValueError("Utiliser items ou availability_id/quantity, jamais les deux.")
            references = [("dish", line.dish_id) if line.dish_id else ("availability", line.availability_id) for line in self.items]
            if len(set(references)) != len(self.items):
                raise ValueError("Un article ne peut apparaitre qu'une fois dans le panier.")
            if len({kind for kind, _ in references}) != 1:
                raise ValueError("Un panier ne peut pas melanger les anciens identifiants de disponibilite et les articles.")
        elif self.availability_id is None or self.quantity is None:
            raise ValueError("Un panier non vide est requis.")
        return self


class PaymentLineResponse(PaymentLineRequest):
    model_config = ConfigDict(from_attributes=True)
    amount_in_cents: int


class PaymentNextAction(BaseModel):
    type: Literal["external", "wait"]
    url: str | None = None


class PaymentResponse(BaseModel):
    id: UUID
    order_id: UUID | None = None
    availability_id: UUID | None = None
    quantity: int
    amount_in_cents: int
    currency: str
    provider: str
    provider_reference: str
    status: str
    checkout_url: str | None = None
    next_action: PaymentNextAction | None = None
    created_at: datetime
    approved_at: datetime | None
    declined_at: datetime | None
    items: list[PaymentLineResponse] = Field(default_factory=list)


class PaymentConfirmationResponse(BaseModel):
    received: bool
