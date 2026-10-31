#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
test_dir="$(mktemp -d "${TMPDIR:-/tmp}/kwitli-backup-safety.XXXXXXXX")"
trap 'rm -rf -- "$test_dir"' EXIT

mkdir -p "$test_dir/bin"
cat >"$test_dir/bin/docker" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'docker %s\n' "$*" >>"$KWITLI_TEST_CALLS"
if [[ " $* " == *" config --format json "* ]]; then
  uploads_name=kwitli-preproduction_uploads
  if [[ "${KWITLI_TEST_BAD_UPLOAD_VOLUME:-0}" == 1 ]]; then
    uploads_name=kwitli-unexpected_uploads
  fi
  cat <<JSON
{"name":"kwitli-preproduction","services":{"postgres":{"environment":{"POSTGRES_DB":"kwitli_preproduction"},"volumes":[{"type":"volume","source":"postgres_data","target":"/var/lib/postgresql"}],"networks":{"data":{}}},"api":{"environment":{"DATABASE_URL":"postgresql+psycopg2://test:test@postgres:5432/kwitli_preproduction"},"volumes":[{"type":"volume","source":"uploads","target":"/app/backend/uploads"}],"networks":{"edge":{},"data":{}}}},"volumes":{"postgres_data":{"name":"kwitli-preproduction_postgres_data"},"uploads":{"name":"$uploads_name"}},"networks":{"data":{"internal":true}}}
JSON
elif [[ " $* " == *" exec --no-TTY postgres "* ]]; then
  printf 'kwitli_preproduction\n'
elif [[ " $* " == *" pg_dump "* ]]; then
  printf 'fictional postgres dump\n'
elif [[ " $* " == *" tarfile "* ]]; then
  printf 'fictional uploads archive\n'
fi
MOCK

cat >"$test_dir/bin/restic" <<'MOCK'
#!/usr/bin/env bash
set -Eeuo pipefail
printf 'restic %s\n' "$*" >>"$KWITLI_TEST_CALLS"
if [[ "${1:-}" == backup ]]; then cat >/dev/null; fi
MOCK

chmod 700 "$test_dir/bin/docker" "$test_dir/bin/restic"
export PATH="$test_dir/bin:$PATH"
export KWITLI_TEST_CALLS="$test_dir/calls"
export RESTIC_REPOSITORY='s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/kwitli-restic-backups/staging/preproduction-test-20261026'
export RESTIC_PASSWORD_FILE="$test_dir/restic-password"
touch "$RESTIC_PASSWORD_FILE"

export KWITLI_COMPOSE_PROJECT_NAME=kwitli-preproduction
export KWITLI_COMPOSE_ENV_FILE=/etc/kwitli/preproduction.compose.env
export KWITLI_COMPOSE_FILE=/opt/kwitli/deploy/compose.production.yaml
export KWITLI_BACKUP_SKIP_RETENTION=1
if RESTIC_REPOSITORY='s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/kwitli-restic-backups/production' \
  bash "$repo_root/deploy/backup-postgres.sh" >"$test_dir/rejected" 2>&1; then
  printf 'FAIL — staging mode accepted a production repository.\n' >&2
  exit 1
fi
[[ ! -s "$KWITLI_TEST_CALLS" ]]

bash "$repo_root/deploy/backup-postgres.sh" >"$test_dir/staging-output"

grep -Fq 'docker compose --project-name kwitli-preproduction' "$KWITLI_TEST_CALLS"
! grep -Fq 'restic forget' "$KWITLI_TEST_CALLS"
grep -Fq 'retention and pruning intentionally skipped' "$test_dir/staging-output"

: >"$KWITLI_TEST_CALLS"
if KWITLI_TEST_BAD_UPLOAD_VOLUME=1 bash "$repo_root/deploy/backup-postgres.sh" >"$test_dir/rejected-volume" 2>&1; then
  printf 'FAIL — staging preflight accepted an unexpected physical uploads volume.\n' >&2
  exit 1
fi
grep -Fq 'volume.uploads.name' "$test_dir/rejected-volume"
! grep -Fq 'exec --no-TTY' "$KWITLI_TEST_CALLS"
! grep -Fq 'restic ' "$KWITLI_TEST_CALLS"

: >"$KWITLI_TEST_CALLS"
unset KWITLI_COMPOSE_PROJECT_NAME KWITLI_COMPOSE_ENV_FILE KWITLI_COMPOSE_FILE KWITLI_BACKUP_SKIP_RETENTION
export RESTIC_REPOSITORY='s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/kwitli-restic-backups/production'
bash "$repo_root/deploy/backup-postgres.sh"
grep -Fq 'restic forget --group-by host,tags --keep-daily 7 --keep-weekly 5 --keep-monthly 12 --prune' "$KWITLI_TEST_CALLS"

printf 'PASS — staging validation pins project/database/repository and skips pruning; default production retention remains unchanged.\n'
