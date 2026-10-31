from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from decimal import Decimal
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sys
from types import SimpleNamespace
from urllib.error import URLError

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.app.core.config import get_settings, Settings
from backend.app.core.currencies import sandbox_provider_for
from backend.app.database import get_session_factory
from backend.app.persistence.models import Dish, DishAvailability, Payment, StockHold, Order
from backend.app.services.payments.paytech import PayTechProvider, CHECKOUT_BASE
from backend.app.services.payments.provider import ProviderError
from backend.tests.test_cart_checkout import cart_fixture, assert_unified_cart_order

TRANSPORT_REQUEST = PayTechProvider._request


@pytest.fixture
def paytech(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "xof_payment_provider", "paytech")
    monkeypatch.setattr(settings, "paytech_api_key", secrets.token_hex(24))
    monkeypatch.setattr(settings, "paytech_api_secret", secrets.token_hex(24))
    state = {"requests": [], "error": False, "response": None, "tokens": [], "drop_after_request": False}

    def request(self, method, path, payload=None):
        self.require_settings()
        state["requests"].append((method, path, payload))
        if state["error"]:
            raise ProviderError("PayTech TEST indisponible.")
        if state["response"] is not None:
            return state["response"]
        token = secrets.token_hex(12)
        state["tokens"].append(token)
        state["response"] = {"success": 1, "token": token, "redirect_url": CHECKOUT_BASE + token}
        if state["drop_after_request"]:
            state["drop_after_request"] = False
            raise ProviderError("PayTech response lost after payment creation.")
        return state["response"]

    monkeypatch.setattr(PayTechProvider, "_request", request)
    customer, lines = cart_fixture(client)
    with get_session_factory()() as session:
        for line, price in zip(lines, [4500, 5000]):
            dish = session.get(Dish, session.get(DishAvailability, line["availability_id"]).dish_id)
            dish.currency, dish.price = "XOF", Decimal(price)
        session.commit()
    return customer, lines, state


def create(client, paytech, key=None):
    headers = paytech[0] if key is None else {**paytech[0], "Idempotency-Key": key}
    response = client.post("/api/v1/payments", headers=headers, json={"items": paytech[1]})
    assert response.status_code == 201
    return response.json()


def sign(payload):
    settings = get_settings()
    value = payload.get("final_item_price", payload["item_price"])
    canonical = f"{value}|{payload['ref_command']}|{settings.paytech_api_key}"
    payload["hmac_compute"] = hmac.new(settings.paytech_api_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return payload


def notification(payment):
    with get_session_factory()() as session:
        token = session.get(Payment, payment["id"]).provider_transaction_id
    return sign({"ref_command": payment["provider_reference"], "token": token,
                 "item_price": str(payment["amount_in_cents"] // 100), "currency": "XOF", "env": "test",
                 "type_event": "sale_complete", "payment_method": "Wave"})


def test_selection_total_pending_reference_and_secret_redaction(client, paytech, caplog):
    payment = create(client, paytech)
    assert sandbox_provider_for("COP") == "payu"
    assert sandbox_provider_for("XOF") == "paytech"
    assert payment["provider"] == "paytech" and payment["status"] == "pending"
    assert payment["currency"] == "XOF" and payment["amount_in_cents"] == 1400000
    method, path, payload = paytech[2]["requests"][0]
    assert (method, path) == ("POST", "payment/request-payment")
    assert payload["env"] == "test" and payload["item_price"] == 14000
    assert payload["target_payment"] == "Wave, Orange Money"
    assert payload["ref_command"] == payment["provider_reference"]
    assert payload["ipn_url"].endswith("/payments/paytech/confirmation")
    with get_session_factory()() as session:
        token = session.get(Payment, payment["id"]).provider_transaction_id
        assert token == paytech[2]["tokens"][0]
    assert payment["checkout_url"] == CHECKOUT_BASE + token
    for secret in (get_settings().paytech_api_key, get_settings().paytech_api_secret):
        assert secret not in str(payment) + caplog.text
    assert token not in caplog.text


@pytest.mark.parametrize("method", ["Wave", "Orange Money"])
@pytest.mark.parametrize("encoding", ["json", "form"])
def test_paid_and_idempotent_notifications(client, paytech, method, encoding):
    payment = create(client, paytech)
    event = notification(payment)
    event["payment_method"] = method
    event["hmac_compute"] = event["hmac_compute"].upper()
    for _ in range(3):
        response = client.post("/api/v1/payments/paytech/confirmation", **({"json": event} if encoding == "json" else {"data": event}))
        assert response.status_code == 200
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "approved"
        assert_unified_cart_order(session)


def test_replay_after_uncertain_paytech_response_does_not_create_another_invoice(client, paytech):
    key = "paytech-uncertain-attempt"
    paytech[2]["drop_after_request"] = True
    first_response = client.post("/api/v1/payments", headers={**paytech[0], "Idempotency-Key": key},
                                 json={"items": paytech[1]})
    assert first_response.status_code == 503
    with get_session_factory()() as session:
        payment = session.scalar(select(Payment))
        payment_id = payment.id
        assert payment.status == "pending" and payment.provider_transaction_id is None
    retry = create(client, paytech, key)
    assert retry["id"] == payment_id
    assert retry["next_action"]["type"] == "wait"
    assert len([request for request in paytech[2]["requests"] if request[0] == "POST"]) == 1


def test_paytech_signed_callback_recovers_token_not_persisted_after_response_loss(client, paytech):
    payment = create(client, paytech)
    provider_token = paytech[2]["tokens"][0]
    with get_session_factory()() as session:
        session.get(Payment, payment["id"]).provider_transaction_id = None
        session.commit()
    event = sign({"ref_command": payment["provider_reference"], "token": provider_token,
                  "item_price": str(payment["amount_in_cents"] // 100), "currency": "XOF", "env": "test",
                  "type_event": "sale_complete", "payment_method": "Wave"})
    assert client.post("/api/v1/payments/paytech/confirmation", json=event).status_code == 200
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).provider_transaction_id == provider_token
        assert_unified_cart_order(session)
        assert all(hold.status == "consumed" for hold in session.scalars(select(StockHold)))
        for line in paytech[1]:
            assert session.get(DishAvailability, line["availability_id"]).remaining_portions == 8 - line["quantity"]


def test_concurrent_callbacks_do_not_duplicate(client, paytech):
    payment = create(client, paytech)
    event = notification(payment)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post("/api/v1/payments/paytech/confirmation", json=event), range(2)))
    assert all(response.status_code == 200 for response in responses)
    with get_session_factory()() as session:
        assert_unified_cart_order(session)


