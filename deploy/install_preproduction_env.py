#!/usr/bin/env python3
"""Installe les deux fichiers de configuration staging, sans afficher les secrets."""

from __future__ import annotations

import json
import os
import pwd
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote


IMAGE = "ghcr.io/delson819/kwitli-api:sha-dba2ef23376437c4f7b3f65e4ade9e35465c2f2a"
PROJECT = "kwitli-preproduction"
DATABASE = "kwitli_preproduction"
API_ENV_PATH = "/etc/kwitli/preproduction.api.env"
SECRET_PATHS = {
    "postgres": Path("/etc/kwitli/.staging-postgres-password"),
    "jwt": Path("/etc/kwitli/.staging-jwt-secret"),
}
PSP_SECRET_KEYS = (
    "WOMPI_PUBLIC_KEY", "WOMPI_PRIVATE_KEY", "WOMPI_EVENTS_SECRET", "WOMPI_INTEGRITY_SECRET",
    "PAYU_API_LOGIN", "PAYU_API_KEY", "PAYU_MERCHANT_ID", "PAYU_ACCOUNT_ID", "PAYU_PUBLIC_KEY",
    "PAYDUNYA_MASTER_KEY", "PAYDUNYA_PRIVATE_KEY", "PAYDUNYA_TOKEN",
    "PAYDUNYA_TEST_CUSTOMER_PHONE", "PAYDUNYA_TEST_CUSTOMER_EMAIL", "PAYDUNYA_TEST_CUSTOMER_PASSWORD",
    "FLUTTERWAVE_SECRET_KEY", "FLUTTERWAVE_WEBHOOK_SECRET", "PAYTECH_API_KEY", "PAYTECH_API_SECRET",
    "RESEND_API_KEY", "RESEND_API",
)
REQUIRED_COMPOSE_KEYS = (
    "KWITLI_APP_ENV", "KWITLI_IMAGE", "KWITLI_API_ENV_FILE", "KWITLI_POSTGRES_DB",
    "KWITLI_POSTGRES_USER", "KWITLI_POSTGRES_PASSWORD", "DATABASE_URL", "PUBLIC_API_URL",
    "TRUSTED_PROXY_IPS", "SERVICE_AREA_MANIFEST_FILE",
)
REQUIRED_API_KEYS = (
    "SECRET_KEY", "SERVICE_AREA_MANIFEST_PATH", "WOMPI_ENV", "WOMPI_API_BASE_URL", "PAYU_ENV", "PAYU_CHECKOUT_URL",
    "PAYDUNYA_MODE", "FLUTTERWAVE_ENV", "PAYTECH_ENV", "RESEND_API_KEY", "RESEND_FROM_EMAIL",
)
SERVICE_AREA_CONTAINER_PATH = "/run/kwitli/service-areas.json"


class InstallError(Exception):
    """Erreur volontairement expurgée de toute valeur de configuration."""


def validate_service_area_manifest_file(path: Path, database_name: str = DATABASE) -> None:
    """Refuse une configuration staging qui pointerait vers un manifeste non fiable."""
    try:
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
                or mode & 0o022 or not mode & 0o004 or metadata.st_size > 256_000):
            raise InstallError("Manifeste de zones absent ou permissions invalides.")
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except InstallError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise InstallError("Manifeste de zones absent ou invalide.") from None
    zones = manifest.get("zones") if isinstance(manifest, dict) else None
    required_ids = manifest.get("required_area_ids") if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict) or manifest.get("version") != 1
            or manifest.get("environment") != "staging"
            or manifest.get("database_name") != database_name
            or not isinstance(zones, list) or not zones
            or not isinstance(required_ids, list) or not required_ids
            or not set(required_ids).issubset({zone.get("id") for zone in zones if isinstance(zone, dict)})
            or any(not isinstance(zone, dict) or zone.get("source_environment") != "staging"
                   or zone.get("active") is not True or zone.get("id") == "ca-sherbrooke-dev"
                   for zone in zones)):
        raise InstallError("Manifeste de zones incompatible avec le staging.")


def parse_env_text(text: str, source: str = "modèle") -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in raw:
            raise InstallError(f"Ligne invalide dans {source}, ligne {number}.")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise InstallError(f"Nom de variable invalide dans {source}, ligne {number}.")
        if key in values:
            raise InstallError(f"Variable dupliquée dans {source}: {key}.")
        values[key] = value.strip()
    return values


def dotenv_quote(value: str) -> str:
    """Produit une valeur littérale compatible avec un fichier --env-file Compose."""
    if value and re.fullmatch(r"[A-Za-z0-9_./:@%+-]+", value):
        return value
    # Compose traite les valeurs entre apostrophes littéralement; seule l'apostrophe s'échappe.
    return "'" + value.replace("'", "\\'") + "'"


