from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping
from urllib.parse import urlparse

from backend.app.core.config import Settings


class PayUValidationError(Exception):
    pass


@dataclass(frozen=True)
class PayUConfirmation:
    reference: str
    provider_transaction_id: str
    provider_status: str
    amount_in_cents: int
    currency: str


@dataclass(frozen=True)
class PayUSandboxTestIdentity:
    """Valeurs non reelles utilisees seulement lorsque le profil ne porte pas ces donnees."""

    document_type: str = "CC"
    document: str = "1000000000"
    phone: str = "3000000000"


PAYU_REQUIRED_FORM_FIELDS = frozenset({
    "merchantId", "accountId", "description", "referenceCode", "amount", "tax",
    "taxReturnBase", "currency", "signature", "payerFullName", "payerEmail",
    "payerPhone", "payerDocumentType", "payerDocument", "buyerFullName", "buyerEmail",
    "buyerDocumentType", "buyerDocument", "telephone",
})
PAYU_SANDBOX_TEST_IDENTITY = PayUSandboxTestIdentity()


class PayUPaymentProvider:
    """Adaptateur WebCheckout PayU Latam, limite au Sandbox colombien."""

    name = "payu"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def hold_minutes(self) -> int:
        return self._settings.payment_hold_minutes

    @property
    def checkout_url(self) -> str:
        self._require_checkout_settings()
        return self._settings.payu_checkout_url

    def checkout_fields(
        self,
        *,
        reference: str,
        amount_in_cents: int,
        currency: str,
        buyer_email: str,
        buyer_full_name: str,
        buyer_phone: str | None,
        confirmation_url: str,
        response_url: str,
    ) -> dict[str, str]:
        self._require_checkout_settings()
        self._require_https_url(confirmation_url, "confirmationUrl")
        self._require_https_url(response_url, "responseUrl")
        if currency != "COP":
            raise PayUValidationError("PayU Colombie requiert la devise COP.")
        if not self._is_valid_reference(reference):
            raise PayUValidationError("La reference PayU doit etre alphanumerique et unique.")
        amount = self._amount_for_checkout(amount_in_cents)
        full_name = buyer_full_name.strip() or "KwitliSandboxTester"
        phone = self._checkout_phone(buyer_phone)
        signature = hashlib.sha256(
            f"{self._settings.payu_api_key}~{self._settings.payu_merchant_id}~{reference}~{amount}~{currency}".encode()
        ).hexdigest()
        fields = {
            "merchantId": self._settings.payu_merchant_id,
            "accountId": self._settings.payu_account_id,
            "description": f"Kwitli {reference}",
            "referenceCode": reference,
            "amount": amount,
            "tax": "0",
            "taxReturnBase": "0",
            "currency": currency,
            "algorithmSignature": "SHA256",
            "signature": signature,
            # PayU WebCheckout utilise test=1 pour les transactions Sandbox.
            "test": "1",
            "payerFullName": full_name,
            "payerEmail": buyer_email,
            "payerPhone": phone,
            "payerDocumentType": PAYU_SANDBOX_TEST_IDENTITY.document_type,
            "payerDocument": PAYU_SANDBOX_TEST_IDENTITY.document,
            "buyerFullName": full_name,
            "buyerEmail": buyer_email,
            "buyerDocumentType": PAYU_SANDBOX_TEST_IDENTITY.document_type,
            "buyerDocument": PAYU_SANDBOX_TEST_IDENTITY.document,
            "telephone": phone,
            "responseUrl": response_url,
            "confirmationUrl": confirmation_url,
        }
        self.validate_sandbox_checkout_fields(fields)
        return fields

    def validate_sandbox_checkout_fields(self, fields: Mapping[str, str]) -> None:
        """Refuse un formulaire Sandbox incomplet ou incoherent."""
        if self._settings.payu_env != "sandbox":
            raise PayUValidationError("La validation du formulaire est reservee au Sandbox PayU.")
        missing = PAYU_REQUIRED_FORM_FIELDS.difference(fields)
        if missing:
            raise PayUValidationError(
                f"Le formulaire PayU Sandbox est incomplet: {', '.join(sorted(missing))}."
            )
        if not self._is_valid_reference(fields["referenceCode"]):
            raise PayUValidationError("La reference PayU doit etre alphanumerique et unique.")
        if fields["currency"] != "COP":
            raise PayUValidationError("PayU Colombie requiert la devise COP.")
        if fields["test"] != "1":
            raise PayUValidationError("Le formulaire PayU Sandbox doit utiliser test=1.")
        self._validate_amounts(fields)
        self._validate_signature(fields)
        payer_complete = all(fields[name].strip() for name in (
            "payerFullName", "payerEmail", "payerPhone", "payerDocumentType", "payerDocument",
        ))
        buyer_complete = all(fields[name].strip() for name in (
            "buyerFullName", "buyerEmail", "buyerDocumentType", "buyerDocument", "telephone",
        ))
        if not payer_complete or not buyer_complete:
            raise PayUValidationError("Les informations obligatoires du payeur ou de l'acheteur sont incompletes.")

    def validate_confirmation(self, payload: dict[str, str]) -> PayUConfirmation:
        required = ("merchant_id", "reference_sale", "value", "currency", "state_pol", "sign")
        if any(not payload.get(key) for key in required):
            raise PayUValidationError("Confirmation PayU incomplete.")
        if payload["merchant_id"] != self._settings.payu_merchant_id:
            raise PayUValidationError("Commerce PayU invalide.")
        if payload["currency"] != "COP":
            raise PayUValidationError("Devise PayU invalide.")
        if not self._is_valid_reference(payload["reference_sale"]):
            raise PayUValidationError("Reference PayU invalide.")
        value = self._confirmation_value(payload["value"])
        signature_payload = "~".join((
            self._settings.payu_api_key, payload["merchant_id"], payload["reference_sale"],
            value, payload["currency"], payload["state_pol"],
        ))
        expected = hashlib.sha256(signature_payload.encode()).hexdigest()
        if not hmac.compare_digest(expected.lower(), payload["sign"].lower()):
            raise PayUValidationError("Signature de confirmation PayU invalide.")
        try:
            amount_in_cents = int((Decimal(payload["value"]) * 100).quantize(Decimal("1")))
        except (InvalidOperation, ValueError) as error:
            raise PayUValidationError("Montant PayU invalide.") from error
        return PayUConfirmation(
            reference=payload["reference_sale"],
            provider_transaction_id=payload.get("transaction_id") or payload.get("reference_pol") or payload["reference_sale"],
            provider_status=payload["state_pol"], amount_in_cents=amount_in_cents, currency=payload["currency"],
        )

    @staticmethod
    def map_status(provider_status: str) -> str:
        return {"4": "approved", "6": "declined", "5": "error"}.get(provider_status, "error")

    @staticmethod
    def _amount_for_checkout(amount_in_cents: int) -> str:
        return format(Decimal(amount_in_cents) / 100, ".2f")

    def _validate_signature(self, fields: Mapping[str, str]) -> None:
        expected = hashlib.sha256(
            f"{self._settings.payu_api_key}~{fields['merchantId']}~{fields['referenceCode']}~{fields['amount']}~{fields['currency']}".encode()
        ).hexdigest()
        if not hmac.compare_digest(expected, fields["signature"]):
            raise PayUValidationError("La signature du formulaire PayU est invalide.")

    @staticmethod
    def _validate_amounts(fields: Mapping[str, str]) -> None:
        try:
            amount = Decimal(fields["amount"])
            tax = Decimal(fields["tax"])
            tax_return_base = Decimal(fields["taxReturnBase"])
        except InvalidOperation as error:
            raise PayUValidationError("Les montants du formulaire PayU sont invalides.") from error
        if amount <= 0 or tax < 0 or tax_return_base < 0 or tax + tax_return_base > amount:
            raise PayUValidationError("Les montants TVA du formulaire PayU sont incoherents.")

    @staticmethod
    def _checkout_phone(phone: str | None) -> str:
        normalized = "".join(character for character in (phone or "") if character.isdigit())
        if 7 <= len(normalized) <= 20:
            return normalized
        return PAYU_SANDBOX_TEST_IDENTITY.phone

    @staticmethod
    def _is_valid_reference(reference: str) -> bool:
        return bool(reference) and reference.isascii() and reference.isalnum()

    @staticmethod
    def _confirmation_value(raw_value: str) -> str:
        try:
            value = Decimal(raw_value)
        except InvalidOperation as error:
            raise PayUValidationError("Montant PayU invalide.") from error
        cents = value.quantize(Decimal("0.01"))
        # Regle PayU: 150.00 devient 150.0, 150.25 reste 150.25.
        if cents.as_tuple().digits[-1] == 0:
            return format(cents, ".1f")
        return format(cents, ".2f")

    def _require_checkout_settings(self) -> None:
        if not all((self._settings.payu_api_key, self._settings.payu_merchant_id, self._settings.payu_account_id, self._settings.payu_checkout_url)):
            raise PayUValidationError("La configuration PayU Sandbox est incomplete.")
        self._require_https_url(self._settings.payu_checkout_url, "PAYU_CHECKOUT_URL")
        checkout_hostname = urlparse(self._settings.payu_checkout_url).hostname
        if checkout_hostname != "sandbox.checkout.payulatam.com":
            raise PayUValidationError("PAYU_CHECKOUT_URL doit utiliser le hostname officiel PayU Sandbox.")
        self._require_https_url(self._settings.public_api_url, "PUBLIC_API_URL")

    @staticmethod
    def _require_https_url(value: str, setting_name: str) -> None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise PayUValidationError(f"{setting_name} doit utiliser une URL HTTPS absolue.")
