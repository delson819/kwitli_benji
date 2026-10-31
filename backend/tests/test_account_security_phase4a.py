from sqlalchemy import select
from datetime import date, timedelta

from backend.app.database import get_session_factory
from backend.app.persistence.models import User


def test_registration_and_login_normalize_email_case(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "Mixed.Case@Example.com", "password": "KwitliSecure123!", "first_name": "Test"},
    )

    assert response.status_code == 201
    token = response.json()["access_token"]
    profile = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert profile.status_code == 200
    assert profile.json()["user"]["email"] == "mixed.case@example.com"
    assert "password_hash" not in profile.json()["user"]
    assert "is_admin" not in profile.json()["user"]

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "MIXED.CASE@EXAMPLE.COM", "password": "KwitliSecure123!"},
    )
    assert login.status_code == 200

    with get_session_factory()() as session:
        user = session.scalar(select(User).where(User.email == "mixed.case@example.com"))
        assert user is not None
        assert user.password_hash != "KwitliSecure123!"
        assert user.password_hash.startswith("$argon2id$")


def test_registration_rejects_duplicate_email_with_different_case(client):
    first = client.post(
        "/api/v1/auth/register",
        json={"email": "Case.Duplicate@example.com", "password": "KwitliSecure123!", "first_name": "First"},
    )
    duplicate = client.post(
        "/api/v1/auth/register",
        json={"email": "case.duplicate@EXAMPLE.COM", "password": "OtherSecure123!", "first_name": "Second"},
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Un compte utilise deja cette adresse e-mail."}


def test_login_lookup_refuses_every_ambiguous_legacy_casefold_match():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from backend.app.repositories.sqlalchemy import SqlAlchemyMarketplaceRepository

    session = Mock()
    session.scalars.return_value = iter((
        SimpleNamespace(id="legacy-a", email="legacy.case@example.com"),
        SimpleNamespace(id="legacy-b", email="LEGACY.CASE@example.com"),
    ))
    repository = SqlAlchemyMarketplaceRepository(session)

    assert repository.get_user_by_email("legacy.case@example.com") is None
    assert repository.get_user_by_email("Legacy.Case@example.com") is None


def _merchant_inventory(client, email: str):
    registration = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "KwitliSecure123!", "first_name": "Merchant"},
    )
    assert registration.status_code == 201
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    cook = client.post(
        "/api/v1/cooks",
        headers=headers,
        json={"display_name": "Commerce privé", "latitude": 14.7, "longitude": -17.4},
    )
    assert cook.status_code == 201
    dish = client.post(
        "/api/v1/dishes",
        headers=headers,
        json={"name": "Plat privé", "description": "Article de test", "price": "1000", "currency": "XOF"},
    )
    assert dish.status_code == 201
    availability = client.post(
        "/api/v1/availabilities",
        headers=headers,
        json={
            "dish_id": dish.json()["id"],
            "available_date": str(date.today() + timedelta(days=2)),
            "start_time": "11:00:00",
            "end_time": "14:00:00",
            "total_portions": 4,
        },
    )
    assert availability.status_code == 201
    return headers, dish.json()["id"], availability.json()["id"]


def test_catalog_and_inventory_reads_are_authenticated_and_owner_scoped(client):
    owner_headers, dish_id, availability_id = _merchant_inventory(client, "catalog-owner@example.com")
    other_headers, other_dish_id, other_availability_id = _merchant_inventory(client, "catalog-other@example.com")
    customer = client.post(
        "/api/v1/auth/register",
        json={"email": "catalog-customer@example.com", "password": "KwitliSecure123!", "first_name": "Client"},
    )
    customer_headers = {"Authorization": f"Bearer {customer.json()['access_token']}"}

    for path in (
        "/api/v1/dishes",
        f"/api/v1/dishes/{dish_id}",
        "/api/v1/availabilities",
        f"/api/v1/availabilities/{availability_id}",
    ):
        assert client.get(path).status_code == 401

    assert [row["id"] for row in client.get("/api/v1/dishes", headers=owner_headers).json()] == [dish_id]
    assert [row["id"] for row in client.get("/api/v1/availabilities", headers=owner_headers).json()] == [availability_id]
    assert client.get(f"/api/v1/dishes/{dish_id}", headers=owner_headers).status_code == 200
    assert client.get(f"/api/v1/availabilities/{availability_id}", headers=owner_headers).status_code == 200

    assert [row["id"] for row in client.get("/api/v1/dishes", headers=other_headers).json()] == [other_dish_id]
    assert client.get("/api/v1/availabilities", headers=other_headers).json()[0]["id"] == other_availability_id
    assert client.get(f"/api/v1/dishes/{dish_id}", headers=other_headers).status_code == 403
    assert client.get(f"/api/v1/availabilities/{availability_id}", headers=other_headers).status_code == 403
    assert client.get("/api/v1/dishes", headers=customer_headers).status_code == 403
    assert client.get("/api/v1/availabilities", headers=customer_headers).status_code == 403