def render_env(values: dict[str, str]) -> bytes:
    return ("".join(f"{key}={dotenv_quote(value)}\n" for key, value in values.items())).encode("utf-8")


def build_database_url(password: str) -> str:
    encoded = quote(password, safe="")
    return f"postgresql+psycopg2://{DATABASE}:{encoded}@postgres:5432/{DATABASE}"


def read_secret(path: Path, minimum_length: int = 32) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise InstallError(f"Secret absent ou illisible: {path.name}.") from None
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_gid != 0
                or stat.S_IMODE(metadata.st_mode) != 0o600):
            raise InstallError(f"Permissions ou type invalide: {path.name} (root:root, 0600 requis).")
        raw = b""
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            raw += chunk
            if len(raw) > 16384:
                raise InstallError(f"Taille invalide: {path.name}.")
    finally:
        os.close(fd)
    raw = raw.removesuffix(b"\n")
    if raw.endswith(b"\r"):
        raw = raw[:-1]
    if not raw or b"\n" in raw or b"\r" in raw or b"\x00" in raw:
        raise InstallError(f"Format invalide: {path.name}.")
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InstallError(f"Format invalide: {path.name}.") from None
    if len(value) < minimum_length or value != value.strip():
        raise InstallError(f"Longueur ou format invalide: {path.name}.")
    return value


def read_regular_file(path: Path) -> str:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise InstallError(f"Fichier requis absent ou non régulier: {path.name}.")
        return path.read_text(encoding="utf-8")
    except OSError:
        raise InstallError(f"Fichier requis absent ou illisible: {path.name}.") from None


def validate_compose_config(
    config: dict,
    compose_values: dict[str, str],
    api_values: dict[str, str],
    api_env_path: str = API_ENV_PATH,
) -> None:
    services = config.get("services", {})
    if set(services) != {"postgres", "api", "caddy"}:
        raise InstallError("Services Compose inattendus.")
    for name in ("postgres", "api"):
        if services[name].get("ports"):
            raise InstallError(f"Port hôte interdit pour {name}.")
    if services["api"].get("image") != IMAGE:
        raise InstallError("Image API inattendue.")
    api_environment = services["api"].get("environment", {})
    postgres_environment = services["postgres"].get("environment", {})
    if api_environment.get("APP_ENV") != "staging" or str(api_environment.get("APP_DEBUG")).lower() != "false":
        raise InstallError("Environnement API staging invalide.")
    if api_environment.get("DATABASE_URL") != compose_values["DATABASE_URL"]:
        raise InstallError("DATABASE_URL API incohérente.")
    if api_environment.get("ALEMBIC_DATABASE_URL") != compose_values["DATABASE_URL"]:
        raise InstallError("ALEMBIC_DATABASE_URL incohérente.")
    if api_environment.get("SERVICE_AREA_MANIFEST_PATH") != "/run/kwitli/service-areas.json":
        raise InstallError("Chemin du manifeste de zones dans le conteneur inattendu.")
    if postgres_environment.get("POSTGRES_DB") != DATABASE or postgres_environment.get("POSTGRES_USER") != DATABASE:
        raise InstallError("Base ou utilisateur PostgreSQL inattendu.")
    if postgres_environment.get("POSTGRES_PASSWORD") != compose_values["KWITLI_POSTGRES_PASSWORD"]:
        raise InstallError("Mot de passe PostgreSQL incohérent.")
    api_env_file = services["api"].get("env_file")
    if isinstance(api_env_file, list) and api_env_file and isinstance(api_env_file[0], dict):
        api_env_file = [entry.get("path") for entry in api_env_file]
    if api_env_file != [api_env_path]:
        raise InstallError("Chemin du fichier d'environnement API inattendu.")
    api_file_values = api_values
    if any(api_file_values.get(key) for key in PSP_SECRET_KEYS):
        raise InstallError("Une clé PSP ou Resend doit rester vide.")
    unexpected_secret_values = [
        key for key, value in api_file_values.items()
        if key != "SECRET_KEY" and re.search(r"(?:KEY|SECRET|TOKEN|PASSWORD)$", key) and value
    ]
    if unexpected_secret_values:
        raise InstallError("Une variable sensible facultative doit rester vide.")
    networks = config.get("networks", {})
    if networks.get("data", {}).get("internal") is not True:
        raise InstallError("Le réseau PostgreSQL doit rester interne.")
    if "data" not in services["postgres"].get("networks", {}) or "data" not in services["api"].get("networks", {}):
        raise InstallError("Réseau privé API/PostgreSQL incomplet.")
    if services["api"].get("depends_on", {}).get("postgres", {}).get("condition") != "service_healthy":
        raise InstallError("Dépendance au healthcheck PostgreSQL absente.")
    if "uploads" not in config.get("volumes", {}):
        raise InstallError("Volume uploads absent.")
    if api_file_values.get("UPLOAD_DIR") != "/app/backend/uploads":
        raise InstallError("Chemin des uploads inattendu.")
    upload_mounts = services["api"].get("volumes", [])
    if not any(
        isinstance(mount, dict) and mount.get("source") == "uploads"
        and mount.get("target") == "/app/backend/uploads"
        for mount in upload_mounts
    ):
        raise InstallError("Volume persistant des uploads mal configuré.")
    manifest_file = compose_values.get("SERVICE_AREA_MANIFEST_FILE", "")
    if not manifest_file.startswith("/etc/kwitli/") or not manifest_file.endswith(".json"):
        raise InstallError("Chemin du manifeste de zones staging invalide.")
    if not any(
        isinstance(mount, dict) and mount.get("source") == manifest_file
        and mount.get("target") == "/run/kwitli/service-areas.json"
        and mount.get("read_only") is True
        for mount in services["api"].get("volumes", [])
    ):
        raise InstallError("Manifeste de zones staging absent ou non monté en lecture seule.")


