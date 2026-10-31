from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.core.service_areas import ServiceAreaInput
from backend.app.database import get_session_factory
from backend.app.persistence.models import ServiceAreaConfig, ServiceAreaEvent
from backend.app.repositories.service_areas import SqlAlchemyServiceAreaRepository


def _payload(**overrides):
    values = {
        "area_id": "north-city", "code": "XX-NC", "label": "North City",
        "country_code": "XX", "country": "Exampleland", "city": "North City",
        "center_latitude": 10.0, "center_longitude": 20.0, "radius_km": 12,
        "timezone": "Etc/UTC", "locale": "en", "currency": "USD",
        "distance_unit": "km", "status": "planned",
    }
    return ServiceAreaInput.model_validate({**values, **overrides})


def test_public_contract_is_preserved_and_only_active_database_zones_are_returned(client):
    response = client.get("/api/v1/service-areas")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    areas = response.json()
    assert {area["id"] for area in areas} == {"legacy-bogota-test", "sn-dakar", "ca-sherbrooke-dev"}
    assert all(set(area) == {
        "id", "code", "label", "country_code", "country", "city", "latitude",
        "longitude", "radius_km", "timezone", "active",
    } for area in areas)
    assert all(area["active"] is True for area in areas)

    with get_session_factory()() as session:
        sherbrooke = session.scalar(select(ServiceAreaConfig).where(
            ServiceAreaConfig.area_id == "ca-sherbrooke-dev",
        ))
        sherbrooke.status = "suspended"
        session.commit()

    areas = client.get("/api/v1/service-areas").json()
    assert "ca-sherbrooke-dev" not in {area["id"] for area in areas}


def test_service_area_data_is_isolated_by_environment_and_unknown_environment_fails_closed():
    with get_session_factory()() as session:
        repo = SqlAlchemyServiceAreaRepository(session)
        assert repo.contains_active_location(4.65, -74.06, "test")
        assert not repo.contains_active_location(4.65, -74.06, "staging")
        assert not repo.contains_active_location(4.65, -74.06, "production")
        assert repo.contains_active_location(4.65, -74.06, "development") is False


def test_active_polygon_is_not_published_or_used_until_polygon_support_exists(client):
    with get_session_factory()() as session:
        session.add(ServiceAreaConfig(
            area_id="future-polygon", environment="test", code="XX-POLYGON",
            label="Future polygon", country_code="XX", country="Exampleland", city="Polygon City",
            center_latitude=None, center_longitude=None, radius_km=None, geometry_type="polygon",
            geometry_metadata={"type": "Polygon", "coordinates": []}, timezone="Etc/UTC",
            locale="en", currency="USD", distance_unit="km", status="active", version=1,
        ))
        session.commit()
        assert not SqlAlchemyServiceAreaRepository(session).contains_active_location(30, 30, "test")
    response = client.get("/api/v1/service-areas")
    assert response.status_code == 200
    assert "future-polygon" not in {area["id"] for area in response.json()}


def test_admin_creates_planned_zone_then_activates_with_reason_and_audit(client):
    from backend.app.persistence.models import User

    password = "ServiceAreaAdmin123!"

    email = "service-area-admin@example.com"
    registered = client.post("/api/v1/auth/register", json={
        "email": email, "password": password, "first_name": "Admin",
    })
    assert registered.status_code == 201
    with get_session_factory()() as session:
        admin = session.scalar(select(User).where(User.email == email))
        admin.is_admin = True
        admin_id = admin.id
        session.commit()
    page = client.get("/admin", auth=(email, password))
    assert page.status_code == 200
    assert "Zones commerciales" in page.text
    create_form = page.text.split('action="/admin/service-areas/create"', 1)[1].split("</form>", 1)[0]
    assert 'name="status" value="planned"' in create_form
    assert '<select name="status">' not in create_form
    import re
    token = re.search(
        r'action="/admin/service-areas/create">.*?name="csrf_token" value="([^"]+)"',
        page.text, re.DOTALL,
    )
    assert token is not None
    token = token.group(1)
    form = {**_payload().model_dump(), "status": "active", "reason": "Configuration approuvée",
            "csrf_token": token}
    response = client.post("/admin/service-areas/create", auth=(email, password), data=form,
                           follow_redirects=False)
    assert response.status_code == 303
    with get_session_factory()() as session:
        area = session.scalar(select(ServiceAreaConfig).where(ServiceAreaConfig.area_id == "north-city"))
        assert area.status == "planned"  # create ne peut jamais ouvrir immédiatement un marché
        assert area.environment == "test"
        assert area.version == 1
        event = session.scalar(select(ServiceAreaEvent).where(ServiceAreaEvent.service_area_row_id == area.row_id))
        assert event.actor_user_id == admin_id
        assert event.reason == "Configuration approuvée"
        active_payload = _payload(status="active")
        repo = SqlAlchemyServiceAreaRepository(session)
        updated = repo.update(area.row_id, 1, active_payload, "test", admin_id, "Validation du marché")
        assert updated.status == "active"
        assert updated.version == 2
        assert len(repo.history(area.row_id, "test")) == 2


