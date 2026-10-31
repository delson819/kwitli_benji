import asyncio
import hashlib
from datetime import date, datetime, timedelta
from decimal import Decimal
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select, update
from starlette.datastructures import Headers, UploadFile


def register(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "ClaveSegura123!", "first_name": "Kwitli"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def open_payu_checkout(client, checkout_url: str):
    parsed = urlparse(checkout_url)
    token = parse_qs(parsed.fragment)["token"][0]
    return client.post(parsed.path, data={"token": token})


def create_market(client, *, portions: int = 8):
    cook_headers = register(client, "security-cook@example.co")
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
            "available_date": str(date.today() + timedelta(days=1)),
            "start_time": "11:00:00",
            "end_time": "22:00:00",
            "total_portions": portions,
        },
        headers=cook_headers,
    ).json()
    return cook_headers, cook, dish, availability


def confirmation(payment: dict, *, state: str, transaction_id: str) -> dict[str, str]:
    raw_value = format(Decimal(payment["amount_in_cents"]) / 100, ".2f")
    normalized = format(Decimal(raw_value), ".1f") if raw_value.endswith("0") else raw_value
    payload = {
        "merchant_id": "test-merchant",
        "reference_sale": payment["provider_reference"],
        "value": raw_value,
        "currency": "COP",
        "state_pol": state,
        "transaction_id": transaction_id,
    }
    payload["sign"] = hashlib.sha256(
        f"test-api-key~test-merchant~{payment['provider_reference']}~{normalized}~COP~{state}".encode()
    ).hexdigest()
    return payload


def test_private_user_data_requires_owner_jwt(client):
    first_headers = register(client, "private-a@example.co")
    second_headers = register(client, "private-b@example.co")
    first = client.get("/api/v1/me", headers=first_headers).json()["user"]
    second = client.get("/api/v1/me", headers=second_headers).json()["user"]

    assert client.get(f"/api/v1/users/{first['id']}").status_code == 401
    assert client.get(f"/api/v1/users/{second['id']}", headers=first_headers).status_code == 404
    own = client.get(f"/api/v1/users/{first['id']}", headers=first_headers)
    assert own.status_code == 200
    assert own.json()["email"] == "private-a@example.co"
    assert client.get("/api/v1/me", headers=first_headers).status_code == 200


def test_public_cook_profile_contains_no_private_user_data(client):
    _headers, cook, _dish, _availability = create_market(client)
    profile = client.get(f"/api/v1/cooks/{cook['id']}/public")

    assert profile.status_code == 200
    assert {"email", "phone", "password_hash", "user_id", "latitude", "longitude"}.isdisjoint(profile.json())


def test_discover_requires_bounded_location_and_hides_pickup_coordinates(client):
    create_market(client)

    assert client.get("/api/v1/discover").status_code == 422
    assert client.get("/api/v1/discover?latitude=91&longitude=-74.06&radius_km=5").status_code == 422
    assert client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=100").status_code == 422
    response = client.get("/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5")

    assert response.status_code == 200
    assert response.json()[0]["distance_km"] == 0
    assert {"latitude", "longitude"}.isdisjoint(response.json()[0])


def test_payu_declined_attempt_can_be_followed_by_approved_attempt(client):
    _cook_headers, _cook, _dish, availability = create_market(client)
    customer_headers = register(client, "payu-retry@example.co")
    payment = client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=customer_headers,
    ).json()
    declined = confirmation(payment, state="6", transaction_id="transaction-a")
    approved = confirmation(payment, state="4", transaction_id="transaction-b")

    assert client.post("/api/v1/payments/payu/confirmation", data=declined).status_code == 200
    assert client.get(f"/api/v1/payments/{payment['id']}", headers=customer_headers).json()["status"] == "declined"
    assert client.post("/api/v1/payments/payu/confirmation", data=approved).status_code == 200
    assert client.post("/api/v1/payments/payu/confirmation", data=approved).status_code == 200
    assert client.post("/api/v1/payments/payu/confirmation", data=declined).status_code == 200

    from backend.app.database import get_session_factory
    from backend.app.persistence.models import Payment, StockHold

    with get_session_factory()() as session:
        stored = session.get(Payment, payment["id"])
        hold = session.scalar(select(StockHold).where(StockHold.payment_id == payment["id"]))
        assert stored is not None and stored.status == "approved"
        assert stored.provider_transaction_id == "transaction-b"
        assert hold is not None and hold.status == "consumed"
    assert len(client.get("/api/v1/orders", headers=customer_headers).json()) == 1
    assert client.get(f"/api/v1/availabilities/{availability['id']}", headers=_cook_headers).json()["remaining_portions"] == 7


