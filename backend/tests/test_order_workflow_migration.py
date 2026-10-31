"""Migration additive testee sur une copie SQLite, sans acces a la base DEV."""
from pathlib import Path
import sqlite3
import sys

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.tests.test_order_foundation import seed_history, snapshot, temporary_engine

PREVIOUS = 'a74d2c93e018'
HEAD = 'b85e3d04f129'


def test_workflow_migration_on_copy_preserves_history(tmp_path, monkeypatch):
    source = temporary_engine(tmp_path)
    monkeypatch.setenv('ALEMBIC_DATABASE_URL', str(source.url))
    config = Config('alembic.ini')
    command.upgrade(config, PREVIOUS)
    seed_history(source)
    before = snapshot(source)
    path = tmp_path / 'working-copy.db'
    with sqlite3.connect(f'file:{source.url.database}?mode=ro', uri=True) as reader, sqlite3.connect(path) as writer:
        reader.backup(writer)
    copy = sa.create_engine(f'sqlite:///{path}')
    monkeypatch.setenv('ALEMBIC_DATABASE_URL', str(copy.url))
    command.upgrade(config, HEAD)
    with copy.connect() as conn:
        assert conn.scalar(sa.text('SELECT version_num FROM alembic_version')) == HEAD
        for table, (columns, rows) in before.items():
            assert conn.execute(sa.text(f"SELECT {','.join(columns)} FROM {table} ORDER BY id")).all() == rows
        assert conn.scalar(sa.text('SELECT COUNT(*) FROM orders WHERE in_progress_at IS NOT NULL')) == 0
        assert conn.exec_driver_sql('PRAGMA integrity_check').scalar() == 'ok'
        assert conn.exec_driver_sql('PRAGMA foreign_key_check').all() == []
    assert snapshot(source) == before
    command.downgrade(config, PREVIOUS)
    assert snapshot(copy) == before
    command.upgrade(config, HEAD)
    with copy.begin() as conn:
        conn.execute(sa.text("UPDATE orders SET in_progress_at='2026-09-25 10:00:00' WHERE id='COP-ready'"))
    with pytest.raises(RuntimeError, match='horodatages operationnels utilises'):
        command.downgrade(config, PREVIOUS)
    with copy.connect() as conn:
        assert conn.scalar(sa.text('SELECT version_num FROM alembic_version')) == HEAD
    copy.dispose()
    source.dispose()
