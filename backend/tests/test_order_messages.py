"""Acces prive et validation des messages lies a une commande."""
from pathlib import Path
import sys

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.database import get_session_factory
from backend.app.persistence.models import CookProfile, DishAvailability, Order, OrderItem, Payment, PaymentItem
from backend.app.security import create_access_token
from backend.tests.test_cart_checkout import cart_fixture
from backend.tests.test_mvp import create_cook_marketplace, payu_confirmation, register


@pytest.fixture
def message_parties(client):
    customer, lines = cart_fixture(client)
    payment = client.post("/api/v1/payments", headers=customer, json={"items": lines}).json()
    confirmed = client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(payment))
    assert confirmed.status_code == 200
    order = client.get("/api/v1/orders", headers=customer).json()[0]
    with get_session_factory()() as session:
        cook = session.get(CookProfile, order["cook_id"])
        merchant = {"Authorization": "Bearer " + create_access_token(cook.user_id)}
    return {"order_id": order["id"], "customer": customer, "merchant": merchant}


def operational_snapshot(order_id):
    with get_session_factory()() as session:
        order = session.get(Order, order_id)
        availability_ids = session.scalars(select(OrderItem.availability_id).where(OrderItem.order_id == order_id)).all()
        availability = session.scalars(select(DishAvailability).where(DishAvailability.id.in_(availability_ids))).all()
        payments = session.scalars(
            select(Payment).join(PaymentItem, PaymentItem.payment_id == Payment.id)
            .where(PaymentItem.order_id == order_id)
        ).all()
        return (
            order.status,
            tuple(sorted((row.id, row.status) for row in payments)),
            tuple(sorted((row.id, row.remaining_portions) for row in availability)),
        )


def test_order_messages_client_and_merchant_can_read_and_write(client, message_parties):
    order_id = message_parties["order_id"]
    path = f"/api/v1/orders/{order_id}/messages"
    before = operational_snapshot(order_id)
    first = client.post(path, headers=message_parties["customer"], json={"body": "  Bonjour, ma commande est prête ?  "})
    second = client.post(path, headers=message_parties["merchant"], json={"body": "Oui, elle vous attend."})
    assert first.status_code == 201
    assert first.json()["body"] == "Bonjour, ma commande est prête ?"
    assert first.json()["sender_role"] == "customer"
    assert second.status_code == 201 and second.json()["sender_role"] == "merchant"

    messages = client.get(path, headers=message_parties["customer"])
    assert messages.status_code == 200
    assert [message["id"] for message in messages.json()] == [first.json()["id"], second.json()["id"]]
    assert [message["sender_role"] for message in messages.json()] == ["customer", "merchant"]
    assert client.get(path, headers=message_parties["merchant"]).json() == messages.json()
    assert operational_snapshot(order_id) == before


def test_order_messages_reject_another_customer(client, message_parties):
    stranger = register(client, "message-stranger@example.co", "Other")
    path = f"/api/v1/orders/{message_parties['order_id']}/messages"
    assert client.get(path, headers=stranger).status_code == 403
    assert client.post(path, headers=stranger, json={"body": "Bonjour"}).status_code == 403


def test_order_messages_reject_another_merchant(client, message_parties):
    other_merchant, *_ = create_cook_marketplace(
        client, email="other-message-merchant@example.co", name="Other", display_name="Autre commerce"
    )
    path = f"/api/v1/orders/{message_parties['order_id']}/messages"
    assert client.get(path, headers=other_merchant).status_code == 403
    assert client.post(path, headers=other_merchant, json={"body": "Bonjour"}).status_code == 403


@pytest.mark.parametrize("body", ["", "   ", "x" * 1001])
def test_order_messages_reject_empty_or_too_long_body(client, message_parties, body):
    path = f"/api/v1/orders/{message_parties['order_id']}/messages"
    response = client.post(path, headers=message_parties["customer"], json={"body": body})
    assert response.status_code == 422


def test_order_messages_accept_exactly_230_characters(client, message_parties):
    path = f"/api/v1/orders/{message_parties['order_id']}/messages"
    response = client.post(path, headers=message_parties["merchant"], json={"body": "x" * 230})
    assert response.status_code == 201
    assert len(response.json()["body"]) == 230


def test_order_messages_reject_231_characters(client, message_parties):
    path = f"/api/v1/orders/{message_parties['order_id']}/messages"
    response = client.post(path, headers=message_parties["customer"], json={"body": "x" * 231})
    assert response.status_code == 422


def test_order_messages_reject_missing_order(client, message_parties):
    path = "/api/v1/orders/00000000-0000-0000-0000-000000000000/messages"
    assert client.get(path, headers=message_parties["customer"]).status_code == 404


def test_order_messages_returns_only_the_50_most_recent_in_chronological_order(client, message_parties):
    path = f"/api/v1/orders/{message_parties['order_id']}/messages"
    for number in range(55):
        response = client.post(path, headers=message_parties["customer"], json={"body": f"Message {number}"})
        assert response.status_code == 201
    messages = client.get(path, headers=message_parties["customer"]).json()
    assert len(messages) == 50
    assert messages[0]["body"] == "Message 5"
    assert messages[-1]["body"] == "Message 54"
    assert [(row["created_at"], row["id"]) for row in messages] == sorted(
        (row["created_at"], row["id"]) for row in messages
    )
