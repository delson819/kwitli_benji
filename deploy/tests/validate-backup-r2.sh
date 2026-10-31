#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077

declare -a STEP_NAMES=("Prérequis/configuration" "Compose temporaire" "Données PostgreSQL fictives" "Uploads fictifs" "Initialisation Restic" "Sauvegarde et rétention" "Snapshots" "Contrôle Restic" "Restauration PostgreSQL" "Restauration uploads/SHA256" "Nettoyage Docker")
declare -a STEP_STATUS=("NON EXÉCUTÉ" "NON EXÉCUTÉ" "NON EXÉCUTÉ" "NON EXÉCUTÉ" "NON EXÉCUTÉ" "NON EXÉCUTÉ" "NON EXÉCUTÉ" "NON EXÉCUTÉ" "NON EXÉCUTÉ" "NON EXÉCUTÉ" "NON EXÉCUTÉ")
current_index=0
current_step="Initialisation"
work=""
compose_started=0

die() {
  local message="$1"
  [[ -z "${current_step:-}" ]] || STEP_STATUS[$current_index]="FAIL"
  printf 'ÉCHEC — %s\n' "$message" >&2
  exit 1
}
step_begin() { current_index="$1"; current_step="${STEP_NAMES[$current_index]}"; printf '\n[ÉTAPE] %s\n' "$current_step"; }
step_pass() { STEP_STATUS[$current_index]="PASS"; printf '[PASS] %s\n' "$current_step"; current_step=""; }
on_error() {
  local status=$? line="${BASH_LINENO[0]:-$LINENO}"
  trap - ERR
  [[ -z "${current_step:-}" ]] || STEP_STATUS[$current_index]="FAIL"
  printf 'ÉCHEC inattendu — étape : %s ; ligne : %s ; code : %s\n' "${current_step:-étape non identifiée}" "$line" "$status" >&2
  exit "$status"
}
trap on_error ERR
report_results() {
  local index
  printf '\n===== RAPPORT FINAL PASS/FAIL =====\n'
  for index in "${!STEP_NAMES[@]}"; do printf '%s : %s\n' "${STEP_NAMES[$index]}" "${STEP_STATUS[$index]}"; done
}
cleanup() {
  local status=$?
  trap - EXIT INT TERM ERR
  set +e
  if (( compose_started )); then
    current_step="${STEP_NAMES[10]}"
    printf '\n[ÉTAPE] %s\n' "$current_step"
    "${compose[@]}" down --volumes --remove-orphans >"$work/cleanup.log" 2>&1
    if (( $? == 0 )); then STEP_STATUS[10]="PASS"; printf '[PASS] Projet temporaire supprimé : %s\n' "$project"
    else STEP_STATUS[10]="FAIL"; printf '[FAIL] Nettoyage du seul projet %s.\n' "$project" >&2; status=1; fi
  else STEP_STATUS[10]="NON EXÉCUTÉ — aucun projet démarré"; fi
  if [[ -n "$work" && -d "$work" ]]; then rm -rf "$work" || status=1; fi
  report_results
  printf 'Le dépôt R2 de validation est conservé. backup-postgres.sh peut y exécuter forget --prune sous la garde du dépôt.\n'
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '%s' "Enregistre la phrase Restic dans ton gestionnaire de mots de passe. Tape OUI pour confirmer : "
[[ -r /dev/tty ]] || die "/dev/tty indisponible."
read -r confirmation < /dev/tty
[[ "$confirmation" == OUI ]] || die "Confirmation requise."
repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
[[ -f "$repo_root/deploy/backup-postgres.sh" ]] || die "backup-postgres.sh introuvable."

step_begin 0
command -v docker >/dev/null 2>&1 || die "Docker CLI introuvable."
command -v restic >/dev/null 2>&1 || die "Restic introuvable."
command -v python3 >/dev/null 2>&1 || die "python3 introuvable."
command -v tar >/dev/null 2>&1 || die "tar introuvable."
docker info >/dev/null 2>&1 || die "Docker daemon inaccessible."
docker compose version >/dev/null 2>&1 || die "Docker Compose indisponible."
real_restic="$(command -v restic)"
printf '%s' "Cloudflare Account ID (32 caractères hexadécimaux) : "
read -r -s AWS_ACCOUNT_ID < /dev/tty; printf '\n'
[[ "$AWS_ACCOUNT_ID" =~ ^[[:xdigit:]]{32}$ ]] || die "Account ID invalide."
printf '%s' "R2 Access Key ID : "; read -r -s AWS_ACCESS_KEY_ID < /dev/tty; printf '\n'
[[ -n "$AWS_ACCESS_KEY_ID" ]] || die "Access Key ID vide."
printf '%s' "R2 Secret Access Key : "; read -r -s AWS_SECRET_ACCESS_KEY < /dev/tty; printf '\n'
[[ -n "$AWS_SECRET_ACCESS_KEY" ]] || die "Secret Access Key vide."
printf '%s' "Phrase secrète Restic de validation : "; read -r -s RESTIC_PASSWORD < /dev/tty; printf '\n'
[[ -n "$RESTIC_PASSWORD" ]] || die "Phrase Restic vide."

run_id="$(date -u +%Y%m%dT%H%M%SZ | tr '[:upper:]' '[:lower:]')-$(python3 -c 'import secrets; print(secrets.token_hex(6))')"
project="kwitli-backup-validation-${run_id}"
repo_suffix="postgres-uploads-${run_id}"
RESTIC_REPOSITORY="s3:https://${AWS_ACCOUNT_ID}.eu.r2.cloudflarestorage.com/kwitli-restic-backups/validation/${repo_suffix}"
[[ "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "Nom Compose invalide."
[[ "$RESTIC_REPOSITORY" == *"/validation/postgres-uploads-"* && "$RESTIC_REPOSITORY" != *"/production"* ]] || die "Dépôt de validation invalide."
work="$(mktemp -d "${TMPDIR:-/tmp}/kwitli-backup-validation.XXXXXX")"
chmod 700 "$work"
RESTIC_PASSWORD_FILE="$work/restic-password"
printf '%s' "$RESTIC_PASSWORD" > "$RESTIC_PASSWORD_FILE"
chmod 600 "$RESTIC_PASSWORD_FILE"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY RESTIC_REPOSITORY RESTIC_PASSWORD_FILE
export KWITLI_VALIDATION_RESTIC_REPOSITORY="$RESTIC_REPOSITORY" KWITLI_REAL_RESTIC="$real_restic"

KWITLI_POSTGRES_DB=kwitli_backup_validation
KWITLI_POSTGRES_USER=kwitli_validation
db_password="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
KWITLI_POSTGRES_PASSWORD="$db_password"
compose_env="$work/compose.env"
compose_file="$work/compose.yaml"
cat > "$compose_env" <<EOF
KWITLI_POSTGRES_DB=$KWITLI_POSTGRES_DB
KWITLI_POSTGRES_USER=$KWITLI_POSTGRES_USER
KWITLI_POSTGRES_PASSWORD=$KWITLI_POSTGRES_PASSWORD
EOF
chmod 600 "$compose_env"
cat > "$compose_file" <<'YAML'
services:
  postgres:
    image: postgres:18.3
    environment:
      POSTGRES_DB: ${KWITLI_POSTGRES_DB:?}
      POSTGRES_USER: ${KWITLI_POSTGRES_USER:?}
      POSTGRES_PASSWORD: ${KWITLI_POSTGRES_PASSWORD:?}
    volumes: [postgres_data:/var/lib/postgresql]
    networks: [isolated]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \"$${POSTGRES_USER}\" -d \"$${POSTGRES_DB}\""]
      interval: 3s
      timeout: 3s
      retries: 30
  api:
    image: python:3.14-slim-bookworm
    command: ["python", "-c", "import time; time.sleep(1000000000)"]
    volumes: [uploads:/app/backend/uploads]
    networks: [isolated]
    depends_on:
      postgres:
        condition: service_healthy
  postgres_restore:
    image: postgres:18.3
    environment:
      POSTGRES_DB: kwitli_backup_validation_restore
      POSTGRES_USER: ${KWITLI_POSTGRES_USER:?}
      POSTGRES_PASSWORD: ${KWITLI_POSTGRES_PASSWORD:?}
    volumes: [postgres_restore_data:/var/lib/postgresql]
    networks: [isolated]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U \"$${POSTGRES_USER}\" -d \"$${POSTGRES_DB}\""]
      interval: 3s
      timeout: 3s
      retries: 30
volumes:
  postgres_data:
  postgres_restore_data:
  uploads:
networks:
  isolated:
    internal: true
YAML
chmod 600 "$compose_file"
export COMPOSE_PROJECT_NAME="$project" KWITLI_COMPOSE_ENV_FILE="$compose_env" KWITLI_COMPOSE_FILE="$compose_file"
compose=(docker compose --project-name "$project" --env-file "$compose_env" --file "$compose_file")

assert_log_safe() {
  local file="$1" content secret
  content="$(<"$file")"
  for secret in "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" "$RESTIC_PASSWORD" "$db_password"; do [[ -z "$secret" || "$content" != *"$secret"* ]] || return 1; done
}
show_log_safely() { assert_log_safe "$1" || { printf 'Sortie masquée car elle pourrait contenir un secret.\n' >&2; return 1; }; cat "$1"; }

step_pass
step_begin 1
existing="$(docker ps -aq --filter "label=com.docker.compose.project=$project")$(docker network ls -q --filter "label=com.docker.compose.project=$project")$(docker volume ls -q --filter "label=com.docker.compose.project=$project")"
[[ -z "$existing" ]] || die "Collision de ressources Compose."
for volume in "${project}_postgres_data" "${project}_postgres_restore_data" "${project}_uploads"; do
  if docker volume inspect "$volume" >/dev/null 2>&1; then die "Volume temporaire attendu déjà existant."; fi
done
if docker network inspect "${project}_isolated" >/dev/null 2>&1; then die "Réseau temporaire attendu déjà existant."; fi
services="$("${compose[@]}" config --services)"
[[ "$services" == *postgres* && "$services" == *api* && "$services" == *postgres_restore* ]] || die "Services Compose absents."
compose_started=1
"${compose[@]}" up -d --wait
step_pass

step_begin 2
"${compose[@]}" exec -T postgres psql --username="$KWITLI_POSTGRES_USER" --dbname="$KWITLI_POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE validation_customers (id integer PRIMARY KEY, name text NOT NULL UNIQUE, label text NOT NULL CHECK (length(label) > 0));
CREATE TABLE validation_orders (id integer PRIMARY KEY, customer_id integer NOT NULL REFERENCES validation_customers(id), reference text NOT NULL UNIQUE, amount_cents integer NOT NULL CHECK (amount_cents > 0));
INSERT INTO validation_customers VALUES (1, 'client-fictif-001', 'client démonstration'), (2, 'client-fictif-002', 'client contrôle');
INSERT INTO validation_orders VALUES (10, 1, 'commande-fictive-A', 1250), (11, 1, 'commande-fictive-B', 2450), (12, 2, 'commande-fictive-C', 990);
SQL
step_pass

step_begin 3
if "${compose[@]}" exec -T api python -c '
import json
from pathlib import Path
root = Path("/app/backend/uploads")
nested = root / "validation" / "nested"
nested.mkdir(parents=True, exist_ok=True)
(root / "validation" / "demo.txt").write_text("fichier fictif KWITLI\n", encoding="utf-8")
(nested / "placeholder.bin").write_bytes(bytes(range(256)))
(nested / "notes.json").write_text(json.dumps({"fictif": True, "id": 7}) + "\n", encoding="utf-8")
'; then
  step_pass
else
  status=$?; STEP_STATUS[3]="FAIL"
  printf '[FAIL] Création des uploads dans api (code %s). État du service :\n' "$status" >&2
  "${compose[@]}" ps api >&2 || true
  current_step=""; exit "$status"
fi

guard_dir="$work/restic-guard"
mkdir -p "$guard_dir"
cat > "$guard_dir/restic" <<'GUARD'
#!/bin/bash
set -Eeuo pipefail
expected="${KWITLI_VALIDATION_RESTIC_REPOSITORY:?Dépôt attendu absent}"
actual="${RESTIC_REPOSITORY:-}"
real_restic="${KWITLI_REAL_RESTIC:?Binaire Restic réel absent}"
case "$expected" in
  s3:https://*.eu.r2.cloudflarestorage.com/kwitli-restic-backups/validation/postgres-uploads-*) ;;
  *) printf 'BLOQUÉ : dépôt attendu hors de /validation.\n' >&2; exit 97 ;;
