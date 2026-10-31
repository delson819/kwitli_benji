from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from backend.app.admin_cli import (
    AdminCliError,
    create_admin,
    main,
    _open_staging_session,
    recover_admin_password,
    revoke_admin,
    _secure_getpass,
    validate_staging_target,
)
from backend.app.core.config import get_settings
from backend.app.database import get_session_factory
from backend.app.persistence.models import User
from backend.app.security import hash_password, verify_password

OWNER_EMAIL = "owner-dedicated-admin@example.com"
OWNER_PASSWORD = "OwnerAdminPassphrase-2026-Long"
TESTER_EMAIL = "existing-staging-tester@example.com"
TESTER_PASSWORD = "TesterPassphrase-2026-Long"
OPERATOR = "kwitliadmin"


def _add_user(email: str, password: str, *, admin: bool = False, active: bool = True) -> str:
    with get_session_factory()() as session:
        user = User(
            email=email,
            password_hash=hash_password(password),
            first_name="Test",
            is_active=active,
            is_admin=admin,
        )
        session.add(user)
        session.commit()
        return user.id


def _user_by_id(user_id: str) -> User:
    with get_session_factory()() as session:
        return session.get(User, user_id)


def test_create_admin_adds_distinct_account_and_only_hashes_password(client, capsys):
    owner_user_id = _add_user("existing-owner@example.com", "ExistingOwnerPassphrase-2026")
    tester_user_id = _add_user(TESTER_EMAIL, TESTER_PASSWORD)
    with get_session_factory()() as session:
        admin_id = create_admin(
            session, OWNER_EMAIL, OWNER_PASSWORD, operator=OPERATOR
        )

    admin = _user_by_id(admin_id)
    assert admin.email == OWNER_EMAIL
    assert admin.is_active is True
    assert admin.is_admin is True
    assert admin.can_cook is False
    assert admin.password_hash != OWNER_PASSWORD
    assert verify_password(OWNER_PASSWORD, admin.password_hash)
    assert _user_by_id(owner_user_id).is_admin is False
    assert _user_by_id(tester_user_id).is_admin is False

    event = json.loads(capsys.readouterr().err.strip())
    assert event["event"] == "kwitli_admin_account_operation"
    assert event["action"] == "create"
    assert event["outcome"] == "success"
    assert event["operator"] == OPERATOR
    assert event["target_user_id"] == admin_id
    assert OWNER_EMAIL not in json.dumps(event)
    assert OWNER_PASSWORD not in json.dumps(event)
    assert admin.password_hash not in json.dumps(event)


def test_create_refuses_existing_email_without_promoting_or_changing_users(client):
    existing_id = _add_user("Owner-Dedicated-Admin@example.com", "ExistingOwnerPassphrase-2026")
    tester_id = _add_user(TESTER_EMAIL, TESTER_PASSWORD)
    with get_session_factory()() as session:
        with pytest.raises(AdminCliError, match="email_already_exists"):
            create_admin(session, OWNER_EMAIL, OWNER_PASSWORD, operator=OPERATOR)

    assert _user_by_id(existing_id).is_admin is False
    assert _user_by_id(tester_id).is_admin is False
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 2


def test_concurrent_create_with_case_variant_produces_one_admin(client, monkeypatch):
    import backend.app.admin_cli as admin_cli

    barrier = Barrier(2)
    original_find_users = admin_cli._find_users

    def synchronized_find_users(session, email):
        matches = original_find_users(session, email)
        barrier.wait(timeout=10)
        return matches

    monkeypatch.setattr(admin_cli, "_find_users", synchronized_find_users)

    def provision(email):
        with get_session_factory()() as session:
            try:
                return ("created", create_admin(session, email, OWNER_PASSWORD, operator=OPERATOR))
            except AdminCliError as exc:
                return ("refused", exc.reason)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(provision, (OWNER_EMAIL, OWNER_EMAIL.upper())))

    assert sorted(result for result, _ in outcomes) == ["created", "refused"]
    assert next(value for result, value in outcomes if result == "refused") == "email_already_exists"
    with get_session_factory()() as session:
        assert session.scalar(
            select(func.count()).select_from(User).where(User.is_admin.is_(True))
        ) == 1


def test_create_rejects_weak_password_without_writing_user(client):
    with get_session_factory()() as session:
        with pytest.raises(AdminCliError, match="password_policy"):
            create_admin(session, OWNER_EMAIL, "short", operator=OPERATOR)
    with get_session_factory()() as session:
        assert session.scalar(
            select(func.count()).select_from(User).where(func.lower(User.email) == OWNER_EMAIL)
        ) == 0


def test_staging_target_guard_requires_staging_url_and_effective_database():
    valid = {
        "app_env": "staging",
        "database_url": "postgresql+psycopg2://kwitli_preproduction:opaque@postgres:5432/kwitli_preproduction",
        "database_name": "kwitli_preproduction",
        "database_user": "kwitli_preproduction",
    }
    validate_staging_target(**valid)
    with pytest.raises(AdminCliError, match="wrong_environment"):
        validate_staging_target(**{**valid, "app_env": "development"})
    with pytest.raises(AdminCliError, match="invalid_database_target"):
        validate_staging_target(**{**valid, "database_name": "kwitli_dev"})
    with pytest.raises(AdminCliError, match="invalid_database_target"):
        validate_staging_target(**{**valid, "database_url": "postgresql:///kwitli_preproduction"})
    with pytest.raises(AdminCliError, match="invalid_database_target"):
        validate_staging_target(**{
            **valid,
            "database_url": "postgresql+psycopg2://kwitli_preproduction:opaque@postgres:55433/kwitli_preproduction",
        })
    with pytest.raises(AdminCliError, match="invalid_database_target"):
        validate_staging_target(**{**valid, "database_user": "postgres"})
    assert "opaque" not in str(AdminCliError("invalid_database_target"))


