from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import Boolean, Column, Date, DateTime, JSON, MetaData, Numeric, String, Table, Time
from alembic.config import Config
from alembic.script import ScriptDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.database import Base
from backend.app import database
from backend.app.persistence import models  # noqa: F401
from scripts.migrate_sqlite_to_postgres import TABLE_ORDER, convert, ensure_private_kyb_files_migratable, require_local_postgres


def test_import_plan_covers_every_business_table():
    assert set(TABLE_ORDER) == set(Base.metadata.tables)


def test_service_area_migration_follows_local_kyb_revision():
    root = Path(__file__).resolve().parents[2]
    scripts = ScriptDirectory.from_config(Config(str(root / "alembic.ini")))
    revision = scripts.get_revision("c73e9f4a2b10")
    assert revision.down_revision == "ab71d9e4c205"


def test_sqlite_import_rejects_kyb_document_rows_without_private_blob_transfer():
    import sqlite3

    source = sqlite3.connect(":memory:")
    source.execute("CREATE TABLE merchant_verification_documents (id TEXT PRIMARY KEY)")
    source.execute("INSERT INTO merchant_verification_documents VALUES ('synthetic-id')")
    with pytest.raises(ValueError, match="fichiers KYB privés chiffrés"):
        ensure_private_kyb_files_migratable(source)
    source.close()


def test_sqlite_values_are_typed_for_postgres():
    table = Table(
        "sample", MetaData(),
        Column("created_at", DateTime(timezone=True)),
        Column("day", Date()), Column("hour", Time()),
        Column("active", Boolean()), Column("price", Numeric(12, 2)),
        Column("payload", JSON()), Column("name", String()),
    )
    assert convert("2026-10-09 10:15:30.123456", table.c.created_at) == datetime(
        2026, 10, 9, 10, 15, 30, 123456, tzinfo=timezone.utc
    )
    assert convert("2026-10-09", table.c.day) == date(2026, 10, 9)
    assert convert("10:15:30", table.c.hour) == time(10, 15, 30)
    assert convert(1, table.c.active) is True
    assert convert(0, table.c.active) is False
    assert convert("4500.50", table.c.price) == Decimal("4500.50")
    assert convert('{"a": 1}', table.c.payload) == {"a": 1}
    assert convert(None, table.c.payload) is None
    assert convert("Cafe", table.c.name) == "Cafe"


def test_invalid_boolean_and_remote_target_are_rejected():
    column = Table("sample", MetaData(), Column("active", Boolean())).c.active
    with pytest.raises(ValueError, match="Booleen SQLite invalide"):
        convert(2, column)
    with pytest.raises(ValueError, match="locale DEV"):
        require_local_postgres("postgresql+psycopg2://user@db.example.com/kwitli")
    with pytest.raises(ValueError, match="PostgreSQL"):
        require_local_postgres("sqlite:///kwitli.db")
    assert require_local_postgres(
        "postgresql+psycopg2:///kwitli_dev?host=/tmp&port=55433"
    ).database == "kwitli_dev"


def test_empty_postgres_requires_alembic_instead_of_create_all(monkeypatch):
    class EmptyInspector:
        def get_table_names(self):
            return []

        def get_view_names(self):
            return []

    monkeypatch.setattr(database, "get_engine", lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))
    monkeypatch.setattr(database, "inspect", lambda _engine: EmptyInspector())
    monkeypatch.setattr(database.Base.metadata, "create_all", lambda **_kwargs: pytest.fail("create_all interdit"))
    with pytest.raises(RuntimeError, match="Alembic"):
        database.init_database()
