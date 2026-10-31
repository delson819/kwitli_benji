"""Autorise COP et XOF sans transformer les montants existants."""
from alembic import op
import sqlalchemy as sa

revision = "e42b0c61af90"
down_revision = "d35c092b1a74"
branch_labels = None
depends_on = None

TABLES = ("dishes", "orders", "payments")
INTEGER_CHECKS = {
    "dishes": "currency != 'XOF' OR price = CAST(price AS BIGINT)",
    "payments": "currency != 'XOF' OR amount_in_cents % 100 = 0",
}


def upgrade():
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_currency", type_="check")
            batch.create_check_constraint(f"ck_{table}_currency", "currency IN ('COP', 'XOF')")
            if table in INTEGER_CHECKS:
                batch.create_check_constraint(f"ck_{table}_xof_integer", INTEGER_CHECKS[table])


def downgrade():
    # Refuser avant toute modification : jamais convertir/supprimer des donnees XOF.
    for table in TABLES:
        if op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {table} WHERE currency = 'XOF'")).scalar():
            raise RuntimeError("Downgrade refuse : des donnees XOF existent.")
    for table in reversed(TABLES):
        with op.batch_alter_table(table) as batch:
            if table in INTEGER_CHECKS:
                batch.drop_constraint(f"ck_{table}_xof_integer", type_="check")
            batch.drop_constraint(f"ck_{table}_currency", type_="check")
            batch.create_check_constraint(f"ck_{table}_currency", "currency = 'COP'")
