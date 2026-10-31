"""Outil interactif hors ligne pour provisionner le compte admin du staging."""

from __future__ import annotations

import argparse
import getpass
import hmac
import json
import os
import re
import sys
import warnings
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.database import get_engine, get_session_factory
from backend.app.persistence.models import User
from backend.app.security import hash_password

EXPECTED_APP_ENV = "staging"
EXPECTED_DATABASE = "kwitli_preproduction"
EXPECTED_DATABASE_USER = "kwitli_preproduction"
EXPECTED_DATABASE_PORT = 5432
ADMIN_PASSWORD_MIN_LENGTH = 16
ADMIN_PASSWORD_MAX_LENGTH = 128
_LINUX_OPERATOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,31}$")
_EMAIL_ADAPTER = TypeAdapter(EmailStr)


class AdminCliError(Exception):
    """Erreur métier exposée uniquement par un code non sensible."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def normalize_email(value: str) -> str:
    try:
        normalized = str(_EMAIL_ADAPTER.validate_python(value.strip())).lower()
    except (AttributeError, ValidationError) as exc:
        raise AdminCliError("invalid_email") from None
    if len(normalized) > 254:
        raise AdminCliError("invalid_email")
    return normalized


def validate_admin_password(password: str) -> None:
    if not ADMIN_PASSWORD_MIN_LENGTH <= len(password) <= ADMIN_PASSWORD_MAX_LENGTH:
        raise AdminCliError("password_policy")


def validate_staging_target(
    *, app_env: str, database_url: str, database_name: str, database_user: str
) -> None:
    """Refuse tout environnement autre que la base Compose de preproduction."""
    if app_env.strip().lower() != EXPECTED_APP_ENV:
        raise AdminCliError("wrong_environment")
    try:
        url = make_url(database_url)
    except Exception:
        raise AdminCliError("invalid_database_target") from None
    if (
        url.get_backend_name() != "postgresql"
        or url.host != "postgres"
        or url.port != EXPECTED_DATABASE_PORT
        or url.username != EXPECTED_DATABASE_USER
        or url.database != EXPECTED_DATABASE
        or database_name != EXPECTED_DATABASE
        or database_user != EXPECTED_DATABASE_USER
    ):
        raise AdminCliError("invalid_database_target")


def _find_users(session: Session, email: str) -> list[User]:
    return list(
        session.scalars(
            select(User)
            .where(func.lower(User.email) == email)
            .limit(2)
            .with_for_update()
        )
    )


def _one_user(session: Session, email: str) -> User:
    matches = _find_users(session, email)
    if len(matches) != 1:
        raise AdminCliError("account_not_found_or_ambiguous")
    return matches[0]


def emit_audit_event(
    action: str,
    outcome: str,
    operator: str,
    *,
    target_user_id: str | None = None,
    reason: str | None = None,
    stream=None,
) -> None:
    """Émet une ligne JSON sans adresse, mot de passe, hash ni détail SQL."""
    event = {
        "event": "kwitli_admin_account_operation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "outcome": outcome,
        "operator": operator,
    }
    if target_user_id is not None:
        event["target_user_id"] = target_user_id
    if reason is not None:
        event["reason"] = reason
    print(json.dumps(event, sort_keys=True), file=stream or sys.stderr, flush=True)


def create_admin(
    session: Session,
    email: str,
    password: str,
    *,
    operator: str,
    audit: Callable = emit_audit_event,
) -> str:
    normalized_email = normalize_email(email)
    validate_admin_password(password)
    if _find_users(session, normalized_email):
        raise AdminCliError("email_already_exists")

    user = User(
        id=str(uuid4()),
        email=normalized_email,
        password_hash=hash_password(password),
        first_name="Kwitli",
        last_name="Admin",
        is_active=True,
        can_cook=False,
        is_admin=True,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        # Le contrôle DB couvre aussi deux créations concurrentes.
        raise AdminCliError("email_already_exists") from None
    except Exception:
        session.rollback()
        raise AdminCliError("database_write_failed") from None

    audit("create", "success", operator, target_user_id=user.id)
    return user.id


def recover_admin_password(
    session: Session,
    email: str,
    password: str,
    *,
    operator: str,
    audit: Callable = emit_audit_event,
) -> str:
    normalized_email = normalize_email(email)
    validate_admin_password(password)
    user = _one_user(session, normalized_email)
    if not user.is_admin:
        raise AdminCliError("target_not_admin")
    if not user.is_active:
        raise AdminCliError("target_inactive")

    user.password_hash = hash_password(password)
    user.auth_version += 1
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise AdminCliError("database_write_failed") from None

    audit("recover_password", "success", operator, target_user_id=user.id)
    return user.id


def revoke_admin(
    session: Session,
    email: str,
    confirmation: str,
    *,
    operator: str,
    audit: Callable = emit_audit_event,
) -> str:
    normalized_email = normalize_email(email)
    user = _one_user(session, normalized_email)
    if not user.is_admin:
        raise AdminCliError("target_not_admin")
    if not hmac.compare_digest(confirmation, f"REVOKE {user.id}"):
        raise AdminCliError("confirmation_mismatch")

    user.is_admin = False
    user.auth_version += 1
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise AdminCliError("database_write_failed") from None

    audit("revoke", "success", operator, target_user_id=user.id)
    return user.id


def _operator_from_environment() -> str:
    value = os.environ.get("KWITLI_ADMIN_OPERATOR", "")
    if not _LINUX_OPERATOR.fullmatch(value):
        raise AdminCliError("operator_identity_required")
    return value


def _prompt_email(prompt: str, secret_prompt: Callable[[str], str]) -> str:
    first = normalize_email(secret_prompt(prompt))
    second = normalize_email(secret_prompt("Confirmez l'adresse (saisie masquée) : "))
    if not hmac.compare_digest(first, second):
        raise AdminCliError("email_confirmation_mismatch")
    return first


def _secure_getpass(prompt: str) -> str:
    """Refuse getpass's echoing fallback instead of risking a visible secret."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass(prompt)
    except getpass.GetPassWarning:
        raise AdminCliError("secure_input_unavailable") from None


