import hashlib
import secrets
from decimal import Decimal
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from contextlib import nullcontext
from types import SimpleNamespace
from urllib.error import URLError
import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.app.core.config import get_settings
from backend.app.database import get_session_factory
from backend.app.core.time import utc_now
from backend.app.persistence.models import Dish, DishAvailability, Payment, Order, StockHold
from backend.app.services.payments.paydunya import PayDunyaProvider
from backend.app.services.payments.provider import ProviderError
from backend.tests.test_cart_checkout import cart_fixture, assert_unified_cart_order
from backend.tests.test_mvp import register


@pytest.fixture
def sandbox(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "xof_payment_provider", "paydunya")
    for field, value in {
        "paydunya_master_key": secrets.token_hex(24), "paydunya_private_key": "test_private_" + secrets.token_hex(24),
        "paydunya_token": secrets.token_hex(24), "paydunya_test_customer_phone": "000000000",
        "paydunya_test_customer_email": "sandbox@example.invalid", "paydunya_test_customer_password": secrets.token_hex(24),
    }.items():
        monkeypatch.setattr(settings, field, value)
    state = {"invoices": {}, "calls": [], "status": "pending", "amount_override": None, "bad_mode": False,
             "bad_reference": False, "error": None, "success": True, "drop_after_invoice": False}

    def request(self, method, path, payload=None):
        self.require_settings()
        state["calls"].append(path)
        if state["error"]:
            raise ProviderError("PayDunya Sandbox indisponible.")
        if path == "checkout-invoice/create":
            token = "test_" + secrets.token_hex(12)
            state["invoices"][token] = payload
            if state["drop_after_invoice"]:
                state["drop_after_invoice"] = False
                raise ProviderError("PayDunya response lost after invoice creation.")
            return {"response_code": "00", "token": token}
        if path == "softpay/checkout/make-payment":
            assert payload["invoice_token"] in state["invoices"]
            if state["success"] and not state.get("force_pending"):
                state["status"] = "completed"
            return {"success": state["success"]}
        token = path.rsplit("/", 1)[1]
        original = state["invoices"][token]
        return {"response_code": "00", "mode": "live" if state["bad_mode"] else "test",
                "hash": hashlib.sha512(settings.paydunya_master_key.encode()).hexdigest(),
                "status": state["status"], "invoice": {"token": token,
                "total_amount": state["amount_override"] if state["amount_override"] is not None else original["invoice"]["total_amount"]},
                "custom_data": {} if state["bad_reference"] else original["custom_data"]}

    monkeypatch.setattr(PayDunyaProvider, "_request", request)
    customer, lines = cart_fixture(client)
    with get_session_factory()() as session:
        for line, price in zip(lines, [4500, 5000]):
            dish = session.get(Dish, session.get(DishAvailability, line["availability_id"]).dish_id)
            dish.currency, dish.price = "XOF", Decimal(price)
        session.commit()
    return customer, lines, state


def create(client, sandbox, key=None):
    customer, lines, _ = sandbox
    headers = customer if key is None else {**customer, "Idempotency-Key": key}
    response = client.post("/api/v1/payments", headers=headers, json={"items": lines})
    assert response.status_code == 201
    return response.json()


def callback(payment):
    with get_session_factory()() as session:
        token = session.get(Payment, payment["id"]).provider_transaction_id
    return {"data[hash]": hashlib.sha512(get_settings().paydunya_master_key.encode()).hexdigest(),
            "data[invoice][token]": token, "data[status]": "completed"}


def test_invoice_pending_total_reference_and_no_secrets(client, sandbox, caplog):
    payment = create(client, sandbox)
    assert payment["status"] == "pending" and payment["provider"] == "paydunya"
    assert payment["currency"] == "XOF" and payment["amount_in_cents"] == 1400000
    assert payment["checkout_url"] is None
    token, invoice = next(iter(sandbox[2]["invoices"].items()))
    assert invoice["invoice"]["total_amount"] == 14000
    assert invoice["custom_data"]["kwitli_reference"] == payment["provider_reference"]
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).provider_transaction_id == token
    for secret in [get_settings().paydunya_master_key, get_settings().paydunya_private_key,
                   get_settings().paydunya_token, get_settings().paydunya_test_customer_password, token]:
        assert secret not in str(payment) + caplog.text


