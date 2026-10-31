import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from backend.app import database
from backend.app import service_area_bootstrap as bootstrap
from backend.app.database import get_session_factory
from backend.app.persistence.models import ServiceAreaConfig, ServiceAreaEvent, User


def _manifest(environment="staging", *, area_id="sn-dakar", source_environment=None, longitude=-17.4677):
    return {
        "version": 1,
        "environment": environment,
        "database_name": "kwitli_test",
        "required_area_ids": [area_id],
        "zones": [{
            "id": area_id,
            "source_environment": source_environment or environment,
            "active": True,
            "code": "SN-DKR",
            "label": "Dakar, Sénégal",
            "country_code": "SN",
            "country": "Sénégal",
            "city": "Dakar",
            "latitude": 14.7167,
            "longitude": longitude,
            "radius_km": 30,
            "timezone": "Africa/Dakar",
            "locale": "fr",
            "currency": "XOF",
            "distance_unit": "km",
        }],
    }


def _write_manifest(tmp_path, payload):
    path = tmp_path / "service-areas.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _admin(session):
    actor = User(email="zone-bootstrap-admin@example.invalid", first_name="Admin", is_admin=True)
    session.add(actor)
    session.flush()
    return actor


def test_bootstrap_preserves_legacy_id_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "get_settings", lambda: SimpleNamespace(app_env="staging"))
    manifest = bootstrap.load_manifest(_write_manifest(tmp_path, _manifest()))
    with get_session_factory()() as session:
        actor = _admin(session)
        actor_id = actor.id
        session.commit()
        assert bootstrap.bootstrap_manifest(
            session, manifest, "kwitli_test", actor_id, "Migration contrôlée staging"
        ) == 1
        assert bootstrap.bootstrap_manifest(
            session, manifest, "kwitli_test", actor_id, "Reprise idempotente"
        ) == 0
        area = session.scalar(select(ServiceAreaConfig).where(
            ServiceAreaConfig.environment == "staging", ServiceAreaConfig.area_id == "sn-dakar"
        ))
        assert area is not None and area.status == "active"
        assert session.scalar(select(func.count(ServiceAreaConfig.row_id)).where(
            ServiceAreaConfig.environment == "staging"
        )) == 1
        assert session.scalar(select(func.count(ServiceAreaEvent.id)).where(
            ServiceAreaEvent.service_area_row_id == area.row_id
        )) == 1


@pytest.mark.parametrize("database_name,app_env,error", [
    ("kwitli_dev", "staging", "database_identity_mismatch"),
    ("kwitli_test", "production", "app_environment_mismatch"),
])
def test_bootstrap_refuses_wrong_database_or_environment(tmp_path, monkeypatch, database_name, app_env, error):
    monkeypatch.setattr(bootstrap, "get_settings", lambda: SimpleNamespace(app_env=app_env))
    manifest = bootstrap.load_manifest(_write_manifest(tmp_path, _manifest()))
    with get_session_factory()() as session:
        actor = _admin(session)
        session.commit()
        with pytest.raises(bootstrap.ServiceAreaBootstrapError, match=error):
            bootstrap.bootstrap_manifest(session, manifest, database_name, actor.id, "Test isolé")
        assert session.scalar(select(func.count(ServiceAreaConfig.row_id)).where(
            ServiceAreaConfig.environment == "staging"
        )) == 0


def test_staging_manifest_rejects_development_zone_before_writes(tmp_path):
    payload = _manifest(area_id="ca-sherbrooke-dev")
    with pytest.raises(bootstrap.ServiceAreaBootstrapError, match="development_zone_forbidden"):
        bootstrap.load_manifest(_write_manifest(tmp_path, payload))


def test_manifest_cannot_omit_a_declared_required_historical_id(tmp_path):
    payload = _manifest()
    payload["required_area_ids"] = ["sn-dakar", "missing-historical-zone"]
    with pytest.raises(bootstrap.ServiceAreaBootstrapError, match="manifest_required_zone_declaration_invalid"):
        bootstrap.load_manifest(_write_manifest(tmp_path, payload))


