from pathlib import Path
import sys
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.database import get_session_factory
from backend.app.persistence.models import CookProfile, Order, OrderResolutionRequest, Payment, User
from backend.app.security import create_access_token
from backend.tests.test_cart_checkout import cart_fixture
from backend.tests.test_mvp import payu_confirmation, register


@pytest.fixture
def cart_order(client):
    customer, lines = cart_fixture(client)
    payment = client.post('/api/v1/payments', headers=customer, json={'items': lines}).json()
    assert client.post('/api/v1/payments/payu/confirmation', data=payu_confirmation(payment)).status_code == 200
    with get_session_factory()() as session:
        order = session.scalar(select(Order))
        merchant_user_id = session.get(CookProfile, order.cook_id).user_id
    return {'id': order.id, 'customer': customer, 'merchant': {'Authorization': 'Bearer ' + create_access_token(merchant_user_id)},
            'merchant_id': merchant_user_id}


def test_client_resolution_request_is_justified_idempotently_pending_only(client, cart_order):
    url = f"/api/v1/orders/{cart_order['id']}/resolution-requests"
    assert client.post(url, headers=cart_order['customer'], json={"reason": "other"}).status_code == 422
    payload = {"reason": "other", "description": "Je souhaite demander une annulation."}
    created = client.post(url, headers=cart_order['customer'], json=payload)
    assert created.status_code == 201
    assert created.json()["request_type"] == "client_cancellation"
    assert created.json()["status"] == "submitted"
    assert client.post(url, headers=cart_order['customer'], json=payload).status_code == 409

    outsider = register(client, "resolution-outsider@example.co", "Intrus")
    assert client.post(url, headers=outsider, json=payload).status_code == 403
    assert client.patch(f"/api/v1/orders/{cart_order['id']}/status", headers=cart_order['customer'],
                        json={"status": "in_progress"}).status_code == 403

    detail = client.get(f"/api/v1/orders/{cart_order['id']}", headers=cart_order['customer']).json()
    assert detail["status"] == "ordered"


def test_legacy_confirmed_order_still_uses_cancellation_request(client, cart_order):
    with get_session_factory()() as session:
        order = session.get(Order, cart_order["id"])
        order.status = "confirmed"
        session.commit()
    response = client.post(f"/api/v1/orders/{cart_order['id']}/resolution-requests",
        headers=cart_order["customer"], json={"reason": "other", "description": "Demande avant préparation."})
    assert response.status_code == 201
    assert response.json()["request_type"] == "client_cancellation"
    assert client.get(f"/api/v1/orders/{cart_order['id']}", headers=cart_order["customer"]).json()["status"] == "confirmed"


def test_client_after_acceptance_submits_claim_not_cancellation(client, cart_order):
    url = f"/api/v1/orders/{cart_order['id']}/resolution-requests"
    assert client.patch(f"/api/v1/orders/{cart_order['id']}/status", headers=cart_order['merchant'],
                        json={"status": "in_progress"}).status_code == 200
    response = client.post(url, headers=cart_order['customer'], json={
        "reason": "excessive_delay", "description": "La commande prend beaucoup de retard.",
    })
    assert response.status_code == 201
    assert response.json()["request_type"] == "client_claim"
    assert client.get(f"/api/v1/orders/{cart_order['id']}", headers=cart_order['customer']).json()["status"] == "in_progress"


@pytest.mark.parametrize("target", ["in_progress", "ready", "picked_up", "completed", "cancelled"])
def test_customer_cannot_apply_operational_or_terminal_status(client, cart_order, target):
    response = client.patch(f"/api/v1/orders/{cart_order['id']}/status",
                            headers=cart_order["customer"], json={"status": target})
    assert response.status_code in {403, 422}
    assert client.get(f"/api/v1/orders/{cart_order['id']}", headers=cart_order["customer"]).json()["status"] == "ordered"


@pytest.mark.parametrize("terminal_status", ["picked_up", "completed"])
def test_customer_can_submit_claim_after_retrieval_without_financial_effect(client, cart_order, terminal_status):
    from backend.app.database import get_session_factory

    with get_session_factory()() as session:
        order = session.get(Order, cart_order["id"])
        order.status = terminal_status
        if terminal_status == "picked_up":
            order.picked_up_at = datetime.now(timezone.utc)
            order.picked_up_by = cart_order["merchant_id"]
            order.pickup_method = "legacy_code"
        session.commit()

    response = client.post(f"/api/v1/orders/{cart_order['id']}/resolution-requests",
        headers=cart_order["customer"], json={"reason": "quality_issue", "description": "Je signale un problème."})
    assert response.status_code == 201
    assert response.json()["request_type"] == "client_claim"
    with get_session_factory()() as session:
        order = session.get(Order, cart_order["id"])
        payment = session.scalar(select(Payment).where(Payment.order_id == cart_order["id"]))
        assert order.status == terminal_status
        assert payment.status == "approved" and payment.refunded_at is None


