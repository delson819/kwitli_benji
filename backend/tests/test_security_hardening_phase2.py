import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from alembic import command
from alembic.config import Config
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select, text, update


def market_today():
    from backend.app.core.time import market_today as current_market_today

    return current_market_today()


def utc_now():
    return datetime.now(timezone.utc)


def register(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "ClaveSegura123!", "first_name": "Kwitli"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def checkout_parts(checkout_url: str) -> tuple[str, str]:
    parsed = urlparse(checkout_url)
    return parsed.path, parse_qs(parsed.fragment)["token"][0]


def open_payu_checkout(client, checkout_url: str):
    path, token = checkout_parts(checkout_url)
    return client.post(path, data={"token": token})


def create_market(client, *, portions: int = 8):
    cook_headers = register(client, "phase2-cook@example.co")
    cook = client.post(
        "/api/v1/cooks",
        json={"display_name": "Cocina Segura", "latitude": 4.65, "longitude": -74.06},
        headers=cook_headers,
    ).json()
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import CookProfile

    with get_session_factory()() as session:
        session.execute(update(CookProfile).where(CookProfile.id == cook["id"]).values(
            is_verified=True, approval_status="approved"
        ))
        session.commit()
    assert client.put("/api/v1/cooks/me/hours", headers=cook_headers, json={"days": [
        {"weekday": weekday, "is_closed": False, "opens_at": "00:00:00", "closes_at": "23:59:59.999999"}
        for weekday in range(7)
    ]}).status_code == 200
    dish = client.post(
        "/api/v1/dishes",
        json={"name": "Ajiaco seguro", "description": "Preparado hoy", "price": "18000", "currency": "COP"},
        headers=cook_headers,
    ).json()
    availability = client.post(
        "/api/v1/availabilities",
        json={
            "dish_id": dish["id"],
            "available_date": str(market_today() + timedelta(days=1)),
            "start_time": "11:00:00",
            "end_time": "22:00:00",
            "total_portions": portions,
        },
        headers=cook_headers,
    ).json()
    return cook_headers, cook, dish, availability


def payu_confirmation(payment: dict, transaction_id: str = "phase2-transaction") -> dict[str, str]:
    raw_value = format(Decimal(payment["amount_in_cents"]) / 100, ".2f")
    normalized = format(Decimal(raw_value), ".1f") if raw_value.endswith("0") else raw_value
    payload = {
        "merchant_id": "test-merchant",
        "reference_sale": payment["provider_reference"],
        "value": raw_value,
        "currency": "COP",
        "state_pol": "4",
        "transaction_id": transaction_id,
    }
    payload["sign"] = hashlib.sha256(
        f"test-api-key~test-merchant~{payment['provider_reference']}~{normalized}~COP~4".encode()
    ).hexdigest()
    return payload


def jwt_for(client, **overrides) -> str:
    from backend.app.core.config import get_settings

    headers = register(client, f"jwt-{hash(frozenset(overrides.items()))}@example.co")
    valid_token = headers["Authorization"].removeprefix("Bearer ")
    user_id = jwt.decode(valid_token, options={"verify_signature": False})["sub"]
    settings = get_settings()
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user_id,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": "phase2-jti",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    dropped_claim = overrides.pop("drop_claim", None)
    claims.update(overrides)
    if dropped_claim is not None:
        claims.pop(dropped_claim)
    signing_key = claims.pop("signing_key", settings.secret_key)
    return jwt.encode(claims, signing_key, algorithm="HS256")


@pytest.mark.parametrize(
    "overrides",
    (
        {"iss": "wrong-api"},
        {"aud": "wrong-mobile"},
        {"exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        {"jti": None},
        {"drop_claim": "jti"},
        {"signing_key": "different-signing-key-that-is-long-enough"},
    ),
)
def test_jwt_strict_claim_validation(client, overrides):
    token = jwt_for(client, **overrides)
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_access_tokens_include_unique_standard_claims(client):
    first = register(client, "jwt-claims-a@example.co")["Authorization"].removeprefix("Bearer ")
    second = register(client, "jwt-claims-b@example.co")["Authorization"].removeprefix("Bearer ")
    first_claims = jwt.decode(first, options={"verify_signature": False})
    second_claims = jwt.decode(second, options={"verify_signature": False})

    assert first_claims["iss"] == "kwitli-api"
    assert first_claims["aud"] == "kwitli-mobile"
    assert first_claims["jti"] != second_claims["jti"]
    assert first_claims["exp"] - first_claims["iat"] == 3600


@pytest.mark.parametrize(
    "secret",
    ("", "secret", "changeme", "too-short", "replace-with-a-long-random-secret"),
)
def test_weak_secret_is_rejected_outside_tests(secret):
    from backend.app.core.config import Settings

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, app_env="production", secret_key=secret)


def test_real_jpeg_and_png_are_decoded_and_reencoded(client, image_bytes):
    headers, _cook, dish, _availability = create_market(client)
    for image_format, mime_type in (("JPEG", "image/jpeg"), ("PNG", "image/png")):
        uploaded = client.post(
            f"/api/v1/dishes/{dish['id']}/photo",
            headers=headers,
            files={"image": (f"dish.{image_format.lower()}", image_bytes(image_format), mime_type)},
        )
        assert uploaded.status_code == 200
        served = client.get(uploaded.json()["photo_url"])
        assert served.status_code == 200
        with Image.open(BytesIO(served.content)) as decoded:
            assert decoded.format == image_format


@pytest.mark.parametrize(
    ("filename", "content", "mime_type"),
    (
        ("fake.jpg", b"\xff\xd8\xff\xe0not-a-real-image", "image/jpeg"),
        ("corrupt.jpg", b"\xff\xd8\xff\xe0\x00\x10truncated", "image/jpeg"),
        ("dish.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml"),
    ),
)
def test_invalid_images_are_rejected(client, filename, content, mime_type):
    headers, _cook, dish, _availability = create_market(client)
    response = client.post(
        f"/api/v1/dishes/{dish['id']}/photo",
        headers=headers,
        files={"image": (filename, content, mime_type)},
    )
    assert response.status_code == 415


def test_image_dimension_limit_and_exif_removal(client, image_bytes):
    from backend.app.core.config import get_settings

    headers, _cook, dish, _availability = create_market(client)
    settings = get_settings()
    settings.upload_max_width = 24
    too_wide = client.post(
        f"/api/v1/dishes/{dish['id']}/photo",
        headers=headers,
        files={"image": ("wide.png", image_bytes("PNG", (25, 2)), "image/png")},
    )
    assert too_wide.status_code == 413

    uploaded = client.post(
        f"/api/v1/dishes/{dish['id']}/photo",
        headers=headers,
        files={"image": ("metadata.jpg", image_bytes("JPEG", with_exif=True), "image/jpeg")},
    )
    assert uploaded.status_code == 200
    with Image.open(BytesIO(client.get(uploaded.json()["photo_url"]).content)) as decoded:
        assert len(decoded.getexif()) == 0


def test_pillow_decompression_bomb_guard_is_enforced(client, image_bytes, monkeypatch):
    headers, _cook, dish, _availability = create_market(client)
    payload = image_bytes("PNG", (8, 8))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 16)
    response = client.post(
        f"/api/v1/dishes/{dish['id']}/photo",
        headers=headers,
        files={"image": ("bomb.png", payload, "image/png")},
    )
    assert response.status_code == 415