def test_checkout_requires_active_unexpired_hold(client):
    _cook_headers, _cook, _dish, availability = create_market(client)
    customer_headers = register(client, "checkout-expired@example.co")
    payment = client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=customer_headers,
    ).json()
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import Payment, StockHold

    with get_session_factory()() as session:
        session.execute(
            update(StockHold)
            .where(StockHold.payment_id == payment["id"])
            .values(expires_at=datetime.now() - timedelta(seconds=1))
        )
        session.commit()
    assert open_payu_checkout(client, payment["checkout_url"]).status_code == 409
    with get_session_factory()() as session:
        stored = session.get(Payment, payment["id"])
        hold = session.scalar(select(StockHold).where(StockHold.payment_id == payment["id"]))
        assert stored is not None and stored.status == "error"
        assert hold is not None and hold.status == "expired"


@pytest.mark.parametrize("payment_status", ("approved", "cancelled", "error"))
def test_checkout_rejects_non_pending_payment(client, payment_status):
    _cook_headers, _cook, _dish, availability = create_market(client)
    customer_headers = register(client, f"checkout-{payment_status}@example.co")
    payment = client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=customer_headers,
    ).json()

    from backend.app.database import get_session_factory
    from backend.app.persistence.models import Payment

    with get_session_factory()() as session:
        session.execute(update(Payment).where(Payment.id == payment["id"]).values(status=payment_status))
        session.commit()
    assert open_payu_checkout(client, payment["checkout_url"]).status_code == 409


def test_profile_upload_authorization_happens_before_file_write(client):
    headers = register(client, "not-a-cook@example.co")
    from backend.app.core.config import get_settings

    upload_dir = Path(get_settings().upload_dir)
    before = set(upload_dir.iterdir())
    response = client.post(
        "/api/v1/cooks/me/photo",
        headers=headers,
        files={"image": ("profile.jpg", b"\xff\xd8\xff\xe0content", "image/jpeg")},
    )

    assert response.status_code == 403
    assert set(upload_dir.iterdir()) == before


def test_dish_upload_authorization_happens_before_file_write(client):
    _headers, _cook, dish, _availability = create_market(client)
    intruder_headers = register(client, "dish-photo-intruder@example.co")
    from backend.app.core.config import get_settings

    upload_dir = Path(get_settings().upload_dir)
    before = set(upload_dir.iterdir())
    response = client.post(
        f"/api/v1/dishes/{dish['id']}/photo",
        headers=intruder_headers,
        files={"image": ("dish.jpg", b"\xff\xd8\xff\xe0content", "image/jpeg")},
    )

    assert response.status_code == 403
    assert set(upload_dir.iterdir()) == before


def test_upload_rate_limit_runs_before_file_write(client, image_bytes):
    headers, _cook, dish, _availability = create_market(client)
    from backend.app.core.config import get_settings

    settings = get_settings()
    settings.rate_limit_upload_requests = 1
    upload_dir = Path(settings.upload_dir)
    payload = {"image": ("dish.jpg", image_bytes("JPEG"), "image/jpeg")}
    assert client.post(f"/api/v1/dishes/{dish['id']}/photo", headers=headers, files=payload).status_code == 200
    before = set(upload_dir.iterdir())
    blocked = client.post(f"/api/v1/dishes/{dish['id']}/photo", headers=headers, files=payload)

    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert set(upload_dir.iterdir()) == before


def test_upload_request_body_is_bounded_before_authentication(client):
    from backend.app.core.config import get_settings

    max_bytes = get_settings().upload_max_bytes
    response = client.post(
        "/api/v1/cooks/me/photo",
        content=b"",
        headers={"Content-Length": str(max_bytes + 65 * 1024)},
    )
    streamed = client.post(
        "/api/v1/cooks/me/photo",
        files={"image": ("oversized.jpg", b"\xff\xd8\xff" + b"x" * (max_bytes + 65 * 1024), "image/jpeg")},
        headers={"Content-Length": "1"},
    )

    assert response.status_code == 413
    assert streamed.status_code == 413


