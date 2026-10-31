from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.database import get_session_factory
from backend.app.persistence.models import Dish, DishAvailability, Order, Payment, PaymentIdempotencyKey, User
from backend.tests.test_mvp import create_cook_marketplace, payu_confirmation, register


def checkout_fixture(client):
    cook, _, _, availability = create_cook_marketplace(client)
    customer = register(client, "payment-idempotency@example.co", "Client")
    return cook, customer, availability, {"items": [{"availability_id": availability["id"], "quantity": 2}]}


def post_payment(client, auth, payload, key):
    return client.post("/api/v1/payments", headers={**auth, "Idempotency-Key": key}, json=payload)


def test_identical_replay_after_lost_response_returns_same_attempt_and_action(client):
    _, customer, _, payload = checkout_fixture(client)
    key = "checkout-session:attempt-0"
    first = post_payment(client, customer, payload, key)
    assert first.status_code == 201
    first_payment = first.json()

    # Simuler une reponse perdue : le premier resultat est ignore, puis le meme POST est rejoue.
    replay = post_payment(client, customer, payload, key)
    assert replay.status_code == 201
    assert replay.json()["id"] == first_payment["id"]
    assert replay.json()["provider_reference"] == first_payment["provider_reference"]
    assert replay.json()["checkout_url"] == first_payment["checkout_url"]
    restored = client.get(f"/api/v1/payments/{first_payment['id']}", headers=customer)
    assert restored.status_code == 200
    assert restored.json()["checkout_url"] == first_payment["checkout_url"]
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(Payment.id))) == 1
        assert session.scalar(select(func.count(PaymentIdempotencyKey.id))) == 1


def test_concurrent_identical_posts_create_one_payment(client):
    _, customer, _, payload = checkout_fixture(client)
    key = "checkout-session:parallel-0"
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: post_payment(client, customer, payload, key), range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(Payment.id))) == 1
        assert session.scalar(select(func.count(PaymentIdempotencyKey.id))) == 1


def test_same_intention_with_new_key_aliases_pending_attempt_but_changed_cart_conflicts(client):
    _, customer, _, payload = checkout_fixture(client)
    original = post_payment(client, customer, payload, "checkout-session:first-try")
    assert original.status_code == 201
    alias = post_payment(client, customer, payload, "checkout-session:other-device")
    assert alias.status_code == 201 and alias.json()["id"] == original.json()["id"]

    changed = {"items": [{"availability_id": payload["items"][0]["availability_id"], "quantity": 3}]}
    conflict = post_payment(client, customer, changed, "checkout-session:first-try")
    assert conflict.status_code == 409
    changed_key = post_payment(client, customer, changed, "checkout-session:changed-cart")
    assert changed_key.status_code == 409
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(Payment.id))) == 1
        assert session.scalar(select(func.count(PaymentIdempotencyKey.id))) == 2


def test_same_key_cannot_reuse_after_server_amount_currency_or_provider_changes(client, monkeypatch):
    _, customer, availability, payload = checkout_fixture(client)
    key = "checkout-session:immutable-intent"
    initial = post_payment(client, customer, payload, key)
    assert initial.status_code == 201

    with get_session_factory()() as session:
        dish = session.get(Dish, session.get(DishAvailability, availability["id"]).dish_id)
        dish.price = Decimal("21000.00")
        session.commit()
    assert post_payment(client, customer, payload, key).status_code == 409

    with get_session_factory()() as session:
        dish = session.get(Dish, session.get(DishAvailability, availability["id"]).dish_id)
        dish.price = Decimal("19000.00")
        dish.currency = "XOF"
        session.commit()
    settings = get_settings()
    monkeypatch.setattr(settings, "xof_payment_provider", "paytech")
    assert post_payment(client, customer, payload, key).status_code == 409
    assert post_payment(client, customer, payload, "checkout-session:different-provider").status_code == 409
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(Payment.id))) == 1


def test_new_attempt_is_allowed_after_confirmed_failure_and_callback_stays_idempotent(client):
    _, customer, availability, payload = checkout_fixture(client)
    failed = post_payment(client, customer, payload, "checkout-session:failed-attempt")
    assert failed.status_code == 201
    payment = failed.json()
    assert client.post("/api/v1/payments/payu/confirmation", data=payu_confirmation(payment, "6")).status_code == 200

    retry = post_payment(client, customer, payload, "checkout-session:new-attempt")
    assert retry.status_code == 201 and retry.json()["id"] != payment["id"]
    approved_event = payu_confirmation(retry.json())
    assert client.post("/api/v1/payments/payu/confirmation", data=approved_event).status_code == 200
    assert client.post("/api/v1/payments/payu/confirmation", data=approved_event).status_code == 200
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(Order.id))) == 1
        assert session.scalar(select(func.count(Payment.id))) == 2


def test_payment_key_required_and_attempt_is_owner_scoped(client):
    _, customer, _, payload = checkout_fixture(client)
    missing = client.post_without_payment_key("/api/v1/payments", headers=customer, json=payload)
    assert missing.status_code == 422
    created = post_payment(client, customer, payload, "checkout-session:owner-only")
    assert created.status_code == 201
    other = register(client, "other-payment-owner@example.co", "Autre client")
    assert client.get(f"/api/v1/payments/{created.json()['id']}", headers=other).status_code == 403


def test_legacy_pending_payment_is_not_reused_or_duplicated(client):
    _, customer, availability, payload = checkout_fixture(client)
    legacy = client.post_without_payment_key(
        "/api/v1/payments", headers=customer, json=payload,
    )
    # Le client de test exige normalement une cle; creer ici un enregistrement legacy via le service.
    assert legacy.status_code == 422
    with get_session_factory()() as session:
        from backend.app.repositories.sqlalchemy import SqlAlchemyMarketplaceRepository
        from backend.app.core.time import utc_now
        from datetime import timedelta
        user_id = session.scalar(select(User.id).where(User.email == "payment-idempotency@example.co"))

        payment_id = str(uuid4())
        token_hash = sha256(b"legacy-token").hexdigest()
        repo = SqlAlchemyMarketplaceRepository(session)
        repo.create_pending_payment_with_hold(
            user_id=user_id,
            availability_id=availability["id"], quantity=2,
            payment_id=payment_id, provider_reference=f"KWITLI{payment_id.replace('-', '').upper()}",
            expires_at=utc_now() + timedelta(minutes=10), checkout_token_hash=token_hash,
            checkout_token_expires_at=utc_now() + timedelta(minutes=10), now=utc_now(),
            max_active_holds_per_user=10, max_held_portions_per_user=100,
        )
        historical = session.get(Payment, payment_id)
        historical.idempotency_fingerprint = None
        historical.idempotency_group = None
        session.commit()
    blocked = post_payment(client, customer, payload, "checkout-session:after-upgrade")
    assert blocked.status_code == 409
    with get_session_factory()() as session:
        assert session.scalar(select(func.count(Payment.id))) == 1
