import hashlib
import re
from decimal import Decimal
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import event, select, update


def register(client, email: str, first_name: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": "ClaveSegura123!",
        "first_name": first_name,
    })
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def open_payu_checkout(client, checkout_url: str):
    parsed = urlparse(checkout_url)
    token = parse_qs(parsed.fragment)["token"][0]
    assert client.get(parsed.path).status_code == 200
    return client.post(parsed.path, data={"token": token})


def payu_confirmation(payment: dict, state_pol: str = "4", amount_in_cents: int | None = None) -> dict[str, str]:
    cents = amount_in_cents if amount_in_cents is not None else payment["amount_in_cents"]
    value = Decimal(cents) / 100
    value_text = format(value, ".2f")
    signed_value = format(value, ".1f") if value_text.endswith("0") else value_text
    payload = {"merchant_id": "test-merchant", "reference_sale": payment["provider_reference"], "value": value_text,
               "currency": payment["currency"], "state_pol": state_pol, "transaction_id": f"txn-{payment['id']}"}
    payload["sign"] = hashlib.sha256(
        f"test-api-key~{payload['merchant_id']}~{payload['reference_sale']}~{signed_value}~{payload['currency']}~{state_pol}".encode()
    ).hexdigest()
    return payload


def create_paid_order(client, customer_headers: dict[str, str], availability_id: str, quantity: int = 1) -> dict:
    payment = client.post("/api/v1/payments", json={"availability_id": availability_id, "quantity": quantity}, headers=customer_headers)
    assert payment.status_code == 201
    event = payu_confirmation(payment.json())
    assert client.post("/api/v1/payments/payu/confirmation", data=event).status_code == 200
    orders = client.get("/api/v1/orders", headers=customer_headers)
    order_id = next(item["id"] for item in orders.json() if item["availability_id"] == availability_id)
    return client.get(f"/api/v1/orders/{order_id}", headers=customer_headers).json()


def create_cook_marketplace(
    client,
    *,
    email="cocinera@example.co",
    name="Ana",
    display_name="Ana Cocina",
    latitude=4.65,
    longitude=-74.06,
    price="25000.00",
):
    cook_headers = register(client, email, name)
    cook = client.post("/api/v1/cooks", json={"display_name": display_name, "latitude": latitude, "longitude": longitude}, headers=cook_headers)
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
    hours_response = client.put("/api/v1/cooks/me/hours", headers=cook_headers, json={"days": [
        {"weekday": weekday, "is_closed": False, "opens_at": "00:00:00", "closes_at": "23:59:59.999999"}
        for weekday in range(7)
    ]})
    assert hours_response.status_code == 200
    dish = client.post("/api/v1/dishes", json={
        "name": "Ajiaco santafereño", "description": "Preparado en casa.",
        "price": price, "currency": "COP", "category": "Almuerzo",
    }, headers=cook_headers)
    assert dish.status_code == 201
    availability = client.post("/api/v1/availabilities", json={
        "dish_id": dish.json()["id"], "available_date": str(date.today() + timedelta(days=1)),
        "start_time": "11:00:00", "end_time": "22:00:00", "total_portions": 8,
    }, headers=cook_headers)
    assert availability.status_code == 201
    return cook_headers, cook.json(), dish.json(), availability.json()


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["storage_backend"] == "postgresql"


def test_register_login_and_me(client):
    headers = register(client, "cliente@example.co", "Luisa")
    me = client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "cliente@example.co"
    assert me.json()["cook_profile"] is None

    login = client.post("/api/v1/auth/login", json={"email": "cliente@example.co", "password": "ClaveSegura123!"})
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_protected_route_requires_token(client):
    response = client.post("/api/v1/dishes", json={
        "name": "Ajiaco santafereño", "description": "Preparado en casa.", "price": "25000.00",
    })
    assert response.status_code == 401


def test_cook_profile_and_dish_use_connected_user(client):
    headers = register(client, "cocinera@example.co", "Ana")
    profile = client.post("/api/v1/cooks", json={"display_name": "Ana Cocina", "latitude": 4.65, "longitude": -74.06}, headers=headers)
    assert profile.status_code == 201
    assert profile.json()["business_vertical"] == "food_service"
    assert client.get("/api/v1/me", headers=headers).json()["cook_profile"]["business_vertical"] == "food_service"

    dish = client.post("/api/v1/dishes", json={
        "name": "Ajiaco santafereño", "description": "Preparado en casa.", "price": "25000.00",
    }, headers=headers)
    assert dish.status_code == 201
    assert dish.json()["cook_id"] == profile.json()["id"]


