from __future__ import annotations

import secrets
import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.core.time import as_utc, market_datetime_as_utc, market_today, utc_now
from backend.app.core.config import get_settings
from backend.app.core.business_hours import is_business_open_at
from backend.app.core.currencies import amount_storage_units, require_currency_environment
from backend.app.core.service_areas import point_in_service_area
from backend.app.discovery import (
    BusinessVertical,
    DEFAULT_BUSINESS_VERTICAL,
    DISTANCE_COMPARISON_EPSILON_KM,
    FEATURED_DISCOVERY_TYPES,
    FRESH_MAX_AGE,
    NEARBY_RADIUS_KM,
    NEW_DISH_MAX_AGE,
    DiscoveryFilter,
)
from backend.app.persistence.models import CookProfile, Dish, DishAvailability, Order, OrderMessage, OrderResolutionRequest, PickupVerification, Review, User, ORDER_RETRIEVED_STATUSES
from backend.app.repositories.sqlalchemy import SqlAlchemyMarketplaceRepository
from backend.app.schemas.availabilities import AvailabilityCreateRequest, AvailabilityUpdateRequest
from backend.app.schemas.cooks import CookCreateRequest, CookUpdateRequest
from backend.app.schemas.business_hours import BusinessHoursSave
from backend.app.schemas.dishes import DishCreateRequest, DishPublicationCreateRequest, DishUpdateRequest
from backend.app.schemas.orders import OrderResolutionDecision, OrderResolutionRequestCreate, OrderCreateRequest
from backend.app.schemas.reviews import ReviewCreateRequest
from backend.app.schemas.users import UserRegisterRequest
from backend.app.security import hash_password, verify_password
from backend.app.services.password_reset_email import PasswordResetEmailSender


class MarketplaceError(Exception):
    pass


class NotFoundError(MarketplaceError):
    pass


class ConflictError(MarketplaceError):
    pass


class AuthenticationError(MarketplaceError):
    pass


class AuthorizationError(MarketplaceError):
    pass


