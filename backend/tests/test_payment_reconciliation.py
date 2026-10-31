from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
import sys

import pytest
from sqlalchemy import event as sql_event, func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.core.config import get_settings
from backend.app.core.time import utc_now
from backend.app.database import get_session_factory
from backend.app.persistence.models import Dish, DishAvailability, Order, OrderItem, Payment, StockHold
from backend.app.repositories.sqlalchemy import SqlAlchemyMarketplaceRepository
from backend.app.services.marketplace import ConflictError, NotFoundError
from backend.app.services.payments.payu import PayUPaymentProvider
from backend.app.services.payments.flutterwave import FlutterwaveProvider
from backend.app.services.payments.provider import InvalidProviderConfirmation, ProviderError
from backend.app.services.payments.service import PaymentService
from backend.tests.test_cart_checkout import assert_unified_cart_order
from backend.tests.test_flutterwave import flutterwave, create, event, auth, PATH
from backend.tests.test_paydunya import sandbox, create as create_paydunya


def service(session):
    settings = get_settings()
    return PaymentService(SqlAlchemyMarketplaceRepository(session), PayUPaymentProvider(settings), settings)


def reconcile(payment):
    with get_session_factory()() as session:
        return service(session).reconcile_pending_payment(payment["id"]).status


def expire(payment, state="active"):
    with get_session_factory()() as session:
        for hold in session.scalars(select(StockHold).where(StockHold.payment_id == payment["id"])):
            hold.expires_at = utc_now() - timedelta(minutes=1)
            hold.status = state
        session.commit()


@pytest.mark.parametrize("hold_state", [None, "active", "expired", "released"])
def test_verified_reconciliation_once(client, flutterwave, hold_state):
    payment = create(client, flutterwave)
    if hold_state:
        expire(payment, hold_state)
    flutterwave[2]["override"] = {"status": "successful"}
    with get_session_factory()() as session:
        expirations = {h.id: h.expires_at for h in session.scalars(select(StockHold))}
        # Le prix paye ne doit pas etre remplace par le prix courant du catalogue.
        for dish in session.scalars(select(Dish)):
            dish.price = Decimal(9999)
        session.commit()
    assert reconcile(payment) == "approved"
    assert reconcile(payment) == "approved"
    assert client.post(PATH, json=event(payment), headers=auth()).status_code == 200
    with get_session_factory()() as session:
        order = assert_unified_cart_order(session)
        assert order.total_price == Decimal(14000)
        for hold in session.scalars(select(StockHold)):
            assert hold.status == "consumed" and hold.expires_at == expirations[hold.id]
        for line in flutterwave[1]:
            assert session.get(DishAvailability, line["availability_id"]).remaining_portions == 8 - line["quantity"]


def test_expired_stock_conflict_stays_explicit(client, flutterwave):
    payment = create(client, flutterwave)
    expire(payment)
    flutterwave[2]["override"] = {"status": "successful"}
    with get_session_factory()() as session:
        session.get(DishAvailability, flutterwave[1][-1]["availability_id"]).remaining_portions = 0
        session.commit()
    assert reconcile(payment) == "paid_stock_conflict"
    assert reconcile(payment) == "paid_stock_conflict"
    assert client.post(PATH, json=event(payment), headers=auth()).status_code == 200
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=flutterwave[0]).json()["status"] == "paid_stock_conflict"
    with get_session_factory()() as session:
        assert not list(session.scalars(select(Order)))
        assert not list(session.scalars(select(OrderItem)))
        assert session.get(Payment, payment["id"]).provider_status == "approved"
        assert session.get(DishAvailability, flutterwave[1][0]["availability_id"]).remaining_portions == 8
        assert all(h.status == "expired" for h in session.scalars(select(StockHold)))


@pytest.mark.parametrize("override", [{"amount": 1}, {"currency": "COP"}, {"tx_ref": "wrong"}, {"id": 999}])
def test_verification_mismatch_no_write(client, flutterwave, override):
    payment = create(client, flutterwave)
    expire(payment)
    flutterwave[2]["override"] = {"status": "successful", **override}
    with pytest.raises(InvalidProviderConfirmation):
        reconcile(payment)
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "pending"
        assert not list(session.scalars(select(Order)))
        assert all(a.remaining_portions == 8 for a in session.scalars(select(DishAvailability)))


def test_pending_provider_never_approves(client, flutterwave):
    payment = create(client, flutterwave)
    expire(payment)
    assert reconcile(payment) == "pending"
    with get_session_factory()() as session:
        assert not list(session.scalars(select(Order)))
        assert all(h.status == "active" for h in session.scalars(select(StockHold)))


def test_existing_order_rejected(client, flutterwave):
    payment = create(client, flutterwave)
    flutterwave[2]["override"] = {"status": "successful"}
    assert reconcile(payment) == "approved"
    with get_session_factory()() as session:
        session.get(Payment, payment["id"]).status = "pending"
        session.commit()
    with pytest.raises(ConflictError):
        reconcile(payment)
    with get_session_factory()() as session:
        assert len(list(session.scalars(select(Order)))) == 1
        assert len(list(session.scalars(select(OrderItem)))) == 2


