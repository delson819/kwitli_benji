from datetime import time, timedelta

import pytest
from sqlalchemy import func, select


def test_discovery_seed_is_idempotent_but_never_publicly_discoverable(client, monkeypatch):
    from backend.app.core.time import market_datetime_as_utc, market_today
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import Dish, DishAvailability
    from backend.app.persistence.models import CookProfile, User
    from scripts.seed_client_discovery import DEMO_CATEGORY, DEMO_DISHES, DEMO_USER_EMAIL, seed_client_discovery

    fixed_now = market_datetime_as_utc(market_today() + timedelta(days=1), time(15, 0))
    monkeypatch.setattr("backend.app.services.marketplace.utc_now", lambda: fixed_now)

    with get_session_factory()() as session:
        first = seed_client_discovery(
            session,
            client_latitude=4.65,
            client_longitude=-74.06,
            now=fixed_now,
        )
        second = seed_client_discovery(
            session,
            client_latitude=4.65,
            client_longitude=-74.06,
            now=fixed_now,
        )
        dish_count = session.scalar(
            select(func.count(Dish.id)).where(Dish.category == DEMO_CATEGORY)
        )
        availability_count = session.scalar(
            select(func.count(DishAvailability.id))
            .join(Dish, Dish.id == DishAvailability.dish_id)
            .where(Dish.category == DEMO_CATEGORY)
        )
        seeded_dishes = list(
            session.scalars(
                select(Dish)
                .where(Dish.category == DEMO_CATEGORY)
                .order_by(Dish.name)
            )
        )
        seed_cook_id = session.scalar(
            select(CookProfile.id).join(User, User.id == CookProfile.user_id).where(User.email == DEMO_USER_EMAIL)
        )

    assert first == second
    assert dish_count == 3
    assert availability_count == 3
    assert {dish.name for dish in seeded_dishes} == {spec.name for spec in DEMO_DISHES}
    assert all(dish.photo_url for dish in seeded_dishes)
    assert all("recién" not in dish.name and "agotadas" not in dish.name and "del mes" not in dish.name for dish in seeded_dishes)
    for dish in seeded_dishes:
        image_response = client.get(dish.photo_url)
        assert image_response.status_code == 200
        assert image_response.headers["content-type"] == "image/jpeg"

    base_url = "/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5"
    nearby = client.get(f"{base_url}&filter=nearby")
    fresh = client.get(f"{base_url}&filter=fresh")
    low_stock = client.get(f"{base_url}&filter=low_stock")
    featured = client.get(f"{base_url}&filter=new")

    assert nearby.status_code == 200
    assert nearby.json() == []
    assert fresh.json() == []
    assert low_stock.json() == []
    assert featured.json() == []
    assert client.get(f"/api/v1/cooks/{seed_cook_id}/public").status_code == 404


def test_discovery_seed_is_rejected_outside_development_and_test(client, monkeypatch):
    from backend.app.core.config import get_settings
    from backend.app.database import get_session_factory
    from scripts.seed_client_discovery import seed_client_discovery

    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    try:
        with get_session_factory()() as session:
            with pytest.raises(RuntimeError, match="development/test"):
                seed_client_discovery(
                    session,
                    client_latitude=4.65,
                    client_longitude=-74.06,
                )
    finally:
        get_settings.cache_clear()


def test_near_me_visual_seed_is_not_exposed_to_client_discovery(client):
    from backend.app.core.time import market_datetime_as_utc, market_today
    from backend.app.database import get_session_factory
    from scripts.seed_client_discovery import seed_client_discovery

    fixed_now = market_datetime_as_utc(market_today() + timedelta(days=1), time(15, 0))
    with get_session_factory()() as session:
        seed_client_discovery(
            session,
            client_latitude=4.65,
            client_longitude=-74.06,
            now=fixed_now,
            scenario="near-me-three",
        )

    response = client.get(
        "/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=1&filter=nearby"
    )

    assert response.status_code == 200
    assert response.json() == []


def test_home_scroll_seed_is_not_exposed_to_client_discovery(client, monkeypatch):
    from backend.app.core.time import market_datetime_as_utc, market_today
    from backend.app.database import get_session_factory
    from scripts.seed_client_discovery import seed_client_discovery

    fixed_now = market_datetime_as_utc(market_today() + timedelta(days=1), time(15, 0))
    monkeypatch.setattr("backend.app.services.marketplace.utc_now", lambda: fixed_now)
    with get_session_factory()() as session:
        result = seed_client_discovery(
            session,
            client_latitude=4.65,
            client_longitude=-74.06,
            now=fixed_now,
            scenario="home-scroll-six",
        )

    response = client.get(
        "/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=1&filter=nearby"
    )

    assert result.dish_count == 6
    assert response.status_code == 200
    assert response.json() == []