class MarketplaceService:
    def __init__(self, repository: SqlAlchemyMarketplaceRepository) -> None:
        self._repository = repository

    def register_user(self, payload: UserRegisterRequest) -> User:
        values = payload.model_dump(exclude={"password"})
        values["email"] = str(payload.email).strip().lower()
        if self._repository.user_email_exists(values["email"]):
            raise ConflictError("Un compte utilise deja cette adresse e-mail.")
        user = User(**values, password_hash=hash_password(payload.password))
        return self._create(user)

    def authenticate(self, email: str, password: str) -> User:
        user = self._repository.get_user_by_email(email)
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            raise AuthenticationError("Email ou mot de passe invalide.")
        return user

    def request_password_reset(self, email: str, sender: PasswordResetEmailSender) -> None:
        if not sender.is_configured:
            return
        user = self._repository.get_user_by_email(email)
        if user is None or not user.is_active or user.password_hash is None:
            return

        now = utc_now()
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expiry = now + timedelta(minutes=get_settings().password_reset_token_expire_minutes)
        self._repository.create_password_reset_token(user.id, token_hash, now, expiry)
        try:
            sender.send_password_reset(user.email, raw_token)
        except Exception:
            # Ne conserve pas un lien inutilisable et ne révèle jamais l'echec selon le compte.
            self._repository.revoke_password_reset_token(token_hash, utc_now())

    def reset_password(self, raw_token: str, new_password: str) -> bool:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        return self._repository.apply_password_reset(token_hash, hash_password(new_password), utc_now())

    def get_user(self, user_id: str) -> User:
        return self._required(self._repository.get_user(user_id), "Utilisateur introuvable.")

    def get_me(self, user: User) -> tuple[User, CookProfile | None]:
        return user, self._repository.get_cook_by_user(user.id)

    def create_cook(self, payload: CookCreateRequest, user: User) -> CookProfile:
        if self._repository.get_cook_by_user(user.id) is not None:
            raise ConflictError("Ce profil cuisinier existe deja.")
        user.can_cook = True
        return self._create(CookProfile(user_id=user.id, **payload.model_dump()))

    def update_cook(self, payload: CookUpdateRequest, user: User) -> CookProfile:
        cook = self._repository.get_cook_by_user(user.id)
        if cook is None:
            raise AuthorizationError("Un profil cuisinier est requis.")
        values = payload.model_dump(exclude_unset=True)
        location_changed = any(
            field in values and values[field] is not None and values[field] != getattr(cook, field)
            for field in ("latitude", "longitude")
        )
        for field, value in values.items():
            setattr(cook, field, value)
        if location_changed and (cook.approval_status == "approved" or cook.is_verified):
            # L'approbation commerciale porte aussi sur le point de retrait publié.
            # Une nouvelle localisation doit être revue avant de redevenir visible.
            cook.approval_status = "pending_review"
            cook.is_verified = False
        return self._repository.update(cook)

    def get_cook(self, cook_id: str) -> CookProfile:
        return self._required(self._repository.get_cook(cook_id), "Cuisinier introuvable.")

    def create_dish(self, payload: DishCreateRequest, user: User) -> Dish:
        self._validate_currency_environment(payload.currency)
        cook = self._repository.get_cook_by_user(user.id)
        if cook is None:
            raise AuthorizationError("Un profil cuisinier est requis pour publier un plat.")
        return self._create(Dish(cook_id=cook.id, **payload.model_dump()))

    def publish_dish_with_availability(
        self,
        payload: DishPublicationCreateRequest,
        user: User,
    ) -> tuple[Dish, DishAvailability]:
        self._validate_currency_environment(payload.currency)
        cook = self._repository.get_cook_by_user(user.id)
        if cook is None:
            raise AuthorizationError("Un profil cuisinier est requis pour publier un plat.")
        dish = Dish(
            cook_id=cook.id,
            name=payload.name,
            description=payload.description,
            price=payload.price,
            currency=payload.currency,
            photo_url=None,
            category=payload.category,
            is_active=payload.is_active,
        )
        availability_values = {
            "available_date": payload.available_date,
            "start_time": payload.start_time,
            "end_time": payload.end_time,
            "total_portions": payload.total_portions,
            "remaining_portions": payload.total_portions,
            "status": "active",
        }
        return self._repository.create_dish_with_availability(dish, availability_values)

    @staticmethod
    def _validate_currency_environment(currency: str) -> None:
        try:
            require_currency_environment(currency)
        except ValueError as exc:
            raise AuthorizationError(str(exc)) from exc

    def set_dish_photo(self, dish_id: str, photo_url: str, user: User) -> Dish:
        dish = self.get_owned_dish(dish_id, user)
        dish.photo_url = photo_url
        return self._repository.update(dish)

    def update_dish(self, dish_id: str, payload: DishUpdateRequest, user: User) -> Dish:
        dish = self.get_owned_dish(dish_id, user)
        values = payload.model_dump(exclude_unset=True)
        if "price" in values:
            amount_storage_units(values["price"], dish.currency)
        for field, value in values.items():
            setattr(dish, field, value)
        return self._repository.update(dish)

    def set_cook_profile_photo(self, photo_url: str, user: User) -> CookProfile:
        cook = self.get_owned_cook_profile(user)
        cook.profile_photo_url = photo_url
        return self._repository.update(cook)

    def get_owned_cook_profile(self, user: User) -> CookProfile:
        cook = self._repository.get_cook_by_user(user.id)
        if cook is None:
            raise AuthorizationError("Un profil cuisinier est requis.")
        return cook

    def get_cook_business_hours(self, user: User) -> list[dict]:
        cook = self.get_owned_cook_profile(user)
        stored = {row.weekday: row for row in self._repository.get_cook_hours(cook.id)}
        return [self._business_hour_value(stored.get(weekday), cook.id, weekday) for weekday in range(7)]

    def save_cook_business_hours(self, payload: BusinessHoursSave, user: User) -> list[dict]:
        cook = self.get_owned_cook_profile(user)
        values = sorted((day.model_dump() for day in payload.days), key=lambda day: day["weekday"])
        rows = self._repository.save_cook_hours(cook.id, values)
        stored = {row.weekday: row for row in rows}
        return [self._business_hour_value(stored.get(weekday), cook.id, weekday) for weekday in range(7)]

    @staticmethod
    def _business_hour_value(row, cook_id: str, weekday: int) -> dict:
        return {
            "id": row.id if row else None,
            "cook_profile_id": cook_id,
            "weekday": weekday,
            "is_closed": row.is_closed if row else True,
            "opens_at": row.opens_at if row else None,
            "closes_at": row.closes_at if row else None,
        }

    def cook_open_status(self, cook_ids: set[str], now: datetime | None = None) -> dict[str, bool]:
        return self._repository.cook_open_status(cook_ids, now or utc_now())

    def is_cook_open(self, cook_id: str, now: datetime | None = None) -> bool:
        return self.cook_open_status({cook_id}, now).get(cook_id, False)

    def get_owned_dish(self, dish_id: str, user: User) -> Dish:
        dish = self.get_dish(dish_id)
        cook = self._repository.get_cook_by_user(user.id)
        if cook is None or dish.cook_id != cook.id:
            raise AuthorizationError("Vous ne pouvez pas modifier cet article.")
        return dish

    def get_dish(self, dish_id: str) -> Dish:
        return self._required(self._repository.get_dish(dish_id), "Plat introuvable.")

    def list_dishes(self) -> list[Dish]:
        return self._repository.list_dishes()

    def list_dishes_for_user(self, user: User) -> list[Dish]:
        cook = self._repository.get_cook_by_user(user.id)
        if cook is None:
            raise AuthorizationError("Un profil commerçant est requis pour consulter ces articles.")
        return self._repository.list_dishes_for_cook(cook.id)

    def create_availability(self, payload: AvailabilityCreateRequest, user: User) -> DishAvailability:
        dish = self.get_dish(str(payload.dish_id))
        cook = self._repository.get_cook_by_user(user.id)
        if cook is None or dish.cook_id != cook.id:
            raise AuthorizationError("Vous ne pouvez pas publier cette disponibilite.")
        values = self._dump_ids(payload)
        values["remaining_portions"] = payload.total_portions
        return self._create(DishAvailability(**values))

    def get_availability(self, availability_id: str) -> DishAvailability:
        return self._required(self._repository.get_availability(availability_id), "Disponibilite introuvable.")

    def list_availabilities(self) -> list[DishAvailability]:
        return self._repository.list_availabilities()

    def list_availabilities_for_user(self, user: User) -> list[DishAvailability]:
        cook = self._repository.get_cook_by_user(user.id)
        if cook is None:
            raise AuthorizationError("Un profil commerçant est requis pour consulter ces disponibilites.")
        return self._repository.list_availabilities_for_cook(cook.id)

    def get_owned_availability(self, availability_id: str, user: User) -> DishAvailability:
        availability = self.get_availability(availability_id)
        dish = self.get_dish(str(availability.dish_id))
        cook = self._repository.get_cook_by_user(user.id)
        if cook is None or dish.cook_id != cook.id:
            raise AuthorizationError("Vous ne pouvez pas modifier cette disponibilite.")
        return availability

    def update_availability(self, availability_id: str, payload: AvailabilityUpdateRequest, user: User) -> DishAvailability:
        availability = self.get_owned_availability(availability_id, user)
        values = payload.model_dump(exclude_unset=True)
        next_date = values.get("available_date", availability.available_date)
        next_start = values.get("start_time", availability.start_time)
        next_end = values.get("end_time", availability.end_time)
        if next_end <= next_start:
            raise ConflictError("L'heure de fin doit etre apres l'heure de debut.")
        if next_date < market_today():
            raise ConflictError("La disponibilite ne peut pas etre dans le passe.")
        if market_datetime_as_utc(next_date, next_end) <= utc_now():
            raise ConflictError("La fin de disponibilite doit rester dans le futur.")
        next_total = values.get("total_portions", availability.total_portions)
        next_remaining = values.get("remaining_portions", availability.remaining_portions)
        if next_remaining > next_total:
            raise ConflictError("Le stock disponible ne peut pas depasser le stock total.")
        for field, value in values.items():
            setattr(availability, field, value)
        return self._repository.update(availability)

    def create_order(self, payload: OrderCreateRequest, user: User):
        try:
            return self._repository.create_order_with_stock_decrement(
                customer_id=user.id,
                availability_id=str(payload.availability_id),
                quantity=payload.quantity,
                now=utc_now(),
            )
        except LookupError as exc:
            raise NotFoundError(str(exc)) from exc
        except ValueError as exc:
            raise ConflictError(str(exc)) from exc

    def get_order(self, order_id: str):
        return self._required(self._repository.get_order(order_id), "Commande introuvable.")

    def get_order_for_user(self, order_id: str, user: User):
        order = self.get_order(order_id)
        cook = self._repository.get_cook_by_user(user.id)
        if order.customer_id != user.id and (cook is None or not self._order_belongs_to_cook(order, cook)):
            raise AuthorizationError("Vous ne pouvez pas consulter cette commande.")
        return order

    def list_order_messages(self, order_id: str, user: User):
        order = self.get_order(order_id)
        self._order_message_role(order, user)
        return self._repository.list_order_messages(order_id, limit=50)

    def create_order_message(self, order_id: str, body: str, user: User):
        order = self.get_order(order_id)
        sender_role = self._order_message_role(order, user)
        normalized_body = body.strip()
        if not normalized_body or len(normalized_body) > 230:
            raise ConflictError("Le message doit contenir entre 1 et 230 caracteres.")
        return self._repository.create_order_message(OrderMessage(
            order_id=order.id,
            sender_id=user.id,
            sender_role=sender_role,
            body=normalized_body,
        ))

    def _order_message_role(self, order: Order, user: User) -> str:
        if order.customer_id == user.id:
            return "customer"
        cook = self._repository.get_cook_by_user(user.id)
        if cook is not None and self._order_belongs_to_cook(order, cook):
            return "merchant"
        raise AuthorizationError("Vous ne pouvez pas acceder aux messages de cette commande.")

    def order_response_for_user(self, order: Order, user: User) -> dict:
        return self._order_response(order, include_pickup_code=order.customer_id == user.id)

    def list_orders_for_user(self, user: User, scope: str, active_only: bool = False):
        cook = self._repository.get_cook_by_user(user.id)
        if scope in {"cook", "merchant"}:
            if cook is None:
                raise AuthorizationError("Un profil cuisinier est requis pour consulter ces commandes.")
            rows = self._repository.list_orders_for_cook(cook.id, active_only)
        else:
            rows = self._repository.list_orders_for_customer(user.id, active_only)
        return [self._order_history_row(order, dish, row_cook, review, include_pickup_code=scope == "customer") for order, dish, row_cook, review in rows]

    def update_order_status(self, order_id: str, next_status: str, user: User):
        if next_status not in {"in_progress", "ready"}:
            raise ConflictError("Statut non accessible par cette action.")
        return self.transition_order_status(order_id, next_status, user)

    def transition_order_status(
        self, order_id: str, target_status: str, actor: User, *, pickup_verification_id: str | None = None,
    ) -> Order:
        """Transaction autonome; la preuve pickup doit etre verifiee et persistee."""
        session = self._repository.session
        actor_id = actor.id
        session.rollback()
        try:
            order = self._required(self._repository.get_order_for_update(order_id), "Commande introuvable.")
            stored_actor = self._repository.get_user(actor_id)
            cook = self._repository.get_cook_by_user(actor_id)
            if stored_actor is None or not stored_actor.is_active or cook is None or not self._order_belongs_to_cook(order, cook):
                raise AuthorizationError("Vous ne pouvez pas modifier cette commande.")
            if target_status not in {"in_progress", "ready", "picked_up"}:
                raise ConflictError("Transition de statut invalide.")
            if target_status == "picked_up" and not pickup_verification_id:
                raise ConflictError("Une preuve de retrait verifiee est requise.")
            if order.status == target_status:
                if target_status == "picked_up" and order.pickup_verification_id != pickup_verification_id:
                    raise ConflictError("Preuve de retrait incoherente.")
                session.commit()
                return order
            allowed = {"ordered": "in_progress", "in_progress": "ready", "ready": "picked_up"}
            # Compatibilite du parcours par code des anciennes commandes uniquement.
            legacy_ready = order.status == "confirmed" and order.availability_id is not None and target_status == "ready"
            if not legacy_ready and allowed.get(order.status) != target_status:
                raise ConflictError("Transition de statut invalide.")
            now = utc_now()
            if target_status == "picked_up":
                proof = session.scalar(select(PickupVerification).where(
                    PickupVerification.id == pickup_verification_id).with_for_update().execution_options(populate_existing=True))
                if (proof is None or proof.status != "verified" or proof.order_id != order.id
                        or proof.customer_id != order.customer_id or proof.merchant_user_id != actor_id
                        or proof.method not in {"proximity", "qr_fallback"} or proof.used_at is None
                        or order.ready_at is None or as_utc(proof.used_at) < as_utc(order.ready_at)
                        or not as_utc(proof.created_at) <= as_utc(proof.used_at) <= now
                        or as_utc(proof.expires_at) <= now):
                    raise ConflictError("Preuve de retrait invalide ou expiree.")
                order.pickup_verification_id = proof.id
                order.pickup_method = proof.method
                order.picked_up_by = actor_id
                order.picked_up_at = now
            elif target_status == "in_progress":
                order.in_progress_at = now
            else:
                order.ready_at = now
            order.status = target_status
            session.commit()
            session.refresh(order)
            return order
        except Exception:
            session.rollback()
            raise

    def confirm_pickup(self, order_id: str, pickup_code: str | None, user: User) -> Order:
        if pickup_code is None:
            return self.confirm_customer_pickup(order_id, user)
        session = self._repository.session
        session.rollback()
        try:
            order = self._required(self._repository.get_order_for_update(order_id), "Commande introuvable.")
            actor = self._repository.get_user(user.id)
            if actor is None or not actor.is_active:
                raise AuthorizationError("Session invalide.")
            self._require_order_cook_owner(order, actor)
            if order.status == "picked_up":
                if order.picked_up_by == actor.id and order.pickup_code and secrets.compare_digest(order.pickup_code, pickup_code):
                    session.commit()
                    return order
                raise ConflictError("Le retrait a deja ete valide.")
            if order.status != "ready":
                raise ConflictError("La commande doit etre prete avant la validation du retrait.")
            if not order.pickup_code or not secrets.compare_digest(order.pickup_code, pickup_code):
                raise ConflictError("Code de retrait invalide.")
            now = utc_now()
            if order.pickup_expires_at is not None and as_utc(order.pickup_expires_at) <= now:
                raise ConflictError("Le code de retrait a expire.")

            # Les nouvelles commandes panier passent par picked_up; le parcours
            # legacy mono-disponibilite conserve son statut completed historique.
            if order.availability_id is not None:
                self._transition(order, "completed")
            else:
                order.status = "picked_up"
                order.picked_up_at = now
                order.picked_up_by = actor.id
                order.pickup_method = "legacy_code"
            session.commit()
            session.refresh(order)
            return order
        except Exception:
            session.rollback()
            raise

    def request_pickup_code(self, order_id: str, user: User) -> Order:
        session = self._repository.session
        session.rollback()
        try:
            order = self._required(self._repository.get_order_for_update(order_id), "Commande introuvable.")
            actor = self._repository.get_user(user.id)
            if actor is None or not actor.is_active:
                raise AuthorizationError("Session invalide.")
            if order.customer_id != actor.id:
                raise AuthorizationError("Seul le client de cette commande peut afficher le code de retrait.")
            if order.status != "ready":
                raise ConflictError("Le code de retrait est disponible lorsque la commande est prete.")
            now = utc_now()
            if order.pickup_expires_at is not None and as_utc(order.pickup_expires_at) <= now:
                raise ConflictError("La periode de retrait est terminee.")
            if not order.pickup_code:
                order.pickup_code = self._repository.new_pickup_code()
            session.commit()
            session.refresh(order)
            return order
        except Exception:
            session.rollback()
            raise

    def confirm_customer_pickup(self, order_id: str, user: User) -> Order:
        order = self.get_order(order_id)
        actor = self._repository.get_user(user.id)
        if actor is None or not actor.is_active:
            raise AuthorizationError("Session invalide.")
        if order.customer_id == actor.id:
            raise ConflictError("Le retrait doit etre confirme par le commercant.")
        cook = self._repository.get_cook_by_user(actor.id)
        if cook is None or not self._order_belongs_to_cook(order, cook):
            raise AuthorizationError("Vous ne pouvez pas valider le retrait de cette commande.")
        raise ConflictError("Une preuve de retrait valide est requise.")

    def submit_order_resolution_request(
        self, order_id: str, payload: OrderResolutionRequestCreate, user: User
    ) -> OrderResolutionRequest:
        session = self._repository.session
        session.rollback()
        try:
            order = self._required(self._repository.get_order_for_update(order_id), "Commande introuvable.")
            actor = self._repository.get_user(user.id)
            if actor is None or not actor.is_active:
                raise AuthorizationError("Session invalide.")

            if order.customer_id == actor.id:
                requester_role = "customer"
                request_type = "client_cancellation" if order.status in {"ordered", "confirmed"} else "client_claim"
                allowed_reasons = {
                    "order_not_received", "incorrect_order", "item_missing", "excessive_delay",
                    "quality_issue", "merchant_unavailable", "other",
                }
            else:
                cook = self._repository.get_cook_by_user(actor.id)
                if cook is None or not self._order_belongs_to_cook(order, cook):
                    raise AuthorizationError("Vous ne pouvez pas demander la resolution de cette commande.")
                if order.status in {"picked_up", "completed", "cancelled"}:
                    raise ConflictError("Cette commande est deja terminee.")
                requester_role = "merchant"
                request_type = "merchant_cancellation"
                allowed_reasons = {
                    "ingredient_unavailable", "item_out_of_stock", "exceptional_closure",
                    "menu_price_error", "technical_issue", "other",
                }

            if payload.reason not in allowed_reasons:
                raise ConflictError("Le motif ne correspond pas au type de demande.")
            if not payload.description.strip():
                raise ConflictError("Une justification est obligatoire.")
            if requester_role == "customer" and order.status == "cancelled":
                raise ConflictError("Cette commande est deja terminee.")

            existing = session.scalar(select(OrderResolutionRequest).where(
                OrderResolutionRequest.order_id == order.id,
                OrderResolutionRequest.requester_id == actor.id,
                OrderResolutionRequest.status == "submitted",
            ).with_for_update())
            if existing is not None:
                raise ConflictError("Une demande est deja en attente pour cette commande.")

            request_row = OrderResolutionRequest(
                order_id=order.id,
                requester_id=actor.id,
                requester_role=requester_role,
                request_type=request_type,
                reason=payload.reason,
                description=payload.description.strip(),
            )
            session.add(request_row)
            session.commit()
            session.refresh(request_row)
            return request_row
        except Exception:
            session.rollback()
            raise

    def list_order_resolution_requests(self, user: User, status_filter: str | None = None) -> list[OrderResolutionRequest]:
        actor = self._repository.get_user(user.id)
        if actor is None or not actor.is_active or not actor.is_admin:
            raise AuthorizationError("Acces reserve au support Kwitli.")
        query = select(OrderResolutionRequest).order_by(OrderResolutionRequest.created_at.asc())
        if status_filter is not None:
            query = query.where(OrderResolutionRequest.status == status_filter)
        return list(self._repository.session.scalars(query.limit(100)))

    def list_admin_restaurants(self, user: User) -> list[dict]:
        actor = self._repository.get_user(user.id)
        if actor is None or not actor.is_active or not actor.is_admin:
            raise AuthorizationError("Acces reserve a l’administration Kwitli.")
        return self._repository.list_admin_restaurants()


    def decide_admin_restaurant(
        self, cook_id: str, action: str, reason: str | None, user: User
    ) -> CookProfile:
        session = self._repository.session
        session.rollback()
        try:
            actor = self._repository.get_user(user.id)
            if actor is None or not actor.is_active or not actor.is_admin:
                raise AuthorizationError("Acces reserve a l’administration Kwitli.")
            cook = session.scalar(
                select(CookProfile).where(CookProfile.id == cook_id).with_for_update()
            )
            if cook is None or cook.business_vertical != "food_service":
                raise NotFoundError("Restaurant introuvable.")
            owner = self._repository.get_user(cook.user_id)
            if owner is None or owner.email.lower().endswith(".invalid"):
                raise NotFoundError("Restaurant introuvable.")

            normalized_reason = (reason or "").strip()
            if action == "reject" and not normalized_reason:
                raise ConflictError("Une raison est obligatoire pour refuser un restaurant.")
            if len(normalized_reason) > 1000:
                raise ConflictError("La raison ne peut pas dépasser 1000 caractères.")

            if action in {"approve", "reactivate"}:
                if action == "approve" and cook.approval_status != "pending_review":
                    raise ConflictError("Seul un restaurant en attente peut être approuvé.")
                if action == "reactivate" and cook.approval_status != "suspended":
                    raise ConflictError("Seul un restaurant suspendu peut être réactivé.")
                missing = []
                if not cook.display_name.strip():
                    missing.append("nom")
                if not (cook.bio or "").strip():
                    missing.append("description")
                if cook.latitude is None or cook.longitude is None:
                    missing.append("point GPS")
                elif not self._repository.is_location_in_active_service_area(
                    cook.latitude, cook.longitude, get_settings().app_env, lock=True
                ):
                    missing.append("point GPS dans une zone commerciale active")
                if len(self._repository.get_cook_hours(cook.id)) != 7:
                    missing.append("horaires des 7 jours")
                if self._repository.count_active_dishes(cook.id) < 1:
                    missing.append("article actif")
                if not owner.is_active:
                    missing.append("compte propriétaire actif")
                if missing:
                    raise ConflictError("Fiche incomplète : " + ", ".join(missing) + ".")
                cook.approval_status = "approved"
                cook.is_verified = True
                cook.approval_reason = None
            elif action == "reject":
                if cook.approval_status != "pending_review":
                    raise ConflictError("Seul un restaurant en attente peut être refusé.")
                cook.approval_status = "rejected"
                cook.is_verified = False
                cook.approval_reason = normalized_reason
            elif action == "suspend":
                if cook.approval_status != "approved":
                    raise ConflictError("Seul un restaurant approuvé peut être suspendu.")
                cook.approval_status = "suspended"
                cook.is_verified = False
                cook.approval_reason = normalized_reason or None
            else:
                raise ConflictError("Action admin invalide.")

            cook.approval_reviewed_at = utc_now()
            cook.approval_reviewed_by = actor.id
            session.commit()
            session.refresh(cook)
            return cook
        except Exception:
            session.rollback()
            raise

    def decide_order_resolution_request(
        self, request_id: str, payload: OrderResolutionDecision, user: User
    ) -> OrderResolutionRequest:
        session = self._repository.session
        session.rollback()
        try:
            actor = self._repository.get_user(user.id)
            if actor is None or not actor.is_active or not actor.is_admin:
                raise AuthorizationError("Acces reserve au support Kwitli.")
            request_row = session.scalar(select(OrderResolutionRequest).where(
                OrderResolutionRequest.id == request_id
            ).with_for_update())
            if request_row is None:
                raise NotFoundError("Demande introuvable.")
            if request_row.status != "submitted":
                raise ConflictError("Cette demande a deja ete traitee.")
            request_row.status = "resolution_requested" if payload.decision == "request_resolution" else payload.decision
            request_row.reviewed_by = actor.id
            request_row.reviewed_at = utc_now()
            request_row.decision_note = payload.note.strip()
            if not request_row.decision_note:
                raise ConflictError("Une note de decision est obligatoire.")
            # Une décision de support est enregistrée, mais ne déclenche ni changement
            # de statut de commande ni mouvement de paiement/remboursement.
            session.commit()
            session.refresh(request_row)
            return request_row
        except Exception:
            session.rollback()
            raise

    def create_review(self, payload: ReviewCreateRequest, user: User) -> Review:
        order = self.get_order(str(payload.order_id))
        if order.customer_id != user.id:
            raise AuthorizationError("Vous ne pouvez pas noter cette commande.")
        if order.status not in ORDER_RETRIEVED_STATUSES:
            raise ConflictError("Cette commande doit etre terminee avant de laisser un avis.")
        if self._repository.get_review_by_order(order.id) is not None:
            raise ConflictError("Cette commande a deja recu un avis.")
        cook = self._order_cook(order)
        if cook.user_id == user.id:
            raise AuthorizationError("Vous ne pouvez pas noter votre propre plat.")
        return self._create(Review(
            order_id=order.id,
            customer_id=user.id,
            cook_id=cook.id,
            rating=payload.rating,
            comment=payload.comment,
        ))

    def list_reviews_for_cook(self, cook_id: str, limit: int, offset: int) -> list[Review]:
        self.get_public_cook_profile(cook_id)
        return self._repository.list_reviews_for_cook(cook_id, limit, offset)

    def get_public_cook_profile(self, cook_id: str) -> dict:
        data = self._repository.get_public_cook_data(cook_id, utc_now())
        if data is None:
            raise NotFoundError("Cuisinier introuvable.")
        cook, reviews, active_dishes, completed_count = data
        if cook.latitude is None or cook.longitude is None or not self._repository.is_location_in_active_service_area(
            cook.latitude, cook.longitude, get_settings().app_env
        ):
            raise NotFoundError("Restaurant indisponible dans les zones commerciales actives.")
        rating_average = (sum((review.rating for review in reviews), Decimal("0")) / len(reviews)).quantize(Decimal("0.01")) if reviews else None
        return {
            "cook_id": cook.id,
            "display_name": cook.display_name,
            "bio": cook.bio,
            "profile_photo_url": cook.profile_photo_url,
            "rating_average": rating_average,
            "rating_count": len(reviews),
            "orders_completed": completed_count,
            "is_verified": cook.is_verified,
            "is_open": self.is_cook_open(cook.id),
            "business_vertical": cook.business_vertical or DEFAULT_BUSINESS_VERTICAL,
            "active_dishes_count": len(active_dishes),
            "member_since": cook.created_at,
            "available_dishes": [
                {
                    "dish_id": dish.id, "availability_id": None, "name": dish.name,
                    "description": dish.description, "photo_url": dish.photo_url, "price": dish.price,
                    "currency": dish.currency, "remaining_portions": None,
                    "start_time": None, "end_time": None,
                }
                for dish in active_dishes
            ],
            "recent_reviews": [
                {"id": review.id, "rating": review.rating, "comment": review.comment, "created_at": review.created_at}
                for review in reviews[:5]
            ],
        }

    def add_favorite_cook(self, cook_id: str, user: User):
        self.get_cook(cook_id)
        try:
            return self._repository.add_favorite_cook(user.id, cook_id)
        except IntegrityError as exc:
            raise ConflictError("Ce cuisinier est deja dans vos favoris.") from exc

    def remove_favorite_cook(self, cook_id: str, user: User) -> None:
        if not self._repository.delete_favorite_cook(user.id, cook_id):
            raise NotFoundError("Favori introuvable.")

    def favorite_cook_status(self, cook_id: str, user: User) -> bool:
        self.get_cook(cook_id)
        return self._repository.is_favorite_cook(user.id, cook_id)

    def list_favorite_cooks(self, user: User) -> list[dict]:
        result = []
        for favorite, cook in self._repository.list_favorite_cooks(user.id):
            profile = self.get_public_cook_profile(cook.id)
            result.append({
                "id": favorite.id, "cook_id": cook.id, "display_name": cook.display_name,
                "profile_photo_url": cook.profile_photo_url, "rating_average": profile["rating_average"],
                "rating_count": profile["rating_count"], "has_active_availability": profile["active_dishes_count"] > 0,
                "created_at": favorite.created_at,
            })
        return result

    def discover(
        self,
        latitude: float,
        longitude: float,
        radius_km: float,
        discovery_filter: DiscoveryFilter | None = None,
        business_vertical: BusinessVertical | None = None,
    ):
        now = utc_now()
        results = []
        seen_dishes: set[str] = set()
        app_env = get_settings().app_env
        active_areas = self._repository.list_active_service_areas(app_env)
        for dish, cook, availability in self._repository.discover(now):
            if dish.id in seen_dishes:
                continue
            seen_dishes.add(dish.id)
            if business_vertical is not None and (cook.business_vertical or DEFAULT_BUSINESS_VERTICAL) != business_vertical:
                continue
            if (cook.latitude is None or cook.longitude is None
                    or not any(point_in_service_area(cook.latitude, cook.longitude, area) for area in active_areas)):
                continue
            raw_distance_km = _haversine_distance_km(latitude, longitude, cook.latitude, cook.longitude)
            if not _is_within_distance(raw_distance_km, radius_km):
                continue
            if not _matches_discovery_filter(
                discovery_filter,
                availability,
                dish,
                raw_distance_km,
                availability.remaining_portions if availability else None,
                now,
            ):
                continue
            distance_km = round(raw_distance_km, 2)
            legacy_stock = availability.remaining_portions if availability and discovery_filter == "low_stock" else None
            results.append((availability, dish, cook, distance_km, legacy_stock))
        return sorted(results, key=lambda item: item[3])

    def review_stats_for_cooks(self, cook_ids: set[str]) -> dict[str, tuple[Decimal, int]]:
        return self._repository.review_stats_for_cooks(cook_ids)

    def _create(self, entity):
        try:
            return self._repository.create(entity)
        except IntegrityError as exc:
            raise ConflictError("La ressource existe deja ou sa reference est invalide.") from exc

    @staticmethod
    def _required(value, message: str):
        if value is None:
            raise NotFoundError(message)
        return value

    @staticmethod
    def _dump_ids(payload) -> dict:
        return {key: str(value) if hasattr(value, "hex") else value for key, value in payload.model_dump().items()}

    def _require_order_cook_owner(self, order: Order, user: User) -> CookProfile:
        cook = self._repository.get_cook_by_user(user.id)
        if cook is None or not self._order_belongs_to_cook(order, cook):
            raise AuthorizationError("Vous ne pouvez pas modifier cette commande.")
        return cook

    def _order_belongs_to_cook(self, order: Order, cook: CookProfile) -> bool:
        return self._order_cook(order).id == cook.id

    def _order_cook(self, order: Order) -> CookProfile:
        if order.cook_id is not None:
            return self.get_cook(order.cook_id)
        availability = self.get_availability(order.availability_id)
        dish = self.get_dish(availability.dish_id)
        return self.get_cook(dish.cook_id)

    @staticmethod
    def _transition(order: Order, next_status: str) -> None:
        allowed = {
            "confirmed": {"ready", "cancelled"},
            "ready": {"completed", "cancelled"},
            "completed": set(),
            "cancelled": set(),
        }
        if next_status not in allowed.get(order.status, set()):
            raise ConflictError("Transition de statut invalide.")
        now = utc_now()
        order.status = next_status
        if next_status == "ready":
            order.ready_at = now
        elif next_status == "completed":
            order.completed_at = now
        elif next_status == "cancelled":
            order.cancelled_at = now

    def _order_response(self, order: Order, include_pickup_code: bool) -> dict:
        cook = self._order_cook(order)
        return {
            "id": order.id, "customer_id": order.customer_id, "availability_id": order.availability_id,
            "quantity": order.quantity, "unit_price": order.unit_price, "total_price": order.total_price,
            "currency": order.currency,
            "status": order.status, "pickup_code": order.pickup_code if include_pickup_code else None,
            "confirmed_at": order.confirmed_at, "ready_at": order.ready_at, "completed_at": order.completed_at,
            "cancelled_at": order.cancelled_at, "pickup_expires_at": order.pickup_expires_at,
            "created_at": order.created_at,
            "in_progress_at": order.in_progress_at, "picked_up_at": order.picked_up_at,
            "cook_id": cook.id, "cook_display_name": cook.display_name,
            "items": [{"id": item.id, "dish_id": item.dish_id, "availability_id": item.availability_id,
                       "dish_name": item.dish_name, "photo_url": item.photo_url, "quantity": item.quantity,
                       "unit_price": item.unit_price, "line_total": item.line_total} for item in order.items],
        }

    def _order_history_row(self, order: Order, dish: Dish | None, cook: CookProfile, review: Review | None, include_pickup_code: bool) -> dict:
        return {
            **self._order_response(order, include_pickup_code),
            "dish_name": dish.name if dish else None, "dish_photo_url": dish.photo_url if dish else None,
            "review_id": review.id if review is not None else None,
            "review_rating": review.rating if review is not None else None,
            "review_comment": review.comment if review is not None else None,
        }


