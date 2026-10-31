from __future__ import annotations

import importlib.util
import io
import tarfile
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "restore_preproduction_backup.py"
SPEC = importlib.util.spec_from_file_location("restore_preproduction_backup", SCRIPT)
restore = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(restore)
INSTALLER_SCRIPT = Path(__file__).resolve().parents[1] / "install_preproduction_backup_env.py"
INSTALLER_SPEC = importlib.util.spec_from_file_location("preproduction_backup_env_installer", INSTALLER_SCRIPT)
installer = importlib.util.module_from_spec(INSTALLER_SPEC)
assert INSTALLER_SPEC.loader is not None
INSTALLER_SPEC.loader.exec_module(installer)


def snapshot(snapshot_id: str, time: str, kind: str, hostname: str = "fixture") -> dict:
    return {
        "id": snapshot_id * 64,
        "time": time,
        "hostname": hostname,
        "tags": ["kwitli", kind],
        "paths": ["/fixture/path"],
    }


class PreproductionRestoreTests(unittest.TestCase):
    def test_installer_environment_contract_and_optional_retention_guard(self) -> None:
        repository = (
            "s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/"
            "kwitli-restic-backups/staging/kwitli-preproduction-20261027t120000z-abcdef123456"
        )
        rendered = installer.render_backup_env(repository, "fixture-access-key", "fixture/secret+key=")
        values = restore.parse_backup_environment_text(rendered)
        self.assertNotIn("KWITLI_BACKUP_SKIP_RETENTION", values)
        self.assertEqual(values["KWITLI_COMPOSE_PROJECT_NAME"], "kwitli-preproduction")
        self.assertTrue(restore.validate_repository(values["RESTIC_REPOSITORY"]))
        values_with_guard = restore.parse_backup_environment_text(
            rendered + "KWITLI_BACKUP_SKIP_RETENTION=1\n"
        )
        self.assertEqual(values_with_guard["KWITLI_BACKUP_SKIP_RETENTION"], "1")

    def test_config_diagnostics_name_bad_control_without_printing_value(self) -> None:
        repository = (
            "s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/"
            "kwitli-restic-backups/staging/kwitli-preproduction-20261027t120000z-abcdef123456"
        )
        rendered = installer.render_backup_env(repository, "fixture-access-key", "fixture-secret-value")
        invalid_retention = rendered + "KWITLI_BACKUP_SKIP_RETENTION=0\n"
        with self.assertRaises(restore.RestoreError) as caught:
            restore.parse_backup_environment_text(invalid_retention)
        self.assertIn("backup.skip-retention", str(caught.exception))
        self.assertNotIn("fixture-secret-value", str(caught.exception))

        unexpected = rendered + "UNEXPECTED_PRIVATE_NAME=do-not-print\n"
        with self.assertRaises(restore.RestoreError) as caught:
            restore.parse_backup_environment_text(unexpected)
        self.assertIn("UNEXPECTED_PRIVATE_NAME", str(caught.exception))
        self.assertNotIn("do-not-print", str(caught.exception))

        invalid_repo = rendered.replace("/staging/", "/production/")
        with self.assertRaises(restore.RestoreError) as caught:
            restore.parse_backup_environment_text(invalid_repo)
        self.assertIn("restic.repository-staging", str(caught.exception))
        self.assertNotIn("fixture-secret-value", str(caught.exception))

    def test_repository_is_restricted_to_staging_bucket_prefix(self) -> None:
        valid = "s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/kwitli-restic-backups/staging/run-01"
        self.assertTrue(restore.validate_repository(valid))
        self.assertFalse(restore.validate_repository(valid.replace("/staging/", "/production/")))
        self.assertFalse(restore.validate_repository(valid.replace("/staging/", "/validation/")))
        self.assertFalse(restore.validate_repository(valid.replace("kwitli-restic-backups", "other-bucket")))

    def test_requires_one_postgres_and_one_uploads_snapshot(self) -> None:
        records = [
            snapshot("a", "2026-10-27T10:00:00Z", "postgres"),
            snapshot("b", "2026-10-27T10:01:00Z", "uploads"),
        ]
        pg, uploads = restore.choose_snapshot_pair({"snapshots": records})
        self.assertEqual(pg["id"], "a" * 64)
        self.assertEqual(uploads["id"], "b" * 64)
        extra_postgres = snapshot("c", "2026-10-27T11:00:00Z", "postgres")
        with self.assertRaisesRegex(restore.RestoreError, "snapshot-pair.ambiguous"):
            restore.choose_snapshot_pair(records + [extra_postgres])

    def test_rejects_missing_mismatched_or_unpaired_snapshots(self) -> None:
        pg = snapshot("a", "2026-10-27T10:00:00Z", "postgres")
        with self.assertRaisesRegex(restore.RestoreError, "snapshot-pair.missing"):
            restore.choose_snapshot_pair([pg])
        uploads = snapshot("b", "2026-10-27T10:01:00Z", "uploads", hostname="other")
        with self.assertRaisesRegex(restore.RestoreError, "snapshot-pair.host-mismatch"):
            restore.choose_snapshot_pair([pg, uploads])

    def test_extracts_uploads_and_returns_non_sensitive_integrity_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "uploads.tar"
            payload = b"fixture upload content"
            with tarfile.open(archive_path, "w") as archive:
                info = tarfile.TarInfo("uploads/sample.bin")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            count, size, digest = restore.validate_and_extract_uploads(archive_path, root / "restored")
            self.assertEqual((count, size), (1, len(payload)))
            self.assertEqual(len(digest), 64)
            self.assertEqual((root / "restored" / "sample.bin").read_bytes(), payload)

    def test_rejects_traversal_and_links_in_upload_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            traversal = root / "traversal.tar"
            with tarfile.open(traversal, "w") as archive:
                info = tarfile.TarInfo("uploads/../../outside")
                info.size = 1
                archive.addfile(info, io.BytesIO(b"x"))
            with self.assertRaisesRegex(restore.RestoreError, "uploads.path-invalid"):
                restore.validate_and_extract_uploads(traversal, root / "traversal-output")

            links = root / "links.tar"
            with tarfile.open(links, "w") as archive:
                info = tarfile.TarInfo("uploads/link")
                info.type = tarfile.SYMTYPE
                info.linkname = "../../outside"
                archive.addfile(info)
            with self.assertRaisesRegex(restore.RestoreError, "uploads.member-type-unsupported"):
                restore.validate_and_extract_uploads(links, root / "links-output")

    def test_restore_container_must_have_only_private_temporary_storage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pgdata = Path(tmp) / "postgres-data"
            safe = {
                "Mounts": [{"Type": "bind", "Source": str(pgdata), "Destination": "/var/lib/postgresql"}],
                "HostConfig": {"NetworkMode": "none", "PortBindings": {}},
            }
            restore._validate_restore_container_info(safe, pgdata)
            unsafe = {
                "Mounts": [{"Type": "volume", "Name": "kwitli-preproduction_postgres_data",
                            "Destination": "/var/lib/postgresql"}],
                "HostConfig": {"NetworkMode": "bridge", "PortBindings": {"5432/tcp": []}},
            }
            with self.assertRaisesRegex(restore.RestoreError, "restore.container-isolation-invalid"):
                restore._validate_restore_container_info(unsafe, pgdata)


if __name__ == "__main__":
    unittest.main()
