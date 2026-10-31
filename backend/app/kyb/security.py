from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import uuid
from uuid import uuid4

from backend.app.core.config import get_settings


class KybSecurityError(ValueError):
    pass


class KybInfectedError(KybSecurityError):
    pass


def _key() -> bytes:
    settings = get_settings()
    raw_keyring = settings.kyb_encryption_keys.get_secret_value()
    try:
        keyring = json.loads(raw_keyring) if raw_keyring else {}
        if settings.kyb_encryption_key.get_secret_value():
            keyring.setdefault(settings.kyb_encryption_key_version, settings.kyb_encryption_key.get_secret_value())
        key = bytes.fromhex(keyring[settings.kyb_encryption_key_version])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise KybSecurityError("KYB encryption is not configured.") from exc
    if len(key) != 32:
        raise KybSecurityError("KYB encryption is not configured.")
    return key


def encrypt_document(data: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise KybSecurityError("KYB encryption is unavailable.") from exc
    settings = get_settings()
    key_id = settings.kyb_encryption_key_version.encode("ascii")
    if not key_id or len(key_id) > 32:
        raise KybSecurityError("KYB encryption key version is invalid.")
    nonce = os.urandom(12)
    aad = b"kwitli-kyb-v1:" + key_id
    ciphertext = AESGCM(_key()).encrypt(nonce, data, aad)
    return b"KWKYB1" + bytes([len(key_id)]) + key_id + nonce + ciphertext


def decrypt_document(data: bytes) -> bytes:
    if not data.startswith(b"KWKYB1") or len(data) < 36:
        raise KybSecurityError("Encrypted document is invalid.")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key_id_size = data[6]
        key_id = data[7:7 + key_id_size].decode("ascii")
        settings = get_settings()
        raw_keyring = settings.kyb_encryption_keys.get_secret_value()
        keyring = json.loads(raw_keyring) if raw_keyring else {}
        if settings.kyb_encryption_key.get_secret_value():
            keyring.setdefault(settings.kyb_encryption_key_version, settings.kyb_encryption_key.get_secret_value())
        key = bytes.fromhex(keyring[key_id])
        nonce_start = 7 + key_id_size
        nonce = data[nonce_start:nonce_start + 12]
        return AESGCM(key).decrypt(nonce, data[nonce_start + 12:], b"kwitli-kyb-v1:" + key_id.encode("ascii"))
    except Exception as exc:
        raise KybSecurityError("Encrypted document cannot be verified.") from exc


def scan_and_encrypt(data: bytes, scanner_path: str | None = None) -> tuple[str, bytes, str]:
    """Scan raw bytes in a private transient file, then return random key, ciphertext, and digest."""
    scanner = scanner_path or get_settings().kyb_clamdscan_path
    executable = shutil.which(scanner)
    if not executable:
        raise KybSecurityError("KYB document scanning is unavailable.")
    with tempfile.TemporaryDirectory(prefix="kwitli-kyb-scan-") as temporary_directory:
        fd, name = tempfile.mkstemp(prefix="scan-", dir=temporary_directory)
        path = Path(name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                result = subprocess.run(
                    [executable, "--no-summary", "--", str(path)],
                    capture_output=True, timeout=30, check=False, text=True,
                    env={"PATH": os.environ.get("PATH", "")},
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise KybSecurityError("KYB document scanning failed.") from exc
            # ClamAV: 0 clean, 1 infected, 2 scanner error. Never surface its output.
            if result.returncode == 1:
                raise KybInfectedError("KYB document was rejected by security scanning.")
            if result.returncode != 0:
                raise KybSecurityError("KYB document scanning failed.")
            return str(uuid4()), encrypt_document(data), hashlib.sha256(data).hexdigest()
        finally:
            path.unlink(missing_ok=True)


def private_path(storage_dir: Path, storage_key: str) -> Path:
    try:
        parsed_key = uuid.UUID(storage_key)
    except (ValueError, TypeError, AttributeError):
        raise KybSecurityError("Private document identifier is invalid.")
    if str(parsed_key) != storage_key:
        raise KybSecurityError("Private document identifier is invalid.")
    root = storage_dir.resolve()
    candidate = (root / f"{storage_key}.kyb").resolve()
    if candidate.parent != root:
        raise KybSecurityError("Private document path is invalid.")
    return candidate


def collection_ready() -> bool:
    settings = get_settings()
    if not settings.kyb_enabled or not shutil.which(settings.kyb_clamdscan_path):
        return False
    upload_root = Path(settings.upload_dir).resolve()
    configured_root = Path(settings.kyb_private_storage_dir)
    if configured_root.is_symlink():
        return False
    private_root = configured_root.resolve()
    if (private_root == Path("/") or private_root == upload_root or upload_root in private_root.parents
            or private_root in upload_root.parents):
        return False
    if private_root.exists() and (not private_root.is_dir() or private_root.stat().st_mode & 0o077):
        return False
    try:
        encrypt_document(b"configuration-check")
    except KybSecurityError:
        return False
    return True