def test_admin_repository_cannot_add_legacy_development_zone_to_staging():
    from backend.app.core.service_areas import ServiceAreaInput
    from backend.app.repositories.service_areas import SqlAlchemyServiceAreaRepository

    payload = ServiceAreaInput.model_validate({
        "area_id": "ca-sherbrooke-dev", "code": "CA-SHERBROOKE-DEV",
        "label": "Development market", "country_code": "CA", "country": "Example",
        "city": "Test City", "center_latitude": 45, "center_longitude": -70,
        "radius_km": 30, "timezone": "Etc/UTC", "locale": "en", "currency": "CAD",
        "status": "active",
    })
    with get_session_factory()() as session:
        with pytest.raises(ValueError, match="historique de développement"):
            SqlAlchemyServiceAreaRepository(session).create(payload, "staging", "unused", "refus")


def test_startup_rejects_active_legacy_development_zone_outside_development(tmp_path, monkeypatch):
    settings = SimpleNamespace(app_env="staging", service_area_manifest_path="")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(bootstrap, "get_settings", lambda: settings)
    with get_session_factory()() as session:
        session.add(ServiceAreaConfig(
            area_id="sn-dakar", environment="staging", code="SN-DKR", label="Dakar, Sénégal",
            country_code="SN", country="Sénégal", city="Dakar", center_latitude=14.7167,
            center_longitude=-17.4677, radius_km=30, geometry_type="circle",
            timezone="Africa/Dakar", locale="fr", currency="XOF", distance_unit="km",
            status="active", version=1,
        ))
        session.add(ServiceAreaConfig(
            area_id="ca-sherbrooke-dev", environment="staging", code="CA-SHERBROOKE-DEV",
            label="Development zone", country_code="CA", country="Example", city="Test City",
            center_latitude=45, center_longitude=-70, radius_km=30, geometry_type="circle",
            timezone="Etc/UTC", locale="en", currency="CAD", distance_unit="km",
            status="active", version=1,
        ))
        session.commit()
    settings.service_area_manifest_path = str(_write_manifest(tmp_path, _manifest()))
    with pytest.raises(RuntimeError, match="development_zone_active_in_non_development"):
        database.init_database()


def test_bootstrap_refuses_missing_admin_and_never_reactivates_suspended_zone(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "get_settings", lambda: SimpleNamespace(app_env="staging"))
    manifest = bootstrap.load_manifest(_write_manifest(tmp_path, _manifest()))
    with get_session_factory()() as session:
        with pytest.raises(bootstrap.ServiceAreaBootstrapError, match="active_admin_actor_required"):
            bootstrap.bootstrap_manifest(session, manifest, "kwitli_test", "missing", "Test")
        actor = _admin(session)
        actor_id = actor.id
        session.commit()
        bootstrap.bootstrap_manifest(session, manifest, "kwitli_test", actor_id, "Initialisation")
        area = session.scalar(select(ServiceAreaConfig).where(
            ServiceAreaConfig.environment == "staging", ServiceAreaConfig.area_id == "sn-dakar"
        ))
        area.status = "suspended"
        session.commit()
        with pytest.raises(bootstrap.ServiceAreaBootstrapError, match="existing_zone_differs_or_is_not_active"):
            bootstrap.bootstrap_manifest(session, manifest, "kwitli_test", actor_id, "Ne pas réactiver")
        assert session.get(ServiceAreaConfig, area.row_id).status == "suspended"