def test_softpay_server_confirm_and_duplicate_callbacks(client, sandbox):
    payment = create(client, sandbox)
    customer, lines, state = sandbox
    endpoint = f"/api/v1/payments/{payment['id']}/paydunya/test-payment"
    response = client.post(endpoint, headers=customer)
    assert response.status_code == 200 and response.json()["status"] == "approved"
    for _ in range(3):
        assert client.post("/api/v1/payments/paydunya/confirmation", data=callback(payment)).status_code == 200
        assert client.post(endpoint, headers=customer).json()["status"] == "approved"
    assert state["calls"].count("softpay/checkout/make-payment") == 1
    with get_session_factory()() as session:
        assert_unified_cart_order(session)
        assert all(hold.status == "consumed" for hold in session.scalars(select(StockHold)))
        for line in lines:
            assert session.get(DishAvailability, line["availability_id"]).remaining_portions == 8 - line["quantity"]


def test_callback_hash_alone_cannot_approve(client, sandbox):
    payment = create(client, sandbox)
    event = callback(payment)
    assert client.post("/api/v1/payments/paydunya/confirmation", data={**event, "data[hash]": "0" * 128}).status_code == 403
    assert client.post("/api/v1/payments/paydunya/confirmation", data=event).status_code == 200
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=sandbox[0]).json()["status"] == "pending"
    sandbox[2]["status"] = "completed"
    assert client.post("/api/v1/payments/paydunya/confirmation", data=event).status_code == 200
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=sandbox[0]).json()["status"] == "approved"


@pytest.mark.parametrize("field,value", [("amount_override", 1), ("amount_override", "NaN"), ("bad_mode", True),
                                         ("bad_reference", True), ("status", "unrecognized")])
def test_incoherent_confirmation_never_approves(client, sandbox, field, value):
    payment = create(client, sandbox)
    sandbox[2]["status"] = "completed"
    sandbox[2][field] = value
    response = client.post("/api/v1/payments/paydunya/confirmation", data=callback(payment))
    assert response.status_code in {403, 503}
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "pending"
        assert not list(session.scalars(select(Order)))


@pytest.mark.parametrize("status", ["failed", "canceled", "cancelled"])
def test_failure_preserves_stock(client, sandbox, status):
    payment = create(client, sandbox)
    sandbox[2]["status"] = status
    response = client.get(f"/api/v1/payments/{payment['id']}", headers=sandbox[0])
    assert response.status_code == 200 and response.json()["status"] in {"declined", "cancelled"}
    with get_session_factory()() as session:
        assert not list(session.scalars(select(Order)))
        assert all(hold.status == "released" for hold in session.scalars(select(StockHold)))


def test_creation_transport_error_keeps_attempt_pending_for_verification(client, sandbox):
    sandbox[2]["error"] = True
    response = client.post("/api/v1/payments", headers=sandbox[0], json={"items": sandbox[1]})
    assert response.status_code == 503
    with get_session_factory()() as session:
        payment = session.scalar(select(Payment))
        assert payment.status == "pending" and payment.provider_creation_state == "uncertain"
        assert all(hold.status == "active" for hold in session.scalars(select(StockHold)))


def test_test_payment_requires_owner_and_never_trusts_softpay_success(client, sandbox):
    payment = create(client, sandbox)
    endpoint = f"/api/v1/payments/{payment['id']}/paydunya/test-payment"
    assert client.post(endpoint).status_code == 401
    other = register(client, "other-test@example.co", "Other")
    assert client.post(endpoint, headers=other).status_code == 403
    sandbox[2]["success"] = False
    assert client.post(endpoint, headers=sandbox[0]).status_code == 503
    assert client.post(endpoint, headers=sandbox[0]).json()["status"] == "pending"
    assert sandbox[2]["calls"].count("softpay/checkout/make-payment") == 1


@pytest.mark.parametrize("kind", ["timeout", "network", "invalid_json", "redirect", "list"])
def test_transport_errors_are_sanitized(client, monkeypatch, kind):
    settings = get_settings()
    monkeypatch.setattr(settings, "paydunya_master_key", secrets.token_hex(24))
    monkeypatch.setattr(settings, "paydunya_private_key", "test_private_" + secrets.token_hex(24))
    monkeypatch.setattr(settings, "paydunya_token", secrets.token_hex(24))
    def request(*args, **kwargs):
        if kind == "timeout":
            raise TimeoutError(settings.paydunya_master_key)
        if kind == "network":
            raise URLError(settings.paydunya_master_key)
        if kind == "redirect":
            return nullcontext(SimpleNamespace(status=302))
        if kind == "list":
            return nullcontext(SimpleNamespace(status=200, read=lambda _: b"[]"))
        return nullcontext(SimpleNamespace(status=200, read=lambda _: b"invalid"))
    monkeypatch.setattr("backend.app.services.payments.paydunya.build_opener", lambda *args: SimpleNamespace(open=request))
    with pytest.raises(ProviderError) as captured:
        PayDunyaProvider(settings)._request("POST", "checkout-invoice/create", {})
    assert settings.paydunya_master_key not in str(captured.value)


