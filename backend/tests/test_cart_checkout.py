from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
import sys

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.app.database import get_session_factory
from backend.app.persistence.models import Dish, DishAvailability, Order, OrderItem, Payment, PaymentItem, StockHold
from backend.tests.test_mvp import create_cook_marketplace, register, payu_confirmation, open_payu_checkout


def cart_fixture(client):
    cook, _, _, first = create_cook_marketplace(client, price="19000.00")
    dish = client.post("/api/v1/dishes", headers=cook, json={
        "name": "Poulet maison", "description": "Cuisine maison", "price": "24000.00", "currency": "COP",
    }).json()
    second = client.post("/api/v1/availabilities", headers=cook, json={
        "dish_id": dish["id"], "available_date": str(date.today() + timedelta(days=1)),
        "start_time": "11:00", "end_time": "22:00", "total_portions": 8,
    }).json()
    customer = register(client, "cart@example.co", "Client")
    lines = [{"availability_id": first["id"], "quantity": 2}, {"availability_id": second["id"], "quantity": 1}]
    return customer, lines


def assert_unified_cart_order(session):
    orders = list(session.scalars(select(Order)))
    assert len(orders) == 1
    order = orders[0]
    assert order.status == "ordered" and order.cook_id is not None
    assert order.availability_id is None and order.quantity is None and order.unit_price is None
    assert order.pickup_code is not None and len(order.pickup_code) == 6
    items = list(session.scalars(select(OrderItem)))
    assert len(items) == 2 and all(item.order_id == order.id for item in items)
    assert order.total_price == sum(item.line_total for item in items)
    payment = session.scalar(select(Payment).where(Payment.order_id == order.id))
    assert payment is not None and payment.status == "approved"
    assert order.total_price * 100 == payment.amount_in_cents
    for line in payment.items:
        item = session.get(OrderItem, line.order_item_id)
        assert item.order_id == order.id and item.availability_id == line.availability_id
        assert item.quantity == line.quantity and item.line_total * 100 == line.amount_in_cents
        assert item.unit_price * item.quantity == item.line_total
        assert line.order_id is None
    return order


def test_cart_total_relay_and_idempotent_approval(client):
    customer, lines = cart_fixture(client)
    response = client.post("/api/v1/payments", headers=customer, json={"items": lines})
    assert response.status_code == 201
    payment = response.json()
    assert payment["amount_in_cents"] == 6200000
    assert len(payment["items"]) == 2
    relay = open_payu_checkout(client, payment["checkout_url"])
    assert relay.status_code == 200
    assert 'name="amount" value="62000.00"' in relay.text
    event = payu_confirmation(payment)
    invalid = {**event, "sign": "0" * 64}
    assert client.post("/api/v1/payments/payu/confirmation", data=invalid).status_code == 403
    first_snapshot = None
    for _ in range(2):
        assert client.post("/api/v1/payments/payu/confirmation", data=event).status_code == 200
        with get_session_factory()() as session:
            order = assert_unified_cart_order(session)
            stored = session.get(Payment, payment["id"])
            snapshot = (order.id, order.created_at, order.confirmed_at, stored.approved_at,
                        tuple(sorted(item.id for item in order.items)))
            if first_snapshot is None:
                first_snapshot = snapshot
            assert snapshot == first_snapshot
    with get_session_factory()() as session:
        assert assert_unified_cart_order(session).total_price == Decimal("62000")
        assert session.get(Payment, payment["id"]).status == "approved"
        assert all(hold.status == "consumed" for hold in session.scalars(select(StockHold)))
        assert all(line.order_item_id for line in session.scalars(select(PaymentItem)))
        for line in lines:
            assert session.get(DishAvailability, line["availability_id"]).remaining_portions == 8 - line["quantity"]