def test_startup_refuses_staging_without_or_with_incorrect_manifest(tmp_path, monkeypatch):
    settings = SimpleNamespace(app_env="staging", service_area_manifest_path="")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(bootstrap, "get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="manifeste de zones commerciales absent"):
        database.init_database()

    settings.service_area_manifest_path = str(_write_manifest(tmp_path, _manifest(longitude=-17.0)))
    with pytest.raises(RuntimeError, match="required_zone_missing|config_mismatch"):
        database.init_database()


def test_startup_accepts_verified_staging_zone_and_respects_later_suspension(tmp_path, monkeypatch):
    settings = SimpleNamespace(app_env="staging", service_area_manifest_path="")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(bootstrap, "get_settings", lambda: settings)
    manifest_path = _write_manifest(tmp_path, _manifest())
    with get_session_factory()() as session:
        session.add(ServiceAreaConfig(
            area_id="sn-dakar", environment="staging", code="SN-DKR", label="Dakar, Sénégal",
            country_code="SN", country="Sénégal", city="Dakar", center_latitude=14.7167,
            center_longitude=-17.4677, radius_km=30, geometry_type="circle",
            timezone="Africa/Dakar", locale="fr", currency="XOF", distance_unit="km",
            status="active", version=1,
        ))
        session.commit()
    settings.service_area_manifest_path = str(manifest_path)
    database.init_database()
    with get_session_factory()() as session:
        area = session.scalar(select(ServiceAreaConfig).where(
            ServiceAreaConfig.environment == "staging", ServiceAreaConfig.area_id == "sn-dakar"
        ))
        area.status = "suspended"
        session.commit()
    # A deliberate suspension is operational state, not schema/config drift.
    database.init_database()


def test_pre_cutover_verification_is_exact_but_runtime_allows_audited_admin_perimeter_change(
    tmp_path, monkeypatch,
):
    settings = SimpleNamespace(app_env="staging", service_area_manifest_path="")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(bootstrap, "get_settings", lambda: settings)
    manifest = bootstrap.load_manifest(_write_manifest(tmp_path, _manifest()))
    with get_session_factory()() as session:
        actor = _admin(session)
        area = ServiceAreaConfig(
            area_id="sn-dakar", environment="staging", code="SN-DKR", label="Dakar, Sénégal",
            country_code="SN", country="Sénégal", city="Dakar", center_latitude=14.7167,
            center_longitude=-17.4677, radius_km=30, geometry_type="circle",
            timezone="Africa/Dakar", locale="fr", currency="XOF", distance_unit="km",
            status="active", version=1,
        )
        session.add(area)
        session.commit()
        from backend.app.repositories.service_areas import SqlAlchemyServiceAreaRepository
        changed = manifest.zones[0].config().model_copy(update={
            "center_longitude": -17.45,
        })
        SqlAlchemyServiceAreaRepository(session).update(
            area.row_id, 1, changed, "staging", actor.id, "Ajustement géographique audité",
        )
        with pytest.raises(bootstrap.ServiceAreaBootstrapError, match="required_zone_config_mismatch"):
            bootstrap.verify_manifest(session, manifest, "kwitli_test")

    settings.service_area_manifest_path = str(tmp_path / "service-areas.json")
    database.init_database()


def test_startup_refuses_unreviewed_perimeter_mismatch(tmp_path, monkeypatch):
    settings = SimpleNamespace(app_env="staging", service_area_manifest_path="")
    monkeypatch.setattr(database, "get_settings", lambda: settings)
    monkeypatch.setattr(bootstrap, "get_settings", lambda: settings)
    settings.service_area_manifest_path = str(_write_manifest(tmp_path, _manifest()))
    with get_session_factory()() as session:
        session.add(ServiceAreaConfig(
            area_id="sn-dakar", environment="staging", code="SN-DKR", label="Dakar, Sénégal",
            country_code="SN", country="Sénégal", city="Dakar", center_latitude=14.7167,
            center_longitude=-17.0, radius_km=30, geometry_type="circle",
            timezone="Africa/Dakar", locale="fr", currency="XOF", distance_unit="km",
            status="active", version=1,
        ))
        session.commit()
    with pytest.raises(RuntimeError, match="required_zone_config_mismatch"):
        database.init_database()
