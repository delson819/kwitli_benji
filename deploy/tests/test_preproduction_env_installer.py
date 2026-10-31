from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "install_preproduction_env.py"
SPEC = importlib.util.spec_from_file_location("preproduction_env_installer", SCRIPT)
assert SPEC and SPEC.loader
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class PreproductionEnvInstallerTests(unittest.TestCase):
    def test_parser_preserves_equals_and_ignores_comments(self):
        self.assertEqual(
            installer.parse_env_text("# comment\nDATABASE_URL=postgresql://u:p@db/name\nRESEND_FROM_EMAIL=Kwitli <noreply@example.invalid>\n"),
            {"DATABASE_URL": "postgresql://u:p@db/name", "RESEND_FROM_EMAIL": "Kwitli <noreply@example.invalid>"},
        )

    def test_parser_rejects_duplicate_names_without_echoing_values(self):
        with self.assertRaises(installer.InstallError) as raised:
            installer.parse_env_text("SECRET_KEY=never-print-this\nSECRET_KEY=again\n")
        self.assertNotIn("never-print-this", str(raised.exception))

    def test_database_url_encodes_password_using_psycopg2_driver(self):
        url = installer.build_database_url("p@ss:/?#% value")
        self.assertEqual(
            url,
            "postgresql+psycopg2://kwitli_preproduction:p%40ss%3A%2F%3F%23%25%20value@postgres:5432/kwitli_preproduction",
        )

    def test_env_writer_quotes_values_with_spaces_and_comment_characters(self):
        rendered = installer.render_env({"PASSWORD": "value # with spaces", "EMAIL": "Kwitli <test@example.invalid>"})
        parsed = installer.parse_env_text(rendered.decode())
        self.assertEqual(parsed, {"PASSWORD": "'value # with spaces'", "EMAIL": "'Kwitli <test@example.invalid>'"})

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose non disponible")
    def test_compose_round_trips_quoted_secret_characters_without_starting_services(self):
        sample = "fake password # with 'apostrophe\\backslash"
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            compose_file = directory / "compose.yaml"
            compose_file.write_text(
                "services:\n  check:\n    image: busybox\n    environment:\n"
                "      SAMPLE: ${SAMPLE:?required}\n",
                encoding="utf-8",
            )
            env_file = directory / "compose.env"
            env_file.write_bytes(installer.render_env({"SAMPLE": sample}))
            result = subprocess.run(
                ["docker", "compose", "--env-file", str(env_file), "-f", str(compose_file), "config", "--format", "json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, "Compose doit accepter les valeurs générées sans démarrer de service")
            rendered = json.loads(result.stdout)
            self.assertEqual(rendered["services"]["check"]["environment"]["SAMPLE"], sample)

    def test_pair_install_refuses_overwrite_and_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            existing = directory / "active.env"
            existing.write_text("old\n")
            with self.assertRaises(installer.InstallError):
                installer.atomic_install_pair(directory, {
                    existing: b"new\n", directory / "other.env": b"other\n",
                }, owner=(os.getuid(), os.getgid()))
            self.assertEqual(existing.read_text(), "old\n")
            self.assertFalse((directory / "other.env").exists())

    def test_pair_install_creates_private_files_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            created = installer.atomic_install_pair(directory, {
                directory / "compose.env": b"APP_ENV=staging\n",
                directory / "api.env": b"SECRET_KEY=fake-test-value\n",
            }, owner=(os.getuid(), os.getgid()))
            self.assertEqual(len(created), 2)
            self.assertEqual((directory / "compose.env").stat().st_mode & 0o777, 0o600)
            self.assertEqual((directory / "api.env").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