def test_cook_profile_supports_business_vertical_create_update_and_rejects_invalid(client):
    headers = register(client, "vertical-cook@example.co", "Ana")
    created = client.post("/api/v1/cooks", json={
        "display_name": "Boulangerie Fatou",
        "latitude": 4.65,
        "longitude": -74.06,
        "business_vertical": "bakery_dessert",
    }, headers=headers)
    assert created.status_code == 201
    assert created.json()["business_vertical"] == "bakery_dessert"

    updated = client.patch("/api/v1/cooks/me", json={"business_vertical": "local_shop"}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["business_vertical"] == "local_shop"

    invalid = client.patch("/api/v1/cooks/me", json={"business_vertical": "restaurant_only"}, headers=headers)
    assert invalid.status_code == 422


def test_dish_publication_creates_active_availability_with_initial_stock(client):
    headers = register(client, "publish-dish@example.co", "Ana")
    assert client.post(
        "/api/v1/cooks",
        json={"display_name": "Ana Cocina", "latitude": 4.65, "longitude": -74.06},
        headers=headers,
    ).status_code == 201

    publication = client.post(
        "/api/v1/dishes/with-availability",
        json={
            "name": "Pollo con arroz",
            "description": "Pollo con arroz casero",
            "price": "18000",
            "currency": "COP",
            "available_date": str(date.today() + timedelta(days=1)),
            "start_time": "11:00:00",
            "end_time": "14:00:00",
            "total_portions": 5,
        },
        headers=headers,
    )

    assert publication.status_code == 201
    payload = publication.json()
    assert payload["dish"]["name"] == "Pollo con arroz"
    assert payload["availability"]["dish_id"] == payload["dish"]["id"]
    assert payload["availability"]["total_portions"] == 5
    assert payload["availability"]["remaining_portions"] == 5
    assert payload["availability"]["status"] == "active"
    assert len(client.get("/api/v1/dishes", headers=headers).json()) == 1
    assert len(client.get("/api/v1/availabilities", headers=headers).json()) == 1


def test_dish_publication_rejects_invalid_price_or_portions_without_creating_a_dish(client):
    headers = register(client, "invalid-publish@example.co", "Ana")
    assert client.post(
        "/api/v1/cooks",
        json={"display_name": "Ana Cocina", "latitude": 4.65, "longitude": -74.06},
        headers=headers,
    ).status_code == 201
    base_payload = {
        "name": "Pollo con arroz",
        "description": "Pollo con arroz casero",
        "price": "18000",
        "currency": "COP",
        "available_date": str(date.today() + timedelta(days=1)),
        "start_time": "11:00:00",
        "end_time": "14:00:00",
        "total_portions": 5,
    }

    invalid_portions = client.post("/api/v1/dishes/with-availability", json={**base_payload, "total_portions": 0}, headers=headers)
    invalid_price = client.post("/api/v1/dishes/with-availability", json={**base_payload, "price": "0"}, headers=headers)
    invalid_window = client.post("/api/v1/dishes/with-availability", json={**base_payload, "start_time": "14:00:00", "end_time": "11:00:00"}, headers=headers)

    assert invalid_portions.status_code == 422
    assert invalid_price.status_code == 422
    assert invalid_window.status_code == 422
    assert client.get("/api/v1/dishes", headers=headers).json() == []
    assert client.get("/api/v1/availabilities", headers=headers).json() == []


def test_dish_publication_requires_a_cook_profile(client):
    headers = register(client, "customer-publish@example.co", "Luisa")
    response = client.post(
        "/api/v1/dishes/with-availability",
        json={
            "name": "Pollo con arroz",
            "description": "Pollo con arroz casero",
            "price": "18000",
            "currency": "COP",
            "available_date": str(date.today() + timedelta(days=1)),
            "start_time": "11:00:00",
            "end_time": "14:00:00",
            "total_portions": 5,
        },
        headers=headers,
    )

    assert response.status_code == 403


def test_cook_can_update_own_pickup_coordinates(client):
    headers = register(client, "pickup-cook@example.co", "Ana")
    created = client.post(
        "/api/v1/cooks",
        json={"display_name": "Ana Cocina", "latitude": 4.65, "longitude": -74.06},
        headers=headers,
    )
    assert created.status_code == 201

    updated = client.patch(
        "/api/v1/cooks/me",
        json={"latitude": 4.651, "longitude": -74.061},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["latitude"] == 4.651
    assert updated.json()["longitude"] == -74.061


def test_customer_without_cook_profile_cannot_create_dish(client):
    headers = register(client, "cliente@example.co", "Luisa")
    response = client.post("/api/v1/dishes", json={
        "name": "Ajiaco santafereño", "description": "Preparado en casa.", "price": "25000.00",
    }, headers=headers)
    assert response.status_code == 403


def test_connected_customer_order_decrements_stock(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "cliente@example.co", "Luisa")
    customer = client.get("/api/v1/me", headers=customer_headers).json()["user"]

    order = create_paid_order(client, customer_headers, availability["id"])
    assert order["customer_id"] == customer["id"]

    updated = client.get(f"/api/v1/availabilities/{availability['id']}", headers=_cook_headers)
    assert updated.status_code == 200
    assert updated.json()["remaining_portions"] == 7


def test_order_payload_cannot_impersonate_another_user(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "cliente@example.co", "Luisa")
    response = create_paid_order(client, customer_headers, availability["id"])
    assert response["customer_id"] != "00000000-0000-0000-0000-000000000000"


def test_cook_can_upload_valid_image_for_own_dish(client, image_bytes):
    headers, _cook, dish, _availability = create_cook_marketplace(client)
    response = client.post(
        f"/api/v1/dishes/{dish['id']}/photo",
        headers=headers,
        files={"image": ("ajiaco.jpg", image_bytes("JPEG"), "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["photo_url"].startswith("/uploads/")
    served_image = client.get(response.json()["photo_url"])
    assert served_image.status_code == 200
    assert served_image.content.startswith(b"\xff\xd8\xff")


def test_upload_rejects_non_image(client):
    headers, _cook, dish, _availability = create_cook_marketplace(client)
    response = client.post(
        f"/api/v1/dishes/{dish['id']}/photo",
        headers=headers,
        files={"image": ("notes.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 415


def test_merchant_can_update_own_dish_and_availability(client):
    headers, _cook, dish, availability = create_cook_marketplace(client)

    updated_dish = client.patch(
        f"/api/v1/dishes/{dish['id']}",
        json={
            "name": "Ajiaco maison",
            "description": "Recette familiale mise a jour.",
            "price": "26000.00",
            "category": "Specialites",
            "is_active": False,
        },
        headers=headers,
    )
    assert updated_dish.status_code == 200
    assert updated_dish.json()["id"] == dish["id"]
    assert updated_dish.json()["name"] == "Ajiaco maison"
    assert updated_dish.json()["description"] == "Recette familiale mise a jour."
    assert updated_dish.json()["price"] == "26000.00"
    assert updated_dish.json()["category"] == "Specialites"
    assert updated_dish.json()["is_active"] is False
    assert updated_dish.json()["currency"] == "COP"

    next_date = str(date.today() + timedelta(days=2))
    updated_availability = client.patch(
        f"/api/v1/availabilities/{availability['id']}",
        json={
            "available_date": next_date,
            "start_time": "12:00:00",
            "end_time": "23:00:00",
            "total_portions": 5,
            "remaining_portions": 3,
            "status": "inactive",
        },
        headers=headers,
    )
    assert updated_availability.status_code == 200
    assert updated_availability.json()["id"] == availability["id"]
    assert updated_availability.json()["available_date"] == next_date
    assert updated_availability.json()["remaining_portions"] == 3
    assert updated_availability.json()["total_portions"] == 5
    assert updated_availability.json()["status"] == "inactive"

    article_reactivated = client.patch(f"/api/v1/dishes/{dish['id']}", json={"is_active": True}, headers=headers)
    assert article_reactivated.status_code == 200
    assert article_reactivated.json()["is_active"] is True
    availability_after_article_toggle = client.get(f"/api/v1/availabilities/{availability['id']}", headers=headers).json()
    assert availability_after_article_toggle["status"] == "inactive"

    availability_reactivated = client.patch(
        f"/api/v1/availabilities/{availability['id']}",
        json={"status": "active"},
        headers=headers,
    )
    assert availability_reactivated.status_code == 200
    assert availability_reactivated.json()["status"] == "active"
    article_after_availability_toggle = client.get(f"/api/v1/dishes/{dish['id']}", headers=headers).json()
    assert article_after_availability_toggle["is_active"] is True

    article_deactivated = client.patch(f"/api/v1/dishes/{dish['id']}", json={"is_active": False}, headers=headers)
    assert article_deactivated.status_code == 200
    assert article_deactivated.json()["is_active"] is False
    availability_still_active = client.get(f"/api/v1/availabilities/{availability['id']}", headers=headers).json()
    assert availability_still_active["status"] == "active"


def test_merchant_catalog_update_blocks_non_owner_and_invalid_stock(client):
    owner_headers, _owner_cook, _owner_dish, availability = create_cook_marketplace(client, email="catalog-owner@example.co")
    _other_headers, _other_cook, other_dish, other_availability = create_cook_marketplace(client, email="catalog-other@example.co")

    assert client.patch(f"/api/v1/dishes/{other_dish['id']}", json={"name": "Tentative interdite"}, headers=owner_headers).status_code == 403
    assert client.patch(
        f"/api/v1/availabilities/{other_availability['id']}",
        json={"remaining_portions": 2},
        headers=owner_headers,
    ).status_code == 403
    assert client.patch(
        f"/api/v1/availabilities/{availability['id']}",
        json={"remaining_portions": -1},
        headers=owner_headers,
    ).status_code == 422
    assert client.patch(
        f"/api/v1/availabilities/{availability['id']}",
        json={"total_portions": 2, "remaining_portions": 3},
        headers=owner_headers,
    ).status_code == 409


def test_catalog_update_preserves_order_item_snapshot_and_refreshes_discovery(client):
    cook_headers, _cook, dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "catalog-customer@example.co", "Luisa")
    payment_response = client.post(
        "/api/v1/payments",
        json={"items": [{"availability_id": availability["id"], "quantity": 1}]},
        headers=customer_headers,
    )
    assert payment_response.status_code == 201
    payment = payment_response.json()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(payment)).status_code == 200
    approved_payment = client.get(f"/api/v1/payments/{payment['id']}", headers=customer_headers).json()
    order = client.get(f"/api/v1/orders/{approved_payment['order_id']}", headers=customer_headers).json()
    original_item = order["items"][0]
    assert original_item["dish_name"] == dish["name"]
    assert original_item["unit_price"] == dish["price"]

    updated_dish = client.patch(
        f"/api/v1/dishes/{dish['id']}",
        json={"name": "Ajiaco actualise", "price": "27000.00", "is_active": True},
        headers=cook_headers,
    )
    assert updated_dish.status_code == 200
    updated_availability = client.patch(
        f"/api/v1/availabilities/{availability['id']}",
        json={"remaining_portions": 4, "total_portions": 7, "status": "active"},
        headers=cook_headers,
    )
    assert updated_availability.status_code == 200

    refreshed_order = client.get(f"/api/v1/orders/{order['id']}", headers=customer_headers).json()
    assert refreshed_order["items"][0]["dish_name"] == original_item["dish_name"]
    assert refreshed_order["items"][0]["unit_price"] == original_item["unit_price"]

    discover = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5")
    assert discover.status_code == 200
    result = next(item for item in discover.json() if item["dish_id"] == dish["id"])
    assert result["dish_name"] == "Ajiaco actualise"
    assert result["price"] == "27000.00"
    assert result["remaining_portions"] is None


def test_coordinates_are_validated(client):
    headers = register(client, "invalid-coordinates@example.co", "Luisa")
    profile = client.post(
        "/api/v1/cooks",
        json={"display_name": "Cocina Inválida", "latitude": 91, "longitude": -74.06},
        headers=headers,
    )
    assert profile.status_code == 422

    discover = client.get("/api/v1/discover?latitude=4.65&longitude=-181&radius_km=5")
    assert discover.status_code == 422


def test_haversine_calculates_distance():
    from backend.app.services.marketplace import haversine_km

    assert haversine_km(4.65, -74.06, 4.65, -74.06) == 0
    assert haversine_km(4.65, -74.06, 4.651, -74.061) > 0


def test_discover_filters_radius_and_sorts_by_distance(client):
    _near_headers, _near_cook, near_dish, _near_availability = create_cook_marketplace(
        client, email="near@example.co", name="Cerca", display_name="Cocina Cerca", latitude=4.651, longitude=-74.061,
    )
    _far_headers, _far_cook, far_dish, _far_availability = create_cook_marketplace(
        client, email="far@example.co", name="Lejos", display_name="Cocina Lejos", latitude=4.70, longitude=-74.10,
    )

    nearby = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=1")
    assert nearby.status_code == 200
    assert [item["dish_id"] for item in nearby.json()] == [near_dish["id"]]
    assert nearby.json()[0]["distance_km"] < 1
    assert {"cook_display_name", "description"}.issubset(nearby.json()[0])

    all_results = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=20")
    assert all_results.status_code == 200
    assert [item["dish_id"] for item in all_results.json()] == [near_dish["id"], far_dish["id"]]


def test_discover_filters_by_business_vertical_and_preserves_default(client):
    food_headers, food_cook, food_dish, _food_availability = create_cook_marketplace(
        client, email="vertical-food@example.co", display_name="Restaurant Senegal",
    )
    bakery_headers, _bakery_cook, bakery_dish, _bakery_availability = create_cook_marketplace(
        client, email="vertical-bakery@example.co", display_name="Patisserie Dakar",
    )
    shop_headers, _shop_cook, shop_dish, _shop_availability = create_cook_marketplace(
        client, email="vertical-shop@example.co", display_name="Epicerie Locale",
    )
    assert food_cook["business_vertical"] == "food_service"
    assert client.patch("/api/v1/cooks/me", headers=bakery_headers, json={"business_vertical": "bakery_dessert"}).status_code == 200
    assert client.patch("/api/v1/cooks/me", headers=shop_headers, json={"business_vertical": "local_shop"}).status_code == 200

    base = "/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5"
    assert {item["dish_id"] for item in client.get(base).json()} == {food_dish["id"], bakery_dish["id"], shop_dish["id"]}
    food = client.get(f"{base}&vertical=food_service")
    bakery = client.get(f"{base}&vertical=bakery_dessert")
    shop = client.get(f"{base}&vertical=local_shop")
    assert food.status_code == bakery.status_code == shop.status_code == 200
    assert [item["dish_id"] for item in food.json()] == [food_dish["id"]]
    assert food.json()[0]["business_vertical"] == "food_service"
    assert [item["dish_id"] for item in bakery.json()] == [bakery_dish["id"]]
    assert bakery.json()[0]["business_vertical"] == "bakery_dessert"
    assert [item["dish_id"] for item in shop.json()] == [shop_dish["id"]]
    assert shop.json()[0]["business_vertical"] == "local_shop"
    assert client.get(f"{base}&vertical=invalid").status_code == 422


def test_discover_keeps_active_dish_when_legacy_availability_is_inactive(client):
    _headers, _cook, dish, availability = create_cook_marketplace(client)
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import DishAvailability

    with get_session_factory()() as session:
        session.execute(update(DishAvailability).where(DishAvailability.id == availability["id"]).values(status="inactive"))
        session.commit()

    response = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5")
    assert response.status_code == 200
    assert [item["dish_id"] for item in response.json()] == [dish["id"]]
    assert response.json()[0]["remaining_portions"] is None


def test_discover_keeps_active_dish_when_legacy_availability_is_expired(client):
    _headers, _cook, dish, availability = create_cook_marketplace(client)
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import DishAvailability

    with get_session_factory()() as session:
        session.execute(
            update(DishAvailability)
            .where(DishAvailability.id == availability["id"])
            .values(available_date=date.today() - timedelta(days=1))
        )
        session.commit()

    response = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5")
    assert response.status_code == 200
    assert [item["dish_id"] for item in response.json()] == [dish["id"]]
    assert response.json()[0]["remaining_portions"] is None


def test_discover_keeps_active_dish_when_legacy_stock_is_zero(client):
    _headers, _cook, dish, availability = create_cook_marketplace(client)
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import DishAvailability

    with get_session_factory()() as session:
        session.execute(
            update(DishAvailability)
            .where(DishAvailability.id == availability["id"])
            .values(remaining_portions=0)
        )
        session.commit()

    response = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5")
    assert response.status_code == 200
    assert [item["dish_id"] for item in response.json()] == [dish["id"]]
    assert response.json()[0]["remaining_portions"] is None


def complete_order(client, cook_headers, customer_headers, availability_id: str) -> dict:
    order = create_paid_order(client, customer_headers, availability_id)
    ready = client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": "ready"}, headers=cook_headers)
    assert ready.status_code == 200
    completed = client.post(
        f"/api/v1/orders/{order['id']}/pickup/confirm",
        json={"pickup_code": order["pickup_code"]},
        headers=cook_headers,
    )
    assert completed.status_code == 200
    return order


def test_public_cook_profile_excludes_private_data_and_supports_profile_photo(client, image_bytes):
    headers, cook, _dish, _availability = create_cook_marketplace(client)
    upload = client.post(
        "/api/v1/cooks/me/photo",
        headers=headers,
        files={"image": ("profile.jpg", image_bytes("JPEG"), "image/jpeg")},
    )
    assert upload.status_code == 200
    assert upload.json()["profile_photo_url"].startswith("/uploads/")

    # Une nouvelle session doit retrouver la photo sans nouvel upload.
    login = client.post("/api/v1/auth/login", json={
        "email": "cocinera@example.co", "password": "ClaveSegura123!",
    })
    assert login.status_code == 200
    restored_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    for _ in range(2):
        restored = client.get("/api/v1/me", headers=restored_headers)
        assert restored.status_code == 200
        assert restored.json()["cook_profile"]["profile_photo_url"] == upload.json()["profile_photo_url"]
    assert client.get(upload.json()["profile_photo_url"]).status_code == 200

    response = client.get(f"/api/v1/cooks/{cook['id']}/public")
    assert response.status_code == 200
    profile = response.json()
    assert profile["cook_id"] == cook["id"]
    assert profile["profile_photo_url"].startswith("/uploads/")
    assert {"email", "phone", "password_hash", "latitude", "longitude", "user_id"}.isdisjoint(profile)


def test_review_requires_completed_order_and_is_unique(client):
    cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "reviewer@example.co", "Luisa")
    order = create_paid_order(client, customer_headers, availability["id"])

    before_completed = client.post("/api/v1/reviews", json={"order_id": order["id"], "rating": 5}, headers=customer_headers)
    assert before_completed.status_code == 409

    client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": "ready"}, headers=cook_headers)
    client.post(
        f"/api/v1/orders/{order['id']}/pickup/confirm",
        json={"pickup_code": order["pickup_code"]},
        headers=cook_headers,
    )
    review = client.post("/api/v1/reviews", json={"order_id": order["id"], "rating": 5, "comment": "Excelente"}, headers=customer_headers)
    assert review.status_code == 201
    assert client.post("/api/v1/reviews", json={"order_id": order["id"], "rating": 5}, headers=customer_headers).status_code == 409
    assert client.post("/api/v1/reviews", json={"order_id": order["id"], "rating": 0}, headers=customer_headers).status_code == 422
    assert client.post("/api/v1/reviews", json={"order_id": "00000000-0000-0000-0000-000000000000", "rating": 5}, headers=customer_headers).status_code == 404
    assert client.post("/api/v1/reviews", json={"order_id": order["id"], "rating": 5}).status_code == 401


def test_review_rejects_non_owner_and_calculates_real_rating(client):
    cook_headers, cook, _dish, availability = create_cook_marketplace(client)
    first_customer = register(client, "first-review@example.co", "Luisa")
    second_customer = register(client, "second-review@example.co", "Sofia")
    intruder = register(client, "intruder-review@example.co", "Mario")

    first_order = complete_order(client, cook_headers, first_customer, availability["id"])
    assert client.post("/api/v1/reviews", json={"order_id": first_order["id"], "rating": 5}, headers=intruder).status_code == 403
    assert client.post("/api/v1/reviews", json={"order_id": first_order["id"], "rating": 5}, headers=first_customer).status_code == 201
    second_order = complete_order(client, cook_headers, second_customer, availability["id"])
    assert client.post("/api/v1/reviews", json={"order_id": second_order["id"], "rating": 3}, headers=second_customer).status_code == 201

    public_profile = client.get(f"/api/v1/cooks/{cook['id']}/public")
    assert public_profile.status_code == 200
    assert public_profile.json()["rating_average"] == "4.00"
    assert public_profile.json()["rating_count"] == 2
    assert public_profile.json()["orders_completed"] == 2
    reviews = client.get(f"/api/v1/reviews/cooks/{cook['id']}?limit=1&offset=0")
    assert reviews.status_code == 200
    assert len(reviews.json()["items"]) == 1
    assert set(reviews.json()["items"][0]) == {"id", "rating", "comment", "created_at"}
    assert "customer_id" not in reviews.json()["items"][0]
    assert "order_id" not in reviews.json()["items"][0]


def test_discovery_uses_public_review_aggregate_without_n_plus_one(client):
    from backend.app.database import get_engine

    cook_headers, cook, _dish, availability = create_cook_marketplace(client)
    _other_headers, other_cook, _other_dish, _other_availability = create_cook_marketplace(
        client, email="no-reviews@example.co", name="Autre", display_name="Sans avis",
    )
    for rating in (5, 4, 3):
        customer = register(client, f"review-{rating}@example.co", f"Client{rating}")
        order = complete_order(client, cook_headers, customer, availability["id"])
        response = client.post("/api/v1/reviews", json={"order_id": order["id"], "rating": rating}, headers=customer)
        assert response.status_code == 201

    review_queries = []

    def record_review_query(_connection, _cursor, statement, _parameters, _context, _executemany):
        if re.search(r"\bfrom\s+reviews\b", statement, re.IGNORECASE):
            review_queries.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", record_review_query)
    try:
        response = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5")
    finally:
        event.remove(engine, "before_cursor_execute", record_review_query)
    assert response.status_code == 200
    assert len(review_queries) == 1
    by_cook = {row["cook_id"]: row for row in response.json()}
    assert by_cook[cook["id"]]["rating_average"] == "4.00"
    assert by_cook[cook["id"]]["review_count"] == 3
    assert by_cook[cook["id"]]["cook_rating"] == "4.00"
    assert by_cook[other_cook["id"]]["rating_average"] is None
    assert by_cook[other_cook["id"]]["review_count"] == 0
    assert Decimal(by_cook[other_cook["id"]]["cook_rating"]) == 0

    profile = client.get(f"/api/v1/cooks/{cook['id']}/public").json()
    assert profile["rating_average"] == "4.00"
    assert profile["rating_count"] == 3
    assert [review["rating"] for review in profile["recent_reviews"]] == [3, 4, 5]
    assert all(set(review) == {"id", "rating", "comment", "created_at"} for review in profile["recent_reviews"])


def test_favorites_are_authenticated_unique_and_listed(client):
    _cook_headers, cook, _dish, _availability = create_cook_marketplace(client)
    customer_headers = register(client, "favorite@example.co", "Luisa")
    add = client.post(f"/api/v1/favorites/cooks/{cook['id']}", headers=customer_headers)
    assert add.status_code == 201
    assert client.post(f"/api/v1/favorites/cooks/{cook['id']}", headers=customer_headers).status_code == 409
    favorites = client.get("/api/v1/favorites/cooks", headers=customer_headers)
    assert favorites.status_code == 200
    assert favorites.json()[0]["cook_id"] == cook["id"]
    assert client.delete(f"/api/v1/favorites/cooks/{cook['id']}", headers=customer_headers).status_code == 204
    assert client.get("/api/v1/favorites/cooks").status_code == 401


def test_order_history_is_scoped_and_status_changes_require_owner(client):
    cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "history@example.co", "Luisa")
    other_cook_headers, _other_cook, _other_dish, _other_availability = create_cook_marketplace(
        client, email="other-cook@example.co", name="Otra", display_name="Otra Cocina"
    )
    order = create_paid_order(client, customer_headers, availability["id"])
    assert client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": "ready"}, headers=other_cook_headers).status_code == 403
    assert client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": "ready"}).status_code == 401
    assert client.get("/api/v1/orders", headers=customer_headers).json()[0]["id"] == order["id"]
    assert client.get("/api/v1/orders?scope=cook", headers=cook_headers).json()[0]["id"] == order["id"]
    assert client.get("/api/v1/orders?scope=cook", headers=customer_headers).status_code == 403


def test_pickup_code_is_generated_and_visible_only_to_customer(client):
    cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "pickup-customer@example.co", "Luisa")
    intruder_headers = register(client, "pickup-intruder@example.co", "Mario")
    order = create_paid_order(client, customer_headers, availability["id"])
    assert order["pickup_code"].isdigit()
    assert len(order["pickup_code"]) == 6
    assert order["confirmed_at"] is not None

    customer_order = client.get(f"/api/v1/orders/{order['id']}", headers=customer_headers)
    cook_orders = client.get("/api/v1/orders?scope=cook", headers=cook_headers)
    assert customer_order.json()["pickup_code"] == order["pickup_code"]
    assert cook_orders.json()[0]["pickup_code"] is None
    assert client.get(f"/api/v1/orders/{order['id']}", headers=intruder_headers).status_code == 403


def test_pickup_confirmation_requires_ready_code_and_owner(client):
    cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "confirm-customer@example.co", "Luisa")
    other_cook_headers, _other_cook, _other_dish, _other_availability = create_cook_marketplace(
        client, email="confirm-other@example.co", name="Otra", display_name="Otra Cocina"
    )
    order = create_paid_order(client, customer_headers, availability["id"])
    endpoint = f"/api/v1/orders/{order['id']}/pickup/confirm"
    assert client.post(endpoint, json={"pickup_code": order["pickup_code"]}, headers=cook_headers).status_code == 409
    assert client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": "ready"}, headers=cook_headers).status_code == 200
    assert client.post(endpoint, json={"pickup_code": "000000"}, headers=cook_headers).status_code == 409
    assert client.get(f"/api/v1/orders/{order['id']}", headers=customer_headers).json()["status"] == "ready"
    assert client.post(endpoint, json={"pickup_code": order["pickup_code"]}, headers=other_cook_headers).status_code == 403
    confirmed = client.post(endpoint, json={"pickup_code": order["pickup_code"]}, headers=cook_headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "completed"
    assert confirmed.json()["completed_at"] is not None
    assert confirmed.json()["pickup_code"] is None
    assert client.post(endpoint, json={"pickup_code": order["pickup_code"]}, headers=cook_headers).status_code == 409
    assert client.post(endpoint, json={"pickup_code": order["pickup_code"]}).status_code == 401


def test_cancellation_requests_require_justification_and_do_not_cancel(client):
    cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "cancel-customer@example.co", "Luisa")
    other_headers = register(client, "cancel-intruder@example.co", "Mario")
    order = create_paid_order(client, customer_headers, availability["id"])
    assert client.delete(f"/api/v1/orders/{order['id']}", headers=customer_headers).status_code == 405
    assert client.post(f"/api/v1/orders/{order['id']}/cancel", json={}, headers=customer_headers).status_code == 422
    payload = {"reason": "other", "description": "Demande de resolution de commande."}
    requested = client.post(f"/api/v1/orders/{order['id']}/cancel", json=payload, headers=customer_headers)
    assert requested.status_code == 200
    assert requested.json()["request_type"] == "client_cancellation"
    assert client.get(f"/api/v1/orders/{order['id']}", headers=customer_headers).json()["status"] == "confirmed"
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=cook_headers).json()["remaining_portions"] == 7
    assert client.post(f"/api/v1/orders/{order['id']}/cancel", json=payload, headers=other_headers).status_code == 403

    ready_order = create_paid_order(client, customer_headers, availability["id"])
    assert client.patch(f"/api/v1/orders/{ready_order['id']}/status", json={"status": "ready"}, headers=cook_headers).status_code == 200
    assert client.post(f"/api/v1/orders/{ready_order['id']}/cancel", json=payload, headers=customer_headers).status_code == 200
    merchant_payload = {"reason": "item_out_of_stock", "description": "Un article est indisponible."}
    merchant_request = client.post(f"/api/v1/orders/{ready_order['id']}/cancel", json=merchant_payload, headers=cook_headers)
    assert merchant_request.status_code == 200
    assert merchant_request.json()["request_type"] == "merchant_cancellation"
    assert client.get(f"/api/v1/orders/{ready_order['id']}", headers=customer_headers).json()["status"] == "ready"
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=cook_headers).json()["remaining_portions"] == 6


