"""Phase schema uniquement : aucune requete provider ni base DEV utilisee."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import sys
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.database import Base
from backend.app.persistence.models import Order, OrderItem, PickupVerification, ORDER_RETRIEVED_STATUSES


PREVIOUS = "e42b0c61af90"
HEAD = "f63a1b82c907"
NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)


def temporary_engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'order-foundation.db'}")

    @sa.event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


def seed_history(engine):
    metadata = sa.MetaData()
    metadata.reflect(engine)
    with engine.begin() as conn:
        conn.execute(metadata.tables["users"].insert(), [
            dict(id=user, email=f"{user}@example.invalid", first_name=user,
                 is_active=True, can_cook=user == "seller", created_at=NOW)
            for user in ("customer", "seller", "other")])
        cook_values = dict(
            id="cook", user_id="seller", display_name="Commerce test", latitude=0, longitude=0,
            rating=0, orders_completed=0, is_verified=False, created_at=NOW)
        if "business_vertical" in metadata.tables["cook_profiles"].c:
            cook_values["business_vertical"] = "food_service"
        conn.execute(metadata.tables["cook_profiles"].insert(), cook_values)
        for currency in ("COP", "XOF"):
            conn.execute(metadata.tables["dishes"].insert(), dict(
                id=currency, cook_id="cook", name="Plat test", description="Test", price=9000,
                currency=currency, is_active=True, created_at=NOW))
            conn.execute(metadata.tables["dish_availabilities"].insert(), dict(
                id=currency, dish_id=currency, available_date=NOW.date(), start_time=NOW.time(),
                end_time=(NOW + timedelta(hours=1)).time(), total_portions=10, remaining_portions=4,
                status="active", created_at=NOW))
            for status in ("confirmed", "ready", "completed", "cancelled"):
                conn.execute(metadata.tables["orders"].insert(), dict(
                    id=f"{currency}-{status}", customer_id="customer", availability_id=currency,
                    quantity=2, unit_price=4500, total_price=9000, currency=currency,
                    status=status, pickup_code="123456", confirmed_at=NOW,
                    completed_at=NOW if status == "completed" else None, created_at=NOW))
        conn.execute(metadata.tables["payments"].insert(), dict(
            id="payment", user_id="customer", order_id="COP-ready", availability_id="COP",
            quantity=4, amount_in_cents=1800000, currency="COP", provider="payu",
            provider_reference="TEST-HISTORY", status="approved", created_at=NOW, updated_at=NOW))
        conn.execute(metadata.tables["dish_availabilities"].insert(), dict(
            id="COP-second", dish_id="COP", available_date=NOW.date(), start_time=NOW.time(),
            end_time=(NOW + timedelta(hours=1)).time(), total_portions=10, remaining_portions=4,
            status="active", created_at=NOW))
        conn.execute(metadata.tables["orders"].update().where(metadata.tables["orders"].c.id == "COP-completed")
                     .values(availability_id="COP-second"))
        # Deux anciennes Orders pour un paiement : ne jamais les fusionner.
        for status in ("ready", "completed"):
            conn.execute(metadata.tables["payment_items"].insert(), dict(
                id=status, payment_id="payment", availability_id="COP" if status == "ready" else "COP-second",
                quantity=2, amount_in_cents=900000, order_id=f"COP-{status}"))
        conn.execute(metadata.tables["stock_holds"].insert(), dict(
            id="hold", user_id="customer", availability_id="COP", payment_id="payment",
            quantity=2, status="consumed", expires_at=NOW, created_at=NOW))
        conn.execute(metadata.tables["reviews"].insert(), dict(
            id="review", order_id="COP-completed", customer_id="customer", cook_id="cook",
            rating=5, created_at=NOW))


def snapshot(engine):
    metadata = sa.MetaData()
    metadata.reflect(engine)
    with engine.connect() as conn:
        return {name: (list(table.columns.keys()), conn.execute(sa.text(f"SELECT * FROM {name} ORDER BY id")).all())
                for name, table in metadata.tables.items() if name != "alembic_version"}


@pytest.fixture(params=["metadata", "migration"])
def schema(request, tmp_path, monkeypatch):
    engine = temporary_engine(tmp_path)
    if request.param == "metadata":
        Base.metadata.create_all(engine)
    else:
        monkeypatch.setenv("ALEMBIC_DATABASE_URL", str(engine.url))
        command.upgrade(Config("alembic.ini"), "head")
    seed_history(engine)
    yield engine
    engine.dispose()


def proof(**changes):
    return dict(id=str(uuid4()), order_id="COP-ready", customer_id="customer", merchant_user_id=None,
                token_hash=sha256(uuid4().bytes).hexdigest(), method="proximity", status="pending",
                created_at=NOW, expires_at=NOW + timedelta(seconds=45), used_at=None) | changes


def test_model_supports_lines_and_legacy_terminals(schema):
    with Session(schema) as session:
        order = session.get(Order, "COP-ready")
        order.items.append(OrderItem(availability_id="COP", dish_id="COP", quantity=3,
                                     unit_price=Decimal("19.99"), line_total=Decimal("59.97"), dish_name="Test"))
        order.items.append(OrderItem(availability_id="COP-second", dish_id="COP", quantity=1,
                                     unit_price=Decimal("20"), line_total=Decimal("20"), dish_name="Test"))
        session.commit()
        assert len(order.items) == 2
        assert order.status == "ready" and order.pickup_code == "123456"
        assert ORDER_RETRIEVED_STATUSES == ("completed", "picked_up")
        assert Order.__table__.c.status.default.arg == "confirmed"


@pytest.mark.parametrize("changes", [
    {"status": "verified", "used_at": NOW},
    {"status": "verified", "merchant_user_id": "seller"},
    {"status": "verified", "merchant_user_id": "seller", "used_at": NOW + timedelta(seconds=45)},
    {"status": "verified", "merchant_user_id": "seller", "used_at": NOW - timedelta(seconds=1)},
    {"used_at": NOW}, {"status": "unknown"}, {"method": "ble"},
    {"token_hash": "short"}, {"expires_at": NOW}, {"customer_id": "other"},
    {"order_id": "missing"}, {"merchant_user_id": "customer"},
])
def test_invalid_verifications_rejected(schema, changes):
    with Session(schema) as session:
        session.add(PickupVerification(**proof(**changes)))
        with pytest.raises(IntegrityError):
            session.commit()


def test_pending_operator_nullable_unique_hash_and_one_verified(schema):
    with Session(schema) as session:
        first = PickupVerification(**proof())
        second = PickupVerification(**proof())
        session.add_all([first, second])
        session.commit()
        assert first.merchant_user_id is None
        session.add(PickupVerification(**proof(token_hash=first.token_hash)))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        first.merchant_user_id, first.used_at, first.status = "seller", NOW, "verified"
        session.commit()
        second.merchant_user_id, second.used_at, second.status = "seller", NOW, "verified"
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize("method", ["proximity", "qr_fallback", "legacy_code"])
def test_pickup_fields_and_same_proof_identity(schema, method):
    with Session(schema) as session:
        order = session.get(Order, "COP-ready")
        order.status = "picked_up"
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        order.status, order.picked_up_at, order.picked_up_by, order.pickup_method = "picked_up", NOW, "seller", method
        if method != "legacy_code":
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
            verification = PickupVerification(**proof(method=method, merchant_user_id="seller", status="verified", used_at=NOW))
            session.add(verification)
            session.flush()
            order.status, order.picked_up_at, order.picked_up_by, order.pickup_method = "picked_up", NOW, "seller", method
            order.pickup_verification_id = verification.id
        session.commit()
        if method != "legacy_code":
            verification_id = order.pickup_verification_id
            other = session.get(Order, "COP-confirmed")
            other.status, other.picked_up_at, other.picked_up_by, other.pickup_method = "picked_up", NOW, "seller", method
            other.pickup_verification_id = verification_id
            with pytest.raises(IntegrityError):
                session.commit()


@pytest.mark.parametrize("changes", [dict(quantity=0), dict(unit_price=0), dict(line_total=0), dict(line_total=99)])
def test_order_item_constraints(schema, changes):
    with Session(schema) as session:
        session.add(OrderItem(**(dict(order_id="COP-ready", availability_id="COP", dish_id="COP",
                                     quantity=2, unit_price=4500, line_total=9000, dish_name="Test") | changes)))
        with pytest.raises(IntegrityError):
            session.commit()


def test_populated_migration_preserves_history_and_links(tmp_path, monkeypatch):
    engine = temporary_engine(tmp_path)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", str(engine.url))
    config = Config("alembic.ini")
    command.upgrade(config, PREVIOUS)
    seed_history(engine)
    original = snapshot(engine)
    command.upgrade(config, HEAD)
    with engine.connect() as conn:
        for name, (columns, rows) in original.items():
            assert conn.execute(sa.text(f"SELECT {','.join(columns)} FROM {name} ORDER BY id")).all() == rows
        assert conn.scalar(sa.text("SELECT COUNT(*) FROM order_items")) == 8
        assert conn.scalar(sa.text("SELECT COUNT(*) FROM orders WHERE cook_id = 'cook'")) == 8
        assert conn.scalar(sa.text("SELECT COUNT(*) FROM pickup_verifications")) == 0
        assert conn.scalar(sa.text("SELECT COUNT(*) FROM orders WHERE pickup_method = 'legacy_code'")) == 2
        assert conn.scalar(sa.text("SELECT COUNT(*) FROM orders WHERE picked_up_by IS NOT NULL")) == 0
        assert conn.scalar(sa.text("SELECT COUNT(*) FROM orders WHERE picked_up_at = completed_at")) == 2
        assert conn.scalar(sa.text("SELECT COUNT(*) FROM order_items WHERE unit_price = 4500 AND line_total = 9000")) == 8
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert conn.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
        assert conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == HEAD
    after = snapshot(engine)
    command.upgrade(config, HEAD)
    assert snapshot(engine) == after
    with pytest.raises(RuntimeError, match="Downgrade refuse"):
        command.downgrade(config, PREVIOUS)
    assert snapshot(engine) == after
    engine.dispose()


def test_invalid_historical_total_stops_migration_without_partial_schema(tmp_path, monkeypatch):
    engine = temporary_engine(tmp_path)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", str(engine.url))
    config = Config("alembic.ini")
    command.upgrade(config, PREVIOUS)
    seed_history(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE orders SET total_price = 100 WHERE id = 'COP-ready'"))
    before = snapshot(engine)
    with pytest.raises(RuntimeError, match="total historique"):
        command.upgrade(config, HEAD)
    assert snapshot(engine) == before
    assert "order_items" not in sa.inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == PREVIOUS
    engine.dispose()
