from datetime import timedelta
import hashlib

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.core.time import utc_now
from backend.app.database import get_session_factory
from backend.app.persistence.models import PasswordResetToken, User
from backend.app.security import hash_password
from backend.app.services.password_reset_email import get_password_reset_email_sender


class FakePasswordResetEmailSender:
    is_configured = True

    def __init__(self, *, fail: bool = False):
        self.messages: list[tuple[str, str]] = []
        self.fail = fail

    def send_password_reset(self, email: str, token: str) -> None:
        if self.fail:
            raise RuntimeError("fake email transport failure")
        self.messages.append((email, token))


def _register(client, email: str = "reset@example.com") -> tuple[dict[str, str], str]:
    response = client.post("/api/v1/auth/register", json={
        "email": email, "password": "InitialSecure123!", "first_name": "Test",
    })
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, response.json()["access_token"]


def _install_sender(client, sender: FakePasswordResetEmailSender) -> None:
    client.app.dependency_overrides[get_password_reset_email_sender] = lambda: sender


def test_password_reset_response_is_generic_and_default_sender_creates_no_token(client):
    _register(client)
    expected = {
        "message": "Si un compte correspond a cette adresse, les instructions seront envoyees lorsque le service sera disponible."
    }

    known = client.post("/api/v1/auth/password-reset/request", json={"email": "RESET@example.com"})
    unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "missing@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == expected
    with get_session_factory()() as session:
        assert session.scalar(select(PasswordResetToken.id)) is None


def test_password_reset_hashes_one_time_token_and_revokes_old_access_tokens(client):
    _old_headers, old_token = _register(client)
    sender = FakePasswordResetEmailSender()
    _install_sender(client, sender)

    requested = client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "RESET@example.com"},
    )
    assert requested.status_code == 202
    assert len(sender.messages) == 1
    recipient, raw_token = sender.messages[0]
    assert recipient == "reset@example.com"
    assert raw_token not in requested.text
    expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with get_session_factory()() as session:
        token_row = session.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == expected_hash))
        assert token_row is not None
        assert raw_token not in token_row.token_hash

    completed = client.post("/api/v1/auth/password-reset/confirm", json={
        "token": raw_token, "new_password": "ReplacementSecure456!",
    })
    assert completed.status_code == 200
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={
        "email": "reset@example.com", "password": "InitialSecure123!",
    }).status_code == 401
    login = client.post("/api/v1/auth/login", json={
        "email": "RESET@example.com", "password": "ReplacementSecure456!",
    })
    assert login.status_code == 200
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}).status_code == 200
    reused = client.post("/api/v1/auth/password-reset/confirm", json={
        "token": raw_token, "new_password": "AnotherSecure789!",
    })
    assert reused.status_code == 400


@pytest.mark.parametrize("token_state", ["expired", "unknown"])
def test_password_reset_rejects_expired_or_unknown_tokens(client, token_state: str):
    _register(client)
    sender = FakePasswordResetEmailSender()
    _install_sender(client, sender)
    assert client.post("/api/v1/auth/password-reset/request", json={"email": "reset@example.com"}).status_code == 202
    token = sender.messages[0][1] if token_state == "expired" else "x" * 48

    if token_state == "expired":
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with get_session_factory()() as session:
            row = session.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
            row.expires_at = utc_now() - timedelta(seconds=1)
            session.commit()

    response = client.post("/api/v1/auth/password-reset/confirm", json={
        "token": token, "new_password": "ReplacementSecure456!",
    })
    assert response.status_code == 400
    assert response.json() == {"detail": "Lien de recuperation invalide ou expire."}


def test_password_reset_sender_failure_does_not_expose_account_or_leave_token_active(client):
    _register(client)
    sender = FakePasswordResetEmailSender(fail=True)
    _install_sender(client, sender)

    response = client.post("/api/v1/auth/password-reset/request", json={"email": "reset@example.com"})
    assert response.status_code == 202
    with get_session_factory()() as session:
        row = session.scalar(select(PasswordResetToken))
        assert row is not None and row.used_at is not None


def test_password_reset_requests_are_rate_limited(client):
    expected = {
        "message": "Si un compte correspond a cette adresse, les instructions seront envoyees lorsque le service sera disponible."
    }
    for _ in range(3):
        response = client.post("/api/v1/auth/password-reset/request", json={"email": "unknown@example.com"})
        assert response.status_code == 202
        assert response.json() == expected
    limited = client.post("/api/v1/auth/password-reset/request", json={"email": "unknown@example.com"})
    assert limited.status_code == 429


def test_ambiguous_legacy_account_does_not_receive_reset_email():
    from unittest.mock import Mock

    from backend.app.services.marketplace import MarketplaceService

    sender = FakePasswordResetEmailSender()
    repository = Mock()
    repository.get_user_by_email.return_value = None
    MarketplaceService(repository).request_password_reset("legacy@example.com", sender)
    repository.get_user_by_email.assert_called_once_with("legacy@example.com")
    assert sender.messages == []


def test_registration_casefold_unique_index_rejects_racing_duplicate(client):
    response = client.post("/api/v1/auth/register", json={
        "email": "Case.Index@example.com", "password": "InitialSecure123!", "first_name": "Test",
    })
    assert response.status_code == 201

    with get_session_factory()() as session:
        session.add(User(
            email="CASE.INDEX@example.com",
            password_hash=hash_password("AnotherSecure123!"),
            first_name="Second",
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_email_identity_migration_stops_before_schema_changes_on_legacy_collision(tmp_path, monkeypatch):
    database_path = tmp_path / "legacy-collision.db"
    url = f"sqlite:///{database_path}"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "6d2f81a4c970")

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO users (id, email, password_hash, first_name, is_active, can_cook, created_at) "
            "VALUES ('legacy-a', 'legacy@example.com', 'hash-a', 'A', 1, 0, '2026-01-01 00:00:00'), "
            "('legacy-b', 'LEGACY@example.com', 'hash-b', 'B', 1, 0, '2026-01-01 00:00:00')"
        )

    with pytest.raises(RuntimeError, match="1 groupe\\(s\\) d'e-mails en collision"):
        command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "auth_version" not in {column["name"] for column in inspector.get_columns("users")}
    assert "password_reset_tokens" not in inspector.get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == "6d2f81a4c970"
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM sqlite_master WHERE type = 'index' AND name = 'uq_users_email_lower'"
        ).scalar_one() == 0
    engine.dispose()