def test_client_cannot_assign_arbitrary_photo_url(client):
    headers = register(client, "photo-url-cook@example.co")
    assert client.post(
        "/api/v1/cooks",
        json={"display_name": "Photo Cook", "latitude": 4.65, "longitude": -74.06},
        headers=headers,
    ).status_code == 201
    response = client.post(
        "/api/v1/dishes",
        json={
            "name": "Plat avec URL",
            "description": "URL client interdite",
            "price": "10000",
            "currency": "COP",
            "photo_url": "https://attacker.example/image.jpg",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_checkout_token_is_stable_hashed_expiring_and_one_time(client):
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import Payment

    _cook_headers, _cook, _dish, availability = create_market(client)
    customer_headers = register(client, "checkout-token@example.co")
    first = client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=customer_headers,
    ).json()
    second = client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=customer_headers,
    ).json()
    _first_path, first_token = checkout_parts(first["checkout_url"])
    _second_path, second_token = checkout_parts(second["checkout_url"])
    first_url = urlparse(first["checkout_url"])
    assert first_url.query == ""
    assert first_url.fragment.startswith("token=")
    assert second["id"] == first["id"]
    assert first_token == second_token
    service_source = (Path(__file__).resolve().parents[1] / "app/services/payments/service.py").read_text(
        encoding="utf-8"
    )
    assert "def _payu_checkout_token" in service_source
    assert "hmac.new(" in service_source

    bridge = client.get(first_url.path)
    assert bridge.status_code == 200
    assert first_token not in bridge.text
    assert client.get(f"/api/v1/payments/{first['id']}", headers=customer_headers).json()["status"] == "pending"
    assert client.get("/api/v1/orders", headers=customer_headers).json() == []

    with get_session_factory()() as session:
        payment = session.get(Payment, first["id"])
        assert payment is not None
        assert payment.checkout_token_hash == hashlib.sha256(first_token.encode()).hexdigest()
        assert first_token != payment.checkout_token_hash
        assert payment.checkout_token_expires_at is not None
        assert payment.checkout_token_used_at is None

    assert open_payu_checkout(client, first["checkout_url"]).status_code == 200
    assert open_payu_checkout(client, first["checkout_url"]).status_code == 409
    with get_session_factory()() as session:
        payment = session.get(Payment, first["id"])
        assert payment is not None and payment.checkout_token_used_at is not None