def test_secure_getpass_refuses_echo_fallback_without_reading_input(monkeypatch):
    import warnings

    import backend.app.admin_cli as admin_cli

    def getpass_with_unsafe_fallback(_prompt):
        warnings.warn("Can not control echo on the terminal.", getpass_warning)
        pytest.fail("the fallback must not read a password after echo control fails")

    getpass_warning = admin_cli.getpass.GetPassWarning
    monkeypatch.setattr(admin_cli.getpass, "getpass", getpass_with_unsafe_fallback)
    with pytest.raises(AdminCliError, match="secure_input_unavailable"):
        _secure_getpass("Password: ")


def test_wrong_environment_is_rejected_before_opening_database(monkeypatch):
    import backend.app.admin_cli as admin_cli

    monkeypatch.setattr(
        admin_cli,
        "get_settings",
        lambda: type("Settings", (), {
            "app_env": "development",
            "database_url": "postgresql+psycopg2://kwitli_preproduction:opaque@postgres:5432/kwitli_preproduction",
        })(),
    )
    monkeypatch.setattr(
        admin_cli,
        "get_engine",
        lambda: pytest.fail("engine must not be opened for a non-staging environment"),
    )
    with pytest.raises(AdminCliError, match="wrong_environment"):
        _open_staging_session()


def test_cli_refuses_noninteractive_invocation_before_database_access(client, monkeypatch, capsys):
    import sys
    from types import SimpleNamespace

    monkeypatch.setenv("KWITLI_ADMIN_OPERATOR", OPERATOR)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    assert main(["create"]) == 2
    output = capsys.readouterr()
    assert "interactive" in output.err.lower()
    assert "database" not in output.err.lower()


def test_recovery_changes_only_an_existing_active_admin_and_invalidates_sessions(client, capsys):
    from backend.app.security import create_access_token

    admin_id = _add_user(OWNER_EMAIL, OWNER_PASSWORD, admin=True)
    tester_id = _add_user(TESTER_EMAIL, TESTER_PASSWORD)
    old_token = create_access_token(admin_id, _user_by_id(admin_id).auth_version)
    with get_session_factory()() as session:
        recovered_id = recover_admin_password(
            session,
            OWNER_EMAIL,
            "RecoveredAdminPassphrase-2026",
            operator=OPERATOR,
        )

    admin = _user_by_id(admin_id)
    assert recovered_id == admin_id
    assert admin.is_admin is True
    assert admin.auth_version == 1
    assert verify_password("RecoveredAdminPassphrase-2026", admin.password_hash)
    assert not verify_password(OWNER_PASSWORD, admin.password_hash)
    assert _user_by_id(tester_id).is_admin is False
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {old_token}"}).status_code == 401
    event = json.loads(capsys.readouterr().err.strip())
    assert event["action"] == "recover_password"
    assert OWNER_EMAIL not in json.dumps(event)
    assert "RecoveredAdminPassphrase-2026" not in json.dumps(event)
    assert admin.password_hash not in json.dumps(event)


def test_recovery_refuses_non_admin_without_changing_password_or_role(client):
    tester_id = _add_user(TESTER_EMAIL, TESTER_PASSWORD)
    original_hash = _user_by_id(tester_id).password_hash
    with get_session_factory()() as session:
        with pytest.raises(AdminCliError, match="target_not_admin"):
            recover_admin_password(
                session,
                TESTER_EMAIL,
                "RecoveredAdminPassphrase-2026",
                operator=OPERATOR,
            )
    tester = _user_by_id(tester_id)
    assert tester.is_admin is False
    assert tester.password_hash == original_hash
    assert tester.auth_version == 0


def test_revoke_removes_only_admin_role_without_deleting_user(client, capsys):
    admin_id = _add_user(OWNER_EMAIL, OWNER_PASSWORD, admin=True)
    tester_id = _add_user(TESTER_EMAIL, TESTER_PASSWORD)
    with get_session_factory()() as session:
        revoked_id = revoke_admin(
            session,
            OWNER_EMAIL,
            f"REVOKE {admin_id}",
            operator=OPERATOR,
        )

    revoked = _user_by_id(admin_id)
    assert revoked_id == admin_id
    assert revoked is not None
    assert revoked.is_active is True
    assert revoked.is_admin is False
    assert revoked.auth_version == 1
    assert verify_password(OWNER_PASSWORD, revoked.password_hash)
    assert _user_by_id(tester_id).is_admin is False
    event = json.loads(capsys.readouterr().err.strip())
    assert event["action"] == "revoke"
    assert OWNER_EMAIL not in json.dumps(event)
    assert OWNER_PASSWORD not in json.dumps(event)
    assert revoked.password_hash not in json.dumps(event)


def test_revoke_requires_exact_target_confirmation_and_preserves_account(client):
    admin_id = _add_user(OWNER_EMAIL, OWNER_PASSWORD, admin=True)
    with get_session_factory()() as session:
        with pytest.raises(AdminCliError, match="confirmation_mismatch"):
            revoke_admin(session, OWNER_EMAIL, "REVOKE wrong-id", operator=OPERATOR)
    admin = _user_by_id(admin_id)
    assert admin is not None
    assert admin.is_admin is True


def test_public_registration_cannot_assign_admin_role(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "public-signup@example.com",
            "password": "PublicSignupPassphrase-2026",
            "first_name": "Public",
            "is_admin": True,
        },
    )
    with get_session_factory()() as session:
        user = session.scalar(select(User).where(User.email == "public-signup@example.com"))
        if response.status_code == 201:
            assert user is not None
            assert user.is_admin is False
        else:
            assert response.status_code == 422
            assert user is None
