import json
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from deploy.install_preproduction_env import InstallError, validate_service_area_manifest_file


def _manifest(**overrides):
    return {
        "version": 1,
        "environment": "staging",
        "database_name": "kwitli_preproduction",
        "required_area_ids": ["legacy-market"],
        "zones": [{"id": "legacy-market", "source_environment": "staging", "active": True}],
        **overrides,
    }


def _pretend_root_readonly(monkeypatch, path):
    metadata = SimpleNamespace(
        st_mode=stat.S_IFREG | 0o444, st_uid=0, st_size=path.stat().st_size,
    )
    monkeypatch.setattr(Path, "lstat", lambda self: metadata if self == path else self.stat())


def test_staging_manifest_preflight_accepts_only_target_manifest(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    _pretend_root_readonly(monkeypatch, path)
    validate_service_area_manifest_file(path)


@pytest.mark.parametrize("overrides", [
    {"environment": "development"},
    {"database_name": "kwitli_dev"},
    {"required_area_ids": ["missing-market"]},
    {"zones": [{"id": "ca-sherbrooke-dev", "source_environment": "staging", "active": True}]},
    {"zones": [{"id": "legacy-market", "source_environment": "development", "active": True}]},
])
def test_staging_manifest_preflight_rejects_wrong_scope(tmp_path, monkeypatch, overrides):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest(**overrides)), encoding="utf-8")
    _pretend_root_readonly(monkeypatch, path)
    with pytest.raises(InstallError, match="incompatible"):
        validate_service_area_manifest_file(path)
