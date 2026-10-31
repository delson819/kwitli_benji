import re
from datetime import time
from decimal import Decimal

from sqlalchemy import func, select

from backend.app.database import get_session_factory
from backend.app.persistence.models import CookProfile, CookProfileHour, Dish, Payment, PaymentItem, User


ADMIN_PASSWORD = "AdminPageTest123!"


def _register(client, email: str, first_name: str) -> None:
    response = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": ADMIN_PASSWORD,
        "first_name": first_name,
    })
    assert response.status_code == 201


def _make_admin(email: str) -> str:
    with get_session_factory()() as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None
        user.is_admin = True
        session.commit()
        return user.id


def _create_restaurant(email="restaurant@example.com", *, with_hours=True, with_dish=True,
                       latitude=14.6928, longitude=-17.4467):
    with get_session_factory()() as session:
        owner = User(email=email, password_hash=None, first_name="Restaurant", is_active=True)
        session.add(owner)
        session.flush()
        cook = CookProfile(
            user_id=owner.id,
            display_name="Restaurant Sénégal",
            bio="Cuisine sénégalaise faite maison.",
            latitude=latitude,
            longitude=longitude,
            business_vertical="food_service",
            is_verified=False,
        )
        session.add(cook)
        session.flush()
        if with_hours:
            for weekday in range(7):
                session.add(CookProfileHour(
                    cook_profile_id=cook.id,
                    weekday=weekday,
                    is_closed=False,
                    opens_at=time(10, 0),
                    closes_at=time(20, 0),
                ))
        if with_dish:
            session.add(Dish(
                cook_id=cook.id,
                name="Yassa de test",
                description="Poulet yassa.",
                price=Decimal("1450"),
                currency="XOF",
                is_active=True,
            ))
        session.commit()
        return cook.id


def _token(response, action):
    match = re.search(
        rf'<form method="post" action="/admin/restaurants/([^"]+)/decision">'
        rf'<input type="hidden" name="action" value="{action}">'
        rf'<input type="hidden" name="csrf_token" value="([^"]+)">',
        response.text,
    )
    assert match is not None
    return match.group(1), match.group(2)


def _post_action(client, admin_email, cook_id, action, token, reason=""):
    return client.post(
        f"/admin/restaurants/{cook_id}/decision",
        auth=(admin_email, ADMIN_PASSWORD),
        data={"action": action, "csrf_token": token, "reason": reason},
        follow_redirects=False,
    )


def _discover(client):
    return client.get("/api/v1/discover?latitude=14.6928&longitude=-17.4467&radius_km=5")


def test_admin_page_requires_authentication(client):
    response = client.get("/admin")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


def test_client_and_merchant_cannot_access_admin_page(client):
    _register(client, "admin-page-client@example.com", "Client")
    response = client.get("/admin", auth=("admin-page-client@example.com", ADMIN_PASSWORD))
    assert response.status_code == 403

    _register(client, "admin-page-merchant@example.com", "Commerce")
    with get_session_factory()() as session:
        user = session.scalar(select(User).where(User.email == "admin-page-merchant@example.com"))
        assert user is not None
        user.can_cook = True
        session.add(CookProfile(
            user_id=user.id,
            display_name="Commerce test",
            latitude=14.7,
            longitude=-17.4,
        ))
        session.commit()
    response = client.get("/admin", auth=("admin-page-merchant@example.com", ADMIN_PASSWORD))
    assert response.status_code == 403


def test_admin_sees_pending_real_restaurants_and_excludes_invalid_accounts(client):
    admin_email = "kwitli-admin@example.com"
    _register(client, admin_email, "Admin")
    _make_admin(admin_email)
    _create_restaurant()
    _create_restaurant("internal@kwitli.invalid")

    response = client.get("/admin", auth=(admin_email, ADMIN_PASSWORD))
    assert response.status_code == 200
    assert "Restaurants en attente" in response.text
    assert "Restaurant Sénégal" in response.text
    assert "pending_review" in response.text
    assert "Horaires configurés (7 jours)" in response.text
    assert "internal@kwitli.invalid" not in response.text
    assert "Prêt à valider" in response.text


