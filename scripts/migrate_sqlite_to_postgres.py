"""Copie transactionnelle de la base DEV SQLite vers un schema PostgreSQL migre."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, Date, DateTime, Integer, JSON, MetaData, Numeric, Table, Time, create_engine, func, inspect, select, text, update
from sqlalchemy.engine import Connection, URL, make_url


ROOT = Path(__file__).resolve().parents[1]
# Ordre des dependances FK. Order et PickupVerification forment un cycle,
# traite en deux passes dans la meme transaction.
TABLE_ORDER = (
    "users",
    "service_area_configs",
    "service_area_events",
    "password_reset_tokens",
    "cook_profiles",
    "cook_profile_hours",
    "merchant_verification_cases",
    "merchant_verification_documents",
    "merchant_verification_events",
    "dishes",
    "dish_availabilities",
    "orders",
    "order_messages",
    "order_resolution_requests",
    "order_items",
    "pickup_verifications",
    "payments",
    "payment_idempotency_keys",
    "payment_items",
    "stock_holds",
    "reviews",
    "favorite_cooks",
)


def require_local_postgres(raw_url: str) -> URL:
    url = make_url(raw_url)
    if url.drivername not in {"postgresql", "postgresql+psycopg2"}:
        raise ValueError("La cible doit etre PostgreSQL avec le pilote psycopg2.")
    host = url.host or url.query.get("host")
    if host not in {None, "localhost", "127.0.0.1", "::1", "/tmp", "/private/tmp"}:
        raise ValueError("Seule une instance PostgreSQL locale DEV est autorisee.")
    if not url.database:
        raise ValueError("Le nom de la base PostgreSQL est obligatoire.")
    return url


def current_head() -> str:
    heads = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_heads()
    if len(heads) != 1:
        raise ValueError("Alembic doit posseder une seule revision HEAD.")
    return heads[0]


def source_fingerprint(path: Path) -> tuple[tuple[int, int] | None, ...]:
    result = []
    for candidate in (path, Path(f"{path}-wal")):
        stat = candidate.stat() if candidate.exists() else None
        result.append((stat.st_size, stat.st_mtime_ns) if stat else None)
    return tuple(result)


def convert(value: object, column) -> object:
    if value is None:
        return None
    kind = column.type
    if isinstance(kind, DateTime):
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    if isinstance(kind, Date):
        return value if isinstance(value, date) else date.fromisoformat(str(value))
    if isinstance(kind, Time):
        return value if isinstance(value, time) else time.fromisoformat(str(value))
    if isinstance(kind, Boolean):
        if value not in (0, 1, False, True):
            raise ValueError(f"Booleen SQLite invalide dans {column.table.name}.{column.name}.")
        return bool(value)
    if isinstance(kind, Numeric):
        return Decimal(str(value))
    if isinstance(kind, JSON):
        return json.loads(value) if isinstance(value, str) else value
    return value


def normalized(value: object, column) -> object:
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        return convert(value, column)
    if isinstance(column.type, Numeric):
        return Decimal(str(value))
    return value


def sqlite_table_names(source: sqlite3.Connection) -> set[str]:
    return {
        row[0] for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def ensure_private_kyb_files_migratable(source: sqlite3.Connection) -> None:
    document_count = source.execute(
        'SELECT COUNT(*) FROM "merchant_verification_documents"'
    ).fetchone()[0]
    if document_count:
        raise ValueError(
            "Import SQLite refuse : les fichiers KYB privés chiffrés doivent être transférés et vérifiés séparément."
        )


def check_schema(source: sqlite3.Connection, target: Connection, tables: dict[str, Table]) -> None:
    expected = set(TABLE_ORDER) | {"alembic_version"}
    if sqlite_table_names(source) != expected or set(tables) != expected:
        raise ValueError("Tables source/cible differentes du schema attendu; import refuse.")
    ensure_private_kyb_files_migratable(source)
    head = current_head()
    source_version = source.execute("SELECT version_num FROM alembic_version").fetchone()
    target_version = target.execute(text("SELECT version_num FROM alembic_version")).first()
    if source_version is None or source_version[0] != head or target_version is None or target_version[0] != head:
        raise ValueError("SQLite et PostgreSQL doivent etre migres au meme HEAD Alembic avant l'import.")
    for name in TABLE_ORDER:
        source_columns = {row[1] for row in source.execute(f'PRAGMA table_info("{name}")')}
        target_columns = set(tables[name].columns.keys())
        if source_columns != target_columns:
            raise ValueError(f"Colonnes incompatibles pour {name}.")
        if "id" not in target_columns:
            raise ValueError(f"Cle primaire id absente de {name}.")


def compare_all(source: sqlite3.Connection, target: Connection, tables: dict[str, Table]) -> dict[str, int]:
    counts = {}
    for name in TABLE_ORDER:
        table = tables[name]
        source_rows = source.execute(f'SELECT * FROM "{name}" ORDER BY id').fetchall()
        target_rows = target.execute(select(table).order_by(table.c.id)).mappings().all()
        if len(source_rows) != len(target_rows):
            raise ValueError(f"Nombre de lignes different pour {name}: {len(source_rows)} / {len(target_rows)}.")
        for before, after in zip(source_rows, target_rows, strict=True):
            for column in table.columns:
                expected = convert(before[column.name], column)
                actual = normalized(after[column.name], column)
                if expected != actual:
                    raise ValueError(f"Valeur ou identifiant different dans {name}, colonne {column.name}.")
        counts[name] = len(source_rows)
    invalid_constraints = target.scalar(text("""
        SELECT count(*) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = current_schema() AND c.contype = 'f' AND NOT c.convalidated
    """))
    if invalid_constraints:
        raise ValueError("Une contrainte FK PostgreSQL n'est pas validee.")
    return counts


def reset_sequences(target: Connection, tables: dict[str, Table]) -> None:
    for name in TABLE_ORDER:
        table = tables[name]
        for column in table.primary_key.columns:
            if not isinstance(column.type, Integer):
                continue
            sequence = target.scalar(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": name, "column_name": column.name},
            )
            if sequence:
                highest = target.scalar(select(func.max(column)))
                target.execute(
                    text("SELECT setval(:sequence, :value, :is_called)"),
                    {"sequence": sequence, "value": highest if highest is not None else 1,
                     "is_called": highest is not None},
                )


def import_data(source: sqlite3.Connection, target: Connection, tables: dict[str, Table]) -> None:
    # Le verrou empeche qu'un backend ecrive pendant la comparaison et l'import.
    for name in TABLE_ORDER:
        target.exec_driver_sql(f'LOCK TABLE "{name}" IN SHARE ROW EXCLUSIVE MODE')
    counts = {name: target.scalar(select(func.count()).select_from(tables[name])) for name in TABLE_ORDER}
    if any(counts.values()):
        compare_all(source, target, tables)
        print("Import deja present et identique; aucune insertion.")
        return

    deferred_orders = []
    for name in TABLE_ORDER:
        table = tables[name]
        for row in source.execute(f'SELECT * FROM "{name}" ORDER BY id'):
            values = {column.name: convert(row[column.name], column) for column in table.columns}
            if name == "orders" and values["pickup_verification_id"] is not None:
                deferred_orders.append((values["id"], values["status"], values["pickup_verification_id"]))
                values["status"] = "ready"
                values["pickup_verification_id"] = None
            target.execute(table.insert().values(**values))
    for order_id, status, verification_id in deferred_orders:
        target.execute(
            update(tables["orders"]).where(tables["orders"].c.id == order_id).values(
                status=status, pickup_verification_id=verification_id
            )
        )
    reset_sequences(target, tables)
    target.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")


def run(sqlite_path: Path, postgres_url: str, *, apply: bool) -> dict[str, int]:
    sqlite_path = sqlite_path.resolve(strict=True)
    if not sqlite_path.is_file():
        raise ValueError("La source SQLite doit etre un fichier existant.")
    url = require_local_postgres(postgres_url)
    fingerprint = source_fingerprint(sqlite_path)
    source = sqlite3.connect(f"{sqlite_path.as_uri()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    engine = create_engine(url)
    try:
        source.execute("PRAGMA query_only=ON")
        source.execute("BEGIN")
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("PRAGMA integrity_check SQLite a echoue.")
        if source.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("PRAGMA foreign_key_check SQLite a echoue.")
        with engine.begin() as target:
            target.exec_driver_sql("SET LOCAL TIME ZONE 'UTC'")
            metadata = MetaData()
            metadata.reflect(bind=target)
            tables = metadata.tables
            check_schema(source, target, tables)
            if apply:
                import_data(source, target, tables)
                counts = compare_all(source, target, tables)
            else:
                counts = {name: source.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                          for name in TABLE_ORDER}
            if source_fingerprint(sqlite_path) != fingerprint:
                raise ValueError("SQLite a change pendant l'import; transaction PostgreSQL annulee.")
        if apply:
            with engine.connect() as target:
                target.exec_driver_sql("SET TIME ZONE 'UTC'")
                compare_all(source, target, tables)
        return counts
    finally:
        source.close()
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=ROOT / "kwitli.db")
    parser.add_argument("--postgres-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--apply", action="store_true", help="Importer; par defaut audit en lecture seule.")
    args = parser.parse_args()
    if not args.postgres_url:
        parser.error("--postgres-url ou DATABASE_URL est obligatoire")
    counts = run(args.sqlite, args.postgres_url, apply=args.apply)
    for name, count in counts.items():
        print(f"{name}: {count}")
    print("Import et verification termines." if args.apply else "Audit termine; aucune donnee importee.")


if __name__ == "__main__":
    main()
