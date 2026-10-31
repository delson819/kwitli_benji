from datetime import time
import pytest
from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.database import get_session_factory
from backend.app.persistence.models import CookProfile, CookProfileHour, Order, OrderItem, Payment, ServiceAreaConfig, User
from backend.app.repositories.service_areas import SqlAlchemyServiceAreaRepository
from backend.app.repositories.sqlalchemy import SqlAlchemyMarketplaceRepository
from backend.app.services.marketplace import ConflictError, MarketplaceService


PASSWORD = "ZoneMarketTest123!"
DAKAR = (14.7167, -17.4677)
OUTSIDE_ACTIVE_MARKETS = (0.0, 0.0)
SHERBROOKE = (45.4042, -71.8929)


def _register(client, email: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/register", json={
        "email": email, "password": PASSWORD, "first_name": "Test",
    })
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create_restaurant(client, slug: str, location=DAKAR, *, approved=True, hours=False):
    headers = _register(client, f"{slug}@example.co")
    response = client.post("/api/v1/cooks", headers=headers, json={
        "display_name": f"Restaurant {slug}",
        "latitude": location[0], "longitude": location[1],
    })
    assert response.status_code == 201
    cook_id = response.json()["id"]
    with get_session_factory()() as session:
        cook = session.get(CookProfile, cook_id)
        if approved:
            cook.is_verified = True
            cook.approval_status = "approved"
        if hours:
            for weekday in range(7):
                session.add(CookProfileHour(
                    cook_profile_id=cook_id, weekday=weekday, is_closed=False,
                    opens_at=time(0, 0), closes_at=time(23, 59, 59),
                ))
        session.commit()
    dish = client.post("/api/v1/dishes", headers=headers, json={
        "name": "Article de test", "description": "Menu de test", "price": "18000",
        "currency": "COP", "is_active": True,
    })
    assert dish.status_code == 201
    return headers, cook_id, dish.json()["id"]


def _enable_staging_policy(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "staging")
    with get_session_factory()() as session:
        session.add(ServiceAreaConfig(
            area_id="staging-pilot-test", environment="staging", code="XX-PILOT-TEST",
            label="Synthetic staging test market", country_code="XX", country="Exampleland",
            city="Pilot City", center_latitude=14.7167, center_longitude=-17.4677,
            radius_km=30, geometry_type="circle", timezone="Africa/Dakar", locale="fr",
            currency="XOF", distance_unit="km", status="active", version=1,
        ))
        session.commit()


def test_active_area_eligibility_reads_persisted_configuration_by_environment():
    with get_session_factory()() as session:
        session.add(ServiceAreaConfig(
            area_id="stage-test", environment="staging", code="XX-STAGE-TEST",
            label="Synthetic staging market", country_code="XX", country="Exampleland",
            city="Test City", center_latitude=14.7167, center_longitude=-17.4677,
            radius_km=30, geometry_type="circle", timezone="Etc/UTC", locale="en",
            currency="USD", distance_unit="km", status="active", version=1,
        ))
        session.commit()
        repo = SqlAlchemyServiceAreaRepository(session)
        assert repo.contains_active_location(*DAKAR, "staging")
        assert not repo.contains_active_location(*OUTSIDE_ACTIVE_MARKETS, "staging")
        assert not repo.contains_active_location(45.4042, -71.8929, "staging")
        assert not repo.contains_active_location(*DAKAR, "production")