def test_stale_admin_update_is_rejected_without_losing_audit_or_overwriting_new_version():
    from backend.app.persistence.models import User
    from backend.app.repositories.service_areas import ServiceAreaConflictError
    import pytest

    with get_session_factory()() as session:
        actor = User(email="zone-concurrency@example.invalid", password_hash=None,
                     first_name="Test", is_active=True)
        session.add(actor)
        session.flush()
        repo = SqlAlchemyServiceAreaRepository(session)
        area = repo.create(_payload(), "test", actor.id, "Initialisation")
        repo.update(area.row_id, 1, _payload(status="active"), "test", actor.id, "Activation")
        with pytest.raises(ServiceAreaConflictError, match="modifiée depuis son affichage"):
            repo.update(area.row_id, 1, _payload(status="suspended"), "test", actor.id, "Suspension obsolète")
        stored = session.get(ServiceAreaConfig, area.row_id)
        assert stored.status == "active"
        assert stored.version == 2
        assert len(repo.history(area.row_id, "test")) == 2


def test_service_area_can_be_suspended_and_reactivated_with_separate_audit_versions():
    from backend.app.persistence.models import User

    with get_session_factory()() as session:
        actor = User(email="zone-reactivation@example.invalid", password_hash=None,
                     first_name="Test", is_active=True)
        session.add(actor)
        session.flush()
        repo = SqlAlchemyServiceAreaRepository(session)
        area = repo.create(_payload(), "test", actor.id, "Initialisation")
        area = repo.update(area.row_id, 1, _payload(status="active"), "test", actor.id, "Activation")
        area = repo.update(area.row_id, 2, _payload(status="suspended"), "test", actor.id, "Suspension")
        area = repo.update(area.row_id, 3, _payload(status="active"), "test", actor.id, "Réactivation")
        assert area.status == "active"
        assert area.version == 4
        history = repo.history(area.row_id, "test")
        assert [event.action for event in history] == ["created", "updated", "updated", "updated"]
        assert [event.to_version for event in history] == [1, 2, 3, 4]


def test_service_area_history_rejects_mutation():
    import pytest
    from sqlalchemy.exc import SQLAlchemyError
    from backend.app.persistence.models import User

    with get_session_factory()() as session:
        actor = User(email="zone-history@example.invalid", password_hash=None,
                     first_name="Test", is_active=True)
        session.add(actor)
        session.flush()
        area = SqlAlchemyServiceAreaRepository(session).create(_payload(), "test", actor.id, "Audit immuable")
        event_id = SqlAlchemyServiceAreaRepository(session).history(area.row_id, "test")[0].id
        with pytest.raises(SQLAlchemyError):
            session.execute(
                ServiceAreaEvent.__table__.delete().where(ServiceAreaEvent.id == event_id)
            )
        session.rollback()


