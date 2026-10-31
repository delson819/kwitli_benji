from ipaddress import ip_interface
from collections.abc import Generator
from datetime import datetime, timezone
from io import BytesIO
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

EXPECTED_TEST_SCHEMA_REVISION = "c73e9f4a2b10"


def _postgres_server_ip(value: str):
    """Convert PostgreSQL's inet text (including its host prefix) to an IP."""
    return ip_interface(value).ip


class PaymentKeyTestClient(TestClient):
    """Les tests historiques simulent une nouvelle tentative sauf clé explicite."""

    def post(self, url, *args, **kwargs):
        if str(url).split("?", 1)[0].rstrip("/") == "/api/v1/payments":
            headers = dict(kwargs.get("headers") or {})
            if not any(name.lower() == "idempotency-key" for name in headers):
                headers["Idempotency-Key"] = f"test-attempt:{uuid4()}"
            kwargs["headers"] = headers
        return super().post(url, *args, **kwargs)

    def post_without_payment_key(self, url, *args, **kwargs):
        return super().post(url, *args, **kwargs)


def _validated_test_database_url(value: str | None) -> str:
    if not value:
        raise pytest.UsageError("TEST_DATABASE_URL est obligatoire; utilisez uniquement PostgreSQL kwitli_test.")
    try:
        url = make_url(value)
    except Exception as exc:
        raise pytest.UsageError("TEST_DATABASE_URL est invalide.") from exc
    query = dict(url.query)
    socket_host = query.get("host")
    explicit_loopback_host = url.host in {"localhost", "127.0.0.1", "::1"} and socket_host is None
    explicit_local_socket = url.host is None and socket_host == "/tmp"
    query_port = query.get("port")
    configured_port = url.port or query_port
    try:
        port_is_explicit_and_valid = (
            configured_port is not None
            and 1 <= int(configured_port) <= 65535
            and (url.port is None or query_port is None or int(url.port) == int(query_port))
        )
    except (TypeError, ValueError):
        port_is_explicit_and_valid = False
    if (url.get_backend_name() != "postgresql" or url.database != "kwitli_test"
            or not (explicit_loopback_host or explicit_local_socket)
            or not port_is_explicit_and_valid
            or set(query) - {"host", "port"}):
        raise pytest.UsageError(
            "Tests refusés : TEST_DATABASE_URL doit cibler explicitement PostgreSQL local, "
            "avec port explicite et base kwitli_test exactement."
        )
    return value


def pytest_configure():
    test_database_url = _validated_test_database_url(os.environ.get("TEST_DATABASE_URL"))
    os.environ["DATABASE_URL"] = test_database_url
    os.environ["ALEMBIC_DATABASE_URL"] = test_database_url
    os.environ["APP_ENV"] = "test"
    # Les tests ne doivent jamais utiliser les clés du .env local.
    os.environ["RESEND_API_KEY"] = ""
    os.environ["RESEND_API"] = ""