def test_out_of_market_restaurant_registration_is_retained_and_coordinates_are_correctable(client, monkeypatch):
    headers = _register(client, "merchant-location-correction@example.co")
    created = client.post("/api/v1/cooks", headers=headers, json={
        "display_name": "Restaurant à corriger",
        "latitude": SHERBROOKE[0],
        "longitude": SHERBROOKE[1],
    })
    assert created.status_code == 201
    assert created.json()["latitude"] == SHERBROOKE[0]
    assert created.json()["longitude"] == SHERBROOKE[1]
    assert created.json()["is_verified"] is False

    _enable_staging_policy(monkeypatch)
    rejected_from_discovery = client.get(
        f"/api/v1/discover?latitude={SHERBROOKE[0]}&longitude={SHERBROOKE[1]}&radius_km=5"
    )
    assert rejected_from_discovery.status_code == 200
    assert all(item["cook_id"] != created.json()["id"] for item in rejected_from_discovery.json())

    corrected = client.patch("/api/v1/cooks/me", headers=headers, json={
        "latitude": DAKAR[0],
        "longitude": DAKAR[1],
    })
    assert corrected.status_code == 200
    assert corrected.json()["latitude"] == DAKAR[0]
    assert corrected.json()["longitude"] == DAKAR[1]
    with get_session_factory()() as session:
        saved = session.get(CookProfile, created.json()["id"])
        assert saved.approval_status == "pending_review"
        assert saved.is_verified is False

    # Une modification partielle sans coordonnées préserve le point enregistré.
    profile_only = client.patch("/api/v1/cooks/me", headers=headers, json={"bio": "Adresse confirmée"})
    assert profile_only.status_code == 200
    assert profile_only.json()["latitude"] == DAKAR[0]
    assert profile_only.json()["longitude"] == DAKAR[1]


def test_approved_restaurant_location_change_returns_to_review_before_discovery(client, monkeypatch):
    headers, cook_id, dish_id = _create_restaurant(client, "approved-location-change", DAKAR)
    _enable_staging_policy(monkeypatch)
    corrected_location = (14.8, -17.4)

    response = client.patch("/api/v1/cooks/me", headers=headers, json={
        "latitude": corrected_location[0],
        "longitude": corrected_location[1],
    })
    assert response.status_code == 200
    assert response.json()["latitude"] == corrected_location[0]
    assert response.json()["longitude"] == corrected_location[1]
    assert response.json()["is_verified"] is False

    discovered = client.get(
        f"/api/v1/discover?latitude={corrected_location[0]}&longitude={corrected_location[1]}&radius_km=5"
    )
    assert discovered.status_code == 200
    assert all(item["cook_id"] != cook_id or item["dish_id"] != dish_id for item in discovered.json())
    with get_session_factory()() as session:
        saved = session.get(CookProfile, cook_id)
        assert saved.approval_status == "pending_review"
        assert saved.is_verified is False


def test_discovery_and_public_menu_block_out_of_market_restaurant_even_at_its_coordinates(client, monkeypatch):
    _, cook_id, _ = _create_restaurant(client, "out-market-discovery", OUTSIDE_ACTIVE_MARKETS)
    _enable_staging_policy(monkeypatch)

    # Des coordonnées client arbitraires ne rendent pas le commerce éligible.
    response = client.get(
        "/api/v1/discover?latitude=0&longitude=0&radius_km=5&vertical=food_service"
    )
    assert response.status_code == 200
    assert response.json() == []
    assert client.get(f"/api/v1/cooks/{cook_id}/public").status_code == 404
    assert client.get(f"/api/v1/reviews/cooks/{cook_id}").status_code == 404


def test_customer_can_browse_dakar_market_without_a_customer_location_gate(client, monkeypatch):
    _, cook_id, dish_id = _create_restaurant(client, "dakar-market-browse", DAKAR)
    _enable_staging_policy(monkeypatch)

    # L'API ne reçoit pas de preuve de présence physique du client : les coordonnées
    # de recherche servent seulement au tri/distance, tandis que l'éligibilité vient du restaurant.
    response = client.get(
        f"/api/v1/discover?latitude={DAKAR[0]}&longitude={DAKAR[1]}&radius_km=5&vertical=food_service"
    )
    assert response.status_code == 200
    assert any(item["cook_id"] == cook_id and item["dish_id"] == dish_id for item in response.json())
    assert client.get(f"/api/v1/cooks/{cook_id}/public").status_code == 200


@pytest.mark.parametrize("case", ["outside_market", "not_approved", "owner_disabled"])
def test_checkout_rejects_ineligible_restaurant_before_creating_payment(client, monkeypatch, case):
    location = OUTSIDE_ACTIVE_MARKETS if case == "outside_market" else DAKAR
    _, cook_id, dish_id = _create_restaurant(
        client, f"checkout-{case}", location,
        approved=case != "not_approved", hours=True,
    )
    customer_headers = _register(client, f"customer-{case}@example.co")
    if case == "owner_disabled":
        with get_session_factory()() as session:
            owner_id = session.scalar(select(CookProfile.user_id).where(CookProfile.id == cook_id))
            session.get(User, owner_id).is_active = False
            session.commit()
    _enable_staging_policy(monkeypatch)

    response = client.post(
        "/api/v1/payments",
        headers={**customer_headers, "Idempotency-Key": f"zone-test-key-{case}"},
        json={"items": [{"dish_id": dish_id, "quantity": 1}]},
    )
    assert response.status_code == 409
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(Payment.id))) == 0


