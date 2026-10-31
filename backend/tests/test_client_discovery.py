from datetime import datetime, time, timedelta, timezone
from math import degrees

from sqlalchemy import update


def _register(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "ClaveSegura123!", "first_name": "Ana"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_listing(
    client,
    slug: str,
    *,
    latitude: float = 4.65,
    longitude: float = -74.06,
) -> tuple[dict, dict]:
    from backend.app.core.time import market_today

    headers = _register(client, f"{slug}@example.co")
    cook = client.post(
        "/api/v1/cooks",
        json={"display_name": f"Cocina {slug}", "latitude": latitude, "longitude": longitude},
        headers=headers,
    )
    assert cook.status_code == 201
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import CookProfile

    with get_session_factory()() as session:
        session.execute(
            update(CookProfile).where(CookProfile.id == cook.json()["id"]).values(
                is_verified=True, approval_status="approved"
            )
        )
        session.commit()
    dish = client.post(
        "/api/v1/dishes",
        json={
            "name": f"Plato {slug}",
            "description": "Preparado en casa.",
            "price": "18000.00",
            "currency": "COP",
        },
        headers=headers,
    )
    assert dish.status_code == 201
    availability = client.post(
        "/api/v1/availabilities",
        json={
            "dish_id": dish.json()["id"],
            "available_date": str(market_today() + timedelta(days=1)),
            "start_time": "11:00:00",
            "end_time": "22:00:00",
            "total_portions": 8,
        },
        headers=headers,
    )
    assert availability.status_code == 201
    return dish.json(), availability.json()


def _discover(client, discovery_filter: str, radius_km: int = 5):
    return client.get(
        f"/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km={radius_km}&filter={discovery_filter}"
    )


def test_nearby_filter_includes_300m_and_exactly_one_km_but_excludes_1_01_km(client):
    latitude_delta_for_one_km = degrees(1 / 6371.0)
    near_dish, _ = _create_listing(
        client,
        "near-300m",
        latitude=4.65 + latitude_delta_for_one_km * 0.3,
    )
    boundary_dish, _ = _create_listing(
        client,
        "near-exact-boundary",
        latitude=4.65 + latitude_delta_for_one_km,
    )
    _far_dish, _ = _create_listing(
        client,
        "far-1-01km",
        latitude=4.65 + latitude_delta_for_one_km * 1.01,
    )

    response = _discover(client, "nearby", radius_km=1)

    assert response.status_code == 200
    assert [item["dish_id"] for item in response.json()] == [
        near_dish["id"],
        boundary_dish["id"],
    ]
    assert [item["distance_km"] for item in response.json()] == [0.3, 1.0]


def test_nearby_filter_includes_exactly_one_km_and_rejects_anything_above():
    from backend.app.services.marketplace import _matches_discovery_filter

    now = datetime.now(timezone.utc)
    assert _matches_discovery_filter("nearby", None, None, 1.0, 1, now)
    assert not _matches_discovery_filter("nearby", None, None, 1.000001, 1, now)
    assert not _matches_discovery_filter("nearby", None, None, 1.5, 1, now)


def test_unverified_business_is_hidden_from_discovery_and_public_profile(client):
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import CookProfile

    dish, _availability = _create_listing(client, "pending-review")
    cook_id = dish["cook_id"]
    with get_session_factory()() as session:
        session.execute(update(CookProfile).where(CookProfile.id == cook_id).values(is_verified=False))
        session.commit()

    base = "/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5"
    response = client.get(base)
    assert response.status_code == 200
    assert all(row["cook_id"] != cook_id for row in response.json())
    assert client.get(f"/api/v1/cooks/{cook_id}/public").status_code == 404

    with get_session_factory()() as session:
        session.execute(update(CookProfile).where(CookProfile.id == cook_id).values(
            is_verified=True, approval_status="approved"
        ))
        session.commit()

    visible = client.get(base)
    assert visible.status_code == 200
    assert any(row["cook_id"] == cook_id for row in visible.json())
    assert client.get(f"/api/v1/cooks/{cook_id}/public").status_code == 200


def test_fresh_filter_includes_10_and_30_minutes_but_excludes_31(client, monkeypatch):
    from backend.app.core.time import market_datetime_as_utc, market_timezone, market_today
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import DishAvailability

    fresh_10, availability_10 = _create_listing(client, "fresh-10")
    fresh_30, availability_30 = _create_listing(client, "fresh-30")
    _stale_31, availability_31 = _create_listing(client, "fresh-31")
    discovery_day = market_today() + timedelta(days=1)
    fixed_now = market_datetime_as_utc(discovery_day, time(12, 0))
    monkeypatch.setattr("backend.app.services.marketplace.utc_now", lambda: fixed_now)

    with get_session_factory()() as session:
        for availability_id, ready_minutes_ago in (
            (availability_10["id"], 10),
            (availability_30["id"], 30),
            (availability_31["id"], 31),
        ):
            ready_at = (fixed_now - timedelta(minutes=ready_minutes_ago)).astimezone(market_timezone())
            session.execute(
                update(DishAvailability)
                .where(DishAvailability.id == availability_id)
                .values(
                    available_date=ready_at.date(),
                    start_time=ready_at.time().replace(tzinfo=None),
                    end_time=time(18, 0),
                )
            )
        session.commit()

    response = _discover(client, "fresh")

    assert response.status_code == 200
    returned_ids = {item["dish_id"] for item in response.json()}
    assert returned_ids == {fresh_10["id"], fresh_30["id"]}
    assert all(item["ready_at"] for item in response.json())


def test_low_stock_filter_includes_one_and_five_only(client):
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import DishAvailability

    listings = {
        stock: _create_listing(client, f"stock-{stock}")
        for stock in (0, 1, 5, 6)
    }
    with get_session_factory()() as session:
        for stock, (_dish, availability) in listings.items():
            session.execute(
                update(DishAvailability)
                .where(DishAvailability.id == availability["id"])
                .values(remaining_portions=stock)
            )
        session.commit()

    response = _discover(client, "low_stock")

    assert response.status_code == 200
    assert {item["remaining_portions"] for item in response.json()} == {1, 5}
    assert {item["dish_id"] for item in response.json()} == {
        listings[1][0]["id"],
        listings[5][0]["id"],
    }


def test_new_filter_supports_all_editorial_types_and_recent_dishes(client, monkeypatch):
    from backend.app.core.time import utc_now
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import Dish

    featured_types = ("new", "dish_of_month", "discovery", "discount")
    featured = {
        featured_type: _create_listing(client, f"featured-{featured_type}")[0]
        for featured_type in featured_types
    }
    recent_dish, _ = _create_listing(client, "recent-unfeatured")
    old_dish, _ = _create_listing(client, "old-unfeatured")
    fixed_now = utc_now()
    monkeypatch.setattr("backend.app.services.marketplace.utc_now", lambda: fixed_now)

    with get_session_factory()() as session:
        for featured_type, dish in featured.items():
            session.execute(
                update(Dish)
                .where(Dish.id == dish["id"])
                .values(featured_type=featured_type, created_at=fixed_now - timedelta(days=30))
            )
        session.execute(
            update(Dish)
            .where(Dish.id == recent_dish["id"])
            .values(featured_type=None, created_at=fixed_now - timedelta(days=1))
        )
        session.execute(
            update(Dish)
            .where(Dish.id == old_dish["id"])
            .values(featured_type=None, created_at=fixed_now - timedelta(days=30))
        )
        session.commit()

    response = _discover(client, "new")

    assert response.status_code == 200
    returned_ids = {item["dish_id"] for item in response.json()}
    assert returned_ids == {dish["id"] for dish in featured.values()} | {recent_dish["id"]}
    assert old_dish["id"] not in returned_ids


def test_discover_accepts_explore_farther_radius_30_km(client):
    dish, _ = _create_listing(client, "explore-30", latitude=4.65 + degrees(27 / 6371.0))

    response = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=30")

    assert response.status_code == 200
    assert [item["dish_id"] for item in response.json()] == [dish["id"]]


def test_filter_without_matching_results_returns_empty_list(client, monkeypatch):
    from backend.app.core.time import as_utc, utc_now

    _create_listing(client, "empty-fresh")
    fixed_now = as_utc(utc_now())
    monkeypatch.setattr("backend.app.services.marketplace.utc_now", lambda: fixed_now)

    response = _discover(client, "fresh")

    assert response.status_code == 200
    assert response.json() == []


def test_internal_seed_category_is_hidden_from_discovery_and_public_profile(client):
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import Dish

    dish, _availability = _create_listing(client, "internal-seed-category")
    with get_session_factory()() as session:
        session.get(Dish, dish["id"]).category = "__kwitli_manual_demo__"
        session.commit()

    response = _discover(client, "nearby")
    assert response.status_code == 200
    assert dish["id"] not in {row["dish_id"] for row in response.json()}

    profile = client.get(f"/api/v1/cooks/{dish['cook_id']}/public")
    assert profile.status_code == 200
    assert all(item["dish_id"] != dish["id"] for item in profile.json()["available_dishes"])
