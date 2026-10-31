from __future__ import annotations

import hmac
import hashlib
import json
import secrets
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.app.persistence.models import CookProfile, CookProfileHour, Dish, DishAvailability, FavoriteCook, MerchantVerificationCase, Order, OrderItem, OrderMessage, PasswordResetToken, Payment, PaymentIdempotencyKey, PaymentItem, Review, StockHold, User, ORDER_RETRIEVED_STATUSES
from backend.app.core.business_hours import is_business_open_at
from backend.app.repositories.service_areas import SqlAlchemyServiceAreaRepository
from backend.app.core.time import as_utc, utc_now
from backend.app.core.config import get_settings
from backend.app.core.currencies import ProviderNotReadyError, amount_storage_units, sandbox_provider_for, require_currency_environment
from backend.app.kyb.policies import active_policy_versions


class HoldLimitExceededError(ValueError):
    pass


class SqlAlchemyMarketplaceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def is_location_in_active_service_area(
        self, latitude: float, longitude: float, app_env: str, *, lock: bool = False,
    ) -> bool:
        return SqlAlchemyServiceAreaRepository(self.session).contains_active_location(
            latitude, longitude, app_env, lock=lock
        )

    def list_active_service_areas(self, app_env: str):
        return SqlAlchemyServiceAreaRepository(self.session).list_for_environment(app_env, active_only=True)

    def _require_order_eligible_cook(self, cook_id: str) -> CookProfile:
        cook = self.session.scalar(
            select(CookProfile).where(CookProfile.id == cook_id).with_for_update()
        )
        if (cook is None or not cook.is_verified or cook.approval_status != "approved"
                or cook.latitude is None or cook.longitude is None
                or not self.is_location_in_active_service_area(
                    cook.latitude, cook.longitude, get_settings().app_env, lock=True
                )):
            raise ValueError("Ce restaurant n'est pas autorisé à recevoir des commandes dans une zone active.")
        owner = self.session.scalar(select(User).where(User.id == cook.user_id).with_for_update())
        if owner is None or not owner.is_active or owner.email.lower().endswith(".invalid"):
            raise ValueError("Le compte de ce restaurant n'est pas actif pour recevoir des commandes.")
        settings = get_settings()
        country = settings.launch_country.upper()
        enforced = {value.strip().upper() for value in settings.kyb_enforced_countries.split(",") if value.strip()}
        if country in enforced:
            versions = active_policy_versions(country)
            approved = self.session.scalar(select(MerchantVerificationCase.id).where(
                MerchantVerificationCase.cook_profile_id == cook_id,
                MerchantVerificationCase.country_code == country,
                MerchantVerificationCase.status == "approved",
                MerchantVerificationCase.policy_version.in_(versions) if versions else text("false"),
            ).limit(1))
            if approved is None:
                raise ValueError("Le dossier KYB de ce restaurant n'est pas approuvé selon la politique active.")
        return cook

    def create(self, entity):
        self.session.add(entity)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise
        self.session.refresh(entity)
        return entity

    def create_dish_with_availability(self, dish: Dish, availability_values: dict) -> tuple[Dish, DishAvailability]:
        """Persiste le catalogue et son stock initial dans une seule transaction."""
        try:
            self.session.add(dish)
            self.session.flush()
            availability = DishAvailability(dish_id=dish.id, **availability_values)
            self.session.add(availability)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(dish)
        self.session.refresh(availability)
        return dish, availability

    def update(self, entity):
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise
        self.session.refresh(entity)
        return entity

    def get_user(self, entity_id: str): return self.session.get(User, entity_id)
    def get_user_by_email(self, email: str):
        matches = list(self.session.scalars(
            select(User).where(func.lower(User.email) == email.strip().lower()).limit(2)
        ))
        # Une collision historique ne doit jamais choisir un compte en fonction de la casse.
        return matches[0] if len(matches) == 1 else None

    def user_email_exists(self, email: str) -> bool:
        return self.session.scalar(
            select(User.id).where(func.lower(User.email) == email.strip().lower()).limit(1)
        ) is not None

    def create_password_reset_token(self, user_id: str, token_hash: str, created_at: datetime, expires_at: datetime) -> None:
        try:
            self.session.execute(
                update(PasswordResetToken)
                .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
                .values(used_at=created_at)
            )
            self.session.add(PasswordResetToken(
                user_id=user_id,
                token_hash=token_hash,
                created_at=created_at,
                expires_at=expires_at,
            ))
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def revoke_password_reset_token(self, token_hash: str, revoked_at: datetime) -> None:
        self.session.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash, PasswordResetToken.used_at.is_(None))
            .values(used_at=revoked_at)
        )
        self.session.commit()

    def apply_password_reset(self, token_hash: str, password_hash: str, now: datetime) -> bool:
        token = self.session.scalar(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash).limit(1)
        )
        if token is None:
            self.session.rollback()
            return False

        try:
            user = self.session.scalar(
                select(User).where(User.id == token.user_id).with_for_update()
            )
            if user is None or not user.is_active:
                self.session.rollback()
                return False
            locked_token = self.session.scalar(
                select(PasswordResetToken).where(PasswordResetToken.id == token.id).with_for_update()
            )
            if locked_token is None or locked_token.used_at is not None or locked_token.expires_at <= now:
                self.session.rollback()
                return False

            user.password_hash = password_hash
            user.auth_version += 1
            self.session.execute(
                update(PasswordResetToken)
                .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
                .values(used_at=now)
            )
            self.session.commit()
            return True
        except Exception:
            self.session.rollback()
            raise
    def get_cook(self, entity_id: str): return self.session.get(CookProfile, entity_id)
    def get_cook_by_user(self, user_id: str): return self.session.scalar(select(CookProfile).where(CookProfile.user_id == user_id))
    def get_cook_hours(self, cook_id: str) -> list[CookProfileHour]:
        return list(self.session.scalars(select(CookProfileHour).where(
            CookProfileHour.cook_profile_id == cook_id
        ).order_by(CookProfileHour.weekday)))

    def get_cook_hours_map(self, cook_ids: set[str]) -> dict[str, dict[int, CookProfileHour]]:
        if not cook_ids:
            return {}
        rows = self.session.scalars(select(CookProfileHour).where(CookProfileHour.cook_profile_id.in_(cook_ids)))
        result: dict[str, dict[int, CookProfileHour]] = {}
        for row in rows:
            result.setdefault(row.cook_profile_id, {})[row.weekday] = row
        return result

    def save_cook_hours(self, cook_id: str, days: list[dict]) -> list[CookProfileHour]:
        existing = {row.weekday: row for row in self.get_cook_hours(cook_id)}
        try:
            for day in days:
                row = existing.get(day["weekday"])
                if row is None:
                    self.session.add(CookProfileHour(cook_profile_id=cook_id, **day))
                else:
                    row.is_closed = day["is_closed"]
                    row.opens_at = day["opens_at"]
                    row.closes_at = day["closes_at"]
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return self.get_cook_hours(cook_id)

    @staticmethod
    def cook_open_from_hours(hours: list[CookProfileHour], now: datetime) -> bool:
        return is_business_open_at({row.weekday: row for row in hours}, now, get_settings().launch_country)

    def cook_open_status(self, cook_ids: set[str], now: datetime) -> dict[str, bool]:
        schedules = self.get_cook_hours_map(cook_ids)
        return {
            cook_id: is_business_open_at(schedules.get(cook_id, {}), now, get_settings().launch_country)
            for cook_id in cook_ids
        }
    def get_dish(self, entity_id: str): return self.session.get(Dish, entity_id)
    def get_availability(self, entity_id: str): return self.session.get(DishAvailability, entity_id)
    def get_order(self, entity_id: str): return self.session.get(Order, entity_id)
    def get_order_for_update(self, entity_id: str):
        self._begin_immediate_on_sqlite()
        return self.session.scalar(select(Order).where(Order.id == entity_id).with_for_update().execution_options(populate_existing=True))
    def get_payment(self, entity_id: str): return self.session.get(Payment, entity_id)
    def get_hold_by_payment(self, payment_id: str): return self.session.scalar(select(StockHold).where(StockHold.payment_id == payment_id))
    def get_payment_by_reference(self, reference: str): return self.session.scalar(select(Payment).where(Payment.provider_reference == reference))
    def get_payment_by_reference_for_update(self, reference: str):
        self._begin_immediate_on_sqlite()
        return self.session.scalar(
            select(Payment).where(Payment.provider_reference == reference).with_for_update()
        )
    def get_payment_by_order_for_update(self, order_id: str):
        return self.session.scalar(select(Payment).where(
            (Payment.order_id == order_id) | Payment.id.in_(select(PaymentItem.payment_id).where(PaymentItem.order_id == order_id))
        ).with_for_update())
    def get_review_by_order(self, order_id: str): return self.session.scalar(select(Review).where(Review.order_id == order_id))

    def list_order_messages(self, order_id: str, limit: int = 50) -> list[OrderMessage]:
        rows = self.session.scalars(
            select(OrderMessage).where(OrderMessage.order_id == order_id)
            .order_by(OrderMessage.created_at.desc(), OrderMessage.id.desc()).limit(limit)
        ).all()
        return list(reversed(rows))

    def create_order_message(self, message: OrderMessage) -> OrderMessage:
        return self.create(message)

    def list_dishes(self):
        return list(self.session.scalars(select(Dish).order_by(Dish.created_at.desc())))

    def list_dishes_for_cook(self, cook_id: str):
        return list(self.session.scalars(
            select(Dish).where(Dish.cook_id == cook_id).order_by(Dish.created_at.desc())
        ))

    def list_availabilities(self):
        return list(self.session.scalars(select(DishAvailability).order_by(DishAvailability.available_date, DishAvailability.start_time)))

    def list_availabilities_for_cook(self, cook_id: str):
        return list(self.session.scalars(
            select(DishAvailability)
            .join(Dish, Dish.id == DishAvailability.dish_id)
            .where(Dish.cook_id == cook_id)
            .order_by(DishAvailability.available_date, DishAvailability.start_time)
        ))

    def create_order_with_stock_decrement(self, *, customer_id: str, availability_id: str, quantity: int, now: datetime):
        availability = self.get_availability(availability_id)
        if availability is None:
            raise LookupError("Disponibilite introuvable.")
        if availability.status != "active" or availability.end_datetime <= now:
            raise ValueError("Cette disponibilite n'est plus active.")
        dish = self.get_dish(availability.dish_id)
        if dish is None or not dish.is_active:
            raise ValueError("Ce plat n'est pas disponible.")
        cook = self._require_order_eligible_cook(dish.cook_id)
        if not self.cook_open_from_hours(self.get_cook_hours(cook.id), now):
            raise ValueError("Ce restaurant est fermé pour le moment.")
        try:
            decrement = self.session.execute(
                update(DishAvailability).where(
                    DishAvailability.id == availability_id,
                    DishAvailability.status == "active",
                    DishAvailability.remaining_portions >= quantity,
                ).values(remaining_portions=DishAvailability.remaining_portions - quantity)
            )
            if decrement.rowcount != 1:
                self.session.rollback()
                raise ValueError("Stock insuffisant pour cette disponibilite.")
            order = Order(
                customer_id=customer_id, availability_id=availability_id, quantity=quantity,
                unit_price=dish.price, total_price=dish.price * Decimal(quantity), status="confirmed",
                pickup_code=self._new_pickup_code(), confirmed_at=now, pickup_expires_at=availability.end_datetime,
            )
            self.session.add(order)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise
        self.session.refresh(order)
        self.session.refresh(availability)
        return order, availability

    def confirm_pickup(self, order: Order, now: datetime) -> Order:
        order.status = "completed"
        order.completed_at = now
        return self.update(order)

    def cancel_order_with_stock_restore(self, order: Order, now: datetime, reason: str | None) -> Order:
        self._begin_immediate_on_sqlite()
        locked_order = self.session.scalar(select(Order).where(Order.id == order.id).with_for_update())
        if locked_order is None:
            raise LookupError("Commande introuvable.")
        if locked_order.status not in {"confirmed", "ready"}:
            raise ValueError("Cette commande ne peut plus etre annulee.")
        restore = self.session.execute(
            update(DishAvailability)
            .where(
                DishAvailability.id == locked_order.availability_id,
                DishAvailability.remaining_portions <= DishAvailability.total_portions - locked_order.quantity,
            )
            .values(remaining_portions=DishAvailability.remaining_portions + locked_order.quantity)
        )
        if restore.rowcount != 1:
            self.session.rollback()
            raise ValueError("Le stock ne peut pas etre restaure pour cette commande.")
        locked_order.status = "cancelled"
        locked_order.cancelled_at = now
        locked_order.cancel_reason = reason
        payment = self.get_payment_by_order_for_update(locked_order.id)
        if payment is not None and payment.status == "approved":
            payment.status = "refund_pending"
            payment.refund_requested_at = now
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise
        self.session.refresh(locked_order)
        return locked_order

    def _new_pickup_code(self) -> str:
        for _attempt in range(10):
            code = f"{secrets.randbelow(1_000_000):06d}"
            exists = self.session.scalar(
                select(Order.id).where(Order.pickup_code == code, Order.status.in_(
                    ("ordered", "in_progress", "confirmed", "ready")
                ))
            )
            if exists is None:
                return code
        raise RuntimeError("Impossible de generer un code de retrait unique.")

    def new_pickup_code(self) -> str:
        return self._new_pickup_code()

    def _begin_immediate_on_sqlite(self) -> None:
        if self.session.bind is not None and self.session.bind.dialect.name == "sqlite":
            self.session.execute(text("BEGIN IMMEDIATE"))

    def cleanup_expired_holds(self, now: datetime, *, commit: bool = True) -> None:
        expired = self.session.execute(update(StockHold).where(StockHold.status == "active", StockHold.expires_at <= now).values(status="expired"))
        if expired.rowcount and commit:
            self.session.commit()

    def active_hold_quantities(self, now: datetime) -> dict[str, int]:
        rows = self.session.execute(select(StockHold.availability_id, func.coalesce(func.sum(StockHold.quantity), 0)).where(
            StockHold.status == "active", StockHold.expires_at > now,
        ).group_by(StockHold.availability_id))
        return {availability_id: int(quantity) for availability_id, quantity in rows}

    def active_hold_usage_for_user(self, user_id: str, now: datetime) -> tuple[int, int]:
        count, quantity = self.session.execute(
            select(func.count(StockHold.id), func.coalesce(func.sum(StockHold.quantity), 0)).where(
                StockHold.user_id == user_id,
                StockHold.status == "active",
                StockHold.expires_at > now,
            )
        ).one()
        return int(count), int(quantity)

    def create_pending_payment_with_hold(
        self,
        *,
        user_id: str,
        availability_id: str | None,
        quantity: int | None,
        payment_id: str,
        provider_reference: str,
        expires_at: datetime,
        checkout_token_hash: str,
        checkout_token_expires_at: datetime,
        now: datetime,
        max_active_holds_per_user: int,
        max_held_portions_per_user: int,
        items: list[tuple[str, int]] | None = None,
        dish_items: list[tuple[str, int]] | None = None,
        required_provider: str | None = None,
        idempotency_key_hash: str | None = None,
        intent_context: dict | None = None,
    ) -> Payment:
        if dish_items is not None:
            return self._create_pending_dish_payment(
                user_id=user_id, lines=dish_items, payment_id=payment_id,
                provider_reference=provider_reference, checkout_token_hash=checkout_token_hash,
                checkout_token_expires_at=checkout_token_expires_at, now=now,
                required_provider=required_provider,
                idempotency_key_hash=idempotency_key_hash, intent_context=intent_context,
            )
        # Le verrou de disponibilite serialise les holds concurrents. SQLite utilise
        # un verrou d'ecriture global, PostgreSQL verrouille uniquement cette ligne.
        self._begin_immediate_on_sqlite()
        try:
            self.cleanup_expired_holds(now, commit=False)
            user_exists = self.session.scalar(
                select(User.id).where(User.id == user_id).with_for_update()
            )
            if user_exists is None:
                raise LookupError("Utilisateur introuvable.")
            legacy_lines = items or ([(availability_id, quantity)] if availability_id is not None and quantity is not None else [])
            if not legacy_lines:
                raise ValueError("Un panier non vide est requis.")
            lines = sorted(legacy_lines)
            prepared = []
            cooks = set()
            currencies = set()
            for line_id, qty in lines:
                availability = self.session.scalar(select(DishAvailability).where(DishAvailability.id == line_id).with_for_update())
                if availability is None:
                    raise LookupError("Disponibilite introuvable.")
                dish = self.session.get(Dish, availability.dish_id)
                if dish is None:
                    raise LookupError("Article introuvable.")
                currencies.add(dish.currency)
                if len(currencies) > 1:
                    raise ValueError("Le panier doit contenir une seule devise. Aucune conversion n'est effectuee.")
                cooks.add(dish.cook_id)
                if len(cooks) > 1:
                    raise ValueError("Le panier doit appartenir a un seul commerce.")
                prepared.append((availability, qty, amount_storage_units(dish.price * Decimal(qty), dish.currency)))
            cook_id = next(iter(cooks))
            cook = self._require_order_eligible_cook(cook_id)
            currency = next(iter(currencies))
            require_currency_environment(currency)
            provider = sandbox_provider_for(currency)
            if required_provider is not None and required_provider != provider:
                raise ProviderNotReadyError("Le paiement XOF necessite l'adaptateur PayDunya Sandbox, non encore active.")
            if any(not dish.is_active or availability.status != "active" or availability.end_datetime <= now
                   for availability, _, _ in prepared
                   for dish in [self.session.get(Dish, availability.dish_id)]):
                raise ValueError("Cette disponibilite n'est plus active.")
            if not self.cook_open_from_hours(self.get_cook_hours(cook_id), now):
                raise ValueError("Ce restaurant est fermé pour le moment.")
            fingerprint = self._payment_intent_fingerprint(
                [("availability", availability.id, qty, amount) for availability, qty, amount in prepared],
                sum(amount for _, _, amount in prepared), currency, provider, intent_context,
            )
            group = self._payment_intent_group([("availability", availability.id) for availability, _, _ in prepared])
            existing = self._reuse_payment_intent(
                user_id, idempotency_key_hash, fingerprint, group,
                [("availability", availability.id) for availability, _, _ in prepared],
            )
            if existing is not None:
                return existing
            active_count, held_portions = self.active_hold_usage_for_user(user_id, now)
            if active_count + len(prepared) > max_active_holds_per_user:
                raise HoldLimitExceededError("Trop de paiements sont deja en attente.")
            if held_portions + sum(qty for _, qty, _ in prepared) > max_held_portions_per_user:
                raise HoldLimitExceededError("Le nombre de portions temporairement reservees est trop eleve.")
            held_quantities = self.active_hold_quantities(now)
            if any(availability.remaining_portions - held_quantities.get(availability.id, 0) < qty
                   for availability, qty, _ in prepared):
                raise ValueError("Stock insuffisant pour demarrer ce paiement.")
            amount_in_cents = sum(amount for _, _, amount in prepared)
            payment = Payment(
                id=payment_id, user_id=user_id, availability_id=prepared[0][0].id, quantity=sum(qty for _, qty, _ in prepared),
                amount_in_cents=amount_in_cents, currency=currency, provider=provider,
                provider_reference=provider_reference, status="pending",
                checkout_token_hash=checkout_token_hash,
                checkout_token_expires_at=checkout_token_expires_at,
                idempotency_fingerprint=fingerprint,
                idempotency_group=group,
                provider_creation_state="creating" if provider != "payu" else "ready",
            )
            self.session.add(payment)
            self.session.flush()
            self._add_payment_idempotency_key(user_id, payment, idempotency_key_hash)
            for availability, qty, amount in prepared:
                self.session.add(StockHold(
                    user_id=user_id, availability_id=availability.id, quantity=qty, payment_id=payment_id,
                    status="active", expires_at=expires_at,
                ))
                if items is not None:
                    self.session.add(PaymentItem(payment_id=payment_id, availability_id=availability.id, quantity=qty, amount_in_cents=amount))
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(payment)
        return payment

    def _create_pending_dish_payment(
        self, *, user_id: str, lines: list[tuple[str, int]], payment_id: str,
        provider_reference: str, checkout_token_hash: str, checkout_token_expires_at: datetime,
        now: datetime, required_provider: str | None,
        idempotency_key_hash: str | None, intent_context: dict | None,
    ) -> Payment:
        """Fige articles/prix pour le MVP sans reserver ni decrementar de stock."""
        try:
            user_exists = self.session.scalar(select(User.id).where(User.id == user_id).with_for_update())
            if user_exists is None:
                raise LookupError("Utilisateur introuvable.")
            prepared = []
            cooks: set[str] = set()
            currencies: set[str] = set()
            for dish_id, qty in sorted(lines):
                dish = self.session.scalar(select(Dish).where(Dish.id == dish_id).with_for_update())
                if dish is None:
                    raise LookupError("Article introuvable.")
                if qty < 1 or qty > 50:
                    raise ValueError("La quantite doit etre comprise entre 1 et 50.")
                cooks.add(dish.cook_id)
                currencies.add(dish.currency)
                if len(cooks) > 1:
                    raise ValueError("Le panier doit appartenir a un seul commerce.")
                if len(currencies) > 1:
                    raise ValueError("Le panier doit contenir une seule devise. Aucune conversion n'est effectuee.")
                prepared.append((dish, qty, amount_storage_units(dish.price * Decimal(qty), dish.currency)))
            if not prepared:
                raise ValueError("Un panier non vide est requis.")
            if any(not dish.is_active for dish, _, _ in prepared):
                raise ValueError("Cet article est inactif et ne peut pas etre commande.")
            cook = self._require_order_eligible_cook(next(iter(cooks)))
            if not self.cook_open_from_hours(self.get_cook_hours(cook.id), now):
                raise ValueError("Ce restaurant est fermé pour le moment.")
            currency = next(iter(currencies))
            require_currency_environment(currency)
            provider = sandbox_provider_for(currency)
            if required_provider is not None and required_provider != provider:
                raise ProviderNotReadyError("Le fournisseur requis n'est pas disponible pour cette devise.")
            fingerprint = self._payment_intent_fingerprint(
                [("dish", dish.id, qty, amount) for dish, qty, amount in prepared],
                sum(amount for _, _, amount in prepared), currency, provider, intent_context,
            )
            group = self._payment_intent_group([("dish", dish.id) for dish, _, _ in prepared])
            existing = self._reuse_payment_intent(
                user_id, idempotency_key_hash, fingerprint, group,
                [("dish", dish.id) for dish, _, _ in prepared],
            )
            if existing is not None:
                return existing
            payment = Payment(
                id=payment_id, user_id=user_id, availability_id=None,
                quantity=sum(qty for _, qty, _ in prepared),
                amount_in_cents=sum(amount for _, _, amount in prepared), currency=currency,
                provider=provider, provider_reference=provider_reference, status="pending",
                checkout_token_hash=checkout_token_hash,
                checkout_token_expires_at=checkout_token_expires_at,
                idempotency_fingerprint=fingerprint,
                idempotency_group=group,
                provider_creation_state="creating" if provider != "payu" else "ready",
            )
            self.session.add(payment)
            self.session.flush()
            self._add_payment_idempotency_key(user_id, payment, idempotency_key_hash)
            for dish, qty, amount in prepared:
                self.session.add(PaymentItem(
                    payment_id=payment_id, dish_id=dish.id, availability_id=None,
                    quantity=qty, amount_in_cents=amount,
                ))
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            raise
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(payment)
        return payment

    @staticmethod
    def _payment_intent_fingerprint(lines, amount: int, currency: str, provider: str, context: dict | None) -> str:
        canonical = {
            "lines": sorted([list(line) for line in lines]),
            "amount": amount,
            "currency": currency,
            "provider": provider,
            "network": (context or {}).get("network"),
            "phone_hash": (context or {}).get("phone_hash"),
            "return_url_hash": (context or {}).get("return_url_hash"),
        }
        return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _payment_intent_group(lines) -> str:
        canonical = sorted([list(line) for line in lines])
        return hashlib.sha256(json.dumps(canonical, separators=(",", ":")).encode()).hexdigest()

    def _reuse_payment_intent(
        self, user_id: str, key_hash: str | None, fingerprint: str, group: str, line_refs,
    ) -> Payment | None:
        if key_hash is None:
            return None
        key = self.session.scalar(select(PaymentIdempotencyKey).where(
            PaymentIdempotencyKey.user_id == user_id,
            PaymentIdempotencyKey.key_hash == key_hash,
        ).with_for_update())
        if key is not None:
            payment = self.session.scalar(select(Payment).where(Payment.id == key.payment_id).with_for_update())
            if payment is None or payment.idempotency_fingerprint != fingerprint:
                raise ValueError("Cette clé d’idempotence est déjà liée à une autre intention de paiement.")
            if payment.status == "pending" and not self._payment_action_is_recoverable(payment, now=utc_now()):
                raise ValueError("Cette tentative est toujours en attente, mais son action de paiement ne peut pas être reprise; vérifiez son état avant de recommencer.")
            payment._idempotency_reused = True
            self.session.commit()
            self.session.refresh(payment)
            return payment

        active = self.session.scalar(select(Payment).where(
            Payment.user_id == user_id,
            Payment.idempotency_group == group,
            Payment.status == "pending",
        ).order_by(Payment.created_at.desc()).with_for_update())
        if active is not None:
            if not self._payment_action_is_recoverable(active, now=utc_now()):
                raise ValueError("Une tentative de ce panier est en attente sans action de paiement récupérable; vérifiez son état avant de recommencer.")
            if active.idempotency_fingerprint != fingerprint:
                raise ValueError("Une tentative de paiement de ce panier est déjà en cours avec un montant ou moyen différent.")
            self._add_payment_idempotency_key(user_id, active, key_hash)
            self.session.commit()
            self.session.refresh(active)
            active._idempotency_reused = True
            return active
        if self._has_legacy_pending_payment(user_id, line_refs):
            raise ValueError("Un paiement historique de ce panier est encore en attente; vérifiez son état avant de recommencer.")
        return None

    @staticmethod
    def _payment_action_is_recoverable(payment: Payment, *, now: datetime) -> bool:
        state = payment.provider_creation_state
        if state in {"creating", "uncertain"}:
            # Une reprise retourne seulement l'etat d'attente; aucun nouvel appel fournisseur.
            return True
        if state != "ready":
            return False
        if payment.provider == "payu":
            return bool(
                payment.checkout_token_hash
                and payment.checkout_token_used_at is None
                and payment.checkout_token_expires_at is not None
                and as_utc(payment.checkout_token_expires_at) > as_utc(now)
            )
        if payment.provider == "paytech":
            return bool(payment.provider_transaction_id)
        if payment.provider == "paydunya":
            return bool(payment.provider_transaction_id)
        if payment.provider == "flutterwave":
            action = payment.provider_action
            return isinstance(action, dict) and action.get("type") in {"external", "wait"}
        return False

    def _has_legacy_pending_payment(self, user_id: str, line_refs) -> bool:
        expected = sorted(line_refs)
        legacy = self.session.scalars(select(Payment).where(
            Payment.user_id == user_id,
            Payment.idempotency_group.is_(None),
            Payment.status == "pending",
        )).all()
        for payment in legacy:
            if payment.items:
                refs = sorted(("dish", item.dish_id) if item.dish_id else ("availability", item.availability_id)
                              for item in payment.items)
            elif payment.availability_id:
                refs = [("availability", payment.availability_id)]
            else:
                refs = []
            if refs == expected:
                return True
        return False

    def _add_payment_idempotency_key(self, user_id: str, payment: Payment, key_hash: str | None) -> None:
        if key_hash is not None:
            self.session.add(PaymentIdempotencyKey(user_id=user_id, payment_id=payment.id, key_hash=key_hash))

    def release_hold(self, payment_id: str) -> None:
        self.session.execute(update(StockHold).where(StockHold.payment_id == payment_id, StockHold.status == "active").values(status="released"))
        self.session.commit()

    def consume_checkout_token(self, payment_id: str, token_hash: str, now: datetime) -> Payment | None:
        self._begin_immediate_on_sqlite()
        payment = self.session.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
        if payment is None:
            return None
        if payment.provider != "payu":
            raise ValueError("Paiement PayU introuvable.")
        if payment.status != "pending":
            raise ValueError("Ce paiement ne peut plus ouvrir le checkout.")
        if payment.checkout_token_hash is None or not hmac.compare_digest(payment.checkout_token_hash, token_hash):
            raise ValueError("Lien de paiement PayU invalide.")
        if payment.checkout_token_used_at is not None:
            raise ValueError("Ce lien de paiement PayU a deja ete utilise.")
        if payment.checkout_token_expires_at is None or as_utc(payment.checkout_token_expires_at) <= now:
            payment.status = "error"
            payment.failure_reason = "checkout_token_expired"
            self.session.commit()
            raise ValueError("Ce lien de paiement PayU a expire.")
        holds = list(self.session.scalars(
            select(StockHold).where(StockHold.payment_id == payment.id).with_for_update()
        ))
        no_stock_checkout = bool(payment.items) and all(line.dish_id is not None for line in payment.items)
        if (not no_stock_checkout and (not holds or any(
            hold.status != "active" or as_utc(hold.expires_at) <= now for hold in holds
        ))):
            for hold in holds:
                if hold.status == "active":
                    hold.status = "expired"
            payment.status = "error"
            payment.failure_reason = "hold_unavailable_before_checkout"
            self.session.commit()
            raise ValueError("La reservation temporaire de stock a expire.")
        payment.checkout_token_used_at = now
        self.session.commit()
        self.session.refresh(payment)
        return payment

    def approve_payment_and_create_order(self, payment: Payment, now: datetime, *, reconcile: bool = False) -> tuple[Payment, Order | None]:
        if payment.status in {"paid_stock_conflict", "reconcile_required"}:
            return payment, None
        if payment.order_id is not None:
            return payment, self.get_order(payment.order_id)
        if reconcile and payment.status != "pending":
            raise ValueError("Seul un paiement pending peut etre reconcilie.")
        if payment.items:
            if all(line.dish_id is not None for line in payment.items):
                return self._approve_dish_cart_payment(payment, now)
            return self._approve_cart_payment(payment, now, reconcile=reconcile)
        if reconcile:
            raise ValueError("Reconciliation sans PaymentItems non prise en charge.")
        hold = self.session.scalar(
            select(StockHold).where(StockHold.payment_id == payment.id).with_for_update()
        )
        if hold is None or hold.status not in {"active", "released"} or as_utc(hold.expires_at) <= now:
            if hold is not None and hold.status == "active":
                hold.status = "expired"
            payment.status = "error"
            payment.failure_reason = "hold_expired_after_provider_approval"
            self.session.commit()
            self.session.refresh(payment)
            return payment, None
        availability = self.session.scalar(
            select(DishAvailability)
            .where(DishAvailability.id == payment.availability_id)
            .with_for_update()
        )
        dish = self.get_dish(availability.dish_id) if availability is not None else None
        if availability is None or dish is None or availability.status != "active" or not dish.is_active:
            payment.status = "error"
            payment.failure_reason = "availability_unavailable"
            hold.status = "released"
            self.update(payment)
            return payment, None
        if hold.status == "released":
            other_held_portions = self.session.scalar(
                select(func.coalesce(func.sum(StockHold.quantity), 0)).where(
                    StockHold.availability_id == availability.id,
                    StockHold.status == "active",
                    StockHold.expires_at > now,
                )
            )
            if availability.remaining_portions - int(other_held_portions or 0) < payment.quantity:
                payment.status = "error"
                payment.failure_reason = "stock_unavailable_after_payment"
                self.session.commit()
                self.session.refresh(payment)
                return payment, None
        decrement = self.session.execute(
            update(DishAvailability).where(
                DishAvailability.id == availability.id,
                DishAvailability.status == "active",
                DishAvailability.remaining_portions >= payment.quantity,
            ).values(remaining_portions=DishAvailability.remaining_portions - payment.quantity)
        )
        if decrement.rowcount != 1:
            payment.status = "error"
            payment.failure_reason = "stock_unavailable_after_payment"
            hold.status = "released"
            self.session.commit()
            self.session.refresh(payment)
            return payment, None
        order = Order(
            customer_id=payment.user_id, availability_id=payment.availability_id, quantity=payment.quantity,
            unit_price=Decimal(payment.amount_in_cents) / Decimal(payment.quantity) / 100,
            total_price=Decimal(payment.amount_in_cents) / 100,
            currency=payment.currency, status="confirmed", pickup_code=self._new_pickup_code(),
            confirmed_at=now, pickup_expires_at=availability.end_datetime,
        )
        self.session.add(order)
        self.session.flush()
        payment.order_id = order.id
        payment.status = "approved"
        payment.approved_at = now
        hold.status = "consumed"
        self.session.commit()
        self.session.refresh(payment)
        self.session.refresh(order)
        return payment, order

    def _approve_cart_payment(self, payment: Payment, now: datetime, *, reconcile: bool = False) -> tuple[Payment, Order | None]:
        # Le paiement est deja verrouille. Toutes les lignes sont validees avant
        # le premier decrement, puis persistees dans une transaction unique.
        holds = {hold.availability_id: hold for hold in self.session.scalars(
            select(StockHold).where(StockHold.payment_id == payment.id).with_for_update()
        )}
        prepared = []
        failure = None
        cooks = set()
        for line in sorted(payment.items, key=lambda item: item.availability_id):
            hold = holds.get(line.availability_id)
            availability = self.session.scalar(select(DishAvailability).where(DishAvailability.id == line.availability_id).with_for_update())
            dish = self.get_dish(availability.dish_id) if availability else None
            allowed_hold_states = {"active", "released", "expired"} if reconcile else {"active", "released"}
            if (hold is None or hold.quantity != line.quantity or hold.user_id != payment.user_id
                    or hold.status not in allowed_hold_states
                    or (not reconcile and as_utc(hold.expires_at) <= now)):
                failure = "hold_expired_after_provider_approval"
                break
            if availability is None or dish is None or not dish.is_active or availability.status != "active":
                failure = "availability_unavailable"
                break
            if reconcile and availability.end_datetime <= now:
                failure = "availability_unavailable"
                break
            cooks.add(dish.cook_id)
            if len(cooks) != 1 or dish.currency != payment.currency:
                failure = "cart_identity_mismatch"
                break
            # Le prix est fige par PaymentItem, jamais repris du catalogue courant.
            if line.quantity <= 0 or line.amount_in_cents <= 0 or line.amount_in_cents % line.quantity or line.order_id is not None or line.order_item_id is not None:
                failure = "payment_items_inconsistent"
                break
            reserved = self.session.scalar(select(func.coalesce(func.sum(StockHold.quantity), 0)).where(
                StockHold.availability_id == line.availability_id, StockHold.payment_id != payment.id,
                StockHold.status == "active", StockHold.expires_at > now,
            ))
            if availability.remaining_portions - int(reserved or 0) < line.quantity:
                failure = "stock_unavailable_after_payment"
                break
            prepared.append((line, hold, availability, dish))
        if not failure and (
            sum(line.amount_in_cents for line, _, _, _ in prepared) != payment.amount_in_cents
            or sum(line.quantity for line, _, _, _ in prepared) != payment.quantity
            or set(holds) != {line.availability_id for line in payment.items}
            or payment.availability_id not in holds
        ):
            failure = "payment_items_inconsistent"
        if failure:
            payment.status = (
                "paid_stock_conflict" if failure in {"availability_unavailable", "stock_unavailable_after_payment"}
                else "reconcile_required"
            ) if reconcile else "error"
            payment.failure_reason = failure
            for hold in holds.values():
                if hold.status == "active":
                    hold.status = "expired" if reconcile and as_utc(hold.expires_at) <= now else "released"
            self.session.commit()
            return payment, None
        try:
            order = Order(
                customer_id=payment.user_id, cook_id=next(iter(cooks)),
                total_price=Decimal(payment.amount_in_cents) / 100, currency=payment.currency,
                status="ordered", confirmed_at=now, pickup_code=self._new_pickup_code(),
            )
            self.session.add(order)
            self.session.flush()
            for line, hold, availability, dish in prepared:
                decrement = self.session.execute(update(DishAvailability).where(
                    DishAvailability.id == availability.id, DishAvailability.remaining_portions >= line.quantity,
                ).values(remaining_portions=DishAvailability.remaining_portions - line.quantity))
                if decrement.rowcount != 1:
                    raise ValueError("Stock modifie pendant la confirmation du panier.")
                order_item = OrderItem(
                    order_id=order.id, availability_id=line.availability_id, dish_id=dish.id, quantity=line.quantity,
                    unit_price=Decimal(line.amount_in_cents) / Decimal(line.quantity) / 100,
                    line_total=Decimal(line.amount_in_cents) / 100, dish_name=dish.name, photo_url=dish.photo_url,
                )
                self.session.add(order_item)
                self.session.flush()
                line.order_item_id = order_item.id
                hold.status = "consumed"
            payment.order_id = order.id
            payment.status = "approved"
            payment.approved_at = now
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return payment, self.get_order(payment.order_id)

    def _approve_dish_cart_payment(self, payment: Payment, now: datetime) -> tuple[Payment, Order | None]:
        lines = sorted(payment.items, key=lambda item: item.dish_id or "")
        prepared = []
        cooks: set[str] = set()
        failure = None
        for line in lines:
            dish = self.session.scalar(select(Dish).where(Dish.id == line.dish_id).with_for_update())
            if dish is None:
                failure = "item_unavailable_after_payment"
                break
            # L'article est valide au demarrage du checkout; une desactivation
            # ulterieure ne doit pas transformer un paiement confirme en commande perdue.
            cooks.add(dish.cook_id)
            if len(cooks) != 1 or dish.currency != payment.currency:
                failure = "cart_identity_mismatch"
                break
            if (line.quantity <= 0 or line.amount_in_cents <= 0 or line.amount_in_cents % line.quantity
                    or line.order_id is not None or line.order_item_id is not None):
                failure = "payment_items_inconsistent"
                break
            prepared.append((line, dish))
        if (not failure and (not prepared
                or sum(line.amount_in_cents for line, _ in prepared) != payment.amount_in_cents
                or sum(line.quantity for line, _ in prepared) != payment.quantity
                or payment.availability_id is not None)):
            failure = "payment_items_inconsistent"
        if not failure and cooks:
            try:
                self._require_order_eligible_cook(next(iter(cooks)))
            except ValueError:
                failure = "restaurant_unavailable_after_payment"
        if failure:
            payment.status = (
                "reconcile_required"
                if payment.provider_status == "successful" or failure == "restaurant_unavailable_after_payment"
                else "error"
            )
            payment.failure_reason = failure
            self.session.commit()
            return payment, None
        try:
            total_quantity = sum(line.quantity for line, _ in prepared)
            order = Order(
                customer_id=payment.user_id, cook_id=next(iter(cooks)), availability_id=None,
                quantity=total_quantity,
                total_price=Decimal(payment.amount_in_cents) / Decimal(100),
                unit_price=Decimal(payment.amount_in_cents) / Decimal(100 * total_quantity),
                currency=payment.currency, status="ordered", confirmed_at=now,
                pickup_code=self._new_pickup_code(),
            )
            self.session.add(order)
            self.session.flush()
            for line, dish in prepared:
                order_item = OrderItem(
                    order_id=order.id, availability_id=None, dish_id=dish.id,
                    quantity=line.quantity,
                    unit_price=Decimal(line.amount_in_cents) / Decimal(100 * line.quantity),
                    line_total=Decimal(line.amount_in_cents) / Decimal(100),
                    dish_name=dish.name, photo_url=dish.photo_url,
                )
                self.session.add(order_item)
                self.session.flush()
                line.order_id = order.id
                line.order_item_id = order_item.id
            payment.order_id = order.id
            payment.status = "approved"
            payment.approved_at = now
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return payment, self.get_order(payment.order_id)

    def discover(self, now: datetime):
        statement = select(Dish, CookProfile, DishAvailability).join(
            CookProfile, CookProfile.id == Dish.cook_id
        ).join(
            User, User.id == CookProfile.user_id
        ).outerjoin(
            DishAvailability, (DishAvailability.dish_id == Dish.id) & (DishAvailability.status == "active")
        ).where(
            Dish.is_active.is_(True),
            CookProfile.is_verified.is_(True),
            CookProfile.approval_status == "approved",
            User.is_active.is_(True),
            ~User.email.endswith(".invalid"),
            or_(Dish.category.is_(None), func.substr(Dish.category, 1, 9) != "__kwitli_"),
        ).order_by(Dish.created_at.desc(), DishAvailability.available_date.desc())
        settings = get_settings()
        country = settings.launch_country.upper()
        enforced = {value.strip().upper() for value in settings.kyb_enforced_countries.split(",") if value.strip()}
        if country in enforced:
            versions = active_policy_versions(country)
            statement = statement.where(CookProfile.id.in_(select(MerchantVerificationCase.cook_profile_id).where(
                MerchantVerificationCase.country_code == country,
                MerchantVerificationCase.status == "approved",
                MerchantVerificationCase.policy_version.in_(versions) if versions else text("false"),
            )))
        return list(self.session.execute(statement))

    def list_admin_restaurants(self):
        active_dishes = (
            select(Dish.cook_id.label("cook_id"), func.count(Dish.id).label("active_dish_count"))
            .where(Dish.is_active.is_(True))
            .group_by(Dish.cook_id)
            .subquery()
        )
        configured_hours = (
            select(CookProfileHour.cook_profile_id.label("cook_id"), func.count(CookProfileHour.id).label("hours_count"))
            .group_by(CookProfileHour.cook_profile_id)
            .subquery()
        )
        rows = self.session.execute(
            select(
                CookProfile,
                User,
                func.coalesce(active_dishes.c.active_dish_count, 0),
                func.coalesce(configured_hours.c.hours_count, 0),
            )
            .join(User, User.id == CookProfile.user_id)
            .outerjoin(active_dishes, active_dishes.c.cook_id == CookProfile.id)
            .outerjoin(configured_hours, configured_hours.c.cook_id == CookProfile.id)
            .where(
                CookProfile.business_vertical == "food_service",
                ~func.lower(User.email).endswith(".invalid"),
            )
            .order_by(CookProfile.created_at.asc())
        )
        result = []
        for cook, user, active_dish_count, hours_count in rows:
            active_dish_count = int(active_dish_count)
            hours_count = int(hours_count)
            coordinates_present = cook.latitude is not None and cook.longitude is not None
            service_area_eligible = bool(
                coordinates_present
                and self.is_location_in_active_service_area(
                    cook.latitude, cook.longitude, get_settings().app_env
                )
            )
            ready = bool(
                (cook.display_name or "").strip()
                and (cook.bio or "").strip()
                and coordinates_present
                and service_area_eligible
                and hours_count == 7
                and active_dish_count > 0
                and user.is_active
            )
            result.append({
                "id": cook.id,
                "display_name": cook.display_name,
                "owner_email": user.email,
                "bio": cook.bio,
                "latitude": cook.latitude,
                "longitude": cook.longitude,
                "owner_active": user.is_active,
                "active_dish_count": active_dish_count,
                "hours_configured": hours_count == 7,
                "hours_count": hours_count,
                "service_area_eligible": service_area_eligible,
                "outside_active_service_area": coordinates_present and not service_area_eligible,
                "ready": ready,
                "is_verified": cook.is_verified,
                "approval_status": cook.approval_status,
                "approval_reason": cook.approval_reason,
                "created_at": cook.created_at,
            })
        return result


    def count_active_dishes(self, cook_id: str) -> int:
        return int(self.session.scalar(
            select(func.count(Dish.id)).where(Dish.cook_id == cook_id, Dish.is_active.is_(True))
        ) or 0)

    def review_stats_for_cooks(self, cook_ids: set[str]) -> dict[str, tuple[Decimal, int]]:
        if not cook_ids:
            return {}
        rows = self.session.execute(
            select(Review.cook_id, func.avg(Review.rating), func.count(Review.id))
            .where(Review.cook_id.in_(cook_ids))
            .group_by(Review.cook_id)
        )
        return {
            cook_id: (Decimal(str(average)).quantize(Decimal("0.01")), int(count))
            for cook_id, average, count in rows
        }

    def get_public_cook_data(self, cook_id: str, now: datetime):
        statement = (select(CookProfile)
            .join(User, User.id == CookProfile.user_id)
            .where(
                CookProfile.id == cook_id,
                CookProfile.is_verified.is_(True),
                CookProfile.approval_status == "approved",
                User.is_active.is_(True),
                ~User.email.endswith(".invalid"),
            ))
        settings = get_settings()
        country = settings.launch_country.upper()
        enforced = {value.strip().upper() for value in settings.kyb_enforced_countries.split(",") if value.strip()}
        if country in enforced:
            versions = active_policy_versions(country)
            statement = statement.where(CookProfile.id.in_(select(MerchantVerificationCase.cook_profile_id).where(
                MerchantVerificationCase.country_code == country,
                MerchantVerificationCase.status == "approved",
                MerchantVerificationCase.policy_version.in_(versions) if versions else text("false"),
            )))
        cook = self.session.scalar(statement)
        if cook is None:
            return None
        reviews = list(self.session.scalars(
            select(Review).where(Review.cook_id == cook_id).order_by(Review.created_at.desc())
        ))
        available = list(self.session.scalars(
            select(Dish).where(
                Dish.cook_id == cook_id,
                Dish.is_active.is_(True),
                or_(Dish.category.is_(None), func.substr(Dish.category, 1, 9) != "__kwitli_"),
            ).order_by(Dish.created_at.desc())
        ))
        completed_count = self.session.scalar(
            select(func.count(Order.id))
            .outerjoin(DishAvailability, DishAvailability.id == Order.availability_id)
            .outerjoin(Dish, Dish.id == DishAvailability.dish_id)
            .where(func.coalesce(Order.cook_id, Dish.cook_id) == cook_id, Order.status.in_(ORDER_RETRIEVED_STATUSES))
        ) or 0
        return cook, reviews, available, int(completed_count)

    def list_reviews_for_cook(self, cook_id: str, limit: int, offset: int) -> list[Review]:
        return list(self.session.scalars(
            select(Review).where(Review.cook_id == cook_id).order_by(Review.created_at.desc()).limit(limit).offset(offset)
        ))

    def list_orders_for_customer(self, customer_id: str, active_only: bool = False):
        return list(self.session.execute(
            select(Order, Dish, CookProfile, Review)
            .outerjoin(DishAvailability, DishAvailability.id == Order.availability_id)
            .outerjoin(Dish, Dish.id == DishAvailability.dish_id)
            .join(CookProfile, CookProfile.id == func.coalesce(Order.cook_id, Dish.cook_id))
            .outerjoin(Review, Review.order_id == Order.id)
            .where(Order.customer_id == customer_id)
            .where(Order.status.in_(("ordered", "in_progress", "ready", "confirmed")) if active_only else True)
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
        ))

    def list_orders_for_cook(self, cook_id: str, active_only: bool = False):
        return list(self.session.execute(
            select(Order, Dish, CookProfile, Review)
            .outerjoin(DishAvailability, DishAvailability.id == Order.availability_id)
            .outerjoin(Dish, Dish.id == DishAvailability.dish_id)
            .join(CookProfile, CookProfile.id == func.coalesce(Order.cook_id, Dish.cook_id))
            .outerjoin(Review, Review.order_id == Order.id)
            .where(CookProfile.id == cook_id)
            .where(Order.status.in_(("ordered", "in_progress", "ready", "confirmed")) if active_only else True)
            .options(selectinload(Order.items))
            .order_by(Order.created_at.desc())
        ))

    def add_favorite_cook(self, user_id: str, cook_id: str) -> FavoriteCook:
        return self.create(FavoriteCook(user_id=user_id, cook_id=cook_id))

    def delete_favorite_cook(self, user_id: str, cook_id: str) -> bool:
        favorite = self.session.scalar(select(FavoriteCook).where(FavoriteCook.user_id == user_id, FavoriteCook.cook_id == cook_id))
        if favorite is None:
            return False
        self.session.delete(favorite)
        self.session.commit()
        return True

    def is_favorite_cook(self, user_id: str, cook_id: str) -> bool:
        return self.session.scalar(select(FavoriteCook.id).where(FavoriteCook.user_id == user_id, FavoriteCook.cook_id == cook_id)) is not None

    def list_favorite_cooks(self, user_id: str):
        return list(self.session.execute(
            select(FavoriteCook, CookProfile)
            .join(CookProfile, CookProfile.id == FavoriteCook.cook_id)
            .join(User, User.id == CookProfile.user_id)
            .where(
                FavoriteCook.user_id == user_id,
                User.is_active.is_(True),
                ~User.email.endswith(".invalid"),
            ).order_by(FavoriteCook.created_at.desc())
        ))