def test_active_dish_checkout_needs_no_availability_and_never_changes_legacy_stock(client):
    cook, _, _, legacy_availability = create_cook_marketplace(client)
    customer = register(client, "no-stock@example.co", "Client")
    active = client.post("/api/v1/dishes", headers=cook, json={
        "name": "Plat sans stock date", "description": "Article du catalogue actif.",
        "price": "24000.00", "currency": "COP", "is_active": True,
    })
    inactive = client.post("/api/v1/dishes", headers=cook, json={
        "name": "Plat non publie", "description": "Article inactif.",
        "price": "12000.00", "currency": "COP", "is_active": False,
    })
    assert active.status_code == inactive.status_code == 201

    discovery = client.get("/api/v1/discover", params={
        "latitude": 4.65, "longitude": -74.06, "radius_km": 5,
    }).json()
    visible_ids = {row["dish_id"] for row in discovery}
    assert active.json()["id"] in visible_ids
    assert inactive.json()["id"] not in visible_ids
    active_row = next(row for row in discovery if row["dish_id"] == active.json()["id"])
    assert active_row["availability_id"] is None
    assert active_row["remaining_portions"] is None

    payment_response = client.post("/api/v1/payments", headers=customer, json={
        "items": [{"dish_id": active.json()["id"], "quantity": 3}],
    })
    assert payment_response.status_code == 201
    payment = payment_response.json()
    assert payment["amount_in_cents"] == 7_200_000
    assert payment["availability_id"] is None
    assert payment["items"] == [{
        "availability_id": None, "dish_id": active.json()["id"],
        "quantity": 3, "amount_in_cents": 7_200_000,
    }]
    assert client.post("/api/v1/payments", headers=customer, json={
        "items": [{"dish_id": inactive.json()["id"], "quantity": 1}],
    }).status_code == 409
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(payment)).status_code == 200

    with get_session_factory()() as session:
        order = session.scalar(select(Order).where(Order.id == payment["order_id"])) if payment.get("order_id") else session.scalar(select(Order))
        assert order is not None and order.quantity == 3 and order.availability_id is None
        assert len(order.items) == 1
        assert order.items[0].availability_id is None
        assert order.items[0].dish_id == active.json()["id"]
        assert order.items[0].quantity == 3
        assert order.items[0].unit_price == Decimal("24000.00")
        assert order.items[0].line_total == Decimal("72000.00")
        assert session.get(DishAvailability, legacy_availability["id"]).remaining_portions == 8
        assert list(session.scalars(select(StockHold))) == []


@pytest.mark.parametrize("state", ["6", "5"])
def test_cart_decline_releases_all_holds_without_orders(client, state):
    customer, lines = cart_fixture(client)
    payment = client.post("/api/v1/payments", headers=customer, json={"items": lines}).json()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(payment, state)).status_code == 200
    assert client.get("/api/v1/orders", headers=customer).json() == []
    with get_session_factory()() as session:
        assert all(hold.status == "released" for hold in session.scalars(select(StockHold)))
        assert all(session.get(DishAvailability, line["availability_id"]).remaining_portions == 8 for line in lines)


def test_cart_invalid_last_line_rolls_back_all_reservations(client):
    customer, lines = cart_fixture(client)
    with get_session_factory()() as session:
        session.get(DishAvailability, lines[1]["availability_id"]).remaining_portions = 0
        session.commit()
    assert client.post("/api/v1/payments", headers=customer, json={"items": lines}).status_code == 409
    with get_session_factory()() as session:
        assert list(session.scalars(select(Payment))) == []
        assert list(session.scalars(select(StockHold))) == []


def test_cart_released_holds_can_approve_a_later_provider_attempt(client):
    customer, lines = cart_fixture(client)
    payment = client.post("/api/v1/payments", headers=customer, json={"items": lines}).json()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(payment, "6")).status_code == 200
    event = payu_confirmation(payment)
    event["transaction_id"] = "another-provider-attempt"
    assert client.post("/api/v1/payments/payu/confirmation", data=event).status_code == 200
    with get_session_factory()() as session:
        assert_unified_cart_order(session)


def test_cart_rejects_multiple_cooks_duplicate_lines_and_client_price(client):
    customer, lines = cart_fixture(client)
    _, _, _, other = create_cook_marketplace(client, email="other@example.co")
    mixed = [lines[0], {"availability_id": other["id"], "quantity": 1}]
    assert client.post("/api/v1/payments", headers=customer, json={"items": mixed}).status_code == 409
    assert client.post("/api/v1/payments", headers=customer, json={"items": [lines[0], lines[0]]}).status_code == 422
    assert client.post("/api/v1/payments", headers=customer, json={"items": lines, "amount_in_cents": 1}).status_code == 422
    assert client.post("/api/v1/payments", headers=customer, json={"items": []}).status_code == 422


def test_cart_late_approval_cannot_partially_consume_stock(client):
    customer, lines = cart_fixture(client)
    payment = client.post("/api/v1/payments", headers=customer, json={"items": lines}).json()
    with get_session_factory()() as session:
        session.get(DishAvailability, lines[1]["availability_id"]).remaining_portions = 0
        session.commit()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(payment)).status_code == 200
    assert client.get("/api/v1/orders", headers=customer).json() == []
    with get_session_factory()() as session:
        assert session.get(DishAvailability, lines[0]["availability_id"]).remaining_portions == 8
        assert session.get(Payment, payment["id"]).status == "error"
        assert not list(session.scalars(select(Order)))
        assert not list(session.scalars(select(OrderItem)))


