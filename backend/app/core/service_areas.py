"""Types et règles géographiques des zones persistées; aucune zone de marché codée ici."""

from math import atan2, cos, radians, sin, sqrt
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


EARTH_RADIUS_KM = 6371.0088
ServiceAreaStatus = Literal["planned", "recruiting", "active", "suspended"]
ServiceAreaEnvironment = Literal["development", "test", "staging", "production"]
LEGACY_DEVELOPMENT_AREA_IDS = frozenset({"ca-sherbrooke-dev"})


def environment_scope(app_env: str) -> ServiceAreaEnvironment:
    normalized = app_env.strip().lower()
    aliases = {"dev": "development", "prod": "production"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"development", "test", "staging", "production"}:
        raise ValueError("Environnement de zones non pris en charge.")
    return normalized  # type: ignore[return-value]


def validate_legacy_area_environment(area_id: str, app_env: str) -> None:
    if area_id in LEGACY_DEVELOPMENT_AREA_IDS and environment_scope(app_env) not in {"development", "test"}:
        raise ValueError("Une zone historique de développement ne peut pas être enregistrée dans cet environnement.")


class ServiceArea(BaseModel):
    """Contrat public historique; seules les zones actives sont exposées."""

    model_config = ConfigDict(frozen=True)

    id: str
    code: str
    label: str
    country_code: str
    country: str
    city: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(gt=0, le=100)
    timezone: str
    active: bool


class ServiceAreaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area_id: str = Field(min_length=2, max_length=80)
    code: str = Field(min_length=2, max_length=40)
    label: str = Field(min_length=2, max_length=160)
    country_code: str = Field(min_length=2, max_length=2)
    country: str = Field(min_length=2, max_length=100)
    city: str = Field(min_length=2, max_length=100)
    center_latitude: float = Field(ge=-90, le=90)
    center_longitude: float = Field(ge=-180, le=180)
    radius_km: float = Field(gt=0, le=100)
    timezone: str = Field(min_length=1, max_length=64)
    locale: str = Field(min_length=2, max_length=32)
    currency: str = Field(min_length=3, max_length=3)
    distance_unit: Literal["km", "mi"] = "km"
    status: ServiceAreaStatus

    @field_validator("area_id")
    @classmethod
    def validate_area_id(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", value):
            raise ValueError("Identifiant de zone invalide.")
        return value

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,39}", value):
            raise ValueError("Code de zone invalide.")
        return value

    @field_validator("country_code")
    @classmethod
    def normalize_country_code(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", value):
            raise ValueError("Code pays invalide.")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("Code devise invalide.")
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        value = value.strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Fuseau horaire IANA invalide.") from exc
        return value

    @field_validator("locale", "label", "country", "city")
    @classmethod
    def trim_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Valeur obligatoire.")
        return value


def public_service_area(row) -> ServiceArea:
    if row.geometry_type != "circle" or row.status != "active":
        raise ValueError("La zone ne peut pas être exposée comme cercle actif.")
    return ServiceArea(
        id=row.area_id,
        code=row.code,
        label=row.label,
        country_code=row.country_code,
        country=row.country,
        city=row.city,
        latitude=row.center_latitude,
        longitude=row.center_longitude,
        radius_km=row.radius_km,
        timezone=row.timezone,
        active=True,
    )


def distance_km(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    latitude_a_rad, latitude_b_rad = radians(latitude_a), radians(latitude_b)
    delta_latitude = latitude_b_rad - latitude_a_rad
    delta_longitude = radians(longitude_b - longitude_a)
    haversine = sin(delta_latitude / 2) ** 2 + cos(latitude_a_rad) * cos(latitude_b_rad) * sin(delta_longitude / 2) ** 2
    haversine = min(1.0, max(0.0, haversine))
    return 2 * EARTH_RADIUS_KM * atan2(sqrt(haversine), sqrt(1 - haversine))


def point_in_service_area(latitude: float, longitude: float, area) -> bool:
    if area.status != "active" or area.geometry_type != "circle":
        return False
    return distance_km(latitude, longitude, area.center_latitude, area.center_longitude) <= area.radius_km
