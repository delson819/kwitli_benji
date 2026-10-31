"""Ajoute les messages prives lies aux commandes."""
from alembic import op
import sqlalchemy as sa


revision = "9a3e6d2f1c80"
down_revision = "4c1a7f9e2b63"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "order_messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("sender_role", sa.String(length=20), nullable=False),
        sa.Column("body", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sender_role IN ('customer', 'merchant')", name="ck_order_messages_sender_role"),
        sa.CheckConstraint("length(trim(body)) > 0 AND length(body) <= 1000", name="ck_order_messages_body"),
    )
    op.create_index("ix_order_messages_order_id", "order_messages", ["order_id"])
    op.create_index("ix_order_messages_sender_id", "order_messages", ["sender_id"])
    op.create_index("ix_order_messages_order_created", "order_messages", ["order_id", "created_at", "id"])


def downgrade():
    op.drop_index("ix_order_messages_order_created", table_name="order_messages")
    op.drop_index("ix_order_messages_sender_id", table_name="order_messages")
    op.drop_index("ix_order_messages_order_id", table_name="order_messages")
    op.drop_table("order_messages")