def test_checkout_token_rejects_wrong_expired_and_cross_payment(client):
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import Payment

    _cook_headers, _cook, _dish, availability = create_market(client)
    headers = register(client, "checkout-token-errors@example.co")
    other_headers = [headers, register(client, "checkout-token-errors-2@example.co"),
                     register(client, "checkout-token-errors-3@example.co")]
    payments = [client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=owner_headers,
    ).json() for owner_headers in other_headers]
    first_path, _first_token = checkout_parts(payments[0]["checkout_url"])
    assert client.post(first_path, data={"token": "invalid-token"}).status_code == 409

    _path_a, token_a = checkout_parts(payments[0]["checkout_url"])
    cross_path = f"/api/v1/payments/{payments[1]['id']}/payu/checkout"
    assert client.post(cross_path, data={"token": token_a}).status_code == 409

    with get_session_factory()() as session:
        session.execute(
            update(Payment)
            .where(Payment.id == payments[2]["id"])
            .values(checkout_token_expires_at=utc_now() - timedelta(seconds=1))
        )
        session.commit()
    assert open_payu_checkout(client, payments[2]["checkout_url"]).status_code == 409


def test_concurrent_approved_callbacks_have_one_effect(client):
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import Payment, StockHold

    _cook_headers, _cook, _dish, availability = create_market(client)
    headers = register(client, "concurrent-approved@example.co")
    payment = client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=headers,
    ).json()
    event = payu_confirmation(payment)

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _index: client.post("/api/v1/payments/payu/confirmation", data=event), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    for _attempt in range(3):
        assert client.post("/api/v1/payments/payu/confirmation", data=event).status_code == 200
    assert len(client.get("/api/v1/orders", headers=headers).json()) == 1
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=_cook_headers).json()["remaining_portions"] == 7
    with get_session_factory()() as session:
        stored = session.get(Payment, payment["id"])
        hold = session.scalar(select(StockHold).where(StockHold.payment_id == payment["id"]))
        assert stored is not None and stored.status == "approved"
        assert hold is not None and hold.status == "consumed"


def test_two_clients_cannot_hold_the_same_last_portion(client):
    _cook_headers, _cook, _dish, availability = create_market(client, portions=1)
    first_headers = register(client, "last-stock-a@example.co")
    second_headers = register(client, "last-stock-b@example.co")
    payload = {"availability_id": availability["id"], "quantity": 1}

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda headers: client.post("/api/v1/payments", json=payload, headers=headers), (first_headers, second_headers)))

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=_cook_headers).json()["remaining_portions"] == 1


def test_customer_cancellation_request_does_not_change_order_payment_or_stock(client):
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import Payment, StockHold

    _cook_headers, _cook, _dish, availability = create_market(client)
    headers = register(client, "refund-pending@example.co")
    payment = client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=headers,
    ).json()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(payment)).status_code == 200
    order = client.get("/api/v1/orders", headers=headers).json()[0]

    payload = {"reason": "other", "description": "Je souhaite annuler cette commande."}
    response = client.post(f"/api/v1/orders/{order['id']}/cancel", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["request_type"] == "client_cancellation"
    assert response.json()["status"] == "submitted"
    assert client.post(f"/api/v1/orders/{order['id']}/cancel", json=payload, headers=headers).status_code == 409
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=_cook_headers).json()["remaining_portions"] == 7
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=headers).json()["status"] == "approved"
    with get_session_factory()() as session:
        stored = session.get(Payment, payment["id"])
        hold = session.scalar(select(StockHold).where(StockHold.payment_id == payment["id"]))
        from backend.app.persistence.models import Order
        stored_order = session.get(Order, order["id"])
        assert stored is not None and stored.refund_requested_at is None and stored.refunded_at is None
        assert stored_order is not None and stored_order.status == "confirmed" and stored_order.cancelled_at is None
        assert hold is not None and hold.status == "consumed"