def test_payment_confirmation_does_not_create_order_if_business_left_active_market(client, monkeypatch):
    _, cook_id, dish_id = _create_restaurant(client, "confirmation-left-market", DAKAR, hours=True)
    customer_headers = _register(client, "customer-confirmation-market@example.co")
    _enable_staging_policy(monkeypatch)
    payment_response = client.post(
        "/api/v1/payments",
        headers={**customer_headers, "Idempotency-Key": "zone-confirmation-key-001"},
        json={"items": [{"dish_id": dish_id, "quantity": 1}]},
    )
    assert payment_response.status_code == 201
    payment = payment_response.json()

    with get_session_factory()() as session:
        cook = session.get(CookProfile, cook_id)
        cook.latitude, cook.longitude = OUTSIDE_ACTIVE_MARKETS
        session.commit()

    from backend.tests.test_mvp import payu_confirmation

    confirmation = client.post(
        "/api/v1/payments/payu/confirmation", data=payu_confirmation(payment)
    )
    assert confirmation.status_code == 200
    # Un rejeu ne transforme pas le paiement bloqué en commande ni en nouvel état.
    replay = client.post(
        "/api/v1/payments/payu/confirmation", data=payu_confirmation(payment)
    )
    assert replay.status_code == 200
    client_payment = client.get(f"/api/v1/payments/{payment['id']}", headers=customer_headers)
    assert client_payment.status_code == 200
    assert client_payment.json()["status"] == "reconcile_required"
    with get_session_factory()() as session:
        stored_payment = session.get(Payment, payment["id"])
        assert stored_payment.status == "reconcile_required"
        assert stored_payment.failure_reason == "restaurant_unavailable_after_payment"
        assert stored_payment.provider_status == "4"
        assert session.scalar(select(func.count(Order.id))) == 0
        assert session.scalar(select(func.count(OrderItem.id))) == 0


def test_admin_cannot_approve_restaurant_outside_active_market(client, monkeypatch):
    _, cook_id, _ = _create_restaurant(
        client, "admin-out-market", OUTSIDE_ACTIVE_MARKETS, approved=False, hours=True,
    )
    _register(client, "zone-admin@example.co")
    with get_session_factory()() as session:
        admin = session.scalar(select(User).where(User.email == "zone-admin@example.co"))
        admin.is_admin = True
        session.commit()
        admin_id = admin.id
    _enable_staging_policy(monkeypatch)

    with get_session_factory()() as session:
        admin = session.get(User, admin_id)
        service = MarketplaceService(SqlAlchemyMarketplaceRepository(session))
        with pytest.raises(ConflictError, match="zone commerciale active"):
            service.decide_admin_restaurant(cook_id, "approve", None, admin)
        assert session.get(CookProfile, cook_id).approval_status == "pending_review"


def test_suspending_zone_blocks_discovery_and_checkout_but_keeps_order_rows(client, monkeypatch):
    headers, cook_id, dish_id = _create_restaurant(client, "suspension-check", DAKAR, hours=True)
    customer_headers = _register(client, "suspension-customer@example.co")
    _enable_staging_policy(monkeypatch)
    with get_session_factory()() as session:
        zone = session.scalar(select(ServiceAreaConfig).where(
            ServiceAreaConfig.environment == "staging",
            ServiceAreaConfig.area_id == "staging-pilot-test",
        ))
        zone.status = "suspended"
        session.commit()

    discover = client.get(
        f"/api/v1/discover?latitude={DAKAR[0]}&longitude={DAKAR[1]}&radius_km=5&vertical=food_service"
    )
    assert all(item["cook_id"] != cook_id for item in discover.json())
    checkout = client.post(
        "/api/v1/payments", headers={**customer_headers, "Idempotency-Key": "suspended-zone-checkout"},
        json={"items": [{"dish_id": dish_id, "quantity": 1}]},
    )
    assert checkout.status_code == 409
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(Order.id))) == 0
