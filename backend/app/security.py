from datetime import timedelta
from uuid import uuid4

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from backend.app.core.config import get_settings
from backend.app.core.time import utc_now

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    return password_hash is not None and password_hasher.verify(password, password_hash)


def create_access_token(user_id: str, auth_version: int = 0) -> str:
    settings = get_settings()
    issued_at = utc_now()
    expires_at = issued_at + timedelta(minutes=settings.access_token_expire_minutes)
    claims = {
        "sub": user_id,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "jti": str(uuid4()),
        "ver": auth_version,
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(claims, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token_claims(token: str) -> dict | None:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "iss", "aud", "jti", "iat", "exp"]},
        )
    except InvalidTokenError:
        return None
    subject = payload.get("sub")
    token_id = payload.get("jti")
    version = payload.get("ver", 0)
    if (
        not isinstance(subject, str) or not subject
        or not isinstance(token_id, str) or not token_id
        or isinstance(version, bool) or not isinstance(version, int) or version < 0
    ):
        return None
    return payload


def decode_access_token(token: str) -> str | None:
    payload = decode_access_token_claims(token)
    return payload["sub"] if payload is not None else None
