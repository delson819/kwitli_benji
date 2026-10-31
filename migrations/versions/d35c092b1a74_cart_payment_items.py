"""Lignes de panier sur le paiement PayU existant."""
from alembic import op
import sqlalchemy as sa

revision = "d35c092b1a74"
down_revision = "c912d44fd821"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("payment_id", sa.String(36), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("availability_id", sa.String(36), sa.ForeignKey("dish_availabilities.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("amount_in_cents", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.id"), unique=True),
        sa.UniqueConstraint("payment_id", "availability_id", name="uq_payment_items_availability"),
        sa.CheckConstraint("quantity > 0", name="ck_payment_items_quantity"),
        sa.CheckConstraint("amount_in_cents > 0", name="ck_payment_items_amount"),
    )
    op.create_index("ix_payment_items_payment_id", "payment_items", ["payment_id"])
    op.drop_index("ix_stock_holds_payment_id", table_name="stock_holds")
    op.create_index("ix_stock_holds_payment_id", "stock_holds", ["payment_id"], unique=False)
    op.create_index("uq_stock_holds_payment_availability", "stock_holds", ["payment_id", "availability_id"], unique=True)


def downgrade():
    # Refuser une perte de donnees si des paniers ont deja ete payes.
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM payment_items")):
        raise RuntimeError("Downgrade refuse: des lignes de paiement existent.")
    op.drop_index("uq_stock_holds_payment_availability", table_name="stock_holds")
    op.drop_index("ix_stock_holds_payment_id", table_name="stock_holds")
    op.create_index("ix_stock_holds_payment_id", "stock_holds", ["payment_id"], unique=True)
    op.drop_table("payment_items")
