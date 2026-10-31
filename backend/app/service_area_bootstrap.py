"""Initialisation idempotente et vérification de la transition vers les zones DB."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.service_areas import (
    ServiceAreaEnvironment, ServiceAreaInput, environment_scope, validate_legacy_area_environment,
)
from backend.app.database import get_engine
from backend.app.persistence.models import ServiceAreaConfig, ServiceAreaEvent, User
from backend.app.repositories.service_areas import _snapshot


class ServiceAreaBootstrapError(ValueError):
    """Erreur expurgée, destinée au CLI et au contrôle de démarrage."""


class LegacyServiceArea(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=2, max_length=80)
    source_environment: ServiceAreaEnvironment
    active: Literal[True]
    code: str
    label: str
    country_code: str
    country: str
    city: str
    latitude: float
    longitude: float
    radius_km: float
    timezone: str
    locale: str
    currency: str
    distance_unit: Literal["km", "mi"] = "km"

    def config(self) -> ServiceAreaInput:
        return ServiceAreaInput.model_validate({
            "area_id": self.id,
            "code": self.code,
            "label": self.label,
            "country_code": self.country_code,
            "country": self.country,
            "city": self.city,
            "center_latitude": self.latitude,
            "center_longitude": self.longitude,
            "radius_km": self.radius_km,
            "timezone": self.timezone,
            "locale": self.locale,
            "currency": self.currency,
            "distance_unit": self.distance_unit,
            "status": "active",
        })


class ServiceAreaBootstrapManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1]
    environment: ServiceAreaEnvironment
    database_name: str = Field(min_length=1, max_length=63)
    required_area_ids: list[str] = Field(min_length=1, max_length=100)
    zones: list[LegacyServiceArea] = Field(min_length=1, max_length=100)


def load_manifest(path: str | Path) -> ServiceAreaBootstrapManifest:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        if len(raw.encode("utf-8")) > 256_000:
            raise ServiceAreaBootstrapError("manifest_too_large")
        manifest = ServiceAreaBootstrapManifest.model_validate_json(raw)
    except ServiceAreaBootstrapError:
        raise
    except (OSError, UnicodeError, ValidationError, ValueError):
        raise ServiceAreaBootstrapError("manifest_invalid") from None

    environment = environment_scope(manifest.environment)
    ids = [zone.id for zone in manifest.zones]
    codes = [zone.config().code for zone in manifest.zones]
    if len(ids) != len(set(ids)) or len(codes) != len(set(codes)):
        raise ServiceAreaBootstrapError("manifest_duplicate_id_or_code")
    required_ids = manifest.required_area_ids
    if (len(required_ids) != len(set(required_ids)) or not set(required_ids).issubset(ids)):
        raise ServiceAreaBootstrapError("manifest_required_zone_declaration_invalid")
    for zone in manifest.zones:
        if environment_scope(zone.source_environment) != environment:
            raise ServiceAreaBootstrapError("source_environment_mismatch")
        try:
            validate_legacy_area_environment(zone.id, environment)
        except ValueError:
            raise ServiceAreaBootstrapError("development_zone_forbidden_in_target") from None
    return manifest


def _matches(area: ServiceAreaConfig, zone: LegacyServiceArea) -> bool:
    expected = zone.config()
    if area.center_latitude is None or area.center_longitude is None or area.radius_km is None:
        return False
    return (
        area.environment == environment_scope(zone.source_environment)
        and area.area_id == expected.area_id
        and area.code == expected.code
        and area.label == expected.label
        and area.country_code == expected.country_code
        and area.country == expected.country
        and area.city == expected.city
        and math.isclose(area.center_latitude, expected.center_latitude, rel_tol=0, abs_tol=1e-8)
        and math.isclose(area.center_longitude, expected.center_longitude, rel_tol=0, abs_tol=1e-8)
        and math.isclose(area.radius_km, expected.radius_km, rel_tol=0, abs_tol=1e-8)
        and area.geometry_type == "circle"
        and area.timezone == expected.timezone
        and area.locale == expected.locale
        and area.currency == expected.currency
        and area.distance_unit == expected.distance_unit
    )


def verify_manifest(session: Session, manifest: ServiceAreaBootstrapManifest, database_name: str) -> None:
    environment = environment_scope(manifest.environment)
    if database_name != manifest.database_name:
        raise ServiceAreaBootstrapError("database_identity_mismatch")
    if environment != environment_scope(get_settings().app_env):
        raise ServiceAreaBootstrapError("app_environment_mismatch")

    expected = {zone.id: zone for zone in manifest.zones}
    existing = {
        area.area_id: area for area in session.scalars(select(ServiceAreaConfig).where(
            ServiceAreaConfig.environment == environment,
            ServiceAreaConfig.area_id.in_(expected.keys()),
        ))
    }
    missing = sorted(set(expected) - set(existing))
    if missing:
        raise ServiceAreaBootstrapError("required_zone_missing:" + ",".join(missing))
    mismatched = sorted(zone_id for zone_id, zone in expected.items() if not _matches(existing[zone_id], zone))
    if mismatched:
        raise ServiceAreaBootstrapError("required_zone_config_mismatch:" + ",".join(mismatched))

    if environment in {"staging", "production"}:
        legacy_dev_zone = session.scalar(select(ServiceAreaConfig.row_id).where(
            ServiceAreaConfig.environment == environment,
            ServiceAreaConfig.area_id == "ca-sherbrooke-dev",
            ServiceAreaConfig.status == "active",
        ).limit(1))
        if legacy_dev_zone:
            raise ServiceAreaBootstrapError("development_zone_active_in_non_development_environment")


def verify_runtime_manifest(
    session: Session, manifest: ServiceAreaBootstrapManifest, database_name: str,
) -> None:
    """Startup gate: preserve required stable IDs without freezing admin-managed settings."""
    environment = environment_scope(manifest.environment)
    if database_name != manifest.database_name:
        raise ServiceAreaBootstrapError("database_identity_mismatch")
    if environment != environment_scope(get_settings().app_env):
        raise ServiceAreaBootstrapError("app_environment_mismatch")

    expected_zones = {zone.id: zone for zone in manifest.zones}
    expected_ids = set(manifest.required_area_ids)
    rows = {
        area.area_id: area for area in session.scalars(select(ServiceAreaConfig).where(
            ServiceAreaConfig.environment == environment,
            ServiceAreaConfig.area_id.in_(expected_ids),
        ))
    }
    missing = sorted(expected_ids - set(rows))
    if missing:
        raise ServiceAreaBootstrapError("required_zone_missing:" + ",".join(missing))
    mismatched = []
    for area_id in sorted(expected_ids):
        area = rows[area_id]
        if _matches(area, expected_zones[area_id]):
            continue
        latest_event = session.scalar(select(ServiceAreaEvent).where(
            ServiceAreaEvent.service_area_row_id == area.row_id,
        ).order_by(ServiceAreaEvent.to_version.desc()).limit(1))
        if (latest_event is None or latest_event.to_version != area.version
                or latest_event.after_state != _snapshot(area)):
            mismatched.append(area_id)
    if mismatched:
        raise ServiceAreaBootstrapError("required_zone_config_mismatch:" + ",".join(mismatched))
    if environment in {"staging", "production"}:
        legacy_dev_zone = session.scalar(select(ServiceAreaConfig.row_id).where(
            ServiceAreaConfig.environment == environment,
            ServiceAreaConfig.area_id == "ca-sherbrooke-dev",
            ServiceAreaConfig.status == "active",
        ).limit(1))
        if legacy_dev_zone:
            raise ServiceAreaBootstrapError("development_zone_active_in_non_development_environment")


def bootstrap_manifest(
    session: Session,
    manifest: ServiceAreaBootstrapManifest,
    database_name: str,
    actor_id: str,
    reason: str,
) -> int:
    environment = environment_scope(manifest.environment)
    if database_name != manifest.database_name:
        raise ServiceAreaBootstrapError("database_identity_mismatch")
    if environment != environment_scope(get_settings().app_env):
        raise ServiceAreaBootstrapError("app_environment_mismatch")
    if not reason.strip() or len(reason.strip()) > 500:
        raise ServiceAreaBootstrapError("justification_required")
    actor = session.get(User, actor_id)
    if actor is None or not actor.is_active or not actor.is_admin:
        raise ServiceAreaBootstrapError("active_admin_actor_required")

    inserted = 0
    try:
        for zone in manifest.zones:
            area = session.scalar(select(ServiceAreaConfig).where(
                ServiceAreaConfig.environment == environment,
                ServiceAreaConfig.area_id == zone.id,
            ).with_for_update())
            if area is not None:
                if not _matches(area, zone) or area.status != "active":
                    raise ServiceAreaBootstrapError("existing_zone_differs_or_is_not_active:" + zone.id)
                continue
            payload = zone.config()
            area = ServiceAreaConfig(
                area_id=payload.area_id,
                environment=environment,
                code=payload.code,
                label=payload.label,
                country_code=payload.country_code,
                country=payload.country,
                city=payload.city,
                center_latitude=payload.center_latitude,
                center_longitude=payload.center_longitude,
                radius_km=payload.radius_km,
                geometry_type="circle",
                geometry_metadata=None,
                timezone=payload.timezone,
                locale=payload.locale,
                currency=payload.currency,
                distance_unit=payload.distance_unit,
                status="active",
                version=1,
            )
            session.add(area)
            session.flush()
            session.add(ServiceAreaEvent(
                service_area_row_id=area.row_id,
                actor_user_id=actor_id,
                action="bootstrapped",
                reason=reason.strip(),
                from_version=None,
                to_version=1,
                before_state=None,
                after_state=_snapshot(area),
            ))
            inserted += 1
        session.flush()
        verify_manifest(session, manifest, database_name)
        session.commit()
        return inserted
    except ServiceAreaBootstrapError:
        session.rollback()
        raise
    except IntegrityError:
        session.rollback()
        raise ServiceAreaBootstrapError("concurrent_or_duplicate_bootstrap") from None
    except Exception:
        session.rollback()
        raise


def _database_name(session: Session) -> str:
    return str(session.execute(text("SELECT current_database()")).scalar_one())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--database-name", required=True)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--actor-id")
    parser.add_argument("--reason", default="")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        if args.verify_only and (args.actor_id or args.reason):
            raise ServiceAreaBootstrapError("verify_only_does_not_accept_write_options")
        with Session(get_engine()) as session:
            actual_database = _database_name(session)
            if actual_database != args.database_name:
                raise ServiceAreaBootstrapError("database_identity_mismatch")
            if args.verify_only:
                verify_manifest(session, manifest, actual_database)
                result = "verified"
            else:
                if not args.actor_id:
                    raise ServiceAreaBootstrapError("active_admin_actor_required")
                inserted = bootstrap_manifest(
                    session, manifest, actual_database, args.actor_id, args.reason
                )
                result = f"bootstrapped:{inserted}"
        print(result)
        return 0
    except ServiceAreaBootstrapError as exc:
        print(f"service-area-bootstrap: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # Do not let SQLAlchemy/driver exceptions print connection details or
        # bind parameters in an operational terminal/session log.
        print("service-area-bootstrap: database_operation_failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
