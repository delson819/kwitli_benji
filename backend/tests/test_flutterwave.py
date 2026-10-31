from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from decimal import Decimal
import json
import secrets
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import get_settings
from backend.app.core.currencies import sandbox_provider_for
from backend.app.database import get_session_factory
from backend.app.persistence.models import Dish, DishAvailability, Payment, StockHold, Order
from backend.app.services.payments.flutterwave import FlutterwaveProvider
from backend.app.services.payments.provider import ProviderError
from backend.tests.test_cart_checkout import cart_fixture, assert_unified_cart_order

PATH = "/api/v1/payments/flutterwave/webhook"
TRANSPORT = FlutterwaveProvider._request


@pytest.fixture
def flutterwave(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "flutterwave_secret_key", "FLWSECK_TEST-" + secrets.token_hex(24))
    monkeypatch.setattr(settings, "flutterwave_webhook_secret", secrets.token_hex(24))
    customer, lines = cart_fixture(client)
    with get_session_factory()() as session:
        for line, price in zip(lines, [4500, 5000]):
            dish = session.get(Dish, session.get(DishAvailability, line["availability_id"]).dish_id)
            dish.currency, dish.price = "XOF", Decimal(price)
        session.commit()
    state = {"requests": [], "transactions": {}, "override": {}, "fail": False,
             "early": False, "action": "callback", "drop_after_charge": False}

    def request(self, method, path, payload=None):
        state["requests"].append((method, path, payload))
        if state["fail"]:
            raise ProviderError("Flutterwave indisponible.")
        if method == "POST":
            identifier = str(len(state["transactions"]) + 101)
            data = {"id": int(identifier), "tx_ref": payload["tx_ref"], "amount": payload["amount"],
                    "currency": "XOF", "status": "pending"}
            state["transactions"][identifier] = data
            if state["drop_after_charge"]:
                state["drop_after_charge"] = False
                raise ProviderError("Flutterwave response lost after charge creation.")
            if state["early"]:
                state["override"] = {"status": "successful"}
                response = client.post(PATH, json={"event": "charge.completed", "data": data}, headers=auth())
                assert response.status_code == 200
            return {"status": "success", "data": data, "meta": {"authorization": {
                "mode": state["action"], "redirect_url": "https://ravesandboxapi.flutterwave.com/authorize"}}}
        identifier = path.split("/")[1] if "verify_by_reference" not in path else next(iter(state["transactions"]))
        return {"status": "success", "data": {**state["transactions"][identifier], **state["override"]}}

    monkeypatch.setattr(FlutterwaveProvider, "_request", request)
    return customer, lines, state


def auth():
    return {"verif-hash": get_settings().flutterwave_webhook_secret}


def create(client, fixture, network="WAVE", key=None):
    headers = fixture[0] if key is None else {**fixture[0], "Idempotency-Key": key}
    response = client.post("/api/v1/payments", headers=headers, json={
        "items": fixture[1], "network": network, "phone_number": "221770000000",
        "return_url": "kwitli://payment-return"})
    assert response.status_code == 201
    return response.json()


def event(payment, identifier=101):
    return {"event": "charge.completed", "data": {"id": identifier, "tx_ref": payment["provider_reference"], "status": "successful"}}


@pytest.mark.parametrize("network", ["WAVE", "ORANGEMONEY"])
def test_request_total_pending_and_secrets(client, flutterwave, network, caplog):
    payment = create(client, flutterwave, network)
    assert sandbox_provider_for("COP") == "payu"
    assert sandbox_provider_for("XOF") == "flutterwave"
    assert payment["provider"] == "flutterwave" and payment["status"] == "pending"
    assert payment["amount_in_cents"] == 1400000 and payment["currency"] == "XOF"
    method, path, body = flutterwave[2]["requests"][0]
    assert (method, path) == ("POST", "charges?type=mobile_money_franco")
    assert body["amount"] == 14000 and body["network"] == network
    assert body["country"] == "SN" and body["currency"] == "XOF" and body["use_qr"] is False
    assert body["phone_number"] == "221770000000" and body["email"]
    assert body["tx_ref"] == payment["provider_reference"]
    parsed_return = urlparse(body["redirect_url"])
    assert parsed_return.scheme == "kwitli" and parsed_return.hostname == "payment-return"
    assert parse_qs(parsed_return.query) == {"payment_id": [payment["id"]]}
    assert payment["next_action"]["type"] == "wait" and payment["checkout_url"] is None
    with get_session_factory()() as session:
        stored = session.get(Payment, payment["id"])
        assert stored.provider_transaction_id == "101" and stored.provider_reference == body["tx_ref"]
    for secret in (get_settings().flutterwave_secret_key, get_settings().flutterwave_webhook_secret):
        assert secret not in json.dumps(payment) + caplog.text


