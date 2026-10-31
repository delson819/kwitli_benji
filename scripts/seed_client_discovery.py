#!/usr/bin/env python3
"""Charge des donnees locales reelles pour valider la decouverte client."""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from math import degrees
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.core.config import get_settings
from backend.app.core.time import as_utc, market_timezone, utc_now
from backend.app.database import get_session_factory, init_database
from backend.app.persistence.models import CookProfile, Dish, DishAvailability, User


DEMO_USER_EMAIL = "client-discovery-demo@kwitli.invalid"
DEMO_CATEGORY = "__kwitli_discovery_demo__"
NEAR_ME_VISUAL_CATEGORY = "__kwitli_near_me_visual_demo__"
HOME_SCROLL_CATEGORY = "__kwitli_home_scroll_demo__"
DEMO_COOK_DISTANCE_KM = 0.3
NEAR_ME_VISUAL_COOK_DISTANCE_KM = 0.03
DEFAULT_CLIENT_LATITUDE = 4.65
DEFAULT_CLIENT_LONGITUDE = -74.06
DEMO_ASSET_DIR = ROOT_DIR / "scripts" / "assets" / "client_discovery"
DEMO_UPLOAD_PREFIX = "kwitli-discovery-demo-"


@dataclass(frozen=True)
class DemoDishSpec:
    name: str
    legacy_names: tuple[str, ...]
    description: str
    price: Decimal
    stock: int
    ready_minutes_ago: int
    photo_filename: str
    featured_type: str | None = None


DEMO_DISHES = (
    DemoDishSpec(
        name="Ajiaco fraîchement préparé",
        legacy_names=("Ajiaco recién hecho",),
        description="Ajiaco colombien maison, prêt depuis dix minutes.",
        price=Decimal("22000.00"),
        stock=8,
        ready_minutes_ago=10,
        photo_filename="ajiaco.jpg",
    ),
    DemoDishSpec(
        name="Poulet maison",
        legacy_names=("Arepas casi agotadas",),
        description="Poulet rôti et riz cuisinés maison, trois portions restantes.",
        price=Decimal("18000.00"),
        stock=3,
        ready_minutes_ago=60,
        photo_filename="poulet-maison.jpg",
    ),
    DemoDishSpec(
        name="Sancocho, plat du mois",
        legacy_names=("Sancocho del mes",),
        description="Sancocho traditionnel sélectionné comme plat du mois.",
        price=Decimal("26000.00"),
        stock=8,
        ready_minutes_ago=60,
        photo_filename="sancocho.jpg",
        featured_type="dish_of_month",
    ),
)

NEAR_ME_VISUAL_DISHES = (
    DemoDishSpec(
        name="Poulet braisé maison",
        legacy_names=(),
        description="Poulet braisé maison accompagné de légumes de saison.",
        price=Decimal("19000.00"),
        stock=8,
        ready_minutes_ago=10,
        photo_filename="poulet-maison.jpg",
    ),
    DemoDishSpec(
        name="Sancocho du jour",
        legacy_names=(),
        description="Sancocho traditionnel préparé aujourd'hui.",
        price=Decimal("24000.00"),
        stock=9,
        ready_minutes_ago=60,
        photo_filename="sancocho.jpg",
        featured_type="dish_of_month",
    ),
    DemoDishSpec(
        name="Riz au poulet",
        legacy_names=(),
        description="Riz au poulet cuisiné maison avec des légumes frais.",
        price=Decimal("17500.00"),
        stock=7,
        ready_minutes_ago=60,
        photo_filename="ajiaco.jpg",
    ),
)