def test_reconciliation_webhook_and_poll_concurrent(client, flutterwave, monkeypatch):
    payment = create(client, flutterwave)
    expire(payment)
    flutterwave[2]["override"] = {"status": "successful"}
    verified = Barrier(3)
    original = FlutterwaveProvider.verify
    def verify(self, *args):
        result = original(self, *args)
        verified.wait(timeout=10)
        return result
    monkeypatch.setattr(FlutterwaveProvider, "verify", verify)
    def run(kind):
        if kind == 0:
            return reconcile(payment)
        if kind == 1:
            assert client.post(PATH, json=event(payment), headers=auth()).status_code == 200
        else:
            assert client.get(f"/api/v1/payments/{payment['id']}", headers=flutterwave[0]).status_code == 200
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, range(3)))
    with get_session_factory()() as session:
        assert_unified_cart_order(session)
        for line in flutterwave[1]:
            assert session.get(DishAvailability, line["availability_id"]).remaining_portions == 8 - line["quantity"]


def test_failure_on_second_line_rolls_back(client, flutterwave):
    payment = create(client, flutterwave)
    expire(payment)
    flutterwave[2]["override"] = {"status": "successful"}
    with get_session_factory()() as session:
        engine = session.get_bind()
    inserted = []
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO order_items"):
            inserted.append(True)
            if len(inserted) == 2:
                raise RuntimeError("Echec ligne test")
    sql_event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="Echec ligne test"):
            reconcile(payment)
    finally:
        sql_event.remove(engine, "before_cursor_execute", fail)
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "pending"
        assert not list(session.scalars(select(Order)))
        assert not list(session.scalars(select(OrderItem)))
        assert all(a.remaining_portions == 8 for a in session.scalars(select(DishAvailability)))
        assert all(h.status == "active" for h in session.scalars(select(StockHold)))
    assert reconcile(payment) == "approved"


def test_other_valid_holds_not_stolen(client, flutterwave):
    payment = create(client, flutterwave)
    expire(payment)
    other = create(client, flutterwave)
    assert other["id"] == payment["id"]
    flutterwave[2]["override"] = {"status": "successful"}
    with get_session_factory()() as session:
        for line in flutterwave[1]:
            session.get(DishAvailability, line["availability_id"]).remaining_portions = line["quantity"]
        session.commit()
    assert reconcile(payment) == "approved"
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "approved"
        assert session.scalar(select(func.count(Payment.id))) == 1


def test_inconsistent_items_need_resolution(client, flutterwave):
    payment = create(client, flutterwave)
    expire(payment)
    flutterwave[2]["override"] = {"status": "successful"}
    with get_session_factory()() as session:
        session.get(Payment, payment["id"]).items[0].amount_in_cents += 200
        session.commit()
    assert reconcile(payment) == "reconcile_required"
    with get_session_factory()() as session:
        assert not list(session.scalars(select(Order)))
        assert all(a.remaining_portions == 8 for a in session.scalars(select(DishAvailability)))


def test_two_reconciliations_concurrent(client, flutterwave):
    payment = create(client, flutterwave)
    expire(payment)
    flutterwave[2]["override"] = {"status": "successful"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda _: reconcile(payment), range(2))) == ["approved", "approved"]
    with get_session_factory()() as session:
        assert_unified_cart_order(session)
        for line in flutterwave[1]:
            assert session.get(DishAvailability, line["availability_id"]).remaining_portions == 8 - line["quantity"]


def test_paydunya_uses_same_expired_hold_reconciliation(client, sandbox):
    payment = create_paydunya(client, sandbox)
    expire(payment)
    sandbox[2]["status"] = "completed"
    assert reconcile(payment) == "approved"
    with get_session_factory()() as session:
        assert_unified_cart_order(session)


def test_missing_payment_rejected(client):
    with get_session_factory()() as session, pytest.raises(NotFoundError):
        service(session).reconcile_pending_payment("missing")


def test_provider_without_server_verification_rejected(client, flutterwave):
    payment = create(client, flutterwave)
    with get_session_factory()() as session:
        session.get(Payment, payment["id"]).provider = "paytech"
        session.commit()
    with pytest.raises(ProviderError, match="Verification serveur indisponible"):
        reconcile(payment)
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "pending"
        assert not list(session.scalars(select(Order)))


def test_payment_changed_during_verification_rejected(client, flutterwave, monkeypatch):
    payment = create(client, flutterwave)
    flutterwave[2]["override"] = {"status": "successful"}
    original = FlutterwaveProvider.verify
    def verify(self, *args):
        result = original(self, *args)
        with get_session_factory()() as session:
            session.get(Payment, payment["id"]).amount_in_cents += 100
            session.commit()
        return result
    monkeypatch.setattr(FlutterwaveProvider, "verify", verify)
    with pytest.raises(InvalidProviderConfirmation):
        reconcile(payment)
    with get_session_factory()() as session:
        assert session.get(Payment, payment["id"]).status == "pending"
        assert not list(session.scalars(select(Order)))