def test_same_intent_reuses_provider_attempt_and_server_only_amount(client, flutterwave):
    get_settings().max_active_holds_per_user = 10
    a = create(client, flutterwave, key="flutterwave-same-intent")
    b = create(client, flutterwave, key="flutterwave-same-intent")
    assert a["id"] == b["id"]
    assert a["provider_reference"] == b["provider_reference"]
    assert len([request for request in flutterwave[2]["requests"] if request[0] == "POST"]) == 1
    assert client.post("/api/v1/payments", headers=flutterwave[0], json={"items": flutterwave[1], "amount": 1}).status_code == 422


def test_flutterwave_redirect_action_is_replayed_without_second_charge(client, flutterwave):
    flutterwave[2]["action"] = "redirect"
    key = "flutterwave-action-replay"
    first = create(client, flutterwave, key=key)
    assert first["next_action"]["type"] == "external"
    replay = create(client, flutterwave, key=key)
    assert replay["id"] == first["id"]
    assert replay["next_action"] == first["next_action"]
    restored = client.get(f"/api/v1/payments/{first['id']}", headers=flutterwave[0])
    assert restored.status_code == 200
    assert restored.json()["next_action"] == first["next_action"]
    assert len([request for request in flutterwave[2]["requests"] if request[0] == "POST"]) == 1


def test_lost_flutterwave_creation_response_is_reconciled_not_reissued(client, flutterwave):
    key = "flutterwave-lost-response"
    flutterwave[2]["drop_after_charge"] = True
    first = create(client, flutterwave, key=key)
    assert first["status"] == "pending" and first["next_action"]["type"] == "wait"
    replay = create(client, flutterwave, key=key)
    assert replay["id"] == first["id"] and replay["next_action"]["type"] == "wait"
    assert len([request for request in flutterwave[2]["requests"] if request[0] == "POST"]) == 1

    flutterwave[2]["override"] = {"status": "successful"}
    verified = client.get(f"/api/v1/payments/{first['id']}", headers=flutterwave[0])
    assert verified.status_code == 200 and verified.json()["status"] == "approved"
    assert len([request for request in flutterwave[2]["requests"] if request[0] == "POST"]) == 1
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(Order.id))) == 1


@pytest.mark.parametrize("return_url", [
    "https://attacker.invalid/payment-return", "javascript:alert(1)",
    "kwitli://other", "kwitli://payment-return?payment_id=forged",
])
def test_invalid_mobile_return_url_rejected(client, flutterwave, return_url):
    response = client.post("/api/v1/payments", headers=flutterwave[0], json={
        "items": flutterwave[1], "network": "WAVE", "phone_number": "221770000000",
        "return_url": return_url})
    assert response.status_code == 503


def test_verified_approval_repeated_concurrent_once(client, flutterwave):
    payment = create(client, flutterwave)
    flutterwave[2]["override"] = {"status": "successful"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(PATH, json=event(payment), headers=auth()), range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert client.post(PATH, json=event(payment), headers=auth()).status_code == 200
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "approved"
        assert_unified_cart_order(session)
        assert all(h.status == "consumed" for h in session.scalars(select(StockHold)))
        for line in flutterwave[1]:
            assert session.get(DishAvailability, line["availability_id"]).remaining_portions == 8 - line["quantity"]


def test_callback_before_creation_response(client, flutterwave):
    flutterwave[2]["early"] = True
    payment = create(client, flutterwave)
    assert payment["status"] == "approved" and payment["next_action"] is None
    with get_session_factory()() as session:
        assert_unified_cart_order(session)


@pytest.mark.parametrize("header", [None, "wrong"])
def test_false_hash_rejected_without_verification(client, flutterwave, header):
    payment = create(client, flutterwave)
    assert client.post(PATH, json=event(payment), headers={} if header is None else {"verif-hash": header}).status_code == 403
    assert len(flutterwave[2]["requests"]) == 1


@pytest.mark.parametrize("override", [{"amount": 1}, {"currency": "COP"}, {"tx_ref": "wrong"}, {"id": 999}, {"status": "invented"}])
def test_wrong_verified_data_rejected(client, flutterwave, override):
    payment = create(client, flutterwave)
    flutterwave[2]["override"] = {"status": "successful", **override}
    assert client.post(PATH, json=event(payment), headers=auth()).status_code == 403
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "pending"
        assert not list(session.scalars(select(Order)))


def test_webhook_claim_not_truth_and_failed_releases(client, flutterwave):
    payment = create(client, flutterwave)
    assert client.post(PATH, json=event(payment), headers=auth()).status_code == 200
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "pending"
    flutterwave[2]["override"] = {"status": "failed"}
    assert client.post(PATH, json=event(payment), headers=auth()).status_code == 200
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "declined"
        assert all(h.status == "released" for h in session.scalars(select(StockHold)))
        assert not list(session.scalars(select(Order)))


def test_uncertain_creation_stays_pending_no_fallback(client, flutterwave):
    flutterwave[2]["fail"] = True
    payment = create(client, flutterwave)
    assert payment["status"] == "pending" and payment["next_action"]["type"] == "wait"
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).failure_reason == "flutterwave_creation_unconfirmed"
        assert all(h.status == "active" for h in session.scalars(select(StockHold)))
    assert len(flutterwave[2]["requests"]) == 1


