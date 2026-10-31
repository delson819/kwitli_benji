#!/usr/bin/env bash
set -Eeuo pipefail

: "${KWITLI_COMPOSE_ENV_FILE:=/etc/kwitli/production.env}"
: "${KWITLI_COMPOSE_FILE:=/opt/kwitli/deploy/compose.production.yaml}"
: "${KWITLI_COMPOSE_PROJECT_NAME:=}"
: "${KWITLI_BACKUP_SKIP_RETENTION:=0}"
: "${RESTIC_REPOSITORY:?Set RESTIC_REPOSITORY in the root-only backup environment}"
: "${RESTIC_PASSWORD_FILE:?Set RESTIC_PASSWORD_FILE in the root-only backup environment}"

export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE

if [[ "$KWITLI_BACKUP_SKIP_RETENTION" != 0 && "$KWITLI_BACKUP_SKIP_RETENTION" != 1 ]]; then
  printf 'KWITLI_BACKUP_SKIP_RETENTION must be 0 or 1.\n' >&2
  exit 2
fi

if [[ "$KWITLI_BACKUP_SKIP_RETENTION" == 1 ]]; then
  if [[ "$KWITLI_COMPOSE_PROJECT_NAME" != kwitli-preproduction || \
        "$KWITLI_COMPOSE_ENV_FILE" != /etc/kwitli/preproduction.compose.env || \
        ! "$RESTIC_REPOSITORY" =~ ^s3:https://[[:xdigit:]]{32}\.eu\.r2\.cloudflarestorage\.com/kwitli-restic-backups/staging/[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
    printf 'Initial backup without retention is restricted to the Kwitli preproduction project and an R2 /staging repository.\n' >&2
    exit 2
  fi
fi

compose=(docker compose)
if [[ -n "$KWITLI_COMPOSE_PROJECT_NAME" ]]; then
  compose+=(--project-name "$KWITLI_COMPOSE_PROJECT_NAME")
fi
compose+=(--env-file "$KWITLI_COMPOSE_ENV_FILE" --file "$KWITLI_COMPOSE_FILE")

dump_name="kwitli-postgres.dump"

if [[ "$KWITLI_BACKUP_SKIP_RETENTION" == 1 ]]; then
  # Keep the resolved Compose configuration in a pipe; it contains credentials.
  "${compose[@]}" config --format json | python3 -c '
import json
import sys
from urllib.parse import urlsplit

config = json.load(sys.stdin)
services = config.get("services", {})
postgres = services.get("postgres", {})
api = services.get("api", {})
env = postgres.get("environment", {}) or {}
api_env = api.get("environment", {}) or {}
try:
    db_url = urlsplit(api_env.get("DATABASE_URL", ""))
    db_port = db_url.port
except ValueError:
    db_url = urlsplit("")
    db_port = None
volumes = config.get("volumes", {}) or {}
api_mounts = {entry.get("target"): entry.get("source") for entry in api.get("volumes", [])}
postgres_mounts = {entry.get("target"): entry.get("source") for entry in postgres.get("volumes", [])}
networks = config.get("networks", {}) or {}
api_networks = api.get("networks", {}) or {}
postgres_networks = postgres.get("networks", {}) or {}

checks = {
    "project.name": config.get("name") == "kwitli-preproduction",
    "service.postgres.present": "postgres" in services,
    "service.api.present": "api" in services,
    "database.postgres.name": env.get("POSTGRES_DB") == "kwitli_preproduction",
    "database.api.url": db_url.scheme == "postgresql+psycopg2"
    and db_url.hostname == "postgres"
    and db_port == 5432
    and db_url.path == "/kwitli_preproduction",
    "volume.postgres.mount": postgres_mounts.get("/var/lib/postgresql") == "postgres_data",
    "volume.postgres.name": volumes.get("postgres_data", {}).get("name") == "kwitli-preproduction_postgres_data",
    # Service mounts use logical Compose keys; the physical Docker volume name
    # is independently resolved in the top-level volumes mapping.
    "volume.uploads.mount": api_mounts.get("/app/backend/uploads") == "uploads",
    "volume.uploads.name": volumes.get("uploads", {}).get("name") == "kwitli-preproduction_uploads",
    "network.postgres.private": "data" in postgres_networks,
    "network.api.private": "data" in api_networks,
    "network.data.internal": networks.get("data", {}).get("internal") is True,
    "port.postgres.unpublished": not postgres.get("ports"),
    "port.api.unpublished": not api.get("ports"),
}
failed = [name for name, passed in checks.items() if not passed]
if failed:
    raise SystemExit("Resolved Compose checks failed: " + ", ".join(failed) + ".")
print("Preflight PASS: kwitli_preproduction, staging PostgreSQL/uploads volumes, no host ports.")
' || {
    printf 'Staging Compose preflight failed; backup stopped before reading data.\n' >&2
    exit 2
  }

  actual_db="$("${compose[@]}" exec --no-TTY postgres sh -ec 'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --no-psqlrc --tuples-only --no-align --command="SELECT current_database()"')"
  if [[ "$actual_db" != kwitli_preproduction ]]; then
    printf 'Runtime database identity mismatch; backup stopped.\n' >&2
    exit 2
  fi
  "${compose[@]}" exec --no-TTY api python -c 'from pathlib import Path; p = Path("/app/backend/uploads"); assert p.is_dir()'
  printf 'Runtime preflight PASS: PostgreSQL database and uploads mount are available.\n'
fi

"${compose[@]}" exec --no-TTY postgres \
  sh -ec 'pg_dump --format=custom --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  | restic backup --stdin --stdin-filename "$dump_name" --tag kwitli --tag postgres

"${compose[@]}" exec --no-TTY api \
  python -c 'import sys, tarfile; archive = tarfile.open(fileobj=sys.stdout.buffer, mode="w|"); archive.add("/app/backend/uploads", arcname="uploads"); archive.close()' \
  | restic backup --stdin --stdin-filename kwitli-uploads.tar --tag kwitli --tag uploads

if [[ "$KWITLI_BACKUP_SKIP_RETENTION" == 1 ]]; then
  printf 'Initial staging validation: retention and pruning intentionally skipped.\n'
else
  restic forget --group-by host,tags --keep-daily 7 --keep-weekly 5 --keep-monthly 12 --prune
fi
