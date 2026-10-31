from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, JSON, LargeBinary, Numeric, String, Text, Time, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base
from backend.app.core.time import market_datetime_as_utc, utc_now
from backend.app.discovery import DEFAULT_BUSINESS_VERTICAL


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return utc_now()


# Les lecteurs seront raccordes a ces deux terminaux lors de la phase service.
ORDER_RETRIEVED_STATUSES = ("completed", "picked_up")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("auth_version >= 0", name="ck_users_auth_version_nonnegative"),
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    can_cook: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default=text("false"))
    auth_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        CheckConstraint("length(token_hash) = 64", name="ck_password_reset_tokens_hash_length"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CookProfile(Base):
    __tablename__ = "cook_profiles"
    __table_args__ = (
        CheckConstraint("rating >= 0 AND rating <= 5", name="ck_cook_profiles_rating"),
        CheckConstraint("orders_completed >= 0", name="ck_cook_profiles_orders_completed"),
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_cook_profiles_latitude"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_cook_profiles_longitude"),
        CheckConstraint("business_vertical IN ('food_service', 'bakery_dessert', 'local_shop')", name="ck_cook_profiles_business_vertical"),
        CheckConstraint(
            "approval_status IN ('draft', 'pending_review', 'approved', 'rejected', 'suspended')",
            name="ck_cook_profiles_approval_status",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rating: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0.00"))
    orders_completed: Mapped[int] = mapped_column(Integer, default=0)
    latitude: Mapped[float] = mapped_column()
    longitude: Mapped[float] = mapped_column()
    business_vertical: Mapped[str] = mapped_column(String(30), default=DEFAULT_BUSINESS_VERTICAL, index=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_status: Mapped[str] = mapped_column(
        String(24), default="pending_review", server_default=text("'pending_review'"), nullable=False
    )
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CookProfileHour(Base):
    __tablename__ = "cook_profile_hours"
    __table_args__ = (
        UniqueConstraint("cook_profile_id", "weekday", name="uq_cook_profile_hours_weekday"),
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_cook_profile_hours_weekday"),
        CheckConstraint(
            "(is_closed AND opens_at IS NULL AND closes_at IS NULL) OR "
            "(NOT is_closed AND opens_at IS NOT NULL AND closes_at IS NOT NULL AND opens_at < closes_at)",
            name="ck_cook_profile_hours_times",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cook_profile_id: Mapped[str] = mapped_column(ForeignKey("cook_profiles.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(Integer)
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    opens_at: Mapped[time | None] = mapped_column(Time, nullable=True)
    closes_at: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ServiceAreaConfig(Base):
    __tablename__ = "service_area_configs"
    __table_args__ = (
        UniqueConstraint("environment", "area_id", name="uq_service_area_environment_id"),
        UniqueConstraint("environment", "code", name="uq_service_area_environment_code"),
        CheckConstraint("environment IN ('development', 'test', 'staging', 'production')", name="ck_service_area_environment"),
        CheckConstraint("status IN ('planned', 'recruiting', 'active', 'suspended')", name="ck_service_area_status"),
        CheckConstraint("geometry_type IN ('circle', 'polygon')", name="ck_service_area_geometry_type"),
        CheckConstraint("center_latitude IS NULL OR center_latitude BETWEEN -90 AND 90", name="ck_service_area_latitude"),
        CheckConstraint("center_longitude IS NULL OR center_longitude BETWEEN -180 AND 180", name="ck_service_area_longitude"),
        CheckConstraint("radius_km IS NULL OR (radius_km > 0 AND radius_km <= 100)", name="ck_service_area_radius"),
        CheckConstraint(
            "(geometry_type = 'circle' AND center_latitude IS NOT NULL AND center_longitude IS NOT NULL AND radius_km IS NOT NULL) OR "
            "(geometry_type = 'polygon' AND geometry_metadata IS NOT NULL)",
            name="ck_service_area_geometry_data",
        ),
        CheckConstraint("version > 0", name="ck_service_area_version"),
    )

    row_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    area_id: Mapped[str] = mapped_column(String(80))
    environment: Mapped[str] = mapped_column(String(20), index=True)
    code: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(160))
    country_code: Mapped[str] = mapped_column(String(2))
    country: Mapped[str] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(100))
    center_latitude: Mapped[float | None] = mapped_column(nullable=True)
    center_longitude: Mapped[float | None] = mapped_column(nullable=True)
    radius_km: Mapped[float | None] = mapped_column(nullable=True)
    geometry_type: Mapped[str] = mapped_column(String(16), default="circle", server_default=text("'circle'"))
    geometry_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3))
    distance_unit: Mapped[str] = mapped_column(String(8), default="km", server_default=text("'km'"))
    status: Mapped[str] = mapped_column(String(16), default="planned", server_default=text("'planned'"))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ServiceAreaEvent(Base):
    __tablename__ = "service_area_events"
    __table_args__ = (
        Index("ix_service_area_events_config_created", "service_area_row_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    service_area_row_id: Mapped[str] = mapped_column(
        ForeignKey("service_area_configs.row_id", ondelete="RESTRICT"), index=True
    )
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    action: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(500))
    from_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_version: Mapped[int] = mapped_column(Integer)
    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dish(Base):
    __tablename__ = "dishes"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_dishes_price"),
        CheckConstraint("currency IN ('COP', 'XOF')", name="ck_dishes_currency"),
        CheckConstraint("currency != 'XOF' OR price = CAST(price AS BIGINT)", name="ck_dishes_xof_integer"),
        CheckConstraint(
            "featured_type IS NULL OR featured_type IN ('new', 'dish_of_month', 'discovery', 'discount')",
            name="ck_dishes_featured_type",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cook_id: Mapped[str] = mapped_column(ForeignKey("cook_profiles.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="COP")
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    featured_type: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DishAvailability(Base):
    __tablename__ = "dish_availabilities"
    __table_args__ = (
        CheckConstraint("total_portions > 0", name="ck_dish_availabilities_total"),
        CheckConstraint("remaining_portions >= 0", name="ck_dish_availabilities_remaining"),
        CheckConstraint("remaining_portions <= total_portions", name="ck_dish_availabilities_stock"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dish_id: Mapped[str] = mapped_column(ForeignKey("dishes.id"), index=True)
    available_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    total_portions: Mapped[int] = mapped_column(Integer)
    remaining_portions: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def ready_at(self) -> datetime:
        return market_datetime_as_utc(self.available_date, self.start_time)

    @property
    def end_datetime(self) -> datetime:
        return market_datetime_as_utc(self.available_date, self.end_time)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_orders_quantity"),
        CheckConstraint("unit_price > 0", name="ck_orders_unit_price"),
        CheckConstraint("total_price > 0", name="ck_orders_total_price"),
        CheckConstraint("currency IN ('COP', 'XOF')", name="ck_orders_currency"),
        UniqueConstraint("id", "customer_id", name="uq_orders_customer"),
        CheckConstraint(
            "pickup_method IS NULL OR pickup_method IN ('proximity', 'qr_fallback', 'legacy_code')",
            name="ck_orders_pickup_method",
        ),
        CheckConstraint(
            "status != 'picked_up' OR (picked_up_at IS NOT NULL AND picked_up_by IS NOT NULL "
            "AND pickup_method IS NOT NULL AND (pickup_method = 'legacy_code' "
            "OR pickup_verification_id IS NOT NULL))",
            name="ck_orders_pickup_required",
        ),
        CheckConstraint(
            "pickup_verification_id IS NULL OR (pickup_method IS NOT NULL "
            "AND pickup_method IN ('proximity', 'qr_fallback') AND picked_up_by IS NOT NULL)",
            name="ck_orders_pickup_proof",
        ),
        ForeignKeyConstraint(
            ["pickup_verification_id", "id", "customer_id", "picked_up_by", "pickup_method"],
            ["pickup_verifications.id", "pickup_verifications.order_id", "pickup_verifications.customer_id",
             "pickup_verifications.merchant_user_id", "pickup_verifications.method"],
            name="fk_orders_pickup_verification", use_alter=True,
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    cook_id: Mapped[str | None] = mapped_column(ForeignKey("cook_profiles.id"), nullable=True, index=True)
    availability_id: Mapped[str | None] = mapped_column(ForeignKey("dish_availabilities.id"), index=True, nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="COP")
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    pickup_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    in_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pickup_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_up_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    pickup_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pickup_verification_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    items: Mapped[list[OrderItem]] = relationship(order_by="OrderItem.id")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "availability_id", name="uq_order_items_availability"),
        CheckConstraint("quantity > 0", name="ck_order_items_quantity"),
        CheckConstraint("unit_price > 0", name="ck_order_items_unit_price"),
        CheckConstraint("line_total > 0", name="ck_order_items_line_total"),
        CheckConstraint("ROUND(line_total, 2) = ROUND(quantity * unit_price, 2)", name="ck_order_items_total"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    availability_id: Mapped[str | None] = mapped_column(ForeignKey("dish_availabilities.id"), nullable=True)
    dish_id: Mapped[str] = mapped_column(ForeignKey("dishes.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    dish_name: Mapped[str] = mapped_column(String(120))
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)


class OrderMessage(Base):
    __tablename__ = "order_messages"
    __table_args__ = (
        CheckConstraint("sender_role IN ('customer', 'merchant')", name="ck_order_messages_sender_role"),
        CheckConstraint("length(trim(body)) > 0 AND length(body) <= 1000", name="ck_order_messages_body"),
        Index("ix_order_messages_order_created", "order_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    sender_role: Mapped[str] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MerchantVerificationCase(Base):
    """Dossier KYB privé, distinct de l'approbation commerciale."""
    __tablename__ = "merchant_verification_cases"
    __table_args__ = (
        CheckConstraint("status IN ('incomplete', 'submitted', 'under_review', 'correction_required', 'approved', 'rejected', 'suspended')", name="ck_merchant_verification_case_status"),
        Index("ix_merchant_verification_case_cook_created", "cook_profile_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cook_profile_id: Mapped[str] = mapped_column(ForeignKey("cook_profiles.id", ondelete="CASCADE"), index=True)
    country_code: Mapped[str] = mapped_column(String(2))
    jurisdiction_code: Mapped[str] = mapped_column(String(64))
    legal_entity_type: Mapped[str] = mapped_column(String(64))
    business_activity: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(40))
    policy_snapshot: Mapped[dict] = mapped_column(JSON)
    additional_requirements: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="incomplete")
    legal_data_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MerchantVerificationDocument(Base):
    __tablename__ = "merchant_verification_documents"
    __table_args__ = (
        CheckConstraint("status IN ('uploaded', 'technically_valid', 'visually_reviewed', 'under_review', 'source_verified', 'not_verifiable', 'rejected', 'replaced', 'expired')", name="ck_merchant_verification_document_status"),
        CheckConstraint("scan_status IN ('pending', 'clean', 'infected', 'error')", name="ck_merchant_verification_document_scan_status"),
        CheckConstraint("size_bytes > 0", name="ck_merchant_verification_document_size"),
        CheckConstraint("length(sha256) = 64", name="ck_merchant_verification_document_sha256"),
        UniqueConstraint("storage_key", name="uq_merchant_verification_document_storage_key"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("merchant_verification_cases.id", ondelete="CASCADE"), index=True)
    requirement_code: Mapped[str] = mapped_column(String(80))
    storage_key: Mapped[str] = mapped_column(String(80))
    media_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded")
    scan_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(ForeignKey("merchant_verification_documents.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MerchantVerificationEvent(Base):
    """Journal append-only des actions, sans données documentaires ni personnelles."""
    __tablename__ = "merchant_verification_events"
    __table_args__ = (
        Index("ix_merchant_verification_event_case_created", "case_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("merchant_verification_cases.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str | None] = mapped_column(ForeignKey("merchant_verification_documents.id"), nullable=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    verification_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verification_result: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    requested_requirement_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderResolutionRequest(Base):
    __tablename__ = "order_resolution_requests"
    __table_args__ = (
        CheckConstraint("requester_role IN ('customer', 'merchant')", name="ck_order_resolution_request_role"),
        CheckConstraint(
            "request_type IN ('client_cancellation', 'client_claim', 'merchant_cancellation')",
            name="ck_order_resolution_request_type",
        ),
        CheckConstraint("status IN ('submitted', 'approved', 'rejected', 'resolution_requested')", name="ck_order_resolution_request_status"),
        CheckConstraint("length(reason) > 0 AND length(description) > 0", name="ck_order_resolution_request_justification"),
        Index("ix_order_resolution_requests_order_status", "order_id", "status"),
        Index(
            "uq_order_resolution_open_requester",
            "order_id",
            "requester_id",
            unique=True,
            sqlite_where=text("status = 'submitted'"),
            postgresql_where=text("status = 'submitted'"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    requester_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    requester_role: Mapped[str] = mapped_column(String(20))
    request_type: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="submitted", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PickupVerification(Base):
    __tablename__ = "pickup_verifications"
    __table_args__ = (
        ForeignKeyConstraint(["order_id", "customer_id"], ["orders.id", "orders.customer_id"],
                             name="fk_pickup_verifications_order_customer"),
        UniqueConstraint("id", "order_id", "customer_id", "merchant_user_id", "method",
                         name="uq_pickup_verifications_identity"),
        CheckConstraint("method IN ('proximity', 'qr_fallback')", name="ck_pickup_verifications_method"),
        CheckConstraint("status IN ('pending', 'verified', 'expired', 'rejected')", name="ck_pickup_verifications_status"),
        CheckConstraint("length(token_hash) = 64", name="ck_pickup_verifications_hash"),
        CheckConstraint("expires_at > created_at", name="ck_pickup_verifications_expiry"),
        CheckConstraint("merchant_user_id IS NULL OR merchant_user_id != customer_id", name="ck_pickup_verifications_participants"),
        CheckConstraint(
            "(status = 'verified' AND merchant_user_id IS NOT NULL AND used_at IS NOT NULL "
            "AND used_at >= created_at AND used_at < expires_at) "
            "OR (status != 'verified' AND used_at IS NULL)",
            name="ck_pickup_verifications_usage",
        ),
        Index("uq_pickup_verifications_verified_order", "order_id", unique=True,
              sqlite_where=text("status = 'verified'"), postgresql_where=text("status = 'verified'")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    merchant_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    method: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint("rating >= 1 AND rating <= 5", name="ck_reviews_rating"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    cook_id: Mapped[str] = mapped_column(ForeignKey("cook_profiles.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FavoriteCook(Base):
    __tablename__ = "favorite_cooks"
    __table_args__ = (UniqueConstraint("user_id", "cook_id", name="uq_favorite_cook_user_cook"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    cook_id: Mapped[str] = mapped_column(ForeignKey("cook_profiles.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_payments_quantity"),
        CheckConstraint("amount_in_cents > 0", name="ck_payments_amount"),
        CheckConstraint("currency IN ('COP', 'XOF')", name="ck_payments_currency"),
        CheckConstraint("currency != 'XOF' OR amount_in_cents % 100 = 0", name="ck_payments_xof_integer"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"), unique=True, nullable=True)
    availability_id: Mapped[str | None] = mapped_column(ForeignKey("dish_availabilities.id"), index=True, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    amount_in_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    provider: Mapped[str] = mapped_column(String(30), default="payu")
    provider_transaction_id: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    provider_reference: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    provider_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    checkout_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checkout_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checkout_token_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_creation_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_action: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refund_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list[PaymentItem]] = relationship(order_by="PaymentItem.id")


class PaymentIdempotencyKey(Base):
    __tablename__ = "payment_idempotency_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "key_hash", name="uq_payment_idempotency_user_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PaymentItem(Base):
    __tablename__ = "payment_items"
    __table_args__ = (
        UniqueConstraint("payment_id", "availability_id", name="uq_payment_items_availability"),
        UniqueConstraint("payment_id", "dish_id", name="uq_payment_items_dish"),
        CheckConstraint("quantity > 0", name="ck_payment_items_quantity"),
        CheckConstraint("amount_in_cents > 0", name="ck_payment_items_amount"),
        CheckConstraint("(availability_id IS NULL) != (dish_id IS NULL)", name="ck_payment_items_single_item_reference"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    availability_id: Mapped[str | None] = mapped_column(ForeignKey("dish_availabilities.id"), nullable=True)
    dish_id: Mapped[str | None] = mapped_column(ForeignKey("dishes.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    amount_in_cents: Mapped[int] = mapped_column(Integer)
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"), unique=True, nullable=True)
    order_item_id: Mapped[str | None] = mapped_column(ForeignKey("order_items.id"), unique=True, nullable=True)


class StockHold(Base):
    __tablename__ = "stock_holds"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_holds_quantity"),
        Index("uq_stock_holds_payment_availability", "payment_id", "availability_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    availability_id: Mapped[str] = mapped_column(ForeignKey("dish_availabilities.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
