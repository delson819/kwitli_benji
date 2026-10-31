import sys
from pathlib import Path
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.database import get_session_factory
from backend.app.persistence.models import Order, Payment, DishAvailability, StockHold
from backend.tests.test_flutterwave import flutterwave, create, event, auth
from backend.tests.test_mvp import register


def test_reference_recovery_ownership_and_no_duplicate_effects(client, flutterwave):
    payment = create(client, flutterwave)
    path = "/api/v1/payments/by-tx-ref/" + payment["provider_reference"]
    assert client.get(path).status_code == 401
    stranger = register(client, "stranger-recovery@example.com", "Autre")
    assert client.get(path, headers=stranger).status_code == 404
    assert client.get("/api/v1/payments/by-tx-ref/unknown", headers=flutterwave[0]).status_code == 404
    assert client.get(path, headers=flutterwave[0]).json()["status"] == "pending"
    flutterwave[2]["override"] = {"status": "successful"}
    first = client.get(path, headers=flutterwave[0])
    assert first.status_code == 200
    approved = first.json()
    assert approved["status"] == "approved" and approved["order_id"]

    def snapshot():
        with get_session_factory()() as session:
            return (
                tuple((p.id, p.order_id) for p in session.scalars(select(Payment))),
                tuple(o.id for o in session.scalars(select(Order))),
                tuple((a.id, a.remaining_portions) for a in session.scalars(select(DishAvailability))),
                tuple((h.id, h.status) for h in session.scalars(select(StockHold))),
            )

    before = snapshot()
    for _ in range(2):
        for url in (path, "/api/v1/payments/" + payment["id"]):
            response = client.get(url, headers=flutterwave[0]).json()
            for key in ("id", "order_id", "items", "status", "amount_in_cents", "currency"):
                assert response[key] == approved[key]
    assert client.post("/api/v1/payments/flutterwave/webhook", headers=auth(), json=event(payment)).status_code == 200
    assert snapshot() == before
