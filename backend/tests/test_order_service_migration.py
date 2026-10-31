"""Migration Phase 2 et confirmation de paiements reserves avant son application."""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.persistence.models import Order, OrderItem, Payment, PaymentItem, StockHold, DishAvailability
from backend.app.repositories.sqlalchemy import SqlAlchemyMarketplaceRepository
from backend.tests.test_order_foundation import NOW, seed_history, snapshot, temporary_engine

PHASE1 = "f63a1b82c907"
PHASE2 = "a74d2c93e018"
CURRENT_HEAD = "6d2f81a4c970"


@pytest.fixture
def migrated_history(tmp_path, monkeypatch):
    engine = temporary_engine(tmp_path)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", str(engine.url))
    config = Config("alembic.ini")
    command.upgrade(config, "e42b0c61af90")
    seed_history(engine)
    command.upgrade(config, PHASE1)
    # Construire le paiement avec le schema precedent, sans la colonne order_item_id.
    metadata = sa.MetaData()
    metadata.reflect(engine)
    with engine.begin() as conn:
        conn.execute(metadata.tables["payments"].insert(), dict(
            id="old-pending", user_id="customer", availability_id="COP", quantity=3,
            amount_in_cents=1350000, currency="COP", provider="payu",
            provider_reference="TEST-OLD-PENDING", status="pending", created_at=NOW, updated_at=NOW))
        for availability_id, quantity in (("COP", 2), ("COP-second", 1)):
            conn.execute(metadata.tables["payment_items"].insert(), dict(
                id=f"pending-{availability_id}", payment_id="old-pending", availability_id=availability_id,
                quantity=quantity, amount_in_cents=450000 * quantity))
            conn.execute(metadata.tables["stock_holds"].insert(), dict(
                id=f"pending-{availability_id}", user_id="customer", availability_id=availability_id,
                payment_id="old-pending", quantity=quantity, status="active",
                expires_at=NOW + timedelta(minutes=10), created_at=NOW))
    before = snapshot(engine)
    command.upgrade(config, CURRENT_HEAD)
    yield engine, config, before
    engine.dispose()


def test_phase2_migration_preserves_all_legacy_values_and_is_reversible(migrated_history):
    engine, config, before = migrated_history
    with engine.connect() as conn:
        for table, (columns, rows) in before.items():
            assert conn.execute(sa.text(f"SELECT {','.join(columns)} FROM {table} ORDER BY id")).all() == rows
        assert conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == CURRENT_HEAD
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert conn.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
        assert conn.scalar(sa.text("SELECT COUNT(*) FROM payment_items WHERE order_item_id IS NOT NULL")) == 0
    with Session(engine) as session:
        legacy = session.get(Order, "COP-completed")
        assert legacy.status == "completed" and legacy.pickup_code == "123456"
        assert session.get(PaymentItem, "completed").order_id == legacy.id
        repository = SqlAlchemyMarketplaceRepository(session)
        assert repository.list_orders_for_customer("customer")
        assert repository.list_orders_for_cook("cook")
    command.downgrade(config, PHASE1)
    assert snapshot(engine) == before
    command.upgrade(config, CURRENT_HEAD)


def test_pre_migration_pending_cart_can_confirm_once(migrated_history):
    engine, config, _ = migrated_history
    with Session(engine) as session:
        repository = SqlAlchemyMarketplaceRepository(session)
        payment = repository.get_payment_by_reference_for_update("TEST-OLD-PENDING")
        payment, order = repository.approve_payment_and_create_order(payment, NOW)
        assert order.status == "ordered" and order.total_price == Decimal("13500")
        assert order.customer_id == "customer" and order.cook_id == "cook"
        assert len(order.items) == 2 and sum(item.line_total for item in order.items) == order.total_price
        assert {item.unit_price for item in order.items} == {Decimal("4500")}
        assert all(session.get(OrderItem, line.order_item_id).order_id == order.id for line in payment.items)
        assert all(line.order_id is None for line in payment.items)
        order_id, approved_at = order.id, payment.approved_at
        assert session.scalar(sa.select(sa.func.count(Order.id))) == 9
        assert session.scalar(sa.select(sa.func.count(OrderItem.id))) == 10
        assert session.get(DishAvailability, "COP").remaining_portions == 2
        assert session.get(DishAvailability, "COP-second").remaining_portions == 3
        session.rollback()
        payment = repository.get_payment_by_reference_for_update("TEST-OLD-PENDING")
        payment, repeated = repository.approve_payment_and_create_order(payment, NOW + timedelta(seconds=1))
        assert repeated.id == order_id and payment.approved_at == approved_at.replace(tzinfo=None)
        assert session.scalar(sa.select(sa.func.count(Order.id))) == 9
        assert session.scalar(sa.select(sa.func.count(OrderItem.id))) == 10
        assert all(hold.status == "consumed" for hold in session.scalars(sa.select(StockHold).where(StockHold.payment_id == payment.id)))
    with pytest.raises(RuntimeError, match="Downgrade refuse"):
        command.downgrade(config, PHASE1)
    with engine.connect() as conn:
        assert conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == CURRENT_HEAD
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []


def test_repeated_historical_payment_keeps_multiple_legacy_orders(migrated_history):
    engine, _, _ = migrated_history
    before = snapshot(engine)
    with Session(engine) as session:
        repository = SqlAlchemyMarketplaceRepository(session)
        payment = repository.get_payment_by_reference_for_update("TEST-HISTORY")
        payment, order = repository.approve_payment_and_create_order(payment, NOW)
        assert order.id == "COP-ready"
        assert {line.order_id for line in payment.items} == {"COP-ready", "COP-completed"}
        assert all(line.order_item_id is None for line in payment.items)
    assert snapshot(engine) == before


def test_payment_item_link_enforces_fk_and_uniqueness(migrated_history):
    engine, _, _ = migrated_history
    with Session(engine) as session:
        line = session.get(PaymentItem, "ready")
        line.order_item_id = "unknown"
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        item = session.scalar(sa.select(OrderItem).where(OrderItem.order_id == "COP-ready"))
        line.order_item_id = item.id
        session.commit()
        item_id = item.id
        other = session.get(PaymentItem, "completed")
        other.order_item_id = item_id
        with pytest.raises(IntegrityError):
            session.commit()