def _prompt_password(secret_prompt: Callable[[str], str]) -> str:
    first = secret_prompt("Mot de passe admin (16 caractères minimum, saisie masquée) : ")
    second = secret_prompt("Confirmez le mot de passe (saisie masquée) : ")
    if not hmac.compare_digest(first, second):
        raise AdminCliError("password_confirmation_mismatch")
    validate_admin_password(first)
    return first


def _open_staging_session():
    settings = get_settings()
    try:
        # Refuser une mauvaise cible depuis la configuration avant même d'ouvrir
        # une connexion; la seconde vérification confirme ensuite l'identité SQL.
        validate_staging_target(
            app_env=settings.app_env,
            database_url=settings.database_url,
            database_name=EXPECTED_DATABASE,
            database_user=EXPECTED_DATABASE_USER,
        )
        engine = get_engine()
        with engine.connect() as connection:
            database_name, database_user = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
        validate_staging_target(
            app_env=settings.app_env,
            database_url=settings.database_url,
            database_name=database_name,
            database_user=database_user,
        )
        return get_session_factory()()
    except AdminCliError:
        raise
    except Exception:
        # Ne jamais inclure URL, identifiant, SQL ou exception DB dans la sortie.
        raise AdminCliError("database_preflight_failed") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gestion ponctuelle et interactive du compte admin Kwitli staging.")
    parser.add_argument("operation", choices=("create", "recover", "revoke"))
    args = parser.parse_args(argv)
    operator = os.environ.get("KWITLI_ADMIN_OPERATOR", "unknown")
    if not _LINUX_OPERATOR.fullmatch(operator):
        emit_audit_event(args.operation, "denied", "unknown", reason="operator_identity_required")
        print("Opération refusée : opérateur serveur non identifié.", file=sys.stderr)
        return 2
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        emit_audit_event(args.operation, "denied", operator, reason="interactive_tty_required")
        print("Opération refusée : exécutez-la dans un terminal interactif direct, sans redirection.", file=sys.stderr)
        return 2

    session = None
    target_user_id = None
    try:
        session = _open_staging_session()
        secret_prompt = _secure_getpass
        if args.operation == "create":
            email = _prompt_email("Adresse dédiée du propriétaire (saisie masquée) : ", secret_prompt)
            password = _prompt_password(secret_prompt)
            target_user_id = create_admin(session, email, password, operator=operator)
        elif args.operation == "recover":
            email = _prompt_email("Adresse du compte admin existant (saisie masquée) : ", secret_prompt)
            user = _one_user(session, email)
            if not user.is_admin or not user.is_active:
                raise AdminCliError("target_not_active_admin")
            target_user_id = user.id
            print(f"Compte admin ciblé : {target_user_id}")
            confirmation = input(f"Tapez RESET PASSWORD {target_user_id} : ")
            if not hmac.compare_digest(confirmation, f"RESET PASSWORD {target_user_id}"):
                raise AdminCliError("confirmation_mismatch")
            password = _prompt_password(secret_prompt)
            recover_admin_password(session, email, password, operator=operator)
        else:
            email = _prompt_email("Adresse du compte admin à révoquer (saisie masquée) : ", secret_prompt)
            user = _one_user(session, email)
            if not user.is_admin:
                raise AdminCliError("target_not_admin")
            target_user_id = user.id
            print(f"Compte admin ciblé : {target_user_id}")
            confirmation = input(f"Tapez REVOKE {target_user_id} : ")
            target_user_id = revoke_admin(
                session, email, confirmation, operator=operator
            )
        print(f"Opération {args.operation} terminée. Identifiant cible : {target_user_id}")
        return 0
    except AdminCliError as exc:
        if session is not None:
            session.rollback()
        emit_audit_event(
            args.operation,
            "denied",
            operator,
            target_user_id=target_user_id,
            reason=exc.reason,
        )
        print(f"Opération refusée ({exc.reason}); aucune autre donnée n'a été modifiée.", file=sys.stderr)
        return 2
    except Exception:
        if session is not None:
            session.rollback()
        emit_audit_event(
            args.operation,
            "error",
            operator,
            target_user_id=target_user_id,
            reason="unexpected_error",
        )
        print("Échec interne; aucun détail sensible n'est affiché. Consultez le journal système.", file=sys.stderr)
        return 1
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main())
