from datetime import datetime, time, timezone
from types import SimpleNamespace

from sqlalchemy import select

from backend.app.core.business_hours import is_business_open_at
from backend.app.database import get_session_factory
from backend.app.persistence.models import Payment
from backend.tests.test_mvp import create_cook_marketplace, register


def test_open_status_uses_market_local_weekday_and_half_open_interval():
    schedule = {0: SimpleNamespace(is_closed=False, opens_at=time(10), closes_at=time(20))}
    assert not is_business_open_at(schedule, datetime(2026, 10, 12, 9, 59, tzinfo=timezone.utc), "SN")
    assert is_business_open_at(schedule, datetime(2026, 10, 12, 10, tzinfo=timezone.utc), "SN")
    assert not is_business_open_at(schedule, datetime(2026, 10, 12, 20, tzinfo=timezone.utc), "SN")
    assert not is_business_open_at(schedule, datetime(2026, 10, 13, 12, tzinfo=timezone.utc), "SN")
    assert not is_business_open_at({}, datetime(2026, 10, 12, 12, tzinfo=timezone.utc), "SN")


def test_merchant_can_read_and_save_all_seven_business_days(client):
    merchant, *_ = create_cook_marketplace(client, email="hours-owner@example.co")
    before = client.get("/api/v1/cooks/me/hours", headers=merchant)
    assert before.status_code == 200
    assert len(before.json()) == 7
    assert all(day["is_closed"] for day in before.json()) is False

    days = [
        {"weekday": weekday, "is_closed": weekday == 2,
         "opens_at": None if weekday == 2 else "10:00:00",
         "closes_at": None if weekday == 2 else "20:00:00"}
        for weekday in range(7)
    ]
    saved = client.put("/api/v1/cooks/me/hours", headers=merchant, json={"days": days})
    assert saved.status_code == 200
    assert len(saved.json()) == 7
    assert saved.json()[0]["opens_at"] == "10:00:00"
    assert saved.json()[2]["is_closed"] is True
    assert saved.json()[2]["opens_at"] is None
    assert client.get("/api/v1/cooks/me/hours", headers=merchant).json() == saved.json()


def test_invalid_or_incomplete_business_hours_are_rejected(client):
    merchant, *_ = create_cook_marketplace(client, email="hours-invalid@example.co")
    invalid = [{"weekday": weekday, "is_closed": False, "opens_at": "20:00", "closes_at": "10:00"}
               for weekday in range(7)]
    assert client.put("/api/v1/cooks/me/hours", headers=merchant, json={"days": invalid}).status_code == 422
    assert client.put("/api/v1/cooks/me/hours", headers=merchant, json={"days": invalid[:6]}).status_code == 422


def test_closed_verified_business_stays_visible_but_payment_is_rejected(client):
    merchant, cook, dish, _availability = create_cook_marketplace(client, email="closed-shop@example.co")
    customer = register(client, "closed-customer@example.co", "Client")
    closed_week = [{"weekday": weekday, "is_closed": True, "opens_at": None, "closes_at": None}
                   for weekday in range(7)]
    saved = client.put("/api/v1/cooks/me/hours", headers=merchant, json={"days": closed_week})
    assert saved.status_code == 200

    discovery = client.get("/api/v1/discover", params={"latitude": 4.65, "longitude": -74.06, "radius_km": 5})
    row = next(result for result in discovery.json() if result["dish_id"] == dish["id"])
    assert row["is_open"] is False
    public = client.get(f"/api/v1/cooks/{cook['id']}/public")
    assert public.status_code == 200 and public.json()["is_open"] is False

    response = client.post("/api/v1/payments", headers=customer, json={
        "items": [{"dish_id": dish["id"], "quantity": 2}],
    })
    assert response.status_code == 409
    assert response.json()["detail"] == "Ce restaurant est fermé pour le moment."
    with get_session_factory()() as session:
        assert session.scalar(select(Payment.id)) is None


def test_open_verified_business_allows_active_item_checkout(client):
    merchant, _cook, dish, _availability = create_cook_marketplace(client, email="open-shop@example.co")
    customer = register(client, "open-customer@example.co", "Client")
    discovery = client.get("/api/v1/discover", params={"latitude": 4.65, "longitude": -74.06, "radius_km": 5})
    row = next(result for result in discovery.json() if result["dish_id"] == dish["id"])
    assert row["is_open"] is True
    payment = client.post("/api/v1/payments", headers=customer, json={
        "items": [{"dish_id": dish["id"], "quantity": 2}],
    })
    assert payment.status_code == 201
