"""Ajoute les cles d'idempotence et l'etat de reprise des paiements."""
from alembic import op
import sqlalchemy as sa


revision = "6d2f81a4c970"
down_revision = "f18c6a4d2b91"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("payments", sa.Column("idempotency_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("payments", sa.Column("idempotency_group", sa.String(length=64), nullable=True))
    op.add_column("payments", sa.Column("provider_creation_state", sa.String(length=20), nullable=True))
    op.add_column("payments", sa.Column("provider_action", sa.JSON(), nullable=True))
    op.create_table(
        "payment_idempotency_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("payment_id", sa.String(length=36), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "key_hash", name="uq_payment_idempotency_user_key"),
    )
    op.create_index("ix_payment_idempotency_keys_payment_id", "payment_idempotency_keys", ["payment_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM payment_idempotency_keys")):
        raise RuntimeError("Downgrade refuse : des cles d'idempotence sont utilisees.")
    op.drop_index("ix_payment_idempotency_keys_payment_id", table_name="payment_idempotency_keys")
    op.drop_table("payment_idempotency_keys")
    op.drop_column("payments", "provider_action")
    op.drop_column("payments", "provider_creation_state")
    op.drop_column("payments", "idempotency_group")
    op.drop_column("payments", "idempotency_fingerprint")