def test_invalid_order_transitions_and_completed_cancellation_are_rejected(client):
    cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "transition-customer@example.co", "Luisa")
    order = create_paid_order(client, customer_headers, availability["id"])
    status_url = f"/api/v1/orders/{order['id']}/status"
    assert client.patch(status_url, json={"status": "completed"}, headers=cook_headers).status_code == 422
    assert client.patch(status_url, json={"status": "ready"}, headers=cook_headers).status_code == 200
    assert client.patch(status_url, json={"status": "ready"}, headers=cook_headers).status_code == 200
    assert client.post(f"/api/v1/orders/{order['id']}/pickup/confirm", json={"pickup_code": order["pickup_code"]}, headers=cook_headers).status_code == 200
    assert client.post(f"/api/v1/orders/{order['id']}/cancel", json={"reason": "other", "description": "Déjà récupérée."}, headers=cook_headers).status_code == 409


def test_payment_retry_reuses_stable_payu_reference_and_preserves_ownership(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "payment-owner@example.co", "Luisa")
    other_headers = register(client, "payment-other@example.co", "Mario")
    payment = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 2}, headers=customer_headers)
    assert payment.status_code == 201
    assert payment.json()["amount_in_cents"] == 5_000_000
    assert payment.json()["currency"] == "COP"
    assert payment.json()["provider"] == "payu"
    assert payment.json()["checkout_url"].startswith("/api/v1/payments/")
    retry = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 2}, headers=customer_headers)
    assert retry.status_code == 201
    assert retry.json()["id"] == payment.json()["id"]
    assert retry.json()["provider_reference"] == payment.json()["provider_reference"]
    assert re.fullmatch(r"KWITLI[A-F0-9]{32}", payment.json()["provider_reference"])
    assert re.fullmatch(r"KWITLI[A-F0-9]{32}", retry.json()["provider_reference"])
    first_checkout = open_payu_checkout(client, payment.json()["checkout_url"])
    second_checkout = open_payu_checkout(client, payment.json()["checkout_url"])
    assert first_checkout.status_code == 200
    assert second_checkout.status_code == 409
    first_fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', first_checkout.text))
    assert first_fields["referenceCode"] == payment.json()["provider_reference"]
    assert client.get(f"/api/v1/payments/{payment.json()['id']}", headers=other_headers).status_code == 403
    assert client.post("/api/v1/orders", json={"availability_id": availability["id"], "quantity": 1}, headers=customer_headers).status_code == 409