def test_concurrent_admin_updates_from_same_version_allow_only_one_winner():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from backend.app.persistence.models import User
    from backend.app.repositories.service_areas import ServiceAreaConflictError

    with get_session_factory()() as session:
        actor = User(email="zone-race@example.invalid", password_hash=None,
                     first_name="Test", is_active=True)
        session.add(actor)
        session.commit()
        actor_id = actor.id
        area = SqlAlchemyServiceAreaRepository(session).create(
            _payload(), "test", actor_id, "Initialisation concurrencée"
        )
        row_id = area.row_id
    barrier = Barrier(2)

    def update(status):
        with get_session_factory()() as session:
            barrier.wait(timeout=5)
            try:
                SqlAlchemyServiceAreaRepository(session).update(
                    row_id, 1, _payload(status=status), "test", actor_id, f"État {status}"
                )
                return "updated"
            except ServiceAreaConflictError:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(update, state) for state in ("active", "suspended")]
        outcomes = sorted(future.result(timeout=10) for future in futures)
    assert outcomes == ["conflict", "updated"]
    with get_session_factory()() as session:
        assert len(SqlAlchemyServiceAreaRepository(session).history(row_id, "test")) == 2


def test_commercial_decision_lock_serializes_zone_suspension():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import sleep
    from backend.app.persistence.models import User

    with get_session_factory()() as session:
        actor = User(email="zone-decision-lock@example.invalid", password_hash=None,
                     first_name="Test", is_active=True)
        session.add(actor)
        session.commit()
        actor_id = actor.id
        repo = SqlAlchemyServiceAreaRepository(session)
        area = repo.create(_payload(), "test", actor_id, "Initialisation verrou")
        area = repo.update(area.row_id, 1, _payload(status="active"), "test", actor_id, "Activation")
        row_id = area.row_id

    decision_locked = Event()
    release_decision = Event()

    def commercial_decision():
        with get_session_factory()() as session:
            assert SqlAlchemyServiceAreaRepository(session).contains_active_location(
                10, 20, "test", lock=True,
            )
            decision_locked.set()
            assert release_decision.wait(timeout=5)
            session.commit()
            return "decision_committed"

    def suspend_area():
        assert decision_locked.wait(timeout=5)
        with get_session_factory()() as session:
            SqlAlchemyServiceAreaRepository(session).update(
                row_id, 2, _payload(status="suspended"), "test", actor_id,
                "Suspension concurrente après décision",
            )
            return "suspension_committed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        decision = pool.submit(commercial_decision)
        suspension = pool.submit(suspend_area)
        assert decision_locked.wait(timeout=5)
        sleep(0.15)
        assert not suspension.done()  # FOR UPDATE attend la décision sous FOR SHARE.
        release_decision.set()
        assert decision.result(timeout=5) == "decision_committed"
        assert suspension.result(timeout=5) == "suspension_committed"

    with get_session_factory()() as session:
        area = session.get(ServiceAreaConfig, row_id)
        assert area.status == "suspended"
        assert not SqlAlchemyServiceAreaRepository(session).contains_active_location(10, 20, "test")


def test_zone_management_post_requires_admin_authentication(client):
    assert client.post("/admin/service-areas/create", data={}).status_code == 401
    password = "NonAdminZone123!"
    email = "not-zone-admin@example.com"
    assert client.post("/api/v1/auth/register", json={
        "email": email, "password": password, "first_name": "Client",
    }).status_code == 201
    assert client.post("/admin/service-areas/create", auth=(email, password), data={}).status_code == 403


def test_suspension_removes_zone_from_new_decisions_without_changing_existing_order():
    from decimal import Decimal
    from backend.app.persistence.models import Order, User

    with get_session_factory()() as session:
        owner = User(email="zone-order-owner@example.invalid", password_hash=None,
                     first_name="Test", is_active=True)
        customer = User(email="zone-order-customer@example.invalid", password_hash=None,
                        first_name="Test", is_active=True)
        session.add_all([owner, customer])
        session.flush()
        repo = SqlAlchemyServiceAreaRepository(session)
        area = repo.create(_payload(status="active"), "test", owner.id, "Zone créée avant activation")
        repo.update(area.row_id, 1, _payload(status="active"), "test", owner.id, "Zone active pour test")
        area = session.get(ServiceAreaConfig, area.row_id)
        order = Order(customer_id=customer.id, total_price=Decimal("10.00"), currency="COP", status="confirmed")
        session.add(order)
        session.commit()
        assert repo.contains_active_location(10, 20, "test")
        repo.update(area.row_id, 2, _payload(status="suspended"), "test", owner.id, "Suspension administrative")
        assert not repo.contains_active_location(10, 20, "test")
        stored_order = session.get(Order, order.id)
        assert stored_order.status == "confirmed"