def test_admin_checklist_blocks_complete_restaurant_outside_active_service_area(client):
    admin_email = "zone-checklist-admin@example.com"
    _register(client, admin_email, "Admin")
    _make_admin(admin_email)
    cook_id = _create_restaurant(
        "terrebonne-restaurant@example.com", latitude=45.7, longitude=-73.6,
    )
    response = client.get("/admin", auth=(admin_email, ADMIN_PASSWORD))

    assert response.status_code == 200
    assert "Restaurant situé hors des zones commerciales actuellement actives" in response.text
    assert "Point GPS dans une zone commerciale active" in response.text
    assert re.search(
        rf'<form method="post" action="/admin/restaurants/{re.escape(cook_id)}/decision">'
        r'.*?value="approve".*?<button type="submit" disabled',
        response.text,
        re.DOTALL,
    )
    with get_session_factory()() as session:
        cook = session.get(CookProfile, cook_id)
        assert cook.approval_status == "pending_review"
        assert cook.is_verified is False



def test_admin_approval_requires_complete_checklist_and_makes_restaurant_discoverable(client):
    admin_email = "approve-admin@example.com"
    _register(client, admin_email, "Admin")
    _make_admin(admin_email)
    cook_id = _create_restaurant(with_hours=False)

    page = client.get("/admin", auth=(admin_email, ADMIN_PASSWORD))
    _, approve_token = _token(page, "approve")
    blocked = _post_action(client, admin_email, cook_id, "approve", approve_token)
    assert blocked.status_code == 409
    assert "horaires des 7 jours" in blocked.text
    assert _discover(client).json() == []

    with get_session_factory()() as session:
        for weekday in range(7):
            session.add(CookProfileHour(
                cook_profile_id=cook_id,
                weekday=weekday,
                is_closed=False,
                opens_at=time(10, 0),
                closes_at=time(20, 0),
            ))
        session.commit()
    page = client.get("/admin", auth=(admin_email, ADMIN_PASSWORD))
    _, approve_token = _token(page, "approve")
    response = _post_action(client, admin_email, cook_id, "approve", approve_token)
    assert response.status_code == 303
    assert len(_discover(client).json()) == 1
    with get_session_factory()() as session:
        cook = session.get(CookProfile, cook_id)
        assert cook is not None
        assert cook.approval_status == "approved" and cook.is_verified is True


def test_admin_rejects_with_required_reason_and_restaurant_stays_hidden(client):
    admin_email = "reject-admin@example.com"
    _register(client, admin_email, "Admin")
    _make_admin(admin_email)
    cook_id = _create_restaurant()
    page = client.get("/admin", auth=(admin_email, ADMIN_PASSWORD))
    _, reject_token = _token(page, "reject")

    missing_reason = _post_action(client, admin_email, cook_id, "reject", reject_token)
    assert missing_reason.status_code == 409
    assert "raison est obligatoire" in missing_reason.text

    page = client.get("/admin", auth=(admin_email, ADMIN_PASSWORD))
    _, reject_token = _token(page, "reject")
    response = _post_action(client, admin_email, cook_id, "reject", reject_token, "Description à corriger")
    assert response.status_code == 303
    assert _discover(client).json() == []
    with get_session_factory()() as session:
        cook = session.get(CookProfile, cook_id)
        assert cook is not None
        assert cook.approval_status == "rejected"
        assert cook.approval_reason == "Description à corriger"
        assert cook.is_verified is False


def test_admin_can_suspend_and_reactivate_approved_restaurant(client):
    admin_email = "suspend-admin@example.com"
    _register(client, admin_email, "Admin")
    _make_admin(admin_email)
    cook_id = _create_restaurant()

    page = client.get("/admin", auth=(admin_email, ADMIN_PASSWORD))
    _, token = _token(page, "approve")
    assert _post_action(client, admin_email, cook_id, "approve", token).status_code == 303
    assert len(_discover(client).json()) == 1

    page = client.get("/admin", auth=(admin_email, ADMIN_PASSWORD))
    _, token = _token(page, "suspend")
    assert _post_action(client, admin_email, cook_id, "suspend", token, "Contrôle en cours").status_code == 303
    assert _discover(client).json() == []

    page = client.get("/admin", auth=(admin_email, ADMIN_PASSWORD))
    _, token = _token(page, "reactivate")
    assert _post_action(client, admin_email, cook_id, "reactivate", token).status_code == 303
    assert len(_discover(client).json()) == 1
    with get_session_factory()() as session:
        cook = session.get(CookProfile, cook_id)
        assert cook is not None and cook.approval_status == "approved" and cook.is_verified is True


def test_admin_decision_requires_valid_csrf_token(client):
    admin_email = "csrf-admin@example.com"
    _register(client, admin_email, "Admin")
    _make_admin(admin_email)
    cook_id = _create_restaurant()
    response = _post_action(client, admin_email, cook_id, "approve", "invalid")
    assert response.status_code == 403
    with get_session_factory()() as session:
        cook = session.get(CookProfile, cook_id)
        assert cook is not None and cook.approval_status == "pending_review"