def test_payu_webhook_uses_its_reference_to_approve_only_the_matching_payment(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "payment-reference-webhook@example.co", "Luisa")
    first = client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=customer_headers,
    ).json()
    assert client.post(
        "/api/v1/payments/payu/confirmation",
        data=payu_confirmation(first, "6"),
    ).status_code == 200
    second = client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=customer_headers,
    ).json()

    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(second)).status_code == 200
    assert client.get(f"/api/v1/payments/{first['id']}", headers=customer_headers).json()["status"] == "declined"
    assert client.get(f"/api/v1/payments/{second['id']}", headers=customer_headers).json()["status"] == "approved"
    assert len(client.get("/api/v1/orders", headers=customer_headers).json()) == 1
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=_cook_headers).json()["remaining_portions"] == 7


def test_payu_checkout_relay_exposes_no_secret(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "payu-form@example.co", "Luisa")
    payment = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 1}, headers=customer_headers).json()
    checkout = open_payu_checkout(client, payment["checkout_url"])
    assert checkout.status_code == 200
    assert "sandbox.checkout.payulatam.com" in checkout.text
    assert "test-api-key" not in checkout.text
    assert "confirmationUrl" in checkout.text
    action = re.search(r'<form[^>]+action="([^"]+)"', checkout.text)
    assert action is not None
    parsed_action = urlparse(action.group(1))
    assert parsed_action.scheme == "https"
    assert parsed_action.hostname == "sandbox.checkout.payulatam.com"
    assert parsed_action.path == "/ppp-web-gateway-payu/"
    assert 'name="test" value="1"' in checkout.text
    assert 'name="test" value="0"' not in checkout.text
    assert 'name="responseUrl" value="https://public-test.example/api/v1/payments/payu/response"' in checkout.text
    assert 'name="confirmationUrl" value="https://public-test.example/api/v1/payments/payu/confirmation"' in checkout.text
    assert "http://" not in checkout.text
    assert "backoffice.payu.sandbox" not in checkout.text
    assert "<meta" not in checkout.text
    assert "window.location" not in checkout.text
    assert client.get("/api/v1/payments/payu/response").status_code == 200
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=customer_headers).json()["status"] == "pending"

    fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', checkout.text))
    required_fields = {
        "merchantId", "accountId", "description", "referenceCode", "amount", "tax",
        "taxReturnBase", "currency", "signature", "payerFullName", "payerEmail",
        "payerPhone", "payerDocumentType", "payerDocument", "buyerFullName", "buyerEmail",
        "buyerDocumentType", "buyerDocument", "telephone",
    }
    assert required_fields.issubset(fields)
    assert fields["algorithmSignature"] == "SHA256"
    assert fields["test"] == "1"
    assert fields["currency"] == "COP"
    assert fields["tax"] == "0"
    assert fields["taxReturnBase"] == "0"
    assert re.fullmatch(r"[A-Z0-9]+", fields["referenceCode"])
    expected_signature = hashlib.sha256(
        f"test-api-key~{fields['merchantId']}~{fields['referenceCode']}~{fields['amount']}~{fields['currency']}".encode()
    ).hexdigest()
    assert fields["signature"] == expected_signature


