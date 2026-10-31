#!/usr/bin/env python3
"""Install a root-only Restic/R2 environment for Kwitli preproduction.

Run on kwitli-prod-01 with sudo. This script creates configuration files only:
it does not contact R2, initialize a repository, back up, restore, or start a timer.
"""

from __future__ import annotations

import getpass
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path("/etc/kwitli")
COMPOSE_ENV = ROOT / "preproduction.compose.env"
API_ENV = ROOT / "preproduction.api.env"
COMPOSE_FILE = Path("/opt/kwitli/deploy/compose.production.yaml")
BACKUP_SCRIPT = Path("/opt/kwitli/deploy/backup-postgres.sh")
BACKUP_ENV = ROOT / "preproduction.backup.env"
RESTIC_PASSWORD_FILE = ROOT / "preproduction-restic-password"
PROJECT = "kwitli-preproduction"
EXPECTED_DB = "kwitli_preproduction"
EXPECTED_PG_VOLUME = f"{PROJECT}_postgres_data"
EXPECTED_UPLOADS_VOLUME = f"{PROJECT}_uploads"
BUCKET = "kwitli-restic-backups"


class SetupError(Exception):
    """Safe, user-facing setup error; never contains entered credentials."""


def validate_account_id(value: str) -> bool:
    return re.fullmatch(r"[0-9A-Fa-f]{32}", value) is not None


def validate_r2_credential(value: str) -> bool:
    # R2 S3 credentials use printable base64-like characters; reject values
    # that could alter systemd EnvironmentFile parsing.
    return re.fullmatch(r"[A-Za-z0-9+/=_-]+", value) is not None


