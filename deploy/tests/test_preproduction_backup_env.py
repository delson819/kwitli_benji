import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "install_preproduction_backup_env.py"
SPEC = importlib.util.spec_from_file_location("preproduction_backup_env", SCRIPT)
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def valid_compose_config():
    return {
        "services": {
            "postgres": {
                "environment": {"POSTGRES_DB": "kwitli_preproduction"},
                "volumes": [{"target": "/var/lib/postgresql", "source": "postgres_data"}],
                "networks": ["data"],
            },
            "api": {
                "environment": {
                    "DATABASE_URL": "postgresql+psycopg2://private-user:private-pass@postgres:5432/kwitli_preproduction"
                },
                "volumes": [{"target": "/app/backend/uploads", "source": "uploads"}],
                "networks": {"data": {}},
            },
        },
        "volumes": {
            "postgres_data": {"name": "kwitli-preproduction_postgres_data"},
            "uploads": {"name": "kwitli-preproduction_uploads"},
        },
        "networks": {"data": {"internal": True}},
    }


class PreproductionComposeValidationTests(unittest.TestCase):
    def test_accepts_logical_upload_volume_key_and_checks_resolved_name(self):
        # Compose keeps `uploads` as the service's logical source key and puts
        # the project-prefixed Docker volume name in top-level `volumes`.
        installer.validate_compose_config(valid_compose_config())

    def test_rejects_wrong_resolved_upload_volume_by_control_name(self):
        config = valid_compose_config()
        config["volumes"]["uploads"]["name"] = "kwitli-other_uploads"
        with self.assertRaisesRegex(installer.SetupError, "volume.uploads.name") as raised:
            installer.validate_compose_config(config)
        self.assertNotIn("private-pass", str(raised.exception))

    def test_rejects_wrong_database_without_showing_database_url(self):
        config = valid_compose_config()
        config["services"]["postgres"]["environment"]["POSTGRES_DB"] = "wrong-db"
        with self.assertRaisesRegex(installer.SetupError, "database.postgres.name") as raised:
            installer.validate_compose_config(config)
        self.assertNotIn("private-pass", str(raised.exception))
        self.assertNotIn("postgresql+psycopg2", str(raised.exception))

    def test_rejects_published_api_port_by_control_name(self):
        config = valid_compose_config()
        config["services"]["api"]["ports"] = [{"target": 8000, "published": "8000"}]
        with self.assertRaisesRegex(installer.SetupError, "port.api.unpublished"):
            installer.validate_compose_config(config)


class StagingRepositoryIdTests(unittest.TestCase):
    def test_generated_id_uses_only_characters_allowed_by_validator(self):
        from datetime import datetime, timezone

        run_id = installer.generate_repository_id(
            datetime(2026, 10, 26, 12, 34, 56, tzinfo=timezone.utc),
            "abcdef123456",
        )
        self.assertEqual(run_id, "kwitli-preproduction-20261026t123456z-abcdef123456")
        self.assertRegex(run_id, r"^[a-z0-9][a-z0-9-]{8,80}$")

    def test_final_repository_path_is_confined_to_staging_bucket_prefix(self):
        run_id = "kwitli-preproduction-20261026t123456z-abcdef123456"
        repository = installer.build_repository("0123456789abcdef0123456789abcdef", run_id)
        self.assertEqual(
            repository,
            "s3:https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com/"
            "kwitli-restic-backups/staging/kwitli-preproduction-20261026t123456z-abcdef123456",
        )
        self.assertNotIn("/production", repository)
        self.assertNotIn("/validation", repository)

    def test_previous_uppercase_timestamp_format_is_rejected(self):
        old_id = "kwitli-preproduction-20261026T123456Z-abcdef123456"
        with self.assertRaisesRegex(installer.SetupError, "identifier is invalid"):
            installer.build_repository("0123456789abcdef0123456789abcdef", old_id)


if __name__ == "__main__":
    unittest.main()
