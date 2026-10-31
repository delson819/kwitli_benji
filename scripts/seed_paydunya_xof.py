#!/usr/bin/env python3
"""Donnees XOF separees pour le prerequis PayDunya Sandbox, sans paiement."""
import argparse
from datetime import time
from decimal import Decimal
from math import degrees
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, select
from backend.app.core.config import get_settings
from backend.app.core.time import market_timezone, utc_now
from backend.app.database import get_session_factory
from backend.app.persistence.models import User, CookProfile, Dish, DishAvailability

EMAIL = "paydunya-xof-demo@kwitli.invalid"
CATEGORY = "__kwitli_paydunya_xof_demo__"
DISHES = (("Poulet yassa", "4500"), ("Thiéboudienne", "5000"), ("Jus bissap", "1000"))


def seed_xof(session, *, latitude: float, longitude: float):
    if get_settings().app_env not in {"development", "test"}:
        raise ValueError("Seed reserve aux environnements development/test.")
    if not -89.9 <= latitude <= 89.9 or not -180 <= longitude <= 180:
        raise ValueError("Coordonnees invalides.")
    # Ce seed ne modifie ni le schema ni le jeu de donnees COP.
    checks = inspect(session.get_bind()).get_check_constraints("dishes")
    if not any(c["name"] == "ck_dishes_currency" and "XOF" in c["sqltext"] for c in checks):
        raise ValueError("Migration COP/XOF requise avant le seed.")
    user = session.scalar(select(User).where(User.email == EMAIL))
    if user is None:
        user = User(email=EMAIL, first_name="DEV", last_name="Senegal", password_hash=None,
                    is_active=False, can_cook=True)
        session.add(user)
        session.flush()
    cook = session.scalar(select(CookProfile).where(CookProfile.user_id == user.id))
    if cook is None:
        cook = CookProfile(user_id=user.id, display_name="Restaurant DEV Sénégal",
                           bio="Données de test XOF uniquement.", latitude=latitude, longitude=longitude)
        session.add(cook)
        session.flush()
    cook.latitude = latitude + degrees(0.3 / 6371)
    cook.longitude = longitude
    # Convention temporelle legacy conservee, pas de migration de marche ici.
    today = utc_now().astimezone(market_timezone()).date()
    ids = []
    for name, price in DISHES:
        dish = session.scalar(select(Dish).where(Dish.cook_id == cook.id, Dish.category == CATEGORY, Dish.name == name))
        if dish is None:
            dish = Dish(cook_id=cook.id, name=name, description="Article DEV pour PayDunya Sandbox.",
                        price=Decimal(price), currency="XOF", category=CATEGORY)
            session.add(dish)
            session.flush()
        if dish.currency != "XOF":
            raise ValueError("Devise inattendue dans le jeu DEV XOF; aucune conversion autorisee.")
        availability = session.scalar(select(DishAvailability).where(
            DishAvailability.dish_id == dish.id, DishAvailability.available_date == today))
        if availability is None:
            availability = DishAvailability(dish_id=dish.id, available_date=today,
                start_time=time(0), end_time=time(23, 59, 59), total_portions=10,
                remaining_portions=10, status="active")
            session.add(availability)
            session.flush()
        # Ne jamais reinitialiser un stock ou un hold existant.
        ids.append(availability.id)
    session.commit()
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    args = parser.parse_args()
    try:
        with get_session_factory()() as session:
            seed_xof(session, latitude=args.latitude, longitude=args.longitude)
    except ValueError as exc:
        print(str(exc))
        return 1
    except Exception:
        print("Seed impossible. Verifiez la base DEV et ses migrations; aucun detail sensible affiche.")
        return 1
    print("Jeu DEV XOF disponible : 3 articles. Fournisseur selon configuration backend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
