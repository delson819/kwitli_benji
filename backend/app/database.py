from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    database_url = get_settings().database_url
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def init_database() -> None:
    # Import en retard pour enregistrer tous les modeles avant l'inspection.
    from backend.app.persistence import models  # noqa: F401

    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not tables and not inspector.get_view_names():
        if engine.dialect.name != "sqlite" or get_settings().app_env.strip().lower() not in {"development", "test"}:
            raise RuntimeError("Base non initialisee : appliquer les migrations Alembic avant le demarrage.")
        Base.metadata.create_all(bind=engine)
        return

    # Une base existante (meme sans alembic_version) ne doit jamais recevoir de DDL
    # au startup. Alembic est responsable des evolutions de schema.
    missing = []
    for table in Base.metadata.tables.values():
        if table.name not in tables:
            missing.append(table.name)
            continue
        columns = {column["name"] for column in inspector.get_columns(table.name)}
        missing.extend(f"{table.name}.{column.name}" for column in table.columns if column.name not in columns)
    if missing:
        raise RuntimeError(
            "Schema existant incomplet : auditer puis appliquer les migrations Alembic avant le demarrage. "
            "Tables/colonnes manquantes : " + ", ".join(sorted(missing))
        )

    settings = get_settings()
    environment = settings.app_env.strip().lower()
    if environment in {"staging", "production", "prod"}:
        manifest_path = getattr(settings, "service_area_manifest_path", "").strip()
        if not manifest_path:
            raise RuntimeError("Démarrage refusé : manifeste de zones commerciales absent.")
        # The additive migration intentionally contains no market seed. Refuse
        # cutover until the target environment has been explicitly bootstrapped.
        from backend.app.service_area_bootstrap import (
            ServiceAreaBootstrapError,
            load_manifest,
            verify_runtime_manifest,
        )

        try:
            manifest = load_manifest(manifest_path)
            from sqlalchemy import text
            from sqlalchemy.orm import Session

            with Session(engine) as session:
                database_name = str(session.execute(text("SELECT current_database()")).scalar_one())
                verify_runtime_manifest(session, manifest, database_name)
        except ServiceAreaBootstrapError as exc:
            raise RuntimeError(f"Démarrage refusé : contrôle du manifeste des zones échoué ({exc}).") from None
        except Exception:
            raise RuntimeError("Démarrage refusé : manifeste de zones invalide ou base cible inaccessible.") from None


def get_db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