def test_merchant_resolution_requires_ownership_and_never_cancels_directly(client, cart_order):
    url = f"/api/v1/orders/{cart_order['id']}/resolution-requests"
    response = client.post(url, headers=cart_order['merchant'], json={
        "reason": "ingredient_unavailable", "description": "Un ingredient requis est indisponible.",
    })
    assert response.status_code == 201
    assert response.json()["request_type"] == "merchant_cancellation"
    assert client.get(f"/api/v1/orders/{cart_order['id']}", headers=cart_order['customer']).json()["status"] == "ordered"

    other_headers = register(client, "resolution-other-merchant@example.co", "Autre")
    assert client.post(url, headers=other_headers, json={
        "reason": "technical_issue", "description": "Incident technique.",
    }).status_code == 403


def test_admin_decision_is_authorized_audited_and_has_no_automatic_financial_effect(client, cart_order):
    request_response = client.post(f"/api/v1/orders/{cart_order['id']}/resolution-requests",
        headers=cart_order['customer'], json={"reason": "other", "description": "Demande de resolution."})
    request_id = request_response.json()["id"]
    assert client.get("/api/v1/orders/resolution-requests").status_code == 401

    admin_headers = register(client, "resolution-admin@example.co", "Support")
    with get_session_factory()() as session:
        admin = session.scalar(select(User).where(User.email == "resolution-admin@example.co"))
        admin.is_admin = True
        session.commit()
        admin_id = admin.id
    admin_headers = {"Authorization": "Bearer " + create_access_token(admin_id)}

    assert client.get("/api/v1/orders/resolution-requests", headers=cart_order['merchant']).status_code == 403
    listing = client.get("/api/v1/orders/resolution-requests", headers=admin_headers)
    assert listing.status_code == 200 and any(row["id"] == request_id for row in listing.json())

    decision = client.patch(f"/api/v1/orders/resolution-requests/{request_id}/decision", headers=admin_headers,
                            json={"decision": "approved", "note": "Resolution approuvee par le support."})
    assert decision.status_code == 200
    assert decision.json()["reviewed_by"] == admin_id
    assert client.patch(f"/api/v1/orders/resolution-requests/{request_id}/decision", headers=admin_headers,
                        json={"decision": "rejected", "note": "Doublon."}).status_code == 409

    with get_session_factory()() as session:
        order = session.get(Order, cart_order['id'])
        payment = session.scalar(select(Payment).where(Payment.order_id == cart_order['id']))
        resolution = session.get(OrderResolutionRequest, request_id)
        assert order.status == "ordered" and order.cancelled_at is None
        assert payment.status == "approved" and payment.refund_requested_at is None
        assert resolution.status == "approved" and resolution.reviewed_by == admin_id


def test_admin_can_request_resolution_without_changing_order_or_payment(client, cart_order):
    from backend.app.database import get_session_factory

    submitted = client.post(f"/api/v1/orders/{cart_order['id']}/resolution-requests",
        headers=cart_order["customer"], json={"reason": "other", "description": "Merci d'examiner ce cas."})
    admin_headers = register(client, "resolution-followup-admin@example.co", "Support")
    with get_session_factory()() as session:
        admin = session.scalar(select(User).where(User.email == "resolution-followup-admin@example.co"))
        admin.is_admin = True
        session.commit()
        admin_headers = {"Authorization": "Bearer " + create_access_token(admin.id)}

    response = client.patch(f"/api/v1/orders/resolution-requests/{submitted.json()['id']}/decision",
        headers=admin_headers, json={"decision": "request_resolution", "note": "Demander des précisions."})
    assert response.status_code == 200
    assert response.json()["status"] == "resolution_requested"
    with get_session_factory()() as session:
        order = session.get(Order, cart_order["id"])
        payment = session.scalar(select(Payment).where(Payment.order_id == cart_order["id"]))
        assert order.status == "ordered" and order.cancelled_at is None
        assert payment.status == "approved" and payment.refunded_at is None