def test_public_approved_catalog_is_visible_but_management_data_stays_private(client):
    from backend.app.persistence.models import CookProfile

    owner_headers, dish_id, availability_id = _merchant_inventory(client, "public-owner@example.com")
    pending_headers, pending_dish_id, _ = _merchant_inventory(client, "public-pending@example.com")
    customer = client.post(
        "/api/v1/auth/register",
        json={"email": "public-customer@example.com", "password": "KwitliSecure123!", "first_name": "Client"},
    )
    customer_headers = {"Authorization": f"Bearer {customer.json()['access_token']}"}
    admin = client.post(
        "/api/v1/auth/register",
        json={"email": "public-admin@example.com", "password": "KwitliSecure123!", "first_name": "Admin"},
    )
    admin_headers = {"Authorization": f"Bearer {admin.json()['access_token']}"}

    with get_session_factory()() as session:
        owner_cook = session.scalar(select(CookProfile).where(CookProfile.user_id == session.scalar(
            select(User.id).where(User.email == "public-owner@example.com")
        )))
        pending_cook = session.scalar(select(CookProfile).where(CookProfile.user_id == session.scalar(
            select(User.id).where(User.email == "public-pending@example.com")
        )))
        admin_user = session.scalar(select(User).where(User.email == "public-admin@example.com"))
        owner_cook.is_verified = True
        owner_cook.approval_status = "approved"
        # Simule un état incohérent : l'ancien indicateur ne suffit pas à publier.
        pending_cook.is_verified = True
        pending_cook.approval_status = "pending_review"
        admin_user.is_admin = True
        session.commit()
        owner_cook_id = owner_cook.id
        pending_cook_id = pending_cook.id

    inactive = client.post(
        "/api/v1/dishes",
        headers=owner_headers,
        json={
            "name": "Article non publié", "description": "Privé", "price": "900",
            "currency": "XOF", "is_active": False,
        },
    )
    assert inactive.status_code == 201
    inactive_dish_id = inactive.json()["id"]

    # Public commerce content is identical for anonymous and authenticated roles.
    for headers in (None, customer_headers, pending_headers, admin_headers):
        response_headers = headers or {}
        discovery = client.get(
            "/api/v1/discover?latitude=14.7&longitude=-17.4&radius_km=5",
            headers=response_headers,
        )
        assert discovery.status_code == 200
        assert [row["dish_id"] for row in discovery.json()] == [dish_id]
        assert discovery.json()[0]["availability_id"] == availability_id

        profile = client.get(f"/api/v1/cooks/{owner_cook_id}/public", headers=response_headers)
        assert profile.status_code == 200
        body = profile.json()
        assert [(row["dish_id"], row["name"], row["price"]) for row in body["available_dishes"]] == [
            (dish_id, "Plat privé", "1000.00")
        ]
        assert {"user_id", "latitude", "longitude", "email", "phone"}.isdisjoint(body)
        assert body["available_dishes"][0]["availability_id"] is None
        assert "remaining_portions" not in body["available_dishes"][0] or body["available_dishes"][0]["remaining_portions"] is None

    assert client.get(f"/api/v1/cooks/{pending_cook_id}/public").status_code == 404
    pending_discovery = client.get("/api/v1/discover?latitude=14.7&longitude=-17.4&radius_km=5")
    assert all(row["dish_id"] != pending_dish_id for row in pending_discovery.json())

    # Private management endpoints require authentication and the owning merchant.
    for path in ("/api/v1/dishes", "/api/v1/availabilities"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=customer_headers).status_code == 403
        assert client.get(path, headers=admin_headers).status_code == 403
    assert {row["id"] for row in client.get("/api/v1/dishes", headers=owner_headers).json()} == {
        dish_id, inactive_dish_id
    }
    assert [row["id"] for row in client.get("/api/v1/availabilities", headers=owner_headers).json()] == [
        availability_id
    ]
    assert client.get(f"/api/v1/dishes/{dish_id}", headers=pending_headers).status_code == 403
    assert client.get(f"/api/v1/availabilities/{availability_id}", headers=pending_headers).status_code == 403