esac
[[ "$expected" != *"/production"* ]] || { printf 'BLOQUÉ : dépôt production interdit.\n' >&2; exit 97; }
[[ "$actual" == "$expected" ]] || { printf 'BLOQUÉ : RESTIC_REPOSITORY différent du dépôt isolé attendu.\n' >&2; exit 97; }
if [[ "${1:-}" == "forget" ]]; then printf '[PASS] Garde : dépôt isolé vérifié juste avant forget/--prune.\n'; fi
exec "$real_restic" "$@"
GUARD
chmod 700 "$guard_dir/restic"
PATH="$guard_dir:$PATH"
export PATH

step_begin 4
printf 'Initialisation du dépôt Restic neuf (%s).\n' "$repo_suffix"
if restic init >"$work/restic-init.log" 2>&1; then
  show_log_safely "$work/restic-init.log" || die "Sortie Restic masquée."
  step_pass
else
  status=$?; STEP_STATUS[4]="FAIL"
  printf '[FAIL] restic init a échoué (code %s) ; sauvegarde non lancée.\n' "$status" >&2
  show_log_safely "$work/restic-init.log" >&2 || true
  current_step=""; exit "$status"
fi

step_begin 5
printf 'Exécution de backup-postgres.sh ; forget --prune est soumis à la garde Restic.\n'
if bash "$repo_root/deploy/backup-postgres.sh" >"$work/backup.log" 2>&1; then
  show_log_safely "$work/backup.log" || die "Sortie de sauvegarde masquée."
  step_pass
