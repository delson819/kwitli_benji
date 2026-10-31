from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.service_areas import (
    ServiceAreaInput, environment_scope, point_in_service_area, validate_legacy_area_environment,
)
from backend.app.persistence.models import ServiceAreaConfig, ServiceAreaEvent


class ServiceAreaConflictError(ValueError):
    pass


class ServiceAreaNotFoundError(LookupError):
    pass


def _snapshot(area: ServiceAreaConfig) -> dict:
    return {
        "area_id": area.area_id, "environment": area.environment, "code": area.code,
        "label": area.label, "country_code": area.country_code, "country": area.country,
        "city": area.city, "center_latitude": area.center_latitude,
        "center_longitude": area.center_longitude, "radius_km": area.radius_km,
        "geometry_type": area.geometry_type, "timezone": area.timezone,
        "locale": area.locale, "currency": area.currency,
        "distance_unit": area.distance_unit, "status": area.status, "version": area.version,
    }


class SqlAlchemyServiceAreaRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_environment(self, app_env: str, *, active_only: bool = False) -> list[ServiceAreaConfig]:
        environment = environment_scope(app_env)
        statement = select(ServiceAreaConfig).where(ServiceAreaConfig.environment == environment)
        if active_only:
            statement = statement.where(ServiceAreaConfig.status == "active")
        return list(self.session.scalars(statement.order_by(ServiceAreaConfig.city, ServiceAreaConfig.area_id)))

    def contains_active_location(
        self, latitude: float, longitude: float, app_env: str, *, lock: bool = False,
    ) -> bool:
        statement = select(ServiceAreaConfig).where(
            ServiceAreaConfig.environment == environment_scope(app_env),
            ServiceAreaConfig.status == "active",
        ).order_by(ServiceAreaConfig.row_id)
        if lock:
            statement = statement.with_for_update(read=True)
        areas = self.session.scalars(statement).all()
        return any(point_in_service_area(latitude, longitude, area) for area in areas)

    def create(self, payload: ServiceAreaInput, environment_name: str, actor_id: str, reason: str) -> ServiceAreaConfig:
        environment = environment_scope(environment_name)
        validate_legacy_area_environment(payload.area_id, environment)
        reason = reason.strip()
        if not reason or len(reason) > 500:
            raise ServiceAreaConflictError("Une justification de 1 à 500 caractères est obligatoire.")
        area = ServiceAreaConfig(
            area_id=payload.area_id, environment=environment, code=payload.code,
            label=payload.label, country_code=payload.country_code, country=payload.country,
            city=payload.city, center_latitude=payload.center_latitude,
            center_longitude=payload.center_longitude, radius_km=payload.radius_km,
            geometry_type="circle", timezone=payload.timezone, locale=payload.locale,
            currency=payload.currency, distance_unit=payload.distance_unit,
            # Une nouvelle ville est toujours inerte au moment de sa création.
            # L'activation est une mise à jour séparée, versionnée et justifiée.
            status="planned", version=1,
        )
        try:
            self.session.add(area)
            self.session.flush()
            self.session.add(ServiceAreaEvent(
                service_area_row_id=area.row_id, actor_user_id=actor_id, action="created",
                reason=reason, from_version=None, to_version=1,
                before_state=None, after_state=_snapshot(area),
            ))
            self.session.commit()
            self.session.refresh(area)
            return area
        except IntegrityError as exc:
            self.session.rollback()
            raise ServiceAreaConflictError("Identifiant ou code de zone déjà utilisé dans cet environnement.") from exc
        except Exception:
            self.session.rollback()
            raise

    def update(
        self, row_id: str, expected_version: int, payload: ServiceAreaInput,
        environment_name: str, actor_id: str, reason: str,
    ) -> ServiceAreaConfig:
        environment = environment_scope(environment_name)
        validate_legacy_area_environment(payload.area_id, environment)
        reason = reason.strip()
        if not reason or len(reason) > 500:
            raise ServiceAreaConflictError("Une justification de 1 à 500 caractères est obligatoire.")
        area = self.session.scalar(select(ServiceAreaConfig).where(
            ServiceAreaConfig.row_id == row_id,
            ServiceAreaConfig.environment == environment,
        ).with_for_update())
        if area is None:
            raise ServiceAreaNotFoundError("Zone introuvable dans cet environnement.")
        if area.area_id != payload.area_id or area.version != expected_version:
            raise ServiceAreaConflictError("La zone a été modifiée depuis son affichage. Rechargez la page.")

        before_state = _snapshot(area)
        values = payload.model_dump(exclude={"area_id"})
        next_version = expected_version + 1
        try:
            result = self.session.execute(
                update(ServiceAreaConfig)
                .where(
                    ServiceAreaConfig.row_id == row_id,
                    ServiceAreaConfig.environment == environment,
                    ServiceAreaConfig.version == expected_version,
                )
                .values(**values, version=next_version, updated_at=datetime.now(timezone.utc))
            )
            if result.rowcount != 1:
                self.session.rollback()
                raise ServiceAreaConflictError("La zone a été modifiée simultanément. Rechargez la page.")
            after_state = {**before_state, **values, "version": next_version}
            self.session.add(ServiceAreaEvent(
                service_area_row_id=row_id, actor_user_id=actor_id, action="updated",
                reason=reason, from_version=expected_version, to_version=next_version,
                before_state=before_state, after_state=after_state,
            ))
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ServiceAreaConflictError("Code de zone déjà utilisé dans cet environnement.") from exc
        except Exception:
            self.session.rollback()
            raise
        self.session.expire_all()
        return self.session.get(ServiceAreaConfig, row_id)

    def history(self, row_id: str, environment_name: str) -> list[ServiceAreaEvent]:
        environment = environment_scope(environment_name)
        area = self.session.scalar(select(ServiceAreaConfig.row_id).where(
            ServiceAreaConfig.row_id == row_id,
            ServiceAreaConfig.environment == environment,
        ))
        if area is None:
            raise ServiceAreaNotFoundError("Zone introuvable dans cet environnement.")
        statement = select(ServiceAreaEvent).where(
            ServiceAreaEvent.service_area_row_id == row_id
        ).order_by(ServiceAreaEvent.created_at, ServiceAreaEvent.id)
        return list(self.session.scalars(statement))