HOME_SCROLL_DISHES = NEAR_ME_VISUAL_DISHES + (
    DemoDishSpec(
        name="Poulet rôti aux herbes",
        legacy_names=(),
        description="Poulet rôti lentement avec des herbes fraîches.",
        price=Decimal("20500.00"),
        stock=6,
        ready_minutes_ago=60,
        photo_filename="poulet-maison.jpg",
    ),
    DemoDishSpec(
        name="Soupe paysanne colombienne",
        legacy_names=(),
        description="Soupe généreuse aux légumes et au maïs.",
        price=Decimal("23000.00"),
        stock=10,
        ready_minutes_ago=60,
        photo_filename="sancocho.jpg",
    ),
    DemoDishSpec(
        name="Riz maison aux légumes",
        legacy_names=(),
        description="Riz maison coloré accompagné de légumes frais.",
        price=Decimal("16500.00"),
        stock=12,
        ready_minutes_ago=60,
        photo_filename="ajiaco.jpg",
    ),
)

DEMO_SCENARIOS = {
    "filters": (DEMO_CATEGORY, DEMO_COOK_DISTANCE_KM, DEMO_DISHES),
    "near-me-three": (
        NEAR_ME_VISUAL_CATEGORY,
        NEAR_ME_VISUAL_COOK_DISTANCE_KM,
        NEAR_ME_VISUAL_DISHES,
    ),
    "home-scroll-six": (
        HOME_SCROLL_CATEGORY,
        NEAR_ME_VISUAL_COOK_DISTANCE_KM,
        HOME_SCROLL_DISHES,
    ),
}


@dataclass(frozen=True)
class SeedResult:
    client_latitude: float
    client_longitude: float
    cook_latitude: float
    cook_longitude: float
    cook_distance_km: float
    dish_count: int


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not -89.9 <= latitude <= 89.9:
        raise ValueError("La latitude de demo doit etre comprise entre -89,9 et 89,9.")
    if not -180 <= longitude <= 180:
        raise ValueError("La longitude de demo doit etre comprise entre -180 et 180.")


def _require_demo_environment() -> None:
    if get_settings().app_env.strip().lower() not in {"development", "test"}:
        raise RuntimeError("Ce seed est reserve aux environnements development/test.")


def _install_demo_photo(filename: str) -> str:
    source = DEMO_ASSET_DIR / filename
    if not source.is_file():
        raise FileNotFoundError(f"Photo de demo introuvable: {source.name}")

    destination_name = f"{DEMO_UPLOAD_PREFIX}{filename}"
    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, upload_dir / destination_name)
    return f"/uploads/{destination_name}"


def _demo_window(now: datetime, ready_minutes_ago: int) -> tuple[datetime, time]:
    local_now = as_utc(now).astimezone(market_timezone())
    minutes_since_midnight = local_now.hour * 60 + local_now.minute
    if minutes_since_midnight < ready_minutes_ago:
        raise ValueError(
            "Le seed doit etre lance assez tard dans la journee du marche pour conserver une disponibilite active le meme jour."
        )
    ready_at = local_now - timedelta(minutes=ready_minutes_ago)
    end_time = time(23, 59, 59)
    if local_now.time() >= end_time:
        raise ValueError("La journee de disponibilite est terminee; relancez le seed apres minuit.")
    return ready_at, end_time