else
  status=$?; STEP_STATUS[5]="FAIL"
  printf '[FAIL] backup-postgres.sh a échoué (code %s).\n' "$status" >&2
  show_log_safely "$work/backup.log" >&2 || true
  current_step=""; exit "$status"
fi

step_begin 6
for kind in postgres uploads; do
  if restic snapshots --json --tag "$kind" >"$work/snapshots-$kind.json" 2>"$work/snapshots-$kind.err"; then
    show_log_safely "$work/snapshots-$kind.err" || die "Sortie Restic masquée."
  else
    status=$?; STEP_STATUS[6]="FAIL"
    printf '[FAIL] Lecture des snapshots %s (code %s).\n' "$kind" "$status" >&2
    show_log_safely "$work/snapshots-$kind.err" >&2 || true
    current_step=""; exit "$status"
  fi
done
python3 - "$work" <<'PY'
import json
import pathlib
import sys
work = pathlib.Path(sys.argv[1])
for kind, other in (("postgres", "uploads"), ("uploads", "postgres")):
    data = json.loads((work / f"snapshots-{kind}.json").read_text())
    snapshots = data if isinstance(data, list) else data.get("snapshots", [])
    if len(snapshots) != 1: raise SystemExit(f"Un snapshot neuf taggé {kind} était attendu.")
    tags = set(snapshots[0].get("tags") or [])
    if not {"kwitli", kind}.issubset(tags) or other in tags: raise SystemExit(f"Tags inattendus pour {kind}.")
    (work / f"snapshot-{kind}.id").write_text(snapshots[0]["id"])
