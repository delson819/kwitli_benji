#!/usr/bin/env python3
"""Restore Kwitli staging snapshots into disposable, isolated local resources.

Run on kwitli-prod-01 with sudo. This tool only reads the dedicated Restic
repository and never changes staging services, their volumes, or R2 snapshots.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path, PurePosixPath


BACKUP_ENV = Path("/etc/kwitli/preproduction.backup.env")
RESTIC_PASSWORD = Path("/etc/kwitli/preproduction-restic-password")
COMPOSE_ENV = Path("/etc/kwitli/preproduction.compose.env")
COMPOSE_FILE = Path("/opt/kwitli/deploy/compose.production.yaml")
PROJECT = "kwitli-preproduction"
DATABASE = "kwitli_preproduction"
POSTGRES_IMAGE = "postgres:18.3"
EXPECTED_PG_VOLUME = f"{PROJECT}_postgres_data"
RESTORE_DATABASE = "kwitli_restore_check"
BUCKET = "kwitli-restic-backups"
REPOSITORY_RE = re.compile(
    rf"s3:https://[0-9a-fA-F]{{32}}\.eu\.r2\.cloudflarestorage\.com/"
    rf"{re.escape(BUCKET)}/staging/[a-zA-Z0-9][a-zA-Z0-9._-]*\Z"
)
SNAPSHOT_ID_RE = re.compile(r"[0-9a-f]{8,64}\Z")
REVISION_RE = re.compile(r"[0-9a-f]{12,32}\Z")
R2_VALUE_RE = re.compile(r"[A-Za-z0-9+/=_-]+\Z")


class RestoreError(Exception):
    """Safe diagnostic without command output, secrets, or user data."""


def validate_repository(repository: str) -> bool:
    return REPOSITORY_RE.fullmatch(repository) is not None


def choose_snapshot_pair(payload: object) -> tuple[dict, dict]:
    if isinstance(payload, dict):
        snapshots = payload.get("snapshots")
    else:
        snapshots = payload
    if not isinstance(snapshots, list):
        raise RestoreError("snapshot-list.invalid")

    found: dict[str, list[dict]] = {"postgres": [], "uploads": []}
    for item in snapshots:
        if not isinstance(item, dict):
            raise RestoreError("snapshot-entry.invalid")
        tags = set(item.get("tags") or [])
        if "kwitli" not in tags:
            continue
        for kind in found:
            if kind in tags and ("uploads" if kind == "postgres" else "postgres") not in tags:
                found[kind].append(item)

    if not found["postgres"] or not found["uploads"]:
        raise RestoreError("snapshot-pair.missing")
    if len(found["postgres"]) != 1 or len(found["uploads"]) != 1:
        raise RestoreError("snapshot-pair.ambiguous")

    pg_snapshot, uploads_snapshot = found["postgres"][0], found["uploads"][0]
    for item in (pg_snapshot, uploads_snapshot):
        if not isinstance(item.get("id"), str) or not SNAPSHOT_ID_RE.fullmatch(item["id"]):
            raise RestoreError("snapshot-id.invalid")
        try:
            datetime.fromisoformat(str(item["time"]).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            raise RestoreError("snapshot-time.invalid") from None
    if pg_snapshot["id"] == uploads_snapshot["id"]:
        raise RestoreError("snapshot-pair.same-id")
    if pg_snapshot.get("hostname") != uploads_snapshot.get("hostname"):
        raise RestoreError("snapshot-pair.host-mismatch")
    return pg_snapshot, uploads_snapshot


def validate_and_extract_uploads(archive_path: Path, destination: Path) -> tuple[int, int, str]:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    seen: set[str] = set()
    total_bytes = 0
    file_count = 0
    manifest = hashlib.sha256()
    free_bytes = shutil.disk_usage(destination.parent).free

    try:
        archive = tarfile.open(archive_path, mode="r:*")
    except (tarfile.TarError, OSError):
        raise RestoreError("uploads.archive-invalid") from None

    with archive:
        for member in archive:
            raw = member.name
            path = PurePosixPath(raw)
            if path.is_absolute() or not path.parts or path.parts[0] != "uploads":
                raise RestoreError("uploads.path-invalid")
            if any(part in ("", ".", "..") for part in path.parts):
                raise RestoreError("uploads.path-invalid")
            relative = PurePosixPath(*path.parts[1:])
            key = relative.as_posix()
            if key in seen:
                raise RestoreError("uploads.path-duplicate")
            seen.add(key)
            if not (member.isdir() or member.isfile()):
                raise RestoreError("uploads.member-type-unsupported")
            if member.isfile():
                if member.size < 0 or total_bytes + member.size > free_bytes:
                    raise RestoreError("uploads.insufficient-space")
                total_bytes += member.size
                file_count += 1

            target = destination.joinpath(*relative.parts) if relative.parts else destination
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(target, flags, 0o600)
                source = archive.extractfile(member)
                if source is None:
                    os.close(descriptor)
                    raise RestoreError("uploads.member-unreadable")
                digest = hashlib.sha256()
                copied = 0
                with os.fdopen(descriptor, "wb") as output, source:
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                        copied += len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if copied != member.size:
                    raise RestoreError("uploads.member-truncated")
                manifest.update(key.encode("utf-8", errors="strict"))
                manifest.update(b"\0")
                manifest.update(digest.digest())
                manifest.update(b"\n")
            except RestoreError:
                raise
            except (OSError, UnicodeError, tarfile.TarError):
                raise RestoreError("uploads.extract-failed") from None

    return file_count, total_bytes, manifest.hexdigest()


def _run(args: list[str], *, env: dict[str, str] | None = None, timeout: int = 60) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, env=env, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise RestoreError("command.execution-failed") from None
    if result.returncode != 0:
        raise RestoreError("command.failed")
    return result.stdout.strip()


def _run_to_file(args: list[str], output: Path, *, env: dict[str, str], timeout: int = 1800) -> None:
    try:
        with output.open("wb") as stream:
            os.chmod(output, 0o600)
            result = subprocess.run(args, stdout=stream, stderr=subprocess.DEVNULL, env=env, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        raise RestoreError("snapshot.restore-read-failed") from None
    if result.returncode != 0:
        raise RestoreError("snapshot.restore-read-failed")


def _run_with_stdin_file(args: list[str], input_file: Path, *, env: dict[str, str] | None = None) -> str:
    try:
        with input_file.open("rb") as stream:
            result = subprocess.run(args, stdin=stream, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, env=env, timeout=1800)
    except (OSError, subprocess.SubprocessError):
        raise RestoreError("archive.validation-failed") from None
    if result.returncode != 0:
        raise RestoreError("archive.validation-failed")
    return result.stdout.decode("utf-8", errors="replace")


def parse_backup_environment_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RestoreError("backup-config.syntax-invalid")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z0-9_]+", key) or key in values or not value:
            raise RestoreError("backup-config.syntax-invalid")
        values[key] = value

    required = {
        "KWITLI_COMPOSE_ENV_FILE", "KWITLI_COMPOSE_FILE", "KWITLI_COMPOSE_PROJECT_NAME",
        "RESTIC_REPOSITORY", "AWS_DEFAULT_REGION", "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY", "RESTIC_PASSWORD_FILE",
    }
    optional = {"KWITLI_BACKUP_SKIP_RETENTION"}
    if not required.issubset(values) or values.keys() - required - optional:
        missing = sorted(required - values.keys())
        unexpected = sorted(values.keys() - required - optional)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        raise RestoreError("backup-config.variables-invalid:" + ";".join(details))
    if "KWITLI_BACKUP_SKIP_RETENTION" in values and values["KWITLI_BACKUP_SKIP_RETENTION"] != "1":
        raise RestoreError("backup-config.checks-failed:backup.skip-retention")

    checks = {
        "compose.env-file": values["KWITLI_COMPOSE_ENV_FILE"] == str(COMPOSE_ENV),
        "compose.file": values["KWITLI_COMPOSE_FILE"] == str(COMPOSE_FILE),
        "compose.project": values["KWITLI_COMPOSE_PROJECT_NAME"] == PROJECT,
        "restic.repository-staging": validate_repository(values["RESTIC_REPOSITORY"]),
        "restic.region": values["AWS_DEFAULT_REGION"] == "auto",
        "restic.password-file": values["RESTIC_PASSWORD_FILE"] == str(RESTIC_PASSWORD),
        "r2.credentials-format": R2_VALUE_RE.fullmatch(values["AWS_ACCESS_KEY_ID"]) is not None
        and R2_VALUE_RE.fullmatch(values["AWS_SECRET_ACCESS_KEY"]) is not None,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RestoreError("backup-config.checks-failed:" + ",".join(failed))
    return values


def _load_backup_environment(path: Path) -> dict[str, str]:
    _require_root_file(path)
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeError):
        raise RestoreError("backup-config.unreadable") from None
    values = parse_backup_environment_text(text)
    _require_root_file(RESTIC_PASSWORD)
    _require_root_file(COMPOSE_ENV)
    if not COMPOSE_FILE.is_file():
        raise RestoreError("compose-file.missing")
    return values


def _require_root_file(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError:
        raise RestoreError("required-file.missing") from None
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise RestoreError("required-file.permissions-invalid")


def _confirm_restore() -> None:
    if not sys.stdin.isatty():
        raise RestoreError("restore.interactive-terminal-required")
    print(
        "This will read the two snapshots from R2 and create a temporary, "
        "unpublished PostgreSQL restore. Staging services and R2 snapshots are not modified."
    )
    try:
        answer = input("Type RESTORE kwitli_preproduction to continue: ")
    except (EOFError, OSError):
        raise RestoreError("restore.confirmation-unavailable") from None
    if answer != "RESTORE kwitli_preproduction":
        raise RestoreError("restore.cancelled")


def _docker_json(args: list[str]) -> object:
    try:
        output = _run(args, timeout=30)
        return json.loads(output)
    except (json.JSONDecodeError, RestoreError):
        raise RestoreError("docker.inspect-failed") from None


def _get_staging_postgres() -> tuple[str, str, dict[str, str]]:
    ids = _run([
        "docker", "ps", "--filter", f"label=com.docker.compose.project={PROJECT}",
        "--filter", "label=com.docker.compose.service=postgres", "--format", "{{.ID}}",
    ]).splitlines()
    if len(ids) != 1 or not re.fullmatch(r"[0-9a-f]{12,64}", ids[0]):
        raise RestoreError("staging.postgres-container-ambiguous")
    objects = _docker_json(["docker", "inspect", ids[0]])
    if not isinstance(objects, list) or len(objects) != 1:
        raise RestoreError("staging.postgres-inspect-invalid")
    container = objects[0]
    labels = container.get("Config", {}).get("Labels") or {}
    if (labels.get("com.docker.compose.project") != PROJECT
            or labels.get("com.docker.compose.service") != "postgres"
            or not container.get("State", {}).get("Running")):
        raise RestoreError("staging.postgres-identity-invalid")
    if container.get("Config", {}).get("Image") != POSTGRES_IMAGE:
        raise RestoreError("staging.postgres-image-unexpected")
    mounts = container.get("Mounts", [])
    if (len(mounts) != 1 or mounts[0].get("Type") != "volume"
            or mounts[0].get("Name") != EXPECTED_PG_VOLUME
            or mounts[0].get("Destination") != "/var/lib/postgresql"):
        raise RestoreError("staging.postgres-volume-unexpected")
    env_items = container.get("Config", {}).get("Env") or []
    container_env = dict(item.split("=", 1) for item in env_items if "=" in item)
    if container_env.get("POSTGRES_DB") != DATABASE or not container_env.get("POSTGRES_USER"):
        raise RestoreError("staging.postgres-database-unexpected")
    image_id = container.get("Image")
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise RestoreError("staging.postgres-image-id-invalid")
    networks = container.get("NetworkSettings", {}).get("Networks", {}) or {}
    data_network = networks.get(f"{PROJECT}_data")
    if not data_network or not data_network.get("NetworkID"):
        raise RestoreError("staging.postgres-network-unexpected")
    network_info = _docker_json(["docker", "network", "inspect", data_network["NetworkID"]])
    if (not isinstance(network_info, list) or len(network_info) != 1
            or network_info[0].get("Internal") is not True):
        raise RestoreError("staging.postgres-network-not-private")
    return ids[0], image_id, container_env


def _verify_local_docker() -> None:
    docker_host = os.environ.get("DOCKER_HOST")
    if docker_host not in (None, "unix:///var/run/docker.sock"):
        raise RestoreError("docker.endpoint-not-local")
    context = _run(["docker", "context", "show"], timeout=15)
    endpoint = _run([
        "docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}", context,
    ], timeout=15)
    if endpoint != "unix:///var/run/docker.sock":
        raise RestoreError("docker.endpoint-not-local")


def _get_api_container() -> str:
    ids = _run([
        "docker", "ps", "--filter", f"label=com.docker.compose.project={PROJECT}",
        "--filter", "label=com.docker.compose.service=api", "--format", "{{.ID}}",
    ]).splitlines()
    if len(ids) != 1 or not re.fullmatch(r"[0-9a-f]{12,64}", ids[0]):
        raise RestoreError("staging.api-container-ambiguous")
    objects = _docker_json(["docker", "inspect", ids[0]])
    if not isinstance(objects, list) or len(objects) != 1:
        raise RestoreError("staging.api-inspect-invalid")
    api = objects[0]
    labels = api.get("Config", {}).get("Labels") or {}
    health = api.get("State", {}).get("Health", {}).get("Status")
    if (labels.get("com.docker.compose.project") != PROJECT
            or labels.get("com.docker.compose.service") != "api"
            or not api.get("State", {}).get("Running")
            or health != "healthy"):
        raise RestoreError("staging.api-not-healthy")
    return ids[0]


def _validate_restore_container_info(info: dict, pgdata: Path) -> None:
    mounts = info.get("Mounts", [])
    host_config = info.get("HostConfig", {})
    if (len(mounts) != 1 or mounts[0].get("Type") != "bind"
            or Path(mounts[0].get("Source", "")).resolve() != pgdata.resolve()
            or mounts[0].get("Destination") != "/var/lib/postgresql"
            or host_config.get("NetworkMode") != "none"
            or host_config.get("PortBindings") not in (None, {})):
        raise RestoreError("restore.container-isolation-invalid")


def _psql(container: str, database: str, query: str) -> str:
    return _run([
        "docker", "exec", container, "psql", "--no-psqlrc", "--set", "ON_ERROR_STOP=1",
        "--username=postgres", f"--dbname={database}", "--no-align", "--tuples-only",
        "--command", query,
    ], timeout=1800)


def _collect_database_counts(container: str) -> tuple[int, int, int, int]:
    tables_text = _psql(
        container, RESTORE_DATABASE,
        "SELECT schemaname || E'\\t' || tablename FROM pg_tables "
        "WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1",
    )
    table_names: list[tuple[str, str]] = []
    for line in tables_text.splitlines():
        if "\t" in line:
            schema, table = line.split("\t", 1)
            table_names.append((schema, table))
    total_rows = 0
    for schema, table in table_names:
        quote = lambda name: '"' + name.replace('"', '""') + '"'
        count = _psql(container, RESTORE_DATABASE,
                      f"SELECT count(*) FROM {quote(schema)}.{quote(table)}")
        if not count.isdigit():
            raise RestoreError("database.row-count-invalid")
        total_rows += int(count)
    revision_text = _psql(
        container, RESTORE_DATABASE,
        "SELECT version_num FROM alembic_version ORDER BY version_num",
    )
    revisions = revision_text.splitlines()
    if len(revisions) != 1 or not REVISION_RE.fullmatch(revisions[0]):
        raise RestoreError("database.alembic-revision-invalid")
    fk_summary = _psql(
        container, RESTORE_DATABASE,
        "SELECT count(*) FILTER (WHERE contype='f'), "
        "count(*) FILTER (WHERE contype='f' AND NOT convalidated) "
        "FROM pg_constraint WHERE connamespace='public'::regnamespace",
    )
    try:
        fk_count, unvalidated_fk_count = (int(part) for part in fk_summary.split("|", 1))
    except (ValueError, TypeError):
        raise RestoreError("database.foreign-key-check-invalid") from None
    if unvalidated_fk_count != 0:
        raise RestoreError("database.foreign-keys-unvalidated")
    return len(table_names), total_rows, fk_count, revisions[0]


def _self_test() -> int:
    valid_repo = "s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/kwitli-restic-backups/staging/restore-test"
    assert validate_repository(valid_repo)
    for invalid in (
        valid_repo.replace("/staging/", "/production/"),
        valid_repo.replace("/staging/", "/validation/"),
        valid_repo.replace("kwitli-restic-backups", "other-bucket"),
    ):
        assert not validate_repository(invalid)

    snapshots = [
        {"id": "a" * 64, "time": "2026-10-27T12:00:00Z", "hostname": "stage", "tags": ["kwitli", "postgres"]},
        {"id": "b" * 64, "time": "2026-10-27T12:01:00Z", "hostname": "stage", "tags": ["kwitli", "uploads"]},
    ]
    pg_snapshot, uploads_snapshot = choose_snapshot_pair(snapshots)
    assert pg_snapshot["id"] != uploads_snapshot["id"]
    try:
        choose_snapshot_pair(snapshots[:1])
    except RestoreError as exc:
        assert str(exc) == "snapshot-pair.missing"
    else:
        raise AssertionError("missing uploads snapshot was accepted")

    with tempfile.TemporaryDirectory(prefix="kwitli-restore-selftest-") as tmp:
        root = Path(tmp)
        archive_path = root / "fixture.tar"
        with tarfile.open(archive_path, "w") as archive:
            info = tarfile.TarInfo("uploads/fixture.bin")
            payload = b"kwitli-restore-fixture"
            info.size = len(payload)
            import io
            archive.addfile(info, io.BytesIO(payload))
        count, size, digest = validate_and_extract_uploads(archive_path, root / "safe-output")
        assert count == 1 and size == len(payload) and len(digest) == 64
        assert (root / "safe-output" / "fixture.bin").read_bytes() == payload

        bad_archive = root / "bad.tar"
        with tarfile.open(bad_archive, "w") as archive:
            info = tarfile.TarInfo("uploads/../../escape")
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
        try:
            validate_and_extract_uploads(bad_archive, root / "bad-output")
        except RestoreError as exc:
            assert str(exc) == "uploads.path-invalid"
        else:
            raise AssertionError("path traversal archive was accepted")

        isolated = {
            "Mounts": [{"Type": "bind", "Source": str(root / "pgdata"), "Destination": "/var/lib/postgresql"}],
            "HostConfig": {"NetworkMode": "none", "PortBindings": {}},
        }
        _validate_restore_container_info(isolated, root / "pgdata")
        published = json.loads(json.dumps(isolated))
        published["HostConfig"]["PortBindings"] = {"5432/tcp": [{"HostPort": "5432"}]}
        try:
            _validate_restore_container_info(published, root / "pgdata")
        except RestoreError as exc:
            assert str(exc) == "restore.container-isolation-invalid"
        else:
            raise AssertionError("published PostgreSQL restore container was accepted")
    print("PASS — dépôt staging isolé, paire de snapshots, archive uploads sûre et refus de path traversal (fixtures locales).")
    return 0


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        return _self_test()
    if sys.argv[1:]:
        print("Usage: sudo python3 /opt/kwitli/deploy/restore_preproduction_backup.py [--self-test]", file=sys.stderr)
        return 2
    if os.geteuid() != 0:
        print("FAIL: run with sudo in the interactive Hetzner SSH terminal.", file=sys.stderr)
        return 2

    def stop_cleanly(signum: int, _frame: object) -> None:
        raise RestoreError(f"restore.interrupted-signal-{signum}")

    signal.signal(signal.SIGINT, stop_cleanly)
    signal.signal(signal.SIGTERM, stop_cleanly)

    temp_dir: Path | None = None
    restore_container: str | None = None
    restore_run_id: str | None = None
    try:
        restic_values = _load_backup_environment(BACKUP_ENV)
        env = os.environ.copy()
        for inherited in (
            "RESTIC_PASSWORD", "RESTIC_PASSWORD_COMMAND", "RESTIC_REPOSITORY_FILE",
            "AWS_PROFILE", "AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_S3",
            "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE",
        ):
            env.pop(inherited, None)
        env.update(restic_values)
        print("Preflight PASS — configuration root-only; repository restricted to R2 /staging/.")

        _verify_local_docker()
        pg_id, image_id, pg_env = _get_staging_postgres()
        api_id = _get_api_container()
        actual_database = _run([
            "docker", "exec", pg_id, "psql", "--no-psqlrc", "--set", "ON_ERROR_STOP=1",
            f"--username={pg_env['POSTGRES_USER']}", f"--dbname={pg_env['POSTGRES_DB']}",
            "--tuples-only", "--no-align", "--command=SELECT current_database()",
        ])
        if actual_database != DATABASE:
            raise RestoreError("staging.database-identity-mismatch")
        expected_heads = _run(["docker", "exec", "--workdir=/app", api_id,
                               "python", "-m", "alembic", "heads"], timeout=60)
        heads = re.findall(r"(?m)^([0-9a-f]{12,32}) \(head\)$", expected_heads)
        if len(heads) != 1:
            raise RestoreError("staging.alembic-head-ambiguous")
        print("Preflight PASS — staging DB identity and PostgreSQL 18.3 image verified; API remains running.")

        _confirm_restore()
        temp_dir = Path(tempfile.mkdtemp(prefix="kwitli-preproduction-restore-", dir="/var/tmp"))
        os.chmod(temp_dir, 0o700)
        env["RESTIC_CACHE_DIR"] = str(temp_dir / "restic-cache")
        snapshots_text = _run(["restic", "snapshots", "--json"], env=env, timeout=300)
        try:
            pg_snapshot, uploads_snapshot = choose_snapshot_pair(json.loads(snapshots_text))
        except (json.JSONDecodeError, RestoreError):
            raise RestoreError("snapshot.pair-validation-failed") from None
        print(
            "Snapshots retenus — PostgreSQL "
            f"{pg_snapshot['id'][:12]} ({pg_snapshot['time']}) ; uploads "
            f"{uploads_snapshot['id'][:12]} ({uploads_snapshot['time']})."
        )

        pgdata = temp_dir / "postgres-data"
        pgdata.mkdir(mode=0o700)
        dump_path = temp_dir / "kwitli-postgres.dump"
        _run_to_file(["restic", "dump", pg_snapshot["id"], "kwitli-postgres.dump"], dump_path, env=env)
        if dump_path.stat().st_size < 5:
            raise RestoreError("postgres.dump-empty")
        with dump_path.open("rb") as stream:
            if stream.read(5) != b"PGDMP":
                raise RestoreError("postgres.dump-format-unexpected")
        print(f"Dump PostgreSQL — format custom confirmé, {dump_path.stat().st_size} octets.")

        restore_run_id = os.urandom(16).hex()
        restore_container = f"kwitli-restore-check-{os.getpid()}-{restore_run_id[:8]}"
        _run(["docker", "run", "--detach", "--name", restore_container,
              "--label", f"com.kwitli.restore-check-id={restore_run_id}",
              "--network", "none",
              "--mount", f"type=bind,source={pgdata},target=/var/lib/postgresql",
              "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
              "--env", "POSTGRES_USER=postgres", "--env", "POSTGRES_DB=postgres",
              image_id], timeout=120)
        container_info = _docker_json(["docker", "inspect", restore_container])
        if not isinstance(container_info, list) or len(container_info) != 1:
            raise RestoreError("restore.container-inspect-invalid")
        labels = container_info[0].get("Config", {}).get("Labels") or {}
        if labels.get("com.kwitli.restore-check-id") != restore_run_id:
            raise RestoreError("restore.container-identity-invalid")
        _validate_restore_container_info(container_info[0], pgdata)

        for _ in range(60):
            ready = subprocess.run(["docker", "exec", restore_container, "pg_isready", "-U", "postgres"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RestoreError("restore.postgres-not-ready")
        version = _run(["docker", "exec", restore_container, "postgres", "--version"])
        if not re.search(r"\b18\.3\b", version):
            raise RestoreError("restore.postgres-version-unexpected")

        listing = _run_with_stdin_file(
            ["docker", "exec", "-i", restore_container, "pg_restore", "--list", "-"], dump_path
        )
        toc_entries = [line for line in listing.splitlines() if line.strip() and not line.lstrip().startswith(";")]
        if not toc_entries:
            raise RestoreError("postgres.dump-toc-empty")
        _run(["docker", "exec", restore_container, "createdb", "--username=postgres", RESTORE_DATABASE])
        _run_with_stdin_file(
            ["docker", "exec", "-i", restore_container, "pg_restore", "--exit-on-error",
             "--no-owner", "--no-privileges", "--username=postgres", f"--dbname={RESTORE_DATABASE}", "-"],
            dump_path,
        )
        table_count, row_count, fk_count, restored_revision = _collect_database_counts(restore_container)
        if restored_revision != heads[0]:
            raise RestoreError("database.alembic-head-mismatch")
        dump_path.unlink()
        print(f"PostgreSQL restauré — révision {restored_revision}, {table_count} tables, {row_count} lignes, {fk_count} clés étrangères.")

        uploads_tar = temp_dir / "kwitli-uploads.tar"
        _run_to_file(["restic", "dump", uploads_snapshot["id"], "kwitli-uploads.tar"], uploads_tar, env=env)
        files, bytes_total, upload_digest = validate_and_extract_uploads(uploads_tar, temp_dir / "uploads-restored")
        print(f"Uploads restaurés — {files} fichiers, {bytes_total} octets; empreinte agrégée SHA-256 {upload_digest}.")
        print("PASS — vérification terminée; aucun service staging ni snapshot R2 modifié.")
        return 0
    except RestoreError as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        return 2
    finally:
        if restore_container is not None and restore_run_id is not None:
            inspected = subprocess.run(["docker", "inspect", restore_container],
                                       capture_output=True, text=True)
            try:
                objects = json.loads(inspected.stdout) if inspected.returncode == 0 else []
            except json.JSONDecodeError:
                objects = []
            if (isinstance(objects, list) and len(objects) == 1
                    and (objects[0].get("Config", {}).get("Labels") or {}).get(
                        "com.kwitli.restore-check-id") == restore_run_id):
                subprocess.run(["docker", "rm", "--force", restore_container],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if temp_dir is not None and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