@pytest.fixture(autouse=True)
def clean_postgres_test_database():
    """Isole chaque test en vidant exclusivement PostgreSQL kwitli_test."""
    from backend.app.database import Base
    from backend.app.persistence import models  # noqa: F401

    database_url = _validated_test_database_url(os.environ.get("TEST_DATABASE_URL"))
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            database_name, schema_name, server_address = connection.execute(text(
                "SELECT current_database(), current_schema(), inet_server_addr()::text"
            )).one()
            if database_name != "kwitli_test" or schema_name != "public":
                raise pytest.UsageError(
                    "Tests refusés : la connexion effective doit viser kwitli_test.public."
                )
            parsed_url = make_url(database_url)
            if parsed_url.query.get("host") == "/tmp":
                if server_address is not None:
                    raise pytest.UsageError("Tests refusés : le socket PostgreSQL effectif est inattendu.")
            else:
                try:
                    server_ip = _postgres_server_ip(server_address) if server_address is not None else None
                    if server_ip is None or not server_ip.is_loopback:
                        raise pytest.UsageError("Tests refusés : le serveur PostgreSQL effectif n'est pas local.")
                except ValueError as exc:
                    raise pytest.UsageError("Tests refusés : adresse PostgreSQL effective invalide.") from exc

            tables = set(connection.exec_driver_sql(
                "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
            ).scalars())
            if "alembic_version" not in tables:
                raise pytest.UsageError("kwitli_test doit être migrée avec Alembic avant pytest.")
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
            if revision != EXPECTED_TEST_SCHEMA_REVISION:
                raise pytest.UsageError(
                    f"Schéma kwitli_test à {revision!r}; appliquer Alembic jusqu'à {EXPECTED_TEST_SCHEMA_REVISION}."
                )
            app_tables = sorted(table.name for table in Base.metadata.sorted_tables if table.name in tables)
            if app_tables:
                quoted = ", ".join(f'"{name}"' for name in app_tables)
                connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
            # Synthetic legacy-compatible markets exist only in the disposable
            # test database. There are intentionally no migration seed rows.
            if "service_area_configs" in tables:
                now = datetime.now(timezone.utc)
                for values in (
                    ("legacy-bogota-test", "test", "CO-BOG-TEST", "Synthetic test area", "CO", "Testland", "Test City", 4.65, -74.06, 30, "America/Bogota", "es-CO", "COP"),
                    ("sn-dakar", "test", "SN-DKR", "Dakar, Sénégal", "SN", "Sénégal", "Dakar", 14.7167, -17.4677, 30, "Africa/Dakar", "fr", "XOF"),
                    ("ca-sherbrooke-dev", "test", "CA-SHERBROOKE-DEV", "Sherbrooke, Canada (DEV)", "CA", "Canada", "Sherbrooke", 45.4042, -71.8929, 30, "America/Toronto", "fr-CA", "CAD"),
                ):
                    connection.execute(text("""
                        INSERT INTO service_area_configs
                        (row_id, area_id, environment, code, label, country_code, country, city,
                         center_latitude, center_longitude, radius_km, geometry_type, geometry_metadata,
                         timezone, locale, currency, distance_unit, status, version, created_at, updated_at)
                        VALUES
                        (:row_id, :area_id, :environment, :code, :label, :country_code, :country, :city,
                         :latitude, :longitude, :radius, 'circle', NULL,
                         :timezone, :locale, :currency, 'km', 'active', 1, :created_at, :updated_at)
                    """), {
                        "row_id": str(uuid4()), "area_id": values[0], "environment": values[1],
                        "code": values[2], "label": values[3], "country_code": values[4],
                        "country": values[5], "city": values[6], "latitude": values[7],
                        "longitude": values[8], "radius": values[9], "timezone": values[10],
                        "locale": values[11], "currency": values[12], "created_at": now, "updated_at": now,
                    })
        yield
        with engine.begin() as connection:
            tables = set(connection.exec_driver_sql(
                "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
            ).scalars())
            app_tables = sorted(table.name for table in Base.metadata.sorted_tables if table.name in tables)
            if app_tables:
                quoted = ", ".join(f'"{name}"' for name in app_tables)
                connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    finally:
        engine.dispose()


@pytest.fixture
def image_bytes():
    def build(image_format: str = "JPEG", size: tuple[int, int] = (24, 24), *, with_exif: bool = False) -> bytes:
        output = BytesIO()
        image = Image.new("RGB", size, color=(230, 120, 40))
        options = {}
        if with_exif:
            metadata = Image.Exif()
            metadata[0x010E] = "metadata that must be removed"
            options["exif"] = metadata
        image.save(output, format=image_format, **options)
        return output.getvalue()

    return build


@pytest.fixture
def client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    database_url = _validated_test_database_url(os.environ.get("TEST_DATABASE_URL"))
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SECRET_KEY", "test-only-secret-key-with-enough-length")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("PUBLIC_API_URL", "https://public-test.example")
    monkeypatch.setenv("PAYU_API_LOGIN", "test-login")
    monkeypatch.setenv("PAYU_API_KEY", "test-api-key")
    monkeypatch.setenv("PAYU_MERCHANT_ID", "test-merchant")
    monkeypatch.setenv("PAYU_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("PAYU_CHECKOUT_URL", "https://sandbox.checkout.payulatam.com/ppp-web-gateway-payu/")
    monkeypatch.setenv("PAYU_API_BASE_URL", "https://sandbox.api.payulatam.com/payments-api/4.0/service.cgi")
    # Aucun test ne doit heriter des credentials PayDunya reels du .env local.
    monkeypatch.setenv("PAYDUNYA_MODE", "sandbox")
    monkeypatch.setenv("XOF_PAYMENT_PROVIDER", "flutterwave")
    monkeypatch.setenv("FLUTTERWAVE_ENV", "test")
    monkeypatch.setenv("FLUTTERWAVE_SECRET_KEY", "")
    monkeypatch.setenv("FLUTTERWAVE_WEBHOOK_SECRET", "")
    monkeypatch.setenv("PAYTECH_ENV", "test")
    monkeypatch.setenv("PAYTECH_API_KEY", "")
    monkeypatch.setenv("PAYTECH_API_SECRET", "")
    for name in ("MASTER_KEY", "PRIVATE_KEY", "TOKEN", "TEST_CUSTOMER_PHONE", "TEST_CUSTOMER_EMAIL", "TEST_CUSTOMER_PASSWORD"):
        monkeypatch.setenv(f"PAYDUNYA_{name}", "")

    from backend.app.core.config import get_settings
    from backend.app.database import get_engine, get_session_factory

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    from backend.app.main import create_app

    with PaymentKeyTestClient(create_app()) as test_client:
        yield test_client

    get_session_factory().kw["bind"].dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()