def test_payu_sandbox_checkout_validation_rejects_missing_mandatory_fields():
    from backend.app.core.config import Settings
    from backend.app.services.payments.payu import PayUPaymentProvider, PayUValidationError

    settings = Settings(
        _env_file=None,
        app_env="test",
        secret_key="test-secret-key",
        payu_api_key="test-api-key",
        payu_merchant_id="test-merchant",
        payu_account_id="test-account",
        payu_checkout_url="https://sandbox.checkout.payulatam.com/ppp-web-gateway-payu/",
        public_api_url="https://public-test.example",
    )
    assert settings.payu_env == "sandbox"
    provider = PayUPaymentProvider(settings)
    fields = provider.checkout_fields(
        reference="KWITLITEST",
        amount_in_cents=1800000,
        currency="COP",
        buyer_email="test@example.co",
        buyer_full_name="Kwitli Sandbox",
        buyer_phone=None,
        confirmation_url="https://public-test.example/api/v1/payments/payu/confirmation",
        response_url="https://public-test.example/api/v1/payments/payu/response",
    )
    provider.validate_sandbox_checkout_fields(fields)
    fields["test"] = "0"
    with pytest.raises(PayUValidationError, match="test=1"):
        provider.validate_sandbox_checkout_fields(fields)
    fields["test"] = "1"
    fields.pop("payerPhone")
    with pytest.raises(PayUValidationError, match="payerPhone"):
        provider.validate_sandbox_checkout_fields(fields)


