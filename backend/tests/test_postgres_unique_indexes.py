from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from backend.app.database import get_session_factory
from backend.app.persistence.models import (
    CookProfile, Dish, DishAvailability, Payment, StockHold, User,
)


def test_migrated_unique_index_definitions_match_postgres_catalog():
    with get_session_factory()() as session:
        definitions = dict(session.execute(text("""
            SELECT indexname, indexdef FROM pg_indexes
            WHERE schemaname = current_schema()
              AND indexname IN ('uq_stock_holds_payment_availability', 'uq_users_email_lower')
        """)).all())
    assert "uq_stock_holds_payment_availability" in definitions
    assert "CREATE UNIQUE INDEX uq_stock_holds_payment_availability" in definitions[
        "uq_stock_holds_payment_availability"
    ]
    assert "(payment_id, availability_id)" in definitions["uq_stock_holds_payment_availability"]
    assert "CREATE UNIQUE INDEX uq_users_email_lower" in definitions["uq_users_email_lower"]
    assert "lower(" in definitions["uq_users_email_lower"]
    assert "email" in definitions["uq_users_email_lower"]


def test_case_insensitive_email_index_rejects_case_variant_directly_in_postgresql():
    with get_session_factory()() as session:
        session.add(User(email="IndexCheck@example.invalid", first_name="First"))
        session.flush()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(User(email="indexcheck@EXAMPLE.invalid", first_name="Second"))
                session.flush()
        assert session.scalar(select(User.id).where(User.email == "IndexCheck@example.invalid")) is not None


def test_stock_hold_unique_index_rejects_duplicate_payment_availability_pair():
    with get_session_factory()() as session:
        user = User(email="hold-index@example.invalid", first_name="Hold")
        session.add(user)
        session.flush()
        cook = CookProfile(
            user_id=user.id, display_name="Temporary business", latitude=0, longitude=0,
        )
        session.add(cook)
        session.flush()
        dish = Dish(
            cook_id=cook.id, name="Temporary item", description="Test",
            price=Decimal("10.00"), currency="COP",
        )
        session.add(dish)
        session.flush()
        availability = DishAvailability(
            dish_id=dish.id, available_date=date.today(), start_time=time(10), end_time=time(11),
            total_portions=2, remaining_portions=2,
        )
        payment = Payment(
            user_id=user.id, quantity=1, amount_in_cents=100, currency="COP",
            provider_reference="unique-index-stock-hold-test",
        )
        session.add_all([availability, payment])
        session.flush()
        session.add(StockHold(
            user_id=user.id, availability_id=availability.id, payment_id=payment.id,
            quantity=1, expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        ))
        session.flush()
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(StockHold(
                    user_id=user.id, availability_id=availability.id, payment_id=payment.id,
                    quantity=1, expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                ))
                session.flush()
