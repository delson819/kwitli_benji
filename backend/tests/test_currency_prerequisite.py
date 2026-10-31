from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import sys
from uuid import uuid4

import pytest
from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.app.core.currencies import amount_storage_units, sandbox_provider_for, require_currency_environment
from backend.app.core.time import utc_now
from backend.app.database import get_session_factory
from backend.app.persistence.models import Dish, DishAvailability, Payment, StockHold
from backend.app.repositories.sqlalchemy import SqlAlchemyMarketplaceRepository
from backend.tests.test_cart_checkout import cart_fixture
from backend.tests.test_mvp import create_cook_marketplace
from scripts.seed_paydunya_xof import seed_xof


def test_xof_schema_and_cop_unchanged(client):
    cook, _, original, _ = create_cook_marketplace(client)
    payload = {"name": "Yassa DEV", "description": "Test", "price": "4500", "currency": "XOF"}
    result = client.post("/api/v1/dishes", headers=cook, json=payload)
    assert result.status_code == 201
    assert result.json()["currency"] == "XOF"
    assert Decimal(result.json()["price"]) == 4500
    for currency, price in [("EUR", "4500"), ("XOF", "4500.50")]:
        assert client.post("/api/v1/dishes", headers=cook, json={**payload, "currency": currency, "price": price}).status_code == 422
    with get_session_factory()() as session:
        stored = session.get(Dish, original["id"])
        assert stored.currency == "COP" and stored.price == Decimal(original["price"])


def test_mixed_currency_server_cart_rejected_without_holds(client):
    customer, lines = cart_fixture(client)
    with get_session_factory()() as session:
        dish = session.get(Dish, session.get(DishAvailability, lines[1]["availability_id"]).dish_id)
        dish.currency = "XOF"
        session.commit()
    response = client.post("/api/v1/payments", headers=customer, json={"items": lines})
    assert response.status_code == 409
    assert "devise" in response.json()["detail"]
    with get_session_factory()() as session:
        assert not list(session.scalars(select(Payment)))
        assert not list(session.scalars(select(StockHold)))


def test_xof_total_from_persisted_items_and_provider_routing(client):
    customer, lines = cart_fixture(client)
    user_id = client.get("/api/v1/me", headers=customer).json()["user"]["id"]
    with get_session_factory()() as session:
        for line, price in zip(lines, [4500, 5000]):
            dish = session.get(Dish, session.get(DishAvailability, line["availability_id"]).dish_id)
            dish.currency, dish.price = "XOF", Decimal(price)
        session.commit()
    # Sans cles PayDunya, ne jamais envoyer XOF vers PayU ni creer un faux checkout.
    assert client.post("/api/v1/payments", headers=customer, json={"items": lines}).status_code == 503
    assert client.post("/api/v1/payments", headers=customer, json={"items": lines, "amount": 1, "currency": "XOF"}).status_code == 422
    with get_session_factory()() as session:
        assert not list(session.scalars(select(StockHold).where(StockHold.status == "active")))
        now = utc_now()
        payment = SqlAlchemyMarketplaceRepository(session).create_pending_payment_with_hold(
            user_id=user_id, availability_id=lines[0]["availability_id"], quantity=None,
            items=[(line["availability_id"], line["quantity"]) for line in lines],
            payment_id=str(uuid4()), provider_reference=f"TEST{uuid4().hex}",
            expires_at=now + timedelta(minutes=10), checkout_token_hash=uuid4().hex,
            checkout_token_expires_at=now + timedelta(minutes=10), now=now,
            max_active_holds_per_user=3, max_held_portions_per_user=10, required_provider="flutterwave")
        assert payment.currency == "XOF" and payment.provider == "flutterwave"
        assert payment.amount_in_cents == 14000 * 100
        assert sum(line.amount_in_cents for line in payment.items) == payment.amount_in_cents
    assert sandbox_provider_for("COP") == "payu"
    assert sandbox_provider_for("XOF") == "flutterwave"
    assert amount_storage_units(Decimal("4500"), "XOF") == 450000


