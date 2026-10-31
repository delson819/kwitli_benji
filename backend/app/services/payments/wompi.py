from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from urllib.parse import urlencode

from backend.app.core.config import Settings


class WompiValidationError(Exception):
    pass


@dataclass(frozen=True)
class CheckoutData:
    reference: str
    amount_in_cents: int
    currency: str
    checkout_url: str


class WompiPaymentProvider:
    checkout_base_url = "https://checkout.wompi.co/p/"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def hold_minutes(self) -> int:
        return self._settings.payment_hold_minutes

    def create_checkout(self, reference: str, amount_in_cents: int, currency: str) -> CheckoutData:
        if not self._settings.wompi_public_key or not self._settings.wompi_integrity_secret:
            raise WompiValidationError("La configuration Wompi Sandbox est incomplete.")
        signature = self.integrity_signature(reference, amount_in_cents, currency)
        query = urlencode({
            "public-key": self._settings.wompi_public_key,
            "currency": currency,
            "amount-in-cents": amount_in_cents,
            "reference": reference,
            "signature:integrity": signature,
        })
        return CheckoutData(reference, amount_in_cents, currency, f"{self.checkout_base_url}?{query}")

    def integrity_signature(self, reference: str, amount_in_cents: int, currency: str) -> str:
        payload = f"{reference}{amount_in_cents}{currency}{self._settings.wompi_integrity_secret}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def validate_event(self, event: dict, header_checksum: str | None) -> None:
        if self._settings.wompi_env == "sandbox" and event.get("environment") != "test":
            raise WompiValidationError("Evenement Wompi hors environnement Sandbox.")
        signature = event.get("signature") or {}
        properties = signature.get("properties")
        checksum = header_checksum or signature.get("checksum")
        timestamp = event.get("timestamp")
        if not isinstance(properties, list) or not checksum or timestamp is None or not self._settings.wompi_events_secret:
            raise WompiValidationError("Signature d'evenement Wompi invalide.")
        values = "".join(str(self._get_path(event.get("data", {}), property_name)) for property_name in properties)
        expected = hashlib.sha256(f"{values}{timestamp}{self._settings.wompi_events_secret}".encode()).hexdigest()
        if not hmac.compare_digest(expected.lower(), str(checksum).lower()):
            raise WompiValidationError("Signature d'evenement Wompi invalide.")

    @staticmethod
    def map_status(provider_status: str) -> str:
        return {
            "PENDING": "pending", "APPROVED": "approved", "DECLINED": "declined",
            "VOIDED": "cancelled", "ERROR": "error",
        }.get(provider_status, "error")

    @staticmethod
    def _get_path(data: dict, path: str):
        current: object = data
        for segment in path.split("."):
            if not isinstance(current, dict) or segment not in current:
                raise WompiValidationError("Propriete de signature Wompi introuvable.")
            current = current[segment]
        return current