def test_payu_checkout_rejects_insecure_configuration_or_callback_urls():
    from backend.app.core.config import Settings
    from backend.app.services.payments.payu import PayUPaymentProvider, PayUValidationError

    settings = Settings(
        _env_file=None,
        app_env="test",
        secret_key="test-secret-key",
        payu_api_key="test-api-key",
        payu_merchant_id="test-merchant",
        payu_account_id="test-account",
        payu_checkout_url="http://sandbox.checkout.payulatam.com/ppp-web-gateway-payu/",
        public_api_url="https://public-test.example",
    )
    with pytest.raises(PayUValidationError, match="PAYU_CHECKOUT_URL"):
        _ = PayUPaymentProvider(settings).checkout_url

    secure_settings = Settings(
        _env_file=None,
        app_env="test",
        secret_key="test-secret-key",
        payu_api_key="test-api-key",
        payu_merchant_id="test-merchant",
        payu_account_id="test-account",
        payu_checkout_url="https://sandbox.checkout.payulatam.com/ppp-web-gateway-payu/",
        public_api_url="https://public-test.example",
    )
    with pytest.raises(PayUValidationError, match="confirmationUrl"):
        PayUPaymentProvider(secure_settings).checkout_fields(
            reference="KWITLITEST",
            amount_in_cents=1800000,
            currency="COP",
            buyer_email="test@example.co",
            buyer_full_name="Kwitli Sandbox",
            buyer_phone=None,
            confirmation_url="http://public-test.example/api/v1/payments/payu/confirmation",
            response_url="https://public-test.example/api/v1/payments/payu/response",
        )