def atomic_install_pair(directory: Path, files: dict[Path, bytes], owner: tuple[int, int] = (0, 0)) -> list[tuple[Path, int, int]]:
    if os.geteuid() != 0 and owner == (0, 0):
        raise InstallError("L'installation doit être lancée avec sudo.")
    directory_info = directory.lstat()
    if (not stat.S_ISDIR(directory_info.st_mode) or directory_info.st_uid != owner[0]
            or directory_info.st_gid != owner[1] or stat.S_IMODE(directory_info.st_mode) & 0o022):
        raise InstallError("Répertoire /etc/kwitli non sûr; vérifier propriétaire et permissions.")
    for destination in files:
        if destination.exists() or destination.is_symlink():
            raise InstallError(f"Refus d'écraser le fichier actif: {destination.name}.")

    temporary: list[tuple[Path, Path, int, int]] = []
    linked: list[tuple[Path, int, int]] = []
    try:
        for destination, content in files.items():
            fd, temp_name = tempfile.mkstemp(prefix=".kwitli-stage-", dir=directory)
            temp_path = Path(temp_name)
            try:
                os.fchown(fd, *owner)
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb", closefd=True) as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                info = temp_path.stat(follow_symlinks=False)
                temporary.append((temp_path, destination, info.st_dev, info.st_ino))
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                temp_path.unlink(missing_ok=True)
                raise
        for temp_path, destination, device, inode in temporary:
            os.link(temp_path, destination, follow_symlinks=False)
            linked.append((destination, device, inode))
        directory_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return linked
    except Exception:
        for destination, device, inode in reversed(linked):
            try:
                info = destination.stat(follow_symlinks=False)
                if (info.st_dev, info.st_ino) == (device, inode):
                    destination.unlink()
            except FileNotFoundError:
                pass
        raise
    finally:
        for temp_path, _, _, _ in temporary:
            temp_path.unlink(missing_ok=True)


