"""Permet une Order multi-lignes sans reutiliser les liens legacy."""
from alembic import op
import sqlalchemy as sa

revision = "a74d2c93e018"
down_revision = "f63a1b82c907"
branch_labels = None
depends_on = None

LEGACY_COLUMNS = {
    "availability_id": sa.String(36),
    "quantity": sa.Integer(),
    "unit_price": sa.Numeric(12, 2),
    "pickup_code": sa.String(6),
}


def upgrade():
    with op.batch_alter_table("orders") as batch:
        for name, column_type in LEGACY_COLUMNS.items():
            batch.alter_column(name, existing_type=column_type, nullable=True)
    with op.batch_alter_table("payment_items") as batch:
        batch.add_column(sa.Column("order_item_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_payment_items_order_item", "order_items", ["order_item_id"], ["id"])
        batch.create_unique_constraint("uq_payment_items_order_item", ["order_item_id"])


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT COUNT(*) FROM payment_items WHERE order_item_id IS NOT NULL")):
        raise RuntimeError("Downgrade refuse : liens OrderItem utilises.")
    if bind.scalar(sa.text("SELECT COUNT(*) FROM orders WHERE availability_id IS NULL OR quantity IS NULL "
                           "OR unit_price IS NULL OR pickup_code IS NULL OR status = 'ordered'")):
        raise RuntimeError("Downgrade refuse : commandes multi-lignes presentes.")
    with op.batch_alter_table("payment_items") as batch:
        batch.drop_constraint("fk_payment_items_order_item", type_="foreignkey")
        batch.drop_constraint("uq_payment_items_order_item", type_="unique")
        batch.drop_column("order_item_id")
    with op.batch_alter_table("orders") as batch:
        for name, column_type in LEGACY_COLUMNS.items():
            batch.alter_column(name, existing_type=column_type, nullable=False)
