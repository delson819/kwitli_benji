"""Collecte PayTech TEST : contrats de doc.paytech.sn, aucun endpoint production."""
import hashlib
import hmac
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from backend.app.services.payments.provider import ProviderError, ProviderRejected, InvalidProviderConfirmation

BASE_URL = "https://paytech.sn/api/"
CHECKOUT_BASE = "https://paytech.sn/payment/checkout/"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PayTechProvider:
    name = "paytech"

    def __init__(self, settings):
        self.settings = settings

    @property
    def hold_minutes(self):
        return self.settings.payment_hold_minutes

    def require_settings(self):
        if self.settings.paytech_env != "test" or self.settings.app_env not in {"development", "test"}:
            raise ProviderError("PayTech est limite aux tests internes env=test.")
        if not self.settings.paytech_api_key or not self.settings.paytech_api_secret:
            raise ProviderError("Configuration PayTech TEST incomplete.")

    @staticmethod
    def valid_token(token):
        return isinstance(token, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", token) is not None

    def _request(self, method, path, payload=None):
        self.require_settings()
        headers = {"API_KEY": self.settings.paytech_api_key, "API_SECRET": self.settings.paytech_api_secret,
                   "Accept": "application/json", "Content-Type": "application/json"}
        try:
            # Pas de logs HTTP, proxy implicite ou redirection contenant nos credentials.
            opener = build_opener(ProxyHandler({}), NoRedirect())
            request = Request(BASE_URL + path, method=method, headers=headers,
                              data=json.dumps(payload).encode() if payload is not None else None)
            with opener.open(request, timeout=10) as response:
                if response.status != 200:
                    raise ProviderError("PayTech TEST indisponible.")
                body = response.read(262145)
            if len(body) > 262144:
                raise ProviderError("Reponse PayTech trop volumineuse.")
            data = json.loads(body)
        except TimeoutError:
            raise ProviderError("Delai PayTech depasse; verifier la demande avant de reessayer.") from None
        except (URLError, OSError, ValueError):
            raise ProviderError("Reponse PayTech inutilisable.") from None
        if not isinstance(data, dict):
            raise ProviderError("Reponse PayTech invalide.")
        return data

    def create_payment(self, payment):
        self.require_settings()
        base = self.settings.public_api_url.rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
            raise ProviderError("PUBLIC_API_URL HTTPS valide requis pour PayTech.")
        if payment.currency != "XOF" or payment.amount_in_cents <= 0 or payment.amount_in_cents % 100:
            raise ProviderError("Montant XOF invalide.")
        data = self._request("POST", "payment/request-payment", {
            "item_name": "Commande KWITLI TEST", "item_price": payment.amount_in_cents // 100,
            "ref_command": payment.provider_reference, "command_name": "Commande KWITLI TEST",
            "currency": "XOF", "env": "test", "target_payment": "Wave, Orange Money",
            "ipn_url": base + "/api/v1/payments/paytech/confirmation",
            "success_url": base + "/api/v1/payments/paytech/return",
            "cancel_url": base + "/api/v1/payments/paytech/return",
        })
        if data.get("success") == 0:
            raise ProviderRejected("PayTech a refuse la creation du paiement.")
        token = data.get("token")
        if data.get("success") != 1 or not self.valid_token(token):
            raise ProviderError("Creation du paiement PayTech non confirmee.")
        checkout = self.checkout_url(token)
        if data.get("redirect_url", data.get("redirectUrl")) != checkout:
            raise ProviderError("URL checkout PayTech invalide.")
        if "redirectUrl" in data and data["redirectUrl"] != checkout:
            raise ProviderError("URL checkout PayTech incoherente.")
        return token, checkout

    def checkout_url(self, token):
        if not self.valid_token(token):
            raise ProviderError("Token de paiement PayTech invalide.")
        return CHECKOUT_BASE + token

    def get_payment_status(self, token):
        """Transport officiel seulement : aucun schema de reponse publie, pas de mapping invente."""
        if not self.valid_token(token):
            raise ProviderError("Token de paiement PayTech invalide.")
        return self._request("GET", "payment/get-status?token_payment=" + token)

    @staticmethod
    def map_status(event):
        # Echecs/annulations et remboursement : evenements documentes uniquement.
        return {"sale_complete": "approved", "sale_canceled": "cancelled",
                "refund_complete": "refunded"}.get(event, "pending")

    def verify_notification(self, payload):
        self.require_settings()
        reference, token = payload.get("ref_command"), payload.get("token")
        amount = payload.get("final_item_price", payload.get("item_price"))
        signature = payload.get("hmac_compute")
        if (not isinstance(reference, str) or not re.fullmatch(r"KWITLI[A-F0-9]{32}", reference)
                or not self.valid_token(token) or not isinstance(amount, (str, int, Decimal)) or isinstance(amount, bool)
                or not isinstance(signature, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", signature)):
            raise InvalidProviderConfirmation("Notification PayTech invalide.")
        canonical = f"{amount}|{reference}|{self.settings.paytech_api_key}"
        expected = hmac.new(self.settings.paytech_api_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature.lower()):
            raise InvalidProviderConfirmation("Notification PayTech invalide.")
        try:
            value = Decimal(str(amount))
            original = Decimal(str(payload.get("item_price")))
            valid = value.is_finite() and 0 < value <= Decimal("1000000000000") and value == value.to_integral_value() and original == value
        except (InvalidOperation, ValueError):
            valid = False
        if (not valid or payload.get("env") != "test" or payload.get("currency") != "XOF"
                or payload.get("type_event") not in {"sale_complete", "sale_canceled"}):
            raise InvalidProviderConfirmation("Montant, environnement ou evenement PayTech invalide.")
        # Les remboursements et promotions restent hors perimetre, aucun ajustement silencieux.
        return reference, token, int(value * 100), self.map_status(payload["type_event"])
