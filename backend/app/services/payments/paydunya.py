"""Collecte PayDunya Sandbox uniquement. Aucune URL fournisseur configurable."""
import hashlib
import hmac
import re
import json
import socket
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from backend.app.services.payments.provider import ProviderError, ProviderRejected, InvalidProviderConfirmation

BASE_URL = "https://app.paydunya.com/sandbox-api/v1/"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PayDunyaProvider:
    name = "paydunya"

    def __init__(self, settings):
        self.settings = settings

    @property
    def hold_minutes(self):
        return self.settings.payment_hold_minutes

    @staticmethod
    def map_status(status):
        return {"completed": "approved", "failed": "declined", "canceled": "cancelled",
                "cancelled": "cancelled", "pending": "pending"}.get(status, "pending")

    def require_settings(self):
        s = self.settings
        if s.app_env not in {"development", "test"} or s.paydunya_mode != "sandbox":
            raise ProviderError("PayDunya est reserve au Sandbox DEV/TEST.")
        if not all((s.paydunya_master_key, s.paydunya_private_key, s.paydunya_token)):
            raise ProviderError("Configuration PayDunya Sandbox incomplete.")
        if not s.paydunya_private_key.startswith("test_private_"):
            raise ProviderError("Une cle privee PayDunya de test est requise.")

    @staticmethod
    def valid_token(token):
        return isinstance(token, str) and re.fullmatch(r"test_[A-Za-z0-9_-]{1,110}", token) is not None

    def _request(self, method, path, payload=None):
        self.require_settings()
        headers = {"PAYDUNYA-MASTER-KEY": self.settings.paydunya_master_key,
                   "PAYDUNYA-PRIVATE-KEY": self.settings.paydunya_private_key,
                   "PAYDUNYA-TOKEN": self.settings.paydunya_token, "Content-Type": "application/json"}
        try:
            # urllib n'emet pas de log HTTP contenant le token de facture.
            # Ni proxy implicite ni redirection avec des entetes secrets.
            opener = build_opener(ProxyHandler({}), NoRedirect())
            request = Request(BASE_URL + path, method=method, headers=headers,
                              data=json.dumps(payload).encode() if payload is not None else None)
            with opener.open(request, timeout=10) as response:
                if response.status != 200:
                    raise ProviderError("PayDunya Sandbox indisponible.")
                raw = response.read(262145)
            if len(raw) > 262144:
                raise ProviderError("Reponse PayDunya trop volumineuse.")
            data = json.loads(raw)
        except (TimeoutError, socket.timeout):
            raise ProviderError("Delai PayDunya depasse; verifier le paiement avant de reessayer.") from None
        except (HTTPError, URLError, OSError, ValueError):
            raise ProviderError("Reponse PayDunya inutilisable.") from None
        if not isinstance(data, dict):
            raise ProviderError("Reponse PayDunya invalide.")
        return data

    def create_invoice(self, payment):
        parsed = urlparse(self.settings.public_api_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ProviderError("PUBLIC_API_URL HTTPS valide requis pour PayDunya.")
        if payment.currency != "XOF" or payment.amount_in_cents % 100:
            raise ProviderError("Montant XOF invalide.")
        data = self._request("POST", "checkout-invoice/create", {
            "invoice": {"total_amount": payment.amount_in_cents // 100, "description": "Commande KWITLI Sandbox"},
            "store": {"name": "KWITLI Sandbox"},
            "custom_data": {"kwitli_reference": payment.provider_reference},
            "actions": {"callback_url": self.settings.public_api_url.rstrip("/") + "/api/v1/payments/paydunya/confirmation"},
        })
        if data.get("response_code") != "00":
            raise ProviderRejected("PayDunya a refuse la creation de la facture.")
        if not self.valid_token(data.get("token")):
            raise ProviderError("Creation de facture PayDunya non confirmee.")
        return data["token"]

    def verify_hash(self, value):
        self.require_settings()
        expected = hashlib.sha512(self.settings.paydunya_master_key.encode()).hexdigest()
        if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{128}", value) or not hmac.compare_digest(expected, value.lower()):
            raise InvalidProviderConfirmation("Confirmation PayDunya invalide.")

    def confirm(self, token, reference, amount_in_cents):
        if not self.valid_token(token):
            raise InvalidProviderConfirmation("Reference PayDunya invalide.")
        data = self._request("GET", "checkout-invoice/confirm/" + token)
        self.verify_hash(data.get("hash"))
        invoice = data.get("invoice")
        custom = data.get("custom_data")
        if (data.get("response_code") != "00" or data.get("mode") != "test"
                or not isinstance(invoice, dict) or invoice.get("token") != token
                or not isinstance(custom, dict) or custom.get("kwitli_reference") != reference):
            raise InvalidProviderConfirmation("Facture PayDunya incoherente.")
        try:
            amount = Decimal(str(invoice.get("total_amount")))
            valid = amount.is_finite() and amount > 0 and amount * 100 == amount_in_cents
        except (InvalidOperation, TypeError, ValueError):
            valid = False
        if not valid or invoice.get("currency", "XOF") != "XOF":
            raise InvalidProviderConfirmation("Montant ou devise PayDunya incoherent.")
        status = data.get("status")
        if not isinstance(status, str) or status not in {"completed", "pending", "failed", "canceled", "cancelled"}:
            raise ProviderError("Statut PayDunya inconnu; paiement non valide.")
        return self.map_status(status)

    def require_test_customer(self):
        self.require_settings()
        s = self.settings
        if not all((s.paydunya_test_customer_phone, s.paydunya_test_customer_email, s.paydunya_test_customer_password)):
            raise ProviderError("Compte client fictif PayDunya Sandbox non configure.")

    def pay_test_invoice(self, token):
        self.require_test_customer()
        if not self.valid_token(token):
            raise ProviderError("Facture Sandbox indisponible.")
        s = self.settings
        data = self._request("POST", "softpay/checkout/make-payment", {
            "phone_phone": s.paydunya_test_customer_phone, "customer_email": s.paydunya_test_customer_email,
            "password": s.paydunya_test_customer_password, "invoice_token": token,
        })
        if data.get("success") is not True:
            raise ProviderError("Paiement test PayDunya non confirme; verifier son statut.")