def test_unpaid_order_cancellation_restores_stock_without_refund(client):
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import Dish, DishAvailability, Order, Payment

    _cook_headers, _cook, _dish, availability_data = create_market(client)
    headers = register(client, "unpaid-cancel@example.co")
    customer = client.get("/api/v1/me", headers=headers).json()["user"]
    now = utc_now()
    with get_session_factory()() as session:
        availability = session.get(DishAvailability, availability_data["id"])
        assert availability is not None
        dish = session.get(Dish, availability.dish_id)
        assert dish is not None
        availability.remaining_portions -= 1
        order = Order(
            customer_id=customer["id"],
            availability_id=availability.id,
            quantity=1,
            unit_price=dish.price,
            total_price=dish.price,
            currency="COP",
            status="confirmed",
            pickup_code="654321",
            confirmed_at=now,
            pickup_expires_at=availability.end_datetime,
        )
        session.add(order)
        session.commit()
        order_id = order.id

    assert client.post(f"/api/v1/orders/{order_id}/cancel", json={
        "reason": "other", "description": "Demande de resolution pour cette commande.",
    }, headers=headers).status_code == 200
    assert client.get(f"/api/v1/availabilities/{availability_data['id']}", headers=_cook_headers).json()["remaining_portions"] == 7
    with get_session_factory()() as session:
        assert session.scalar(select(Payment).where(Payment.order_id == order_id)) is None
        from backend.app.persistence.models import Order
        assert session.get(Order, order_id).status == "confirmed"


@pytest.mark.parametrize(
    "dish_overrides",
    (
        {"currency": "USD"},
        {"price": "-1"},
        {"price": "2000000.01"},
        {"name": "   "},
        {"name": " a "},
        {"description": "x" * 2001},
    ),
)
def test_strict_dish_business_limits(client, dish_overrides):
    headers = register(client, f"validation-{len(str(dish_overrides))}-{hash(str(dish_overrides))}@example.co")
    assert client.post(
        "/api/v1/cooks",
        json={"display_name": "Validation Cook", "latitude": 4.65, "longitude": -74.06},
        headers=headers,
    ).status_code == 201
    payload = {"name": "Plat valide", "description": "Description", "price": "18000", "currency": "COP"}
    response = client.post("/api/v1/dishes", json={**payload, **dish_overrides}, headers=headers)
    assert response.status_code == 422


def test_availability_portion_coordinate_and_time_limits(client):
    headers = register(client, "validation-limits@example.co")
    assert client.post(
        "/api/v1/cooks",
        json={"display_name": "Invalid Coordinates", "latitude": 90.1, "longitude": -74.06},
        headers=headers,
    ).status_code == 422
    assert client.post(
        "/api/v1/cooks",
        json={"display_name": "Validation Cook", "latitude": 4.65, "longitude": -74.06},
        headers=headers,
    ).status_code == 201
    dish = client.post(
        "/api/v1/dishes",
        json={"name": "Plat valide", "description": "Description", "price": "18000", "currency": "COP"},
        headers=headers,
    ).json()
    base = {
        "dish_id": dish["id"],
        "available_date": str(market_today() + timedelta(days=1)),
        "start_time": "11:00:00",
        "end_time": "12:00:00",
        "total_portions": 1,
    }
    assert client.post("/api/v1/availabilities", json={**base, "total_portions": 0}, headers=headers).status_code == 422
    assert client.post("/api/v1/availabilities", json={**base, "total_portions": 501}, headers=headers).status_code == 422
    assert client.post("/api/v1/availabilities", json={**base, "end_time": "10:00:00"}, headers=headers).status_code == 422
    assert client.post(
        "/api/v1/availabilities",
        json={**base, "available_date": str(market_today() - timedelta(days=1))},
        headers=headers,
    ).status_code == 422
    assert client.post(
        "/api/v1/payments",
        json={"availability_id": "00000000-0000-0000-0000-000000000000", "quantity": 51},
        headers=headers,
    ).status_code == 422
    for invalid_quantity in (0, -1):
        assert client.post(
            "/api/v1/payments",
            json={
                "availability_id": "00000000-0000-0000-0000-000000000000",
                "quantity": invalid_quantity,
            },
            headers=headers,
        ).status_code == 422