def generate_repository_id(now: datetime | None = None, random_suffix: str | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dt%H%M%S") + "z"
    suffix = random_suffix if random_suffix is not None else secrets.token_hex(6)
    run_id = f"kwitli-preproduction-{timestamp}-{suffix}"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{8,80}", run_id):
        raise SetupError("Generated staging repository identifier is invalid.")
    return run_id


def build_repository(account_id: str, run_id: str) -> str:
    if not validate_account_id(account_id):
        raise SetupError("Cloudflare Account ID must contain 32 hexadecimal characters.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{8,80}", run_id):
        raise SetupError("Generated staging repository identifier is invalid.")
    repository = (
        f"s3:https://{account_id.lower()}.eu.r2.cloudflarestorage.com/"
        f"{BUCKET}/staging/{run_id}"
    )
    if not re.fullmatch(
        rf"s3:https://[0-9a-f]{{32}}\.eu\.r2\.cloudflarestorage\.com/{re.escape(BUCKET)}/staging/[a-z0-9][a-z0-9-]{{8,80}}",
        repository,
    ):
        raise SetupError("Generated Restic repository path is outside the allowed staging format.")
    return repository


def render_backup_env(repository: str, access_key: str, secret_key: str) -> str:
    if not re.fullmatch(
        rf"s3:https://[0-9a-f]{{32}}\.eu\.r2\.cloudflarestorage\.com/{re.escape(BUCKET)}/staging/[a-z0-9][a-z0-9-]{{8,80}}",
        repository,
    ):
        raise SetupError("The Restic repository must be under the dedicated R2 staging prefix.")
    if not validate_r2_credential(access_key) or not validate_r2_credential(secret_key):
        raise SetupError("R2 credentials contain unsupported characters; no files were created.")
    return (
        f"KWITLI_COMPOSE_ENV_FILE={COMPOSE_ENV}\n"
        f"KWITLI_COMPOSE_FILE={COMPOSE_FILE}\n"
        f"KWITLI_COMPOSE_PROJECT_NAME={PROJECT}\n"
        f"RESTIC_REPOSITORY={repository}\n"
        "AWS_DEFAULT_REGION=auto\n"
        f"AWS_ACCESS_KEY_ID={access_key}\n"
        f"AWS_SECRET_ACCESS_KEY={secret_key}\n"
        f"RESTIC_PASSWORD_FILE={RESTIC_PASSWORD_FILE}\n"
    )


def validate_compose_config(config: dict) -> None:
    services = config.get("services", {})
    postgres = services.get("postgres", {})
    api = services.get("api", {})
    pg_env = postgres.get("environment", {}) or {}
    api_env = api.get("environment", {}) or {}
    database_url = urlsplit(api_env.get("DATABASE_URL", ""))
    volumes = config.get("volumes", {}) or {}
    networks = config.get("networks", {}) or {}
    api_mounts = {
        item.get("target"): item.get("source") for item in api.get("volumes", [])
    }
    postgres_mounts = {
        item.get("target"): item.get("source") for item in postgres.get("volumes", [])
    }
    postgres_networks = postgres.get("networks", {}) or {}
    api_networks = api.get("networks", {}) or {}

    checks = {
        "service.postgres.present": "postgres" in services,
        "service.api.present": "api" in services,
        "database.postgres.name": pg_env.get("POSTGRES_DB") == EXPECTED_DB,
        "database.api.url": database_url.scheme == "postgresql+psycopg2"
        and database_url.hostname == "postgres"
        and database_url.port == 5432
        and database_url.path == f"/{EXPECTED_DB}",
        "volume.postgres.mount": postgres_mounts.get("/var/lib/postgresql") == "postgres_data",
        "volume.postgres.name": volumes.get("postgres_data", {}).get("name") == EXPECTED_PG_VOLUME,
        # Compose service mounts refer to logical volume keys. The physical,
        # project-prefixed Docker volume name is resolved under top-level volumes.
        "volume.uploads.mount": api_mounts.get("/app/backend/uploads") == "uploads",
        "volume.uploads.name": volumes.get("uploads", {}).get("name") == EXPECTED_UPLOADS_VOLUME,
        "network.postgres.private": "data" in postgres_networks,
        "network.api.private": "data" in api_networks,
        "network.data.internal": networks.get("data", {}).get("internal") is True,
        "port.postgres.unpublished": not postgres.get("ports"),
        "port.api.unpublished": not api.get("ports"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SetupError("Resolved Compose checks failed: " + ", ".join(failed) + ".")


def require_root_only_file(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SetupError(f"Required staging file is unavailable: {path.name}.") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
        raise SetupError(f"Required staging file must be a root-owned regular file with mode 0600: {path.name}.")


def run_preflight() -> None:
    if os.geteuid() != 0:
        raise SetupError("Run this script with sudo in the interactive SSH terminal.")
    if not Path("/dev/tty").exists() or not sys.stdin.isatty():
        raise SetupError("An interactive SSH terminal is required; no configuration was created.")
    if not ROOT.is_dir():
        raise SetupError("/etc/kwitli is absent; this script will not create or replace the directory.")
    root_info = ROOT.stat()
    if root_info.st_uid != 0 or stat.S_IMODE(root_info.st_mode) & 0o077:
        raise SetupError("/etc/kwitli must be root-owned and inaccessible to group/other users.")

    for target in (BACKUP_ENV, RESTIC_PASSWORD_FILE):
        if target.exists() or target.is_symlink():
            raise SetupError(f"Refusing to overwrite existing configuration: {target.name}.")

    require_root_only_file(COMPOSE_ENV)
    require_root_only_file(API_ENV)
    if not COMPOSE_FILE.is_file() or not BACKUP_SCRIPT.is_file():
        raise SetupError("The staging Compose file or backup script is missing on the server.")
    try:
        script_text = BACKUP_SCRIPT.read_text(encoding="utf-8")
    except OSError as exc:
        raise SetupError("Could not inspect the deployed backup script.") from exc
    required_markers = (
        "KWITLI_BACKUP_SKIP_RETENTION",
        "kwitli-preproduction",
        "kwitli-restic-backups/staging/",
        "Initial staging validation: retention and pruning intentionally skipped.",
    )
    if not all(marker in script_text for marker in required_markers):
        raise SetupError("The staging-safe backup-postgres.sh version is not installed on the server.")

    try:
        version = subprocess.run(
            ["/usr/bin/restic", "version"], capture_output=True, text=True, timeout=10, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError("Restic is unavailable or its version could not be checked.") from exc
    if "0.18.1" not in version or "linux/arm64" not in version:
        raise SetupError("Expected Restic 0.18.1 for linux/arm64 was not confirmed.")

    compose_command = [
        "docker", "compose", "--project-name", PROJECT,
        "--env-file", str(COMPOSE_ENV), "-f", str(COMPOSE_FILE),
        "config", "--format", "json",
    ]
    try:
        result = subprocess.run(
            compose_command, capture_output=True, text=True, timeout=30, check=True
        )
        validate_compose_config(json.loads(result.stdout))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, SetupError) as exc:
        if isinstance(exc, SetupError):
            raise
        # Compose stderr/stdout can contain interpolated credentials.
        raise SetupError("Docker Compose staging validation failed; output was suppressed to protect secrets.") from exc

    for name, expected_volume_key in (
        (EXPECTED_PG_VOLUME, "postgres_data"),
        (EXPECTED_UPLOADS_VOLUME, "uploads"),
    ):
        try:
            result = subprocess.run(
                ["docker", "volume", "inspect", name],
                capture_output=True, text=True, timeout=10, check=True,
            )
            volumes = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            raise SetupError(f"Expected existing staging volume was not verified: {name}.") from exc
        labels = volumes[0].get("Labels") or {} if len(volumes) == 1 else {}
        if labels.get("com.docker.compose.project") != PROJECT or labels.get("com.docker.compose.volume") != expected_volume_key:
            raise SetupError(f"Existing volume ownership did not match the staging project: {name}.")


def write_exclusive(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.fchown(descriptor, 0, 0)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    finally:
        os.close(descriptor)


def install_pair(env_text: str, restic_password: str) -> None:
    created: list[Path] = []
    try:
        write_exclusive(RESTIC_PASSWORD_FILE, (restic_password + "\n").encode("utf-8"))
        created.append(RESTIC_PASSWORD_FILE)
        write_exclusive(BACKUP_ENV, env_text.encode("ascii"))
        created.append(BACKUP_ENV)
        for path in created:
            os.chmod(path, 0o600)
            os.chown(path, 0, 0)
    except Exception:
        for path in created:
            try:
                path.unlink()
            except OSError:
                pass
        raise


def prompt_secret(label: str) -> str:
    value = getpass.getpass(label)
    if not value or "\n" in value or "\r" in value:
        raise SetupError("A required secret is empty or contains a line break; no configuration was created.")
    return value


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        generated_id = generate_repository_id(
            datetime(2026, 10, 26, 12, 34, 56, tzinfo=timezone.utc),
            "abcdef123456",
        )
        assert generated_id == "kwitli-preproduction-20261026t123456z-abcdef123456"
        repository = build_repository("0123456789abcdef0123456789abcdef", generated_id)
        assert repository.endswith(f"/{BUCKET}/staging/{generated_id}")
        assert "/production" not in repository and "/validation" not in repository
        assert not validate_account_id("not-an-account-id")
        try:
            build_repository(
                "0123456789abcdef0123456789abcdef",
                "kwitli-preproduction-20261026T123456Z-abcdef123456",
            )
        except SetupError:
            pass
        else:
            raise AssertionError("uppercase timestamp marker must not pass the lowercase repository-ID policy")
        rendered = render_backup_env(repository, "test-access-key", "test/secret+key=")
        assert "RESTIC_PASSWORD=" not in rendered
        assert f"RESTIC_PASSWORD_FILE={RESTIC_PASSWORD_FILE}" in rendered
        assert "KWITLI_BACKUP_SKIP_RETENTION=" not in rendered
        validate_compose_config({
            "services": {
                "postgres": {
                    "environment": {"POSTGRES_DB": EXPECTED_DB},
                    "volumes": [{"target": "/var/lib/postgresql", "source": "postgres_data"}],
                    "networks": ["data"],
                },
                "api": {
                    "environment": {"DATABASE_URL": f"postgresql+psycopg2://user:pass@postgres:5432/{EXPECTED_DB}"},
                    "volumes": [{"target": "/app/backend/uploads", "source": "uploads"}],
                    "networks": {"data": {}},
                },
            },
            "volumes": {
                "postgres_data": {"name": EXPECTED_PG_VOLUME},
                "uploads": {"name": EXPECTED_UPLOADS_VOLUME},
            },
            "networks": {"data": {"internal": True}},
        })
        try:
            invalid = repository.replace("/staging/", "/production/")
            render_backup_env(invalid, "test-access-key", "test/secret+key=")
        except SetupError:
            pass
        else:
            raise AssertionError("a production repository path must be rejected")
        print("PASS — configuration validation self-test (no files, secrets or network).")
        return 0
    if sys.argv[1:]:
        print("Usage: sudo python3 install_preproduction_backup_env.py [--self-test]", file=sys.stderr)
        return 2

    try:
        run_preflight()
        # Validate the generated identifier and the final path shape before
        # asking for any R2 credential or Restic passphrase.
        run_id = generate_repository_id()
        placeholder_repository = build_repository("0" * 32, run_id)
        render_backup_env(placeholder_repository, "placeholder-access", "placeholder-secret")

        account_id = input("Cloudflare Account ID (32 hexadecimal characters): ").strip()
        if not validate_account_id(account_id):
            raise SetupError("Cloudflare Account ID format is invalid; no configuration was created.")
        repository = build_repository(account_id, run_id)

        access_key = prompt_secret("R2 Access Key ID (hidden): ")
        if not validate_r2_credential(access_key):
            raise SetupError("R2 Access Key ID contains unsupported characters; no configuration was created.")
        secret_key = prompt_secret("R2 Secret Access Key (hidden): ")
        if not validate_r2_credential(secret_key):
            raise SetupError("R2 Secret Access Key contains unsupported characters; no configuration was created.")
        restic_password = prompt_secret("Restic encryption passphrase (hidden): ")
        if len(restic_password) < 20:
            raise SetupError("Restic passphrase must contain at least 20 characters.")
        confirmation = prompt_secret("Confirm Restic passphrase (hidden): ")
        if restic_password != confirmation:
            raise SetupError("Restic passphrases do not match; no configuration was created.")
        env_text = render_backup_env(repository, access_key, secret_key)
        install_pair(env_text, restic_password)
    except (SetupError, OSError, UnicodeError, EOFError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            print("\nConfiguration cancelled; no pre-existing file was changed.", file=sys.stderr)
            return 130
        print(f"Configuration not installed: {exc}", file=sys.stderr)
        return 1

    print("PASS — staging backup configuration created (secret values suppressed).")
    print("PASS — root:root, mode 0600 verified for both files.")
    print("PASS — existing staging volumes and resolved Compose target verified; no database writes.")
    print("R2 repository is configured under the dedicated /staging prefix; no R2 request was made.")
    print("STOP — restic init, backup, restore, timer activation and retention were not run.")
    print("Next explicit command, only after reviewing the generated path:")
    print(
        "sudo systemd-run --wait --pipe --collect "
        "--property=EnvironmentFile=/etc/kwitli/preproduction.backup.env "
        "/usr/bin/restic init"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
