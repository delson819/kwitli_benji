"""Le startup ne migre jamais implicitement une base persistante."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app import database
from backend.app.persistence import models  # noqa: F401


@pytest.fixture
def startup_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'startup.db'}")
    monkeypatch.setattr(database, "get_engine", lambda: engine)
    monkeypatch.setattr(database, "get_settings", lambda: SimpleNamespace(app_env="test"))
    yield engine
    engine.dispose()


def schema_snapshot(engine):
    with engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
        ).all()


@pytest.mark.parametrize("environment", ["development", "test"])
def test_empty_dev_test_database_initialized_once(startup_db, monkeypatch, environment):
    monkeypatch.setattr(database, "get_settings", lambda: SimpleNamespace(app_env=environment))
    database.init_database()
    assert set(database.Base.metadata.tables).issubset(inspect(startup_db).get_table_names())
    before = schema_snapshot(startup_db)

    def forbidden_create_all(*args, **kwargs):
        pytest.fail("create_all ne doit pas etre appele sur une base existante")

    monkeypatch.setattr(database.Base.metadata, "create_all", forbidden_create_all)
    database.init_database()
    assert schema_snapshot(startup_db) == before


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_non_dev_empty_database_requires_alembic(startup_db, monkeypatch, environment):
    monkeypatch.setattr(database, "get_settings", lambda: SimpleNamespace(app_env=environment))
    with pytest.raises(RuntimeError, match="Alembic"):
        database.init_database()
    assert inspect(startup_db).get_table_names() == []


@pytest.mark.parametrize("managed", [True, False])
def test_partial_database_never_receives_tables_or_columns(startup_db, managed):
    with startup_db.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO users VALUES ('existing')")
        if managed:
            connection.exec_driver_sql("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('e42b0c61af90')")
    before = schema_snapshot(startup_db)
    with pytest.raises(RuntimeError, match="Schema existant incomplet"):
        database.init_database()
    assert schema_snapshot(startup_db) == before
    with startup_db.connect() as connection:
        assert connection.exec_driver_sql("SELECT * FROM users").all() == [("existing",)]


def test_managed_database_stays_unchanged_until_explicit_migration(startup_db, monkeypatch):
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", str(startup_db.url))
    config = Config("alembic.ini")
    command.upgrade(config, "e42b0c61af90")
    before = schema_snapshot(startup_db)
    with pytest.raises(RuntimeError, match="orders.cook_id"):
        database.init_database()
    assert schema_snapshot(startup_db) == before
    assert "order_items" not in inspect(startup_db).get_table_names()
    command.upgrade(config, "head")
    before = schema_snapshot(startup_db)
    database.init_database()
    assert schema_snapshot(startup_db) == before


def test_version_table_alone_is_not_a_virgin_database(startup_db):
    with startup_db.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
    before = schema_snapshot(startup_db)
    with pytest.raises(RuntimeError, match="Schema existant incomplet"):
        database.init_database()
    assert schema_snapshot(startup_db) == before