PY
pg_snapshot="$(<"$work/snapshot-postgres.id")"
uploads_snapshot="$(<"$work/snapshot-uploads.id")"
[[ -n "$pg_snapshot" && -n "$uploads_snapshot" && "$pg_snapshot" != "$uploads_snapshot" ]] || die "Snapshots absents ou confondus."
step_pass

step_begin 7
if restic check --read-data >"$work/restic-check.log" 2>&1; then
  show_log_safely "$work/restic-check.log" || die "Sortie Restic masquée."
  step_pass
else
  status=$?; STEP_STATUS[7]="FAIL"
  printf '[FAIL] restic check --read-data (code %s).\n' "$status" >&2
  show_log_safely "$work/restic-check.log" >&2 || true
  current_step=""; exit "$status"
fi

step_begin 8
if restic dump "$pg_snapshot" kwitli-postgres.dump >"$work/kwitli-postgres.dump" 2>"$work/dump-postgres.log"; then
  show_log_safely "$work/dump-postgres.log" || die "Sortie Restic masquée."
else
  status=$?; STEP_STATUS[8]="FAIL"
  printf '[FAIL] Extraction du dump PostgreSQL (code %s).\n' "$status" >&2
  show_log_safely "$work/dump-postgres.log" >&2 || true
  current_step=""; exit "$status"
