#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077

readonly bucket="kwitli-restic-backups"
readonly endpoint_suffix=".eu.r2.cloudflarestorage.com"
readonly tag="kwitli-hetzner-r2-validation"
work=""
RESTIC_BIN=""
RESTIC_REPOSITORY=""

fail() {
  printf 'FAIL — %s\n' "$1" >&2
  exit 1
}

assert_safe_destination() {
  [[ "$RESTIC_REPOSITORY" =~ ^s3:https://[0-9a-f]{32}\.eu\.r2\.cloudflarestorage\.com/kwitli-restic-backups/validation/hetzner-[a-z0-9-]+$ ]] || return 1
  [[ "$RESTIC_REPOSITORY" != *"/production"* ]]
}

restic_run() {
  local operation="${1:-}" argument status
  shift || true

  assert_safe_destination || return 96
  case "$operation" in
    init|backup|snapshots|check|restore) ;;
    *) return 97 ;;
  esac
  for argument in "$@"; do
    case "$argument" in
      -r|--repo|--repo=*|--repository-file|--repository-file=*) return 98 ;;
    esac
  done

  if "$RESTIC_BIN" "$operation" "$@" >"$work/restic-${operation}.stdout" 2>"$work/restic-${operation}.stderr"; then
    return 0
  else
    status=$?
    printf 'Échec Restic pendant %s (code %s); sortie fournisseur masquée.\n' "$operation" "$status" >&2
    return "$status"
  fi
}

self_test() {
  local test_dir valid_repo original_repo invalid_repo
  test_dir="$(mktemp -d "${TMPDIR:-/tmp}/kwitli-restic-r2.selftest.XXXXXXXX")"
  chmod 700 "$test_dir"
  work="$test_dir"
  RESTIC_BIN="$test_dir/fake-restic"
  cat >"$RESTIC_BIN" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$FAKE_RESTIC_CALLS"
if [[ "${1:-}" == init && "${RESTIC_REPOSITORY:-}" == "${FAKE_RESTIC_EXISTING_REPOSITORY:-}" ]]; then
  exit 17
fi
FAKE
  chmod 700 "$RESTIC_BIN"
  export FAKE_RESTIC_CALLS="$test_dir/calls"

  valid_repo="s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/${bucket}/validation/hetzner-test-123"
  RESTIC_REPOSITORY="$valid_repo"
  export RESTIC_REPOSITORY
  restic_run init || fail "Le faux binaire n'a pas accepté la destination de validation."
  [[ "$(wc -l <"$FAKE_RESTIC_CALLS" | tr -d ' ')" == 1 ]] || fail "Le faux binaire n'a pas reçu l'appel autorisé attendu."

  original_repo="$RESTIC_REPOSITORY"
  export FAKE_RESTIC_EXISTING_REPOSITORY="$original_repo"
  if restic_run init 2>/dev/null; then fail "Une destination déjà initialisée a été réutilisée."; fi
  [[ "$(wc -l <"$FAKE_RESTIC_CALLS" | tr -d ' ')" == 2 ]] || fail "L'initialisation d'un dépôt préexistant n'a pas été contrôlée."

  for invalid_repo in \
    "s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/${bucket}/production" \
    "s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/other-bucket/validation/hetzner-test-456" \
    "s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/${bucket}/validation/previous-run"; do
    RESTIC_REPOSITORY="$invalid_repo"
    if restic_run init 2>/dev/null; then fail "Une destination interdite a été acceptée."; fi
    [[ "$(wc -l <"$FAKE_RESTIC_CALLS" | tr -d ' ')" == 2 ]] || fail "Le faux binaire a été appelé pour une destination interdite."
  done

  RESTIC_REPOSITORY="$original_repo"
  if restic_run erase 2>/dev/null; then fail "Une sous-commande hors liste a été acceptée."; fi
  [[ "$(wc -l <"$FAKE_RESTIC_CALLS" | tr -d ' ')" == 2 ]] || fail "Le faux binaire a reçu une sous-commande hors liste."

  rm -rf -- "$test_dir"
  work=""
  printf 'PASS — garde de destination, refus d’un dépôt préexistant et liste blanche testés avec un faux binaire; aucun appel réseau.\n'
}

cleanup() {
  local status=$?
  trap - EXIT HUP INT TERM
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION
  unset RESTIC_PASSWORD RESTIC_PASSWORD_FILE RESTIC_REPOSITORY RESTIC_CACHE_DIR
  unset aws_access_key_id aws_secret_access_key restic_password account_id
  if [[ -n "$work" && -d "$work" && "$work" == "${TMPDIR:-/tmp}"/kwitli-restic-r2.* ]]; then
    rm -rf -- "$work"
  fi
  exit "$status"
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "${1:-}" == "--self-test" && "$#" == 1 ]]; then
  self_test
  exit 0
fi
[[ "$#" == 0 ]] || fail "Aucun argument n'est accepté."

[[ "$(uname -s)" == Linux ]] || fail "Le test réel doit être exécuté sur Linux ARM64."
case "$(uname -m)" in aarch64|arm64) ;; *) fail "Architecture ARM64 attendue." ;; esac
command -v restic >/dev/null 2>&1 || fail "Restic n'est pas installé."
command -v python3 >/dev/null 2>&1 || fail "Python 3 est requis pour vérifier le snapshot."
[[ -r /dev/tty && -w /dev/tty ]] || fail "Terminal interactif requis; les secrets ne seront pas lus depuis un heredoc."

RESTIC_BIN="$(command -v restic)"
restic_version="$(restic version 2>/dev/null | head -n 1)" || fail "Impossible de lire la version de Restic."
[[ "$restic_version" == restic\ *linux/arm64* ]] || fail "Le binaire Restic ne confirme pas Linux ARM64."
printf 'Restic confirmé : %s\n' "$restic_version"