def test_payu_checkout_does_not_fallback_to_request_base_url(monkeypatch):
    from backend.app.api.routes.payments import public_payment_url
    from backend.app.core.config import get_settings
    from backend.app.services.payments.payu import PayUValidationError

    monkeypatch.setenv("PUBLIC_API_URL", "")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    get_settings.cache_clear()
    try:
        with pytest.raises(PayUValidationError, match="PUBLIC_API_URL"):
            public_payment_url("/api/v1/payments/payu/confirmation")
    finally:
        get_settings.cache_clear()


def test_payu_confirmation_without_jwt_approves_once_and_rejects_invalid_signature(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "payment-approved@example.co", "Luisa")
    payment = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 1}, headers=customer_headers).json()
    event = payu_confirmation(payment)
    invalid = {**event, "sign": "0" * 64}
    assert client.post("/api/v1/payments/payu/confirmation", data=invalid).status_code == 403
    assert client.post(
        "/api/v1/payments/payu/confirmation",
        data={**event, "sign": event["sign"].upper()},
    ).status_code == 200
    assert client.post("/api/v1/payments/payu/confirmation", data=event).status_code == 200
    stored = client.get(f"/api/v1/payments/{payment['id']}", headers=customer_headers)
    assert stored.json()["status"] == "approved"
    assert len(client.get("/api/v1/orders", headers=customer_headers).json()) == 1
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=_cook_headers).json()["remaining_portions"] == 7


@pytest.mark.parametrize(("raw_value", "formatted_value"), (
    ("150.00", "150.0"),
    ("150.25", "150.25"),
    ("18000.00", "18000.0"),
    ("18000", "18000.0"),
    ("18000.50", "18000.5"),
    ("18000.55", "18000.55"),
))
def test_payu_confirmation_value_uses_official_decimal_representation(raw_value, formatted_value):
    from backend.app.services.payments.payu import PayUPaymentProvider

    assert PayUPaymentProvider._confirmation_value(raw_value) == formatted_value