def test_xof_seed_separate_idempotent_and_dev_only(client, monkeypatch):
    _, _, original, _ = create_cook_marketplace(client)
    with get_session_factory()() as session:
        ids = seed_xof(session, latitude=14.7, longitude=-17.4)
        session.get(DishAvailability, ids[0]).remaining_portions = 7
        session.commit()
        assert seed_xof(session, latitude=14.7, longitude=-17.4) == ids
        assert session.get(DishAvailability, ids[0]).remaining_portions == 7
        assert session.get(Dish, original["id"]).currency == "COP"
        assert session.get(Dish, original["id"]).price == Decimal(original["price"])
        assert len(list(session.scalars(select(Dish).where(Dish.currency == "XOF")))) == 3
        from backend.app.core.config import get_settings
        monkeypatch.setattr(get_settings(), "app_env", "production")
        with pytest.raises(ValueError):
            seed_xof(session, latitude=14.7, longitude=-17.4)
        with pytest.raises(ValueError):
            require_currency_environment("XOF")
        require_currency_environment("COP")


def test_currency_migration_preserves_populated_cop_database(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    url = f"sqlite:///{tmp_path / 'currency.db'}"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "d35c092b1a74")
    engine = create_engine(url)
    # Un parent reference rend la regression SQLite/FK observable.
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id,email,first_name,is_active,can_cook,created_at) VALUES ('u','dev@example.invalid','DEV',1,1,CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO cook_profiles (id,user_id,display_name,latitude,longitude,rating,orders_completed,is_verified,created_at) VALUES ('c','u','DEV',0,0,0,0,0,CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO dishes (id,cook_id,name,description,price,currency,is_active,created_at) VALUES ('d','c','COP legacy','DEV',19000,'COP',1,CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO dish_availabilities (id,dish_id,available_date,start_time,end_time,total_portions,remaining_portions,status,created_at) VALUES ('a','d','2026-09-18','11:00','22:00',8,8,'active',CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO orders (id,customer_id,availability_id,quantity,unit_price,total_price,currency,status,pickup_code,confirmed_at,created_at) VALUES ('o','u','a',1,19000,19000,'COP','confirmed','123456',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO payments (id,user_id,order_id,availability_id,quantity,amount_in_cents,currency,provider,provider_reference,status,created_at,updated_at) VALUES ('p','u','o','a',1,1900000,'COP','payu','COP_LEGACY','approved',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        conn.execute(text("INSERT INTO payment_items (id,payment_id,availability_id,quantity,amount_in_cents,order_id) VALUES ('i','p','a',1,1900000,'o')"))
        conn.execute(text("INSERT INTO stock_holds (id,user_id,availability_id,payment_id,quantity,status,expires_at,created_at) VALUES ('h','u','a','p',1,'consumed',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        original = {table: conn.execute(text(f"SELECT * FROM {table}")).all()
                    for table in ("dishes", "dish_availabilities", "orders", "payments", "payment_items", "stock_holds")}
    command.upgrade(config, "e42b0c61af90")
    with engine.begin() as conn:
        for table, rows in original.items():
            assert conn.execute(text(f"SELECT * FROM {table}")).all() == rows
        assert conn.execute(text("SELECT price,currency FROM dishes WHERE id='d'")).one() == (19000, "COP")
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
    command.downgrade(config, "d35c092b1a74")
    command.upgrade(config, "e42b0c61af90")
    with engine.begin() as conn:
        for table, rows in original.items():
            assert conn.execute(text(f"SELECT * FROM {table}")).all() == rows
        conn.execute(text("INSERT INTO dishes (id,cook_id,name,description,price,currency,is_active,created_at) VALUES ('x','c','XOF DEV','DEV',4500,'XOF',1,CURRENT_TIMESTAMP)"))
    with pytest.raises(RuntimeError, match="XOF"):
        command.downgrade(config, "d35c092b1a74")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT currency FROM dishes WHERE id='x'")).scalar() == "XOF"
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "e42b0c61af90"
    engine.dispose()