def test_cart_uses_reserved_prices_not_current_catalog(client):
    customer, lines = cart_fixture(client)
    payment = client.post("/api/v1/payments", headers=customer, json={"items": lines}).json()
    with get_session_factory()() as session:
        for line in lines:
            dish = session.get(Dish, session.get(DishAvailability, line["availability_id"]).dish_id)
            dish.price = Decimal("99999")
        session.commit()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(payment)).status_code == 200
    with get_session_factory()() as session:
        order = assert_unified_cart_order(session)
        assert order.total_price == Decimal("62000")
        assert {item.unit_price for item in order.items} == {Decimal("19000"), Decimal("24000")}
        assert all(item.dish_name for item in order.items)


def test_second_order_item_failure_rolls_back_entire_approval(client):
    from backend.app.core.time import utc_now
    from backend.app.repositories.sqlalchemy import SqlAlchemyMarketplaceRepository
    customer, lines = cart_fixture(client)
    payment = client.post("/api/v1/payments", headers=customer, json={"items": lines}).json()
    factory = get_session_factory()
    engine = factory.kw["bind"]
    inserts = 0

    def fail_second_line(conn, cursor, statement, parameters, context, executemany):
        nonlocal inserts
        if statement.startswith("INSERT INTO order_items"):
            inserts += 1
            if inserts == 2:
                raise RuntimeError("Echec de persistence simule")

    event.listen(engine, "before_cursor_execute", fail_second_line)
    try:
        with factory() as session:
            repository = SqlAlchemyMarketplaceRepository(session)
            stored = repository.get_payment_by_reference_for_update(payment["provider_reference"])
            with pytest.raises(RuntimeError, match="simule"):
                repository.approve_payment_and_create_order(stored, utc_now())
    finally:
        event.remove(engine, "before_cursor_execute", fail_second_line)
    assert inserts == 2
    with factory() as session:
        assert not list(session.scalars(select(Order)))
        assert not list(session.scalars(select(OrderItem)))
        stored = session.get(Payment, payment["id"])
        assert stored.order_id is None and stored.status == "pending" and stored.approved_at is None
        assert all(line.order_item_id is None for line in stored.items)
        assert all(hold.status == "active" for hold in session.scalars(select(StockHold)))
        assert all(session.get(DishAvailability, line["availability_id"]).remaining_portions == 8 for line in lines)
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(payment)).status_code == 200
    with factory() as session:
        assert_unified_cart_order(session)


def test_cart_migration_on_fresh_database_only(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(url)
    inspector = inspect(engine)
    assert "payment_items" in inspector.get_table_names()
    indexes = {index["name"]: index for index in inspector.get_indexes("stock_holds")}
    assert not indexes["ix_stock_holds_payment_id"]["unique"]
    assert indexes["uq_stock_holds_payment_availability"]["unique"]
    engine.dispose()
    command.downgrade(config, "c912d44fd821")
    command.upgrade(config, "head")


def test_business_vertical_migration_backfills_existing_cooks(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path / 'business_vertical.db'}"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "b85e3d04f129")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO users (id, email, password_hash, first_name, is_active, can_cook, created_at) "
            "VALUES ('user-vertical', 'legacy-vertical@example.co', 'hash', 'Legacy', 1, 1, '2026-01-01 00:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO cook_profiles (id, user_id, display_name, rating, orders_completed, latitude, longitude, is_verified, created_at) "
            "VALUES ('cook-vertical', 'user-vertical', 'Legacy Cook', 0, 0, 4.65, -74.06, 0, '2026-01-01 00:00:00')"
        )
    command.upgrade(config, "head")
    with engine.begin() as connection:
        vertical = connection.exec_driver_sql(
            "SELECT business_vertical FROM cook_profiles WHERE id = 'cook-vertical'"
        ).scalar_one()
        assert vertical == "food_service"
        indexes = {row[1] for row in connection.exec_driver_sql("PRAGMA index_list(cook_profiles)")}
        assert "ix_cook_profiles_business_vertical" in indexes
        table_sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'cook_profiles'"
        ).scalar_one()
        assert "ck_cook_profiles_business_vertical" in table_sql
        assert "bakery_dessert" in table_sql and "local_shop" in table_sql
        connection.exec_driver_sql(
            "INSERT INTO users (id, email, password_hash, first_name, is_active, can_cook, created_at) "
            "VALUES ('user-invalid-vertical', 'invalid-vertical@example.co', 'hash', 'Invalid', 1, 1, '2026-01-01 00:00:00')"
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO cook_profiles (id, user_id, display_name, rating, orders_completed, latitude, longitude, is_verified, created_at, business_vertical) "
                "VALUES ('cook-invalid-vertical', 'user-invalid-vertical', 'Invalid Cook', 0, 0, 4.65, -74.06, 0, '2026-01-01 00:00:00', 'invalid')"
            )
    engine.dispose()
