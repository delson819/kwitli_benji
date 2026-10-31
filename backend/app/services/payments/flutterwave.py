"""Collecte v3 mobile_money_franco, Senegal XOF, cles TEST uniquement."""
import hmac
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from backend.app.services.payments.provider import ProviderError, InvalidProviderConfirmation

BASE_URL = "https://api.flutterwave.com/v3/"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FlutterwaveProvider:
    name = "flutterwave"

    def __init__(self, settings):
        self.settings = settings

    @property
    def hold_minutes(self):
        return self.settings.payment_hold_minutes

    def require_settings(self):
        # Staging accepte uniquement des cles FLWSECK_TEST- : aucun argent reel.
        if (self.settings.app_env not in {"development", "test", "staging"}
                or self.settings.flutterwave_env != "test"
                or not self.settings.flutterwave_secret_key.startswith("FLWSECK_TEST-")
                or not self.settings.flutterwave_webhook_secret.strip()):
            raise ProviderError("Configuration Flutterwave TEST incomplete ou non autorisee.")

    def verify_webhook_secret(self, supplied):
        self.require_settings()
        if not isinstance(supplied, str) or not hmac.compare_digest(
                supplied.encode(), self.settings.flutterwave_webhook_secret.encode()):
            raise InvalidProviderConfirmation("Notification Flutterwave invalide.")

    def _request(self, method, path, payload=None):
        self.require_settings()
        try:
            request = Request(BASE_URL + path, method=method,
                              headers={"Authorization": "Bearer " + self.settings.flutterwave_secret_key,
                                       "Content-Type": "application/json", "Accept": "application/json"},
                              data=json.dumps(payload).encode() if payload is not None else None)
            with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=20) as response:
                if response.status not in {200, 201}:
                    raise ProviderError("Reponse Flutterwave indisponible.")
                raw = response.read(262145)
            if len(raw) > 262144:
                raise ProviderError("Reponse Flutterwave trop volumineuse.")
            data = json.loads(raw, parse_float=Decimal)
        except (URLError, OSError, ValueError):
            raise ProviderError("Flutterwave non confirme; verifier le paiement avant toute nouvelle tentative.") from None
        if not isinstance(data, dict) or data.get("status") != "success" or not isinstance(data.get("data"), dict):
            raise ProviderError("Reponse Flutterwave inutilisable; verification requise.")
        return data

    @staticmethod
    def transaction_id(value):
        if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"[1-9][0-9]{0,19}", str(value)):
            raise InvalidProviderConfirmation("Identifiant Flutterwave invalide.")
        return str(value)

    @staticmethod
    def map_status(status):
        return {"successful": "approved", "failed": "declined", "cancelled": "cancelled"}.get(status, "pending")

    def validate_transaction(self, data, reference, amount, transaction_id=None):
        identifier = self.transaction_id(data.get("id"))
        try:
            value = Decimal(str(data.get("amount")))
            valid_amount = value.is_finite() and value * 100 == amount
        except InvalidOperation:
            valid_amount = False
        if (not valid_amount or data.get("currency") != "XOF" or data.get("tx_ref") != reference
                or (transaction_id is not None and identifier != transaction_id)
                or data.get("status") not in {"pending", "successful", "failed", "cancelled"}):
            raise InvalidProviderConfirmation("Transaction Flutterwave incoherente.")
        return identifier, self.map_status(data["status"])

    @staticmethod
    def next_action(response):
        meta = response.get("meta") or {}
        if not isinstance(meta, dict):
            raise ProviderError("Action Flutterwave invalide.")
        authorization = meta.get("authorization") or {}
        if not isinstance(authorization, dict):
            raise ProviderError("Action Flutterwave invalide.")
        mode = authorization.get("mode")
        if mode in {None, "callback"}:
            return {"type": "wait"}
        url = authorization.get("redirect_url")
        if mode != "redirect" or not isinstance(url, str) or len(url) > 4096:
            raise ProviderError("Autorisation Flutterwave non prise en charge.")
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            port = parsed.port
        except ValueError:
            raise ProviderError("URL d'autorisation Flutterwave invalide.") from None
        # Autoriser seulement les pages HTTPS fournisseur/opérateur, jamais un schema arbitraire.
        allowed = ("flutterwave.com", "myflutterwave.com", "wave.com", "orangemoney.sn")
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or port not in {None, 443} or any(ord(c) < 33 for c in url)
                or not any(host == domain or host.endswith("." + domain) for domain in allowed)):
            raise ProviderError("URL d'autorisation Flutterwave refusee.")
        return {"type": "external", "url": url}

    def payment_return_url(self, base_url, payment_id):
        if not isinstance(base_url, str):
            raise ProviderError("URL de retour Kwitli requise.")
        try:
            parsed = urlparse(base_url)
            query = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=10)
        except ValueError:
            raise ProviderError("URL de retour Kwitli invalide.") from None
        native = (parsed.scheme == "kwitli" and parsed.hostname == "payment-return"
                  and parsed.path in {"", "/"})
        expo_dev = (self.settings.app_env in {"development", "test"}
                    and parsed.scheme in {"exp", "exps"} and bool(parsed.hostname)
                    and parsed.path.rstrip("/").endswith("/payment-return"))
        if (not (native or expo_dev) or parsed.username or parsed.password or parsed.fragment
                or any(key == "payment_id" for key, _ in query)):
            raise ProviderError("URL de retour Kwitli invalide.")
        query.append(("payment_id", str(payment_id)))
        return urlunparse(parsed._replace(query=urlencode(query)))

    def create_payment(self, payment, user, network, phone, return_url):
        self.require_settings()
        if (network not in {"WAVE", "ORANGEMONEY"} or not isinstance(phone, str)
                or not re.fullmatch(r"\+?[0-9]{9,15}", phone)):
            raise ProviderError("Reseau et telephone Flutterwave requis.")
        if payment.currency != "XOF" or payment.amount_in_cents % 100 or not 10000 <= payment.amount_in_cents <= 214748364700:
            raise ProviderError("Montant Flutterwave XOF invalide (minimum 100 XOF).")
        redirect_url = self.payment_return_url(return_url, payment.id)
        response = self._request("POST", "charges?type=mobile_money_franco", {
            "amount": payment.amount_in_cents // 100, "currency": "XOF", "country": "SN",
            "network": network, "phone_number": phone, "email": user.email,
            "fullname": " ".join(p for p in (user.first_name, user.last_name) if p),
            "tx_ref": payment.provider_reference, "use_qr": False, "redirect_url": redirect_url,
        })
        identifier, _ = self.validate_transaction(response["data"], payment.provider_reference, payment.amount_in_cents)
        return identifier, self.next_action(response)

    def verify(self, reference, amount, transaction_id=None):
        path = ("transactions/" + self.transaction_id(transaction_id) + "/verify" if transaction_id
                else "transactions/verify_by_reference?" + urlencode({"tx_ref": reference}))
        response = self._request("GET", path)
        return self.validate_transaction(response["data"], reference, amount, transaction_id)