@pytest.mark.parametrize("field,value,resign", [
    ("hmac_compute", "0" * 64, False), ("item_price", "1", False), ("item_price", "1", True),
    ("env", "prod", True), ("currency", "COP", True), ("token", "unrelated", True),
    ("type_event", "unrecognized", True), ("type_event", "refund_complete", True),
    ("final_item_price", "100", True),
])
def test_invalid_callback_cannot_change_payment(client, paytech, field, value, resign):
    payment = create(client, paytech)
    event = {**notification(payment), field: value}
    if resign:
        event = sign(event)
    assert client.post("/api/v1/payments/paytech/confirmation", json=event).status_code == 403
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "pending"
        assert not list(session.scalars(select(Order)))


def test_cancel_releases_holds_without_order_and_return_is_not_truth(client, paytech):
    payment = create(client, paytech)
    assert client.get("/api/v1/payments/paytech/return?status=success").status_code == 200
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=paytech[0]).json()["status"] == "pending"
    event = {**notification(payment), "type_event": "sale_canceled"}
    assert client.post("/api/v1/payments/paytech/confirmation", json=event).status_code == 200
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "cancelled"
        assert not list(session.scalars(select(Order)))
        assert all(hold.status == "released" for hold in session.scalars(select(StockHold)))


@pytest.mark.parametrize(("response", "expected_state", "expected_hold"), [
    ({"success": 0}, "error", "released"),
    ({"success": 1}, "pending", "active"),
    ({"success": 1, "token": "../bad"}, "pending", "active"),
    ({"success": 1, "token": "valid", "redirect_url": "http://paytech.sn/payment/checkout/valid"}, "pending", "active"),
    ({"success": 1, "token": "valid", "redirect_url": "https://attacker.invalid/"}, "pending", "active"),
])
def test_invalid_provider_response_is_not_reissued_when_outcome_is_ambiguous(client, paytech, response, expected_state, expected_hold):
    paytech[2]["response"] = response
    assert client.post("/api/v1/payments", headers=paytech[0], json={"items": paytech[1]}).status_code == 503
    with get_session_factory()() as session:
        payment = session.scalar(select(Payment))
        assert payment.status == expected_state
        assert payment.provider_creation_state == ("failed" if expected_state == "error" else "uncertain")
        assert all(hold.status == expected_hold for hold in session.scalars(select(StockHold)))


@pytest.mark.parametrize("kind", ["timeout", "network", "json", "redirect"])
def test_transport_failures_safe(client, paytech, monkeypatch, kind):
    import backend.app.services.payments.paytech as module
    monkeypatch.setattr(PayTechProvider, "_request", TRANSPORT_REQUEST)
    def request(*args, **kwargs):
        if kind == "timeout":
            raise TimeoutError(get_settings().paytech_api_secret)
        if kind == "network":
            raise URLError(get_settings().paytech_api_key)
        return nullcontext(SimpleNamespace(status=302 if kind == "redirect" else 200, read=lambda _: b"not json"))
    monkeypatch.setattr(module, "build_opener", lambda *args: SimpleNamespace(open=request))
    with pytest.raises(ProviderError) as captured:
        PayTechProvider(get_settings()).get_payment_status("valid")
    assert get_settings().paytech_api_secret not in str(captured.value)
    assert get_settings().paytech_api_key not in str(captured.value)


def test_status_endpoint_contract_does_not_invent_mapping(client, paytech):
    provider = PayTechProvider(get_settings())
    paytech[2]["response"] = {"undocumented": "response"}
    assert provider.get_payment_status("valid") == {"undocumented": "response"}
    assert paytech[2]["requests"][-1][:2] == ("GET", "payment/get-status?token_payment=valid")
    assert provider.map_status("anything_unknown") == "pending"


def test_production_rejected_and_duplicates_rejected(client, paytech, monkeypatch):
    with pytest.raises(ValueError):
        Settings(_env_file=None, app_env="test", paytech_env="prod")
    monkeypatch.setattr(get_settings(), "app_env", "production")
    with pytest.raises(ProviderError):
        PayTechProvider(get_settings()).require_settings()
    response = client.post("/api/v1/payments/paytech/confirmation", content='{"token":"a","token":"b"}', headers={"Content-Type": "application/json"})
    assert response.status_code == 400