def remove_our_files(files: list[tuple[Path, int, int]]) -> None:
    for path, device, inode in reversed(files):
        try:
            info = path.stat(follow_symlinks=False)
            if (info.st_dev, info.st_ino) == (device, inode):
                path.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    if os.geteuid() != 0:
        raise InstallError("Lancer ce script avec sudo depuis le compte kwitliadmin.")
    sudo_user = os.environ.get("SUDO_USER", "")
    if not sudo_user or sudo_user == "root":
        raise InstallError("Compte appelant sudo introuvable.")
    try:
        home = Path(pwd.getpwnam(sudo_user).pw_dir)
    except KeyError:
        raise InstallError("Compte appelant sudo invalide.") from None

    models = home / "kwitli-deploy-stage" / "deploy"
    compose_model = parse_env_text(read_regular_file(models / "preproduction.compose.env.example"), "modèle Compose")
    api_model = parse_env_text(read_regular_file(models / "preproduction.api.env.example"), "modèle API")
    missing_compose = sorted(set(REQUIRED_COMPOSE_KEYS) - set(compose_model))
    missing_api = sorted(set(REQUIRED_API_KEYS) - set(api_model))
    if missing_compose or missing_api:
        raise InstallError("Variables requises absentes des modèles.")

    compose_path = Path("/opt/kwitli/deploy/compose.production.yaml")
    compose_text = read_regular_file(compose_path)
    expected_compose_fragments = (
        "APP_ENV: ${KWITLI_APP_ENV:",
        "DATABASE_URL: ${DATABASE_URL:",
        "ALEMBIC_DATABASE_URL: ${DATABASE_URL:",
        "POSTGRES_INITDB_ARGS: --encoding=UTF8 --locale=C.UTF-8",
        "SERVICE_AREA_MANIFEST_PATH: /run/kwitli/service-areas.json",
        "${SERVICE_AREA_MANIFEST_FILE:?Set the reviewed manifest for this environment}:/run/kwitli/service-areas.json:ro",
    )
    if any(fragment not in compose_text for fragment in expected_compose_fragments):
        raise InstallError("Compose staging incompatible avec l'installateur.")
    if any(api_model.get(key, "") for key in PSP_SECRET_KEYS):
        raise InstallError("Une clé PSP ou Resend doit rester vide dans le modèle.")
    if (api_model.get("WOMPI_ENV") != "sandbox" or api_model.get("PAYU_ENV") != "sandbox"
            or api_model.get("PAYDUNYA_MODE") != "sandbox" or api_model.get("FLUTTERWAVE_ENV") != "test"
            or api_model.get("PAYTECH_ENV") != "test"):
        raise InstallError("Mode sandbox/test inattendu dans le modèle API.")

    manifest_file = "/etc/kwitli/preproduction.service-areas.json"
    validate_service_area_manifest_file(Path(manifest_file))

    postgres_password = read_secret(SECRET_PATHS["postgres"])
    jwt_secret = read_secret(SECRET_PATHS["jwt"])

    compose_values = dict(compose_model)
    compose_values.update({
        "KWITLI_APP_ENV": "staging",
        "KWITLI_IMAGE": IMAGE,
        "KWITLI_API_ENV_FILE": API_ENV_PATH,
        "SERVICE_AREA_MANIFEST_FILE": manifest_file,
        "KWITLI_POSTGRES_DB": DATABASE,
        "KWITLI_POSTGRES_USER": DATABASE,
        "KWITLI_POSTGRES_PASSWORD": postgres_password,
        "DATABASE_URL": build_database_url(postgres_password),
        "PUBLIC_API_URL": "https://api.kwitli.app",
        "TRUSTED_PROXY_IPS": "172.30.0.2",
    })
    api_values = dict(api_model)
    api_values["SECRET_KEY"] = jwt_secret
    api_values["SERVICE_AREA_MANIFEST_PATH"] = SERVICE_AREA_CONTAINER_PATH
    api_values["UPLOAD_DIR"] = "/app/backend/uploads"
    api_values["RESEND_API_KEY"] = ""
    api_values.pop("RESEND_API", None)
    if (compose_values["KWITLI_APP_ENV"] != "staging" or compose_values["KWITLI_IMAGE"] != IMAGE
            or compose_values["KWITLI_POSTGRES_DB"] != DATABASE or compose_values["KWITLI_POSTGRES_USER"] != DATABASE):
        raise InstallError("Paramètres staging inattendus.")
    if compose_values["SERVICE_AREA_MANIFEST_FILE"] != manifest_file:
        raise InstallError("Chemin du manifeste staging inattendu.")
    if any(api_values.get(key, "") for key in PSP_SECRET_KEYS):
        raise InstallError("Une clé PSP ou Resend n'est pas vide.")

    target_dir = Path("/etc/kwitli")
    compose_target = target_dir / "preproduction.compose.env"
    api_target = target_dir / "preproduction.api.env"
    created: list[tuple[Path, int, int]] = []
    try:
        created = atomic_install_pair(target_dir, {
            compose_target: render_env(compose_values),
            api_target: render_env(api_values),
        })
        clean_env = {"PATH": os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"), "HOME": "/root"}
        with tempfile.TemporaryDirectory(prefix="kwitli-compose-check-") as docker_config:
            clean_env["DOCKER_CONFIG"] = docker_config
            result = subprocess.run(
                ["docker", "compose", "--project-name", PROJECT, "--env-file", str(compose_target),
                 "-f", str(compose_path), "config", "--no-env-resolution", "--format", "json"],
                check=False, capture_output=True, text=True, env=clean_env, timeout=30,
            )
        if result.returncode != 0:
            raise InstallError("docker compose config a échoué; détails masqués pour protéger les secrets.")
        try:
            rendered = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            raise InstallError("La configuration Compose rendue est invalide; détails masqués.") from None
        validate_compose_config(rendered, compose_values, api_values)
        for path in (compose_target, api_target):
            metadata = path.stat(follow_symlinks=False)
            if metadata.st_uid != 0 or metadata.st_gid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
                raise InstallError("Permissions finales invalides sur un fichier staging.")
    except Exception:
        if created:
            remove_our_files(created)
        raise
    print("PASS: fichiers staging installés root:root 0600; variables, secrets, URL PostgreSQL et Compose validés sans afficher leur contenu.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except InstallError as error:
        print(f"STOP: {error}", file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        print("STOP: erreur interne; détails masqués pour protéger les secrets.", file=sys.stderr)
        raise SystemExit(1)