fi
"${compose[@]}" exec -T postgres_restore pg_restore --no-owner --username="$KWITLI_POSTGRES_USER" --dbname=kwitli_backup_validation_restore < "$work/kwitli-postgres.dump"
make_db_report() {
  local service="$1" database="$2" destination="$3"
  "${compose[@]}" exec -T "$service" psql --username="$KWITLI_POSTGRES_USER" --dbname="$database" --set ON_ERROR_STOP=1 --no-align --tuples-only --field-separator='|' <<'SQL' >"$destination"
SELECT 'tables', count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';
SELECT 'customers', id, name, label FROM validation_customers ORDER BY id;
SELECT 'orders', id, customer_id, reference, amount_cents FROM validation_orders ORDER BY id;
SELECT 'foreign_keys', count(*) FROM pg_constraint WHERE contype='f' AND conrelid IN ('validation_orders'::regclass);
SELECT 'constraints', count(*) FROM pg_constraint WHERE conrelid IN ('validation_customers'::regclass, 'validation_orders'::regclass);
SQL
}
make_db_report postgres "$KWITLI_POSTGRES_DB" "$work/db-original.txt"
make_db_report postgres_restore kwitli_backup_validation_restore "$work/db-restored.txt"
cmp -s "$work/db-original.txt" "$work/db-restored.txt" || die "Données PostgreSQL restaurées différentes."
grep -q '^foreign_keys|1$' "$work/db-restored.txt" || die "Clé étrangère restaurée absente."
if "${compose[@]}" exec -T postgres_restore psql --username="$KWITLI_POSTGRES_USER" --dbname=kwitli_backup_validation_restore --set ON_ERROR_STOP=1 --command="INSERT INTO validation_orders VALUES (99, 999, 'commande-invalide', 1)" >"$work/fk-check.log" 2>&1; then
  die "La base restaurée a accepté une clé étrangère invalide."
else
  grep -qi 'foreign key constraint' "$work/fk-check.log" || die "Erreur FK attendue absente."
fi
step_pass

step_begin 9
mkdir -p "$work/uploads-restored"
if restic dump "$uploads_snapshot" kwitli-uploads.tar >"$work/kwitli-uploads.tar" 2>"$work/dump-uploads.log"; then
  show_log_safely "$work/dump-uploads.log" || die "Sortie Restic masquée."
else
  status=$?; STEP_STATUS[9]="FAIL"
  printf '[FAIL] Extraction de kwitli-uploads.tar (code %s).\n' "$status" >&2
  show_log_safely "$work/dump-uploads.log" >&2 || true
  current_step=""; exit "$status"
fi
tar -xf "$work/kwitli-uploads.tar" -C "$work/uploads-restored"
"${compose[@]}" exec -T api python -c '
import hashlib
from pathlib import Path
root = Path("/app/backend/uploads")
files = sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix())
for path in files: print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}")
' > "$work/uploads-original.sha256"
python3 - "$work/uploads-restored/uploads" >"$work/uploads-restored.sha256" <<'PY'
import hashlib
from pathlib import Path
import sys
root = Path(sys.argv[1])
files = sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix())
for path in files: print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root).as_posix()}")
PY
cmp -s "$work/uploads-original.sha256" "$work/uploads-restored.sha256" || die "Manifestes SHA256 différents."
step_pass
printf '\nDépôt R2 de validation conservé : %s\n' "$repo_suffix"
printf 'backup-postgres.sh exécute forget --prune ; la garde l’a limité à ce dépôt de validation.\n'