def test_external_action_and_status_refresh(client, flutterwave):
    flutterwave[2]["action"] = "redirect"
    payment = create(client, flutterwave)
    assert payment["next_action"] == {"type": "external", "url": "https://ravesandboxapi.flutterwave.com/authorize"}
    flutterwave[2]["override"] = {"status": "successful"}
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=flutterwave[0]).json()["status"] == "approved"
    assert client.get(f"/api/v1/payments/{payment['id']}").status_code == 401


def test_reference_reconciliation_after_lost_response(client, flutterwave, monkeypatch):
    original = FlutterwaveProvider._request
    def lost(self, method, path, payload=None):
        response = original(self, method, path, payload)
        if method == "POST":
            raise ProviderError("Reponse perdue.")
        return response
    monkeypatch.setattr(FlutterwaveProvider, "_request", lost)
    payment = create(client, flutterwave)
    flutterwave[2]["override"] = {"status": "successful"}
    response = client.get(f"/api/v1/payments/{payment['id']}", headers=flutterwave[0])
    assert response.status_code == 200 and response.json()["status"] == "approved"
    assert "verify_by_reference?tx_ref=" in flutterwave[2]["requests"][-1][1]


def test_invalid_creation_response_stays_pending(client, flutterwave, monkeypatch):
    monkeypatch.setattr(FlutterwaveProvider, "_request", lambda *args: {"data": {"id": 123, "amount": 1}})
    payment = create(client, flutterwave)
    assert payment["status"] == "pending"
    with get_session_factory()() as session:
        assert not list(session.scalars(select(Order)))


def test_late_failed_event_does_not_reverse_approved(client, flutterwave):
    payment = create(client, flutterwave)
    flutterwave[2]["override"] = {"status": "successful"}
    assert client.post(PATH, headers=auth(), json=event(payment)).status_code == 200
    flutterwave[2]["override"] = {"status": "failed"}
    assert client.post(PATH, headers=auth(), json=event(payment)).status_code == 200
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "approved"
        assert_unified_cart_order(session)


@pytest.mark.parametrize("url", ["http://flutterwave.com", "https://flutterwave.com.evil.invalid", "javascript:alert(1)", "https://localhost"])
def test_unsafe_action_rejected(url):
    with pytest.raises(ProviderError):
        FlutterwaveProvider.next_action({"meta": {"authorization": {"mode": "redirect", "redirect_url": url}}})


@pytest.mark.parametrize("kind", ["timeout", "network", "json", "redirect", "invalid"])
def test_transport_errors_sanitized(client, flutterwave, monkeypatch, kind):
    import backend.app.services.payments.flutterwave as module
    monkeypatch.setattr(FlutterwaveProvider, "_request", TRANSPORT)
    def request(*args, **kwargs):
        if kind == "timeout":
            raise TimeoutError(get_settings().flutterwave_secret_key)
        if kind == "network":
            raise URLError(get_settings().flutterwave_secret_key)
        return nullcontext(SimpleNamespace(status=302 if kind == "redirect" else 200,
                           read=lambda _: b"not json" if kind == "json" else b'{}'))
    monkeypatch.setattr(module, "build_opener", lambda *args: SimpleNamespace(open=request))
    with pytest.raises(ProviderError) as exc:
        FlutterwaveProvider(get_settings()).verify("reference", 10000, "123")
    assert get_settings().flutterwave_secret_key not in str(exc.value)


def test_live_key_and_prod_blocked(client, flutterwave, monkeypatch):
    provider = FlutterwaveProvider(get_settings())
    monkeypatch.setattr(get_settings(), "flutterwave_secret_key", "FLWSECK-" + secrets.token_hex(20))
    with pytest.raises(ProviderError):
        provider.require_settings()
    monkeypatch.setattr(get_settings(), "app_env", "production")
    with pytest.raises(ProviderError):
        provider.require_settings()


def test_invalid_webhook_shape_and_duplicate_keys(client, flutterwave):
    assert client.post(PATH, headers=auth(), content='{"event":"a","event":"b"}').status_code == 400
    assert client.post(PATH, headers=auth(), json={"event": "charge.completed", "data": []}).status_code == 403
    assert client.post(PATH, headers=auth(), content=b"x" * 65537).status_code == 413