def seed_client_discovery(
    session: Session,
    *,
    client_latitude: float,
    client_longitude: float,
    now: datetime | None = None,
    scenario: str = "filters",
) -> SeedResult:
    """Cree ou remet a jour un jeu de donnees de decouverte sans doublons."""
    _require_demo_environment()
    _validate_coordinates(client_latitude, client_longitude)
    try:
        category, cook_distance_km, dish_specs = DEMO_SCENARIOS[scenario]
    except KeyError as exc:
        raise ValueError(f"Scenario de demo inconnu: {scenario}") from exc
    current_time = as_utc(now or utc_now())
    cook_latitude = client_latitude + degrees(cook_distance_km / 6371.0)

    user = session.scalar(select(User).where(User.email == DEMO_USER_EMAIL))
    if user is None:
        user = User(
            email=DEMO_USER_EMAIL,
            password_hash=None,
            first_name="Démo",
            last_name="Découverte",
            is_active=False,
            can_cook=True,
        )
        session.add(user)
        session.flush()

    cook = session.scalar(select(CookProfile).where(CookProfile.user_id == user.id))
    if cook is None:
        cook = CookProfile(
            user_id=user.id,
            display_name="Cuisine démo Kwitli",
            bio="Cuisine locale de démonstration pour valider la découverte.",
            latitude=cook_latitude,
            longitude=client_longitude,
        )
        session.add(cook)
        session.flush()
    else:
        cook.latitude = cook_latitude
        cook.longitude = client_longitude
        cook.display_name = "Cuisine démo Kwitli"
        cook.bio = "Cuisine locale de démonstration pour valider la découverte."

    session.execute(
        update(Dish)
        .where(
            Dish.category.in_(tuple(config[0] for config in DEMO_SCENARIOS.values())),
            Dish.category != category,
        )
        .values(is_active=False)
    )

    for spec in dish_specs:
        dish = session.scalars(
            select(Dish).where(
                Dish.cook_id == cook.id,
                Dish.category == category,
                Dish.name.in_((spec.name, *spec.legacy_names)),
            ).order_by(Dish.created_at).limit(1)
        ).first()
        if dish is None:
            dish = Dish(
                cook_id=cook.id,
                name=spec.name,
                description=spec.description,
                price=spec.price,
                currency="COP",
                category=category,
            )
            session.add(dish)
            session.flush()

        dish.name = spec.name
        dish.description = spec.description
        dish.price = spec.price
        dish.currency = "COP"
        dish.category = category
        dish.photo_url = _install_demo_photo(spec.photo_filename)
        dish.featured_type = spec.featured_type
        dish.is_active = True
        # Seul le plat editorial doit entrer dans Nouveautes par featured_type.
        dish.created_at = current_time - timedelta(days=30)

        availability = session.scalar(
            select(DishAvailability)
            .where(DishAvailability.dish_id == dish.id)
            .order_by(DishAvailability.created_at.desc())
            .limit(1)
        )
        ready_at, end_time = _demo_window(current_time, spec.ready_minutes_ago)
        if availability is None:
            availability = DishAvailability(
                dish_id=dish.id,
                available_date=ready_at.date(),
                start_time=ready_at.time().replace(tzinfo=None),
                end_time=end_time,
                total_portions=spec.stock,
                remaining_portions=spec.stock,
                status="active",
            )
            session.add(availability)
        else:
            availability.available_date = ready_at.date()
            availability.start_time = ready_at.time().replace(tzinfo=None)
            availability.end_time = end_time
            availability.total_portions = max(availability.total_portions, spec.stock)
            availability.remaining_portions = spec.stock
            availability.status = "active"

    session.commit()
    return SeedResult(
        client_latitude=client_latitude,
        client_longitude=client_longitude,
        cook_latitude=cook_latitude,
        cook_longitude=client_longitude,
        cook_distance_km=cook_distance_km,
        dish_count=len(dish_specs),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Charge les donnees locales de decouverte client Kwitli.")
    parser.add_argument("--latitude", type=float, default=DEFAULT_CLIENT_LATITUDE)
    parser.add_argument("--longitude", type=float, default=DEFAULT_CLIENT_LONGITUDE)
    parser.add_argument("--scenario", choices=tuple(DEMO_SCENARIOS), default="filters")
    return parser.parse_args()


def main() -> int:
    settings = get_settings()
    if settings.app_env.strip().lower() not in {"development", "test"}:
        print("Erreur: ce seed est reserve aux environnements development/test.")
        return 1

    args = parse_args()
    init_database()
    with get_session_factory()() as session:
        result = seed_client_discovery(
            session,
            client_latitude=args.latitude,
            client_longitude=args.longitude,
            scenario=args.scenario,
        )

    print("Demo discovery: ready")
    print(f"Simulator location: {result.client_latitude:.6f},{result.client_longitude:.6f}")
    print(f"Demo cook: approximately {result.cook_distance_km:.2f} km away")
    print(f"Demo dishes: {result.dish_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