def test_availability_uses_dakar_timezone_and_rejects_elapsed_same_day(monkeypatch):
    from backend.app.core.time import market_datetime_as_utc
    from backend.app.schemas.availabilities import AvailabilityCreateRequest

    assert market_datetime_as_utc(date(2026, 1, 15), time(12)) == datetime(
        2026, 1, 15, 12, tzinfo=timezone.utc
    )
    monkeypatch.setattr(
        "backend.app.schemas.availabilities.utc_now",
        lambda: datetime(2026, 1, 15, 18, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "backend.app.schemas.availabilities.market_today",
        lambda: date(2026, 1, 15),
    )
    with pytest.raises(ValidationError, match="availability end must be in the future"):
        AvailabilityCreateRequest(
            dish_id="00000000-0000-0000-0000-000000000000",
            available_date=date(2026, 1, 15),
            start_time=time(11),
            end_time=time(12),
            total_portions=1,
        )


def test_database_foreign_keys_and_constraints_are_active(client):
    from backend.app.database import get_engine

    inspector = inspect(get_engine())
    availability_foreign_keys = inspector.get_foreign_keys("dish_availabilities")
    assert any(
        foreign_key["constrained_columns"] == ["dish_id"]
        and foreign_key["referred_table"] == "dishes"
        and foreign_key["referred_columns"] == ["id"]
        for foreign_key in availability_foreign_keys
    )
    assert {constraint["name"] for constraint in inspector.get_check_constraints("dishes")} >= {
        "ck_dishes_currency",
        "ck_dishes_price",
    }
    assert {constraint["name"] for constraint in inspector.get_check_constraints("dish_availabilities")} >= {
        "ck_dish_availabilities_remaining",
        "ck_dish_availabilities_stock",
        "ck_dish_availabilities_total",
    }


def test_alembic_builds_a_fresh_sqlite_schema(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    database_path = tmp_path / "alembic-fresh.db"
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    inspector = inspect(engine)
    assert {"users", "cook_profiles", "dishes", "dish_availabilities", "orders", "payments", "stock_holds"}.issubset(inspector.get_table_names())
    assert "checkout_token_hash" in {column["name"] for column in inspector.get_columns("payments")}
    assert inspector.get_check_constraints("payments")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    engine.dispose()

    command.downgrade(config, "base")
    downgraded_engine = create_engine(f"sqlite:///{database_path}")
    assert set(inspect(downgraded_engine).get_table_names()) - {"alembic_version"} == set()
    downgraded_engine.dispose()

    command.upgrade(config, "head")
    upgraded_engine = create_engine(f"sqlite:///{database_path}")
    assert {"users", "payments", "stock_holds"}.issubset(inspect(upgraded_engine).get_table_names())
    upgraded_engine.dispose()


def test_mobile_secure_store_and_permission_configuration():
    root = Path(__file__).resolve().parents[2]
    secure_session = (root / "mobile/src/services/secureSession.ts").read_text(encoding="utf-8")
    core = (root / "mobile/src/services/secureSessionCore.ts").read_text(encoding="utf-8")
    app_config = json.loads((root / "mobile/app.json").read_text(encoding="utf-8"))["expo"]

    assert "expo-secure-store" in secure_session
    assert "AsyncStorage.removeItem" in secure_session
    assert "console." not in secure_session + core
    assert app_config["ios"]["bundleIdentifier"] == "app.kwitli.mobile"
    assert app_config["android"]["package"] == "app.kwitli.mobile"
    blocked = set(app_config["android"]["blockedPermissions"])
    assert {
        "android.permission.RECORD_AUDIO",
        "android.permission.ACCESS_BACKGROUND_LOCATION",
        "android.permission.SYSTEM_ALERT_WINDOW",
        "android.permission.READ_EXTERNAL_STORAGE",
        "android.permission.WRITE_EXTERNAL_STORAGE",
    }.issubset(blocked)
    assert "android.permission.ACCESS_BACKGROUND_LOCATION" not in app_config["android"]["permissions"]
    location_plugin = next(
        plugin
        for plugin in app_config["plugins"]
        if isinstance(plugin, list) and plugin[0] == "expo-location"
    )
    assert location_plugin[1]["locationAlwaysAndWhenInUsePermission"] is False
    assert location_plugin[1]["locationAlwaysPermission"] is False
    assert location_plugin[1]["isIosBackgroundLocationEnabled"] is False
    secure_store_plugin = next(
        plugin
        for plugin in app_config["plugins"]
        if isinstance(plugin, list) and plugin[0] == "expo-secure-store"
    )
    assert secure_store_plugin[1]["faceIDPermission"] is False


def test_refund_service_is_an_abstraction_without_provider_refund_call():
    root = Path(__file__).resolve().parents[2]
    source = (root / "backend/app/services/refunds.py").read_text(encoding="utf-8")
    assert "class RefundService" in source
    assert "services.payments" not in source
    assert "requests." not in source
