"""Autorise le checkout MVP par article sans stock date."""
from alembic import op
import sqlalchemy as sa


revision = "c2f4a8b19d30"
down_revision = "9a3e6d2f1c80"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("order_items") as batch:
        batch.alter_column(
            "availability_id", existing_type=sa.String(length=36), nullable=True,
        )

    with op.batch_alter_table("payments") as batch:
        batch.alter_column(
            "availability_id", existing_type=sa.String(length=36), nullable=True,
        )

    with op.batch_alter_table("payment_items") as batch:
        batch.alter_column(
            "availability_id", existing_type=sa.String(length=36), nullable=True,
        )
        batch.add_column(sa.Column("dish_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_payment_items_dish_id_dishes", "dishes", ["dish_id"], ["id"])
        batch.create_unique_constraint("uq_payment_items_dish", ["payment_id", "dish_id"])
        batch.create_check_constraint(
            "ck_payment_items_single_item_reference",
            "(availability_id IS NULL) != (dish_id IS NULL)",
        )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM payment_items WHERE dish_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Downgrade refuse: des PaymentItem utilisent le nouveau checkout par dish_id.")
    with op.batch_alter_table("payment_items") as batch:
        batch.drop_constraint("ck_payment_items_single_item_reference", type_="check")
        batch.drop_constraint("uq_payment_items_dish", type_="unique")
        batch.drop_constraint("fk_payment_items_dish_id_dishes", type_="foreignkey")
        batch.drop_column("dish_id")
        batch.alter_column("availability_id", existing_type=sa.String(length=36), nullable=False)
    with op.batch_alter_table("payments") as batch:
        batch.alter_column("availability_id", existing_type=sa.String(length=36), nullable=False)
    with op.batch_alter_table("order_items") as batch:
        batch.alter_column("availability_id", existing_type=sa.String(length=36), nullable=False)