def test_upload_limits_types_sizes_and_cleans_partial_files(client, tmp_path, monkeypatch, image_bytes):
    headers, _cook, dish, _availability = create_market(client)
    svg = client.post(
        f"/api/v1/dishes/{dish['id']}/photo",
        headers=headers,
        files={"image": ("dish.svg", b"<svg></svg>", "image/svg+xml")},
    )
    too_large = client.post(
        f"/api/v1/dishes/{dish['id']}/photo",
        headers=headers,
        files={"image": ("dish.jpg", b"\xff\xd8\xff" + b"x" * (5 * 1024 * 1024), "image/jpeg")},
    )
    assert svg.status_code == 415
    assert too_large.status_code == 413
    assert version("python-multipart") == "0.0.31"

    from backend.app.services.storage import LocalImageStorage

    storage_dir = tmp_path / "partial-upload"
    storage = LocalImageStorage(storage_dir, 1024)
    upload = UploadFile(
        BytesIO(image_bytes("JPEG")),
        filename="dish.jpg",
        headers=Headers({"content-type": "image/jpeg"}),
    )

    def fail_replace(_source, _target):
        raise OSError("simulated write failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        asyncio.run(storage.save_image(upload))
    assert list(storage_dir.iterdir()) == []


def test_active_hold_limits_expire_and_are_isolated_by_user(client):
    _cook_headers, _cook, _dish, availability = create_market(client)
    from backend.app.core.config import get_settings
    from backend.app.database import get_session_factory
    from backend.app.persistence.models import StockHold

    settings = get_settings()
    settings.max_active_holds_per_user = 2
    first_headers = register(client, "hold-limit-a@example.co")
    second_headers = register(client, "hold-limit-b@example.co")
    payload = {"availability_id": availability["id"], "quantity": 1}
    first = client.post("/api/v1/payments", json=payload, headers=first_headers)
    assert first.status_code == 201
    replay = client.post("/api/v1/payments", json=payload, headers=first_headers)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert client.post("/api/v1/payments", json=payload, headers=second_headers).status_code == 201

    with get_session_factory()() as session:
        session.execute(
            update(StockHold)
            .where(StockHold.payment_id == first.json()["id"])
            .values(expires_at=datetime.now() - timedelta(seconds=1))
        )
        session.commit()
    restarted = client.post("/api/v1/payments", json=payload, headers=first_headers)
    assert restarted.status_code == 201
    assert restarted.json()["id"] == first.json()["id"]


def test_held_portion_limit_is_enforced(client):
    _cook_headers, _cook, _dish, availability = create_market(client)
    from backend.app.core.config import get_settings

    settings = get_settings()
    settings.max_active_holds_per_user = 10
    settings.max_held_portions_per_user = 2
    headers = register(client, "held-portions@example.co")
    assert client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 2},
        headers=headers,
    ).status_code == 201
    assert client.post(
        "/api/v1/payments",
        json={"availability_id": availability["id"], "quantity": 1},
        headers=headers,
    ).status_code == 409


def test_login_rate_limit_returns_retry_after(client):
    from backend.app.core.config import get_settings

    limit = get_settings().rate_limit_login_requests
    payload = {"email": "unknown@example.co", "password": "wrong"}
    for _attempt in range(limit):
        assert client.post("/api/v1/auth/login", json=payload).status_code == 401
    blocked = client.post("/api/v1/auth/login", json=payload)

    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_authenticated_rate_limit_does_not_mix_users(client):
    _cook_headers, _cook, _dish, availability = create_market(client)
    from backend.app.core.config import get_settings

    get_settings().rate_limit_payment_requests = 1
    first_headers = register(client, "rate-user-a@example.co")
    second_headers = register(client, "rate-user-b@example.co")
    payload = {"availability_id": availability["id"], "quantity": 1}

    assert client.post("/api/v1/payments", json=payload, headers=first_headers).status_code == 201
    blocked = client.post("/api/v1/payments", json=payload, headers=first_headers)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    assert client.post("/api/v1/payments", json=payload, headers=second_headers).status_code == 201


def test_discover_rate_limit_ignores_untrusted_forwarded_for(client):
    from backend.app.core.config import get_settings

    get_settings().rate_limit_discover_requests = 1
    path = "/api/v1/discover?latitude=4.65&longitude=-74.06&radius_km=5"
    assert client.get(path, headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    blocked = client.get(path, headers={"X-Forwarded-For": "198.51.100.2"})
    assert blocked.status_code == 429