def _matches_discovery_filter(
    discovery_filter: DiscoveryFilter | None,
    availability: DishAvailability | None,
    dish: Dish,
    distance_km: float,
    remaining_portions: int,
    now: datetime,
) -> bool:
    if discovery_filter is None:
        return True
    if discovery_filter == "nearby":
        return _is_within_distance(distance_km, NEARBY_RADIUS_KM)
    if discovery_filter == "fresh":
        if availability is None:
            return False
        ready_at = availability.ready_at
        return now - FRESH_MAX_AGE <= ready_at <= now
    if discovery_filter == "low_stock":
        return remaining_portions is not None and 1 <= remaining_portions <= 5
    if discovery_filter == "new":
        return (
            dish.featured_type in FEATURED_DISCOVERY_TYPES
            or as_utc(dish.created_at) >= now - NEW_DISH_MAX_AGE
        )
    return False


def _is_within_distance(distance_km: float, maximum_km: float) -> bool:
    # Absorbe uniquement le bruit d'arrondi du calcul Haversine a la borne exacte.
    return distance_km <= maximum_km + DISTANCE_COMPARISON_EPSILON_KM


def _haversine_distance_km(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    earth_radius_km = 6371.0
    latitude_delta = radians(latitude_b - latitude_a)
    longitude_delta = radians(longitude_b - longitude_a)
    haversine = sin(latitude_delta / 2) ** 2 + cos(radians(latitude_a)) * cos(radians(latitude_b)) * sin(longitude_delta / 2) ** 2
    return 2 * earth_radius_km * asin(sqrt(haversine))


def haversine_km(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    return round(_haversine_distance_km(latitude_a, longitude_a, latitude_b, longitude_b), 2)
