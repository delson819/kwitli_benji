"""Contrat minimal commun; les transports propres aux fournisseurs restent isoles."""
from typing import Protocol


class PaymentProvider(Protocol):
    name: str

    @property
    def hold_minutes(self) -> int: ...

    def map_status(self, status: str) -> str: ...


class ProviderError(Exception):
    """Message public constant, jamais le contenu de la reponse fournisseur."""


class ProviderRejected(ProviderError):
    """Le fournisseur a explicitement refuse la creation sans creer de paiement."""


class InvalidProviderConfirmation(ProviderError):
    pass