def test_production_disabled(client, sandbox, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    with pytest.raises(ProviderError):
        PayDunyaProvider(get_settings()).require_settings()


def test_concurrent_callbacks_apply_stock_once(client, sandbox):
    payment = create(client, sandbox)
    event = callback(payment)
    sandbox[2]["status"] = "completed"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post("/api/v1/payments/paydunya/confirmation", data=event), range(2)))
    assert all(response.status_code == 200 for response in responses)
    with get_session_factory()() as session:
        assert_unified_cart_order(session)
        for line in sandbox[1]:
            assert session.get(DishAvailability, line["availability_id"]).remaining_portions == 8 - line["quantity"]


def test_softpay_success_still_requires_completed_status(client, sandbox):
    payment = create(client, sandbox)
    sandbox[2]["force_pending"] = True
    response = client.post(f"/api/v1/payments/{payment['id']}/paydunya/test-payment", headers=sandbox[0])
    assert response.status_code == 200 and response.json()["status"] == "pending"
    with get_session_factory()() as session:
        assert not list(session.scalars(select(Order)))


def test_expired_hold_cannot_start_softpay(client, sandbox):
    payment = create(client, sandbox)
    with get_session_factory()() as session:
        for hold in session.scalars(select(StockHold)):
            hold.expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
    assert client.post(f"/api/v1/payments/{payment['id']}/paydunya/test-payment", headers=sandbox[0]).status_code == 409
    assert "softpay/checkout/make-payment" not in sandbox[2]["calls"]


def test_softpay_timeout_does_not_retry_collection(client, sandbox):
    payment = create(client, sandbox)
    sandbox[2]["error"] = True
    endpoint = f"/api/v1/payments/{payment['id']}/paydunya/test-payment"
    assert client.post(endpoint, headers=sandbox[0]).status_code == 503
    sandbox[2]["error"] = None
    assert client.post(endpoint, headers=sandbox[0]).json()["status"] == "pending"
    assert sandbox[2]["calls"].count("softpay/checkout/make-payment") == 1


def test_duplicate_provider_token_rejected_without_exposure(client, sandbox, monkeypatch, caplog):
    payment = create(client, sandbox)
    with get_session_factory()() as session:
        token = session.get(Payment, payment["id"]).provider_transaction_id
    monkeypatch.setattr(PayDunyaProvider, "create_invoice", lambda self, payment: token)
    response = client.post("/api/v1/payments", headers=sandbox[0], json={"items": [sandbox[1][0]]})
    assert response.status_code == 503
    assert token not in response.text + caplog.text
    with get_session_factory()() as session:
        failed = session.scalar(select(Payment).where(Payment.id != payment["id"]))
        assert failed.status == "pending" and failed.provider_creation_state == "uncertain"
        assert all(hold.status == "active" for hold in session.scalars(select(StockHold).where(StockHold.payment_id == failed.id)))


def test_lost_invoice_response_reuses_attempt_and_callback_recovers_token(client, sandbox):
    key = "paydunya-lost-response"
    sandbox[2]["drop_after_invoice"] = True
    first_response = client.post("/api/v1/payments", headers={**sandbox[0], "Idempotency-Key": key},
                                 json={"items": sandbox[1]})
    assert first_response.status_code == 503
    token, invoice = next(iter(sandbox[2]["invoices"].items()))
    reference = invoice["custom_data"]["kwitli_reference"]
    with get_session_factory()() as session:
        payment = session.scalar(select(Payment))
        payment_id = payment.id
        assert payment.provider_transaction_id is None and payment.status == "pending"
    retry = create(client, sandbox, key)
    assert retry["id"] == payment_id and retry["next_action"]["type"] == "wait"
    assert sandbox[2]["calls"].count("checkout-invoice/create") == 1

    sandbox[2]["status"] = "completed"
    callback_payload = {
        "data[hash]": hashlib.sha512(get_settings().paydunya_master_key.encode()).hexdigest(),
        "data[invoice][token]": token,
        "data[custom_data][kwitli_reference]": reference,
    }
    assert client.post("/api/v1/payments/paydunya/confirmation", data=callback_payload).status_code == 200
    with get_session_factory()() as session:
        stored = session.get(Payment, payment_id)
        assert stored.status == "approved" and stored.provider_transaction_id == token
        assert_unified_cart_order(session)