# Ignore toute configuration héritée qui pourrait rediriger le dépôt ou les identifiants.
unset AWS_PROFILE AWS_SHARED_CREDENTIALS_FILE AWS_CONFIG_FILE AWS_ENDPOINT_URL AWS_ENDPOINT_URL_S3
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION AWS_REGION
unset RESTIC_REPOSITORY RESTIC_REPOSITORY_FILE RESTIC_PASSWORD RESTIC_PASSWORD_COMMAND RESTIC_PASSWORD_FILE RESTIC_CACHE_DIR

printf 'Account ID Cloudflare (32 caractères hexadécimaux, saisi séparément) : ' >/dev/tty
IFS= read -r account_id </dev/tty
[[ "$account_id" =~ ^[[:xdigit:]]{32}$ ]] || fail "Account ID invalide."
account_id="${account_id,,}"

printf 'R2 Access Key ID (saisie masquée) : ' >/dev/tty
IFS= read -r -s aws_access_key_id </dev/tty
printf '\n' >/dev/tty
[[ -n "$aws_access_key_id" && ! "$aws_access_key_id" =~ [[:space:]] ]] || fail "Access Key ID invalide."
printf 'R2 Secret Access Key (saisie masquée) : ' >/dev/tty
IFS= read -r -s aws_secret_access_key </dev/tty
printf '\n' >/dev/tty
[[ -n "$aws_secret_access_key" ]] || fail "Secret Access Key vide."
printf 'Phrase Restic de validation distincte de la production (saisie masquée) : ' >/dev/tty
IFS= read -r -s restic_password </dev/tty
printf '\n' >/dev/tty
[[ -n "$restic_password" ]] || fail "Phrase Restic vide."

work="$(mktemp -d "${TMPDIR:-/tmp}/kwitli-restic-r2.XXXXXXXX")"
chmod 700 "$work"

printf '%s' "$restic_password" >"$work/restic-password"
chmod 600 "$work/restic-password"
unset restic_password

export AWS_ACCESS_KEY_ID="$aws_access_key_id"
export AWS_SECRET_ACCESS_KEY="$aws_secret_access_key"
export AWS_DEFAULT_REGION=auto
export RESTIC_PASSWORD_FILE="$work/restic-password"
export RESTIC_CACHE_DIR="$work/cache"
unset aws_access_key_id aws_secret_access_key

run_id="$(date -u +%Y%m%d-%H%M%S)-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
RESTIC_REPOSITORY="s3:https://${account_id}${endpoint_suffix}/${bucket}/validation/hetzner-${run_id}"
export RESTIC_REPOSITORY
unset account_id
assert_safe_destination || fail "La destination calculée ne correspond pas à la politique de validation."

source_dir="$work/source"
restore_dir="$work/restore"
mkdir -m 700 "$source_dir" "$restore_dir"
mkdir -m 700 "$source_dir/nested"
printf 'Contenu entièrement fictif Kwitli R2 validation.\n' >"$source_dir/readme.txt"
printf '{"fake":true,"record":1}\n' >"$source_dir/nested/fixture.json"
head -c 4096 /dev/zero >"$source_dir/nested/payload.bin"

printf 'Dépôt isolé : s3://<account>.eu.r2.cloudflarestorage.com/%s/validation/hetzner-%s\n' "$bucket" "$run_id"

restic_run init || fail "Initialisation du dépôt neuf impossible; aucun dépôt antérieur ne sera réutilisé."
printf 'PASS — dépôt neuf initialisé.\n'

(
  cd "$source_dir"
  restic_run backup --tag "$tag" .
) || fail "Sauvegarde des fichiers fictifs échouée."
printf 'PASS — fichiers fictifs sauvegardés.\n'

restic_run snapshots --json --tag "$tag" || fail "Lecture des snapshots échouée."
snapshot_id="$(python3 - "$work/restic-snapshots.stdout" "$tag" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    snapshots = json.load(stream)
matches = [s for s in snapshots if sys.argv[2] in (s.get("tags") or [])]
if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0].get("id", "")):
    raise SystemExit(1)
print(matches[0]["id"])
PY
)" || fail "Le snapshot fictif attendu est absent ou ambigu."
printf 'PASS — snapshot fictif présent.\n'

restic_run check --read-data || fail "Le contrôle intégral Restic a échoué."
printf 'PASS — restic check --read-data.\n'

restic_run restore "$snapshot_id" --target "$restore_dir" || fail "La restauration du snapshot a échoué."
restored_count="$(find "$restore_dir" -type f | wc -l)"
restored_count="${restored_count//[[:space:]]/}"
[[ "$restored_count" == 3 ]] || fail "La restauration ne contient pas exactement les trois fichiers attendus."
for relative_path in readme.txt nested/fixture.json nested/payload.bin; do
  file_name="${relative_path##*/}"
  restored_file="$(find "$restore_dir" -type f -name "$file_name" -print -quit)"
  [[ -n "$restored_file" ]] || fail "Un fichier fictif restauré est absent."
  original_hash="$(sha256sum -- "$source_dir/$relative_path")"
  original_hash="${original_hash%% *}"
  restored_hash="$(sha256sum -- "$restored_file")"
  restored_hash="${restored_hash%% *}"
  [[ "$original_hash" == "$restored_hash" ]] || fail "Un SHA256 restauré ne correspond pas."
done
printf 'PASS — restauration et comparaison SHA256 identiques.\n'
printf 'PASS — dépôt R2 conservé pour inspection; aucune suppression distante effectuée.\n'
