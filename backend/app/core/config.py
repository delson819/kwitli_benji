from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Kwitli"
    app_version: str = "0.1.0"
    app_description: str = "API de commande hyperlocale pour les commerces alimentaires Kwitli."
    api_v1_prefix: str = "/api/v1"
    app_env: str = "development"
    app_debug: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    public_api_url: str = ""
    launch_country: str = "SN"
    ui_locale: str = "fr"
    currency: str = "XOF"
    # Dernier fallback configurable ; les marchés connus ont leur fuseau dans core.time.
    market_timezone: str = "UTC"
    database_url: str = "postgresql+psycopg2:///kwitli_dev?host=/tmp&port=55433"
    secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "kwitli-api"
    jwt_audience: str = "kwitli-mobile"
    access_token_expire_minutes: int = Field(default=60, ge=5, le=1440)
    password_reset_token_expire_minutes: int = Field(default=30, ge=5, le=120)
    resend_api_key: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
        validation_alias=AliasChoices("RESEND_API_KEY", "RESEND_API"),
    )
    resend_from_email: str = Field(
        default="Kwitli <noreply@mail.kwitli.app>",
        validation_alias="RESEND_FROM_EMAIL",
    )
    password_reset_app_url: str = "kwitli://reset-password"
    upload_max_bytes: int = 5 * 1024 * 1024
    upload_max_width: int = Field(default=4096, ge=1, le=16_384)
    upload_max_height: int = Field(default=4096, ge=1, le=16_384)
    upload_max_pixels: int = Field(default=12_000_000, ge=1, le=100_000_000)
    upload_dir: str = str(Path(__file__).resolve().parents[2] / "uploads")
    service_area_manifest_path: str = ""
    kyb_enabled: bool = False
    kyb_enforced_countries: str = ""
    kyb_private_storage_dir: str = "/var/lib/kwitli/kyb-private"
    kyb_encryption_key: SecretStr = Field(default=SecretStr(""), repr=False)
    kyb_encryption_keys: SecretStr = Field(default=SecretStr(""), repr=False)
    kyb_encryption_key_version: str = "v1"
    kyb_max_document_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024)
    kyb_clamdscan_path: str = "clamdscan"
    wompi_env: str = "sandbox"
    wompi_public_key: str = ""
    wompi_private_key: str = ""
    wompi_events_secret: str = ""
    wompi_integrity_secret: str = ""
    wompi_api_base_url: str = "https://sandbox.wompi.co/v1"
    payu_env: str = "sandbox"
    paydunya_mode: str = "sandbox"
    xof_payment_provider: Literal["flutterwave", "paytech", "paydunya"] = "flutterwave"
    flutterwave_env: Literal["test"] = "test"
    flutterwave_secret_key: str = Field(default="", repr=False)
    flutterwave_webhook_secret: str = Field(default="", repr=False)
    paytech_env: Literal["test"] = "test"
    paytech_api_key: str = Field(default="", repr=False)
    paytech_api_secret: str = Field(default="", repr=False)
    paydunya_master_key: str = Field(default="", repr=False)
    paydunya_private_key: str = Field(default="", repr=False)
    paydunya_token: str = Field(default="", repr=False)
    paydunya_test_customer_phone: str = Field(default="", repr=False)
    paydunya_test_customer_email: str = Field(default="", repr=False)
    paydunya_test_customer_password: str = Field(default="", repr=False)
    payu_api_login: str = ""
    payu_api_key: str = ""
    payu_merchant_id: str = ""
    payu_account_id: str = ""
    payu_public_key: str = ""
    payu_api_base_url: str = ""
    payu_checkout_url: str = "https://sandbox.checkout.payulatam.com/ppp-web-gateway-payu/"
    payment_hold_minutes: int = Field(default=10, ge=1)
    checkout_token_expire_minutes: int = Field(default=10, ge=1, le=15)
    max_active_holds_per_user: int = Field(default=3, ge=1, le=20)
    max_held_portions_per_user: int = Field(default=10, ge=1, le=100)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_login_requests: int = Field(default=5, ge=1)
    rate_limit_login_account_requests: int = Field(default=10, ge=1)
    rate_limit_password_reset_requests: int = Field(default=3, ge=1)
    rate_limit_register_requests: int = Field(default=10, ge=1)
    rate_limit_payment_requests: int = Field(default=10, ge=1)
    rate_limit_upload_requests: int = Field(default=10, ge=1)
    rate_limit_pickup_requests: int = Field(default=10, ge=1)
    rate_limit_review_requests: int = Field(default=10, ge=1)
    rate_limit_discover_requests: int = Field(default=60, ge=1)
    rate_limit_max_buckets: int = Field(default=10_000, ge=100)
    trusted_proxy_ips: str = "127.0.0.1,::1"

    @model_validator(mode="after")
    def validate_wompi_sandbox_keys(self) -> "Settings":
        environment = self.app_env.strip().lower()
        secret = self.secret_key.strip()
        placeholders = {
            "secret",
            "changeme",
            "change-me",
            "replace-me",
            "replace-with-a-long-random-secret",
            "your-secret-key",
        }
        if environment != "test" and (len(secret) < 32 or secret.lower() in placeholders):
            raise ValueError("SECRET_KEY doit contenir au moins 32 caracteres non factices.")
        if self.jwt_algorithm != "HS256":
            raise ValueError("JWT_ALGORITHM doit etre HS256.")
        if not self.jwt_issuer.strip() or not self.jwt_audience.strip():
            raise ValueError("JWT_ISSUER et JWT_AUDIENCE sont obligatoires.")
        if self.wompi_env != "sandbox":
            raise ValueError("Seul WOMPI_ENV=sandbox est autorise.")
        if self.wompi_public_key and not self.wompi_public_key.startswith("pub_test_"):
            raise ValueError("La cle publique Wompi Sandbox doit commencer par pub_test_.")
        if self.wompi_private_key and not self.wompi_private_key.startswith("prv_test_"):
            raise ValueError("La cle privee Wompi Sandbox doit commencer par prv_test_.")
        if self.payu_env != "sandbox":
            raise ValueError("Seul PAYU_ENV=sandbox est autorise.")
        if self.paydunya_mode != "sandbox":
            raise ValueError("Seul PAYDUNYA_MODE=sandbox est autorise.")
        if self.public_api_url and not self.public_api_url.startswith("https://"):
            raise ValueError("PUBLIC_API_URL doit utiliser HTTPS.")
        if self.kyb_enabled and (not (self.kyb_encryption_key.get_secret_value() or self.kyb_encryption_keys.get_secret_value())
                                 or not self.kyb_private_storage_dir):
            raise ValueError("KYB_ENABLED exige une clé de chiffrement et un stockage privé configurés.")
        return self

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_prefix="",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