def test_payu_approved_confirmation_uses_sha256_and_normalized_value(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client, price="18000.00")
    customer_headers = register(client, "payment-18000@example.co", "Luisa")
    payment = client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=customer_headers,
    ).json()
    event = payu_confirmation(payment)

    assert event["value"] == "18000.00"
    assert len(event["sign"]) == 64
    assert event["sign"] == hashlib.sha256(
        f"test-api-key~{event['merchant_id']}~{event['reference_sale']}~18000.0~COP~4".encode()
    ).hexdigest()
    assert client.post("/api/v1/payments/payu/confirmation", data=event).status_code == 200
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=customer_headers).json()["status"] == "approved"
    assert len(client.get("/api/v1/orders", headers=customer_headers).json()) == 1
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=_cook_headers).json()["remaining_portions"] == 7


def test_payu_confirmation_rejects_validly_signed_non_cop_currency(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    customer_headers = register(client, "payment-currency@example.co", "Luisa")
    payment = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 1}, headers=customer_headers).json()
    event = payu_confirmation(payment)
    event["currency"] = "USD"
    event["sign"] = hashlib.sha256(
        f"test-api-key~{event['merchant_id']}~{event['reference_sale']}~{event['value'][:-1]}~USD~{event['state_pol']}".encode()
    ).hexdigest()

    assert client.post("/api/v1/payments/payu/confirmation", data=event).status_code == 403
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=customer_headers).json()["status"] == "pending"


def test_declined_error_mismatch_and_stock_failure_do_not_create_order(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    first_headers = register(client, "payment-declined@example.co", "Luisa")
    second_headers = register(client, "payment-error@example.co", "Mario")
    declined = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 1}, headers=first_headers).json()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(declined, "6")).status_code == 200
    assert client.get(f"/api/v1/payments/{declined['id']}", headers=first_headers).json()["status"] == "declined"
    assert client.get("/api/v1/orders", headers=first_headers).json() == []

    mismatch = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 1}, headers=second_headers).json()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(mismatch, amount_in_cents=mismatch["amount_in_cents"] + 1)).status_code == 200
    assert client.get(f"/api/v1/payments/{mismatch['id']}", headers=second_headers).json()["status"] == "error"
    assert client.get("/api/v1/orders", headers=second_headers).json() == []


def test_approved_payment_never_makes_stock_negative(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import DishAvailability

    with get_session_factory()() as session:
        session.execute(update(DishAvailability).where(DishAvailability.id == availability["id"]).values(remaining_portions=1, total_portions=1))
        session.commit()

    first_headers = register(client, "payment-stock-first@example.co", "Luisa")
    second_headers = register(client, "payment-stock-second@example.co", "Mario")
    first = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 1}, headers=first_headers).json()
    second = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 1}, headers=second_headers)
    assert second.status_code == 409
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(first)).status_code == 200
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=_cook_headers).json()["remaining_portions"] == 0


def test_active_hold_does_not_hide_active_dish_but_legacy_checkout_still_enforces_it(client):
    _cook_headers, _cook, dish, availability = create_cook_marketplace(client)
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import DishAvailability

    with get_session_factory()() as session:
        session.execute(update(DishAvailability).where(DishAvailability.id == availability["id"]).values(remaining_portions=1, total_portions=1))
        session.commit()
    first_headers = register(client, "hold-first@example.co", "Luisa")
    second_headers = register(client, "hold-second@example.co", "Mario")
    payment = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 1}, headers=first_headers)
    assert payment.status_code == 201
    discovered = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5").json()
    assert [item["dish_id"] for item in discovered] == [dish["id"]]
    assert discovered[0]["remaining_portions"] is None
    assert client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 1}, headers=second_headers).status_code == 409


def test_declined_and_error_release_stock_holds(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import DishAvailability

    customer_headers = register(client, "hold-release@example.co", "Luisa")
    declined = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 8}, headers=customer_headers).json()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(declined, "6")).status_code == 200
    discovered = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5").json()
    assert discovered[0]["remaining_portions"] is None
    with get_session_factory()() as session:
        assert session.get(DishAvailability, availability["id"]).remaining_portions == 8
    errored = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 8}, headers=customer_headers).json()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(errored, "5")).status_code == 200
    discovered = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5").json()
    assert discovered[0]["remaining_portions"] is None
    with get_session_factory()() as session:
        assert session.get(DishAvailability, availability["id"]).remaining_portions == 8


def test_expired_hold_is_cleaned_before_next_payment(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    from datetime import datetime, timedelta
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import StockHold

    first_headers = register(client, "hold-expired-first@example.co", "Luisa")
    second_headers = register(client, "hold-expired-second@example.co", "Mario")
    first = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 8}, headers=first_headers).json()
    with get_session_factory()() as session:
        session.execute(update(StockHold).where(StockHold.payment_id == first["id"]).values(expires_at=datetime.now() - timedelta(minutes=1)))
        session.commit()
    second = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 8}, headers=second_headers)
    assert second.status_code == 201


def test_payu_approved_after_expired_hold_creates_no_order(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    from datetime import datetime, timedelta
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import StockHold

    customer_headers = register(client, "payu-expired@example.co", "Luisa")
    payment = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 1}, headers=customer_headers).json()
    with get_session_factory()() as session:
        session.execute(update(StockHold).where(StockHold.payment_id == payment["id"]).values(expires_at=datetime.now() - timedelta(minutes=1)))
        session.commit()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(payment)).status_code == 200
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=customer_headers).json()["status"] == "error"
    assert client.get("/api/v1/orders", headers=customer_headers).json() == []
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=_cook_headers).json()["remaining_portions"] == 8


def test_approved_payment_consumes_hold_once(client):
    _cook_headers, _cook, _dish, availability = create_cook_marketplace(client)
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import StockHold

    customer_headers = register(client, "hold-approved@example.co", "Luisa")
    payment = client.post("/api/v1/payments", json={"availability_id": availability["id"], "quantity": 1}, headers=customer_headers).json()
    event = payu_confirmation(payment)
    assert client.post("/api/v1/payments/payu/confirmation", data=event).status_code == 200
    assert client.post("/api/v1/payments/payu/confirmation", data=event).status_code == 200
    with get_session_factory()() as session:
        hold = session.scalar(select(StockHold).where(StockHold.payment_id == payment["id"]))
        assert hold is not None
        assert hold.status == "consumed"
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=customer_headers).json()["status"] == "approved"
    assert len(client.get("/api/v1/orders", headers=customer_headers).json()) == 1
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=_cook_headers).json()["remaining_portions"] == 7
