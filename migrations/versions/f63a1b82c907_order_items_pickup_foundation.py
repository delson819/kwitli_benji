"""Socle additif OrderItem et preuve de retrait, sans activation des services."""
from decimal import Decimal
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "f63a1b82c907"
down_revision = "e42b0c61af90"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Refuser toute correction implicite d'un historique incoherent avant le DDL.
    orders = sa.table("orders", sa.column("id"), sa.column("quantity"),
                      sa.column("unit_price", sa.Numeric(12, 2)), sa.column("total_price", sa.Numeric(12, 2)))
    for row in bind.execute(sa.select(orders)).mappings():
        if row["total_price"] != (row["unit_price"] * row["quantity"]).quantize(Decimal("0.01")):
            raise RuntimeError("Migration refusee : total historique incompatible avec OrderItem.")
    if bind.scalar(sa.text("""SELECT COUNT(*) FROM orders o
        LEFT JOIN dish_availabilities a ON a.id = o.availability_id
        LEFT JOIN dishes d ON d.id = a.dish_id
        LEFT JOIN cook_profiles c ON c.id = d.cook_id
        WHERE a.id IS NULL OR d.id IS NULL OR c.id IS NULL""")):
        raise RuntimeError("Migration refusee : commande historique sans commerce/article valide.")

    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("cook_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("picked_up_by", sa.String(36), nullable=True))
        batch.add_column(sa.Column("pickup_method", sa.String(20), nullable=True))
        batch.add_column(sa.Column("pickup_verification_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_orders_cook", "cook_profiles", ["cook_id"], ["id"])
        batch.create_foreign_key("fk_orders_picked_up_by", "users", ["picked_up_by"], ["id"])
        batch.create_unique_constraint("uq_orders_customer", ["id", "customer_id"])
        batch.create_unique_constraint("uq_orders_pickup_verification", ["pickup_verification_id"])
        batch.create_check_constraint("ck_orders_pickup_method",
            "pickup_method IS NULL OR pickup_method IN ('proximity', 'qr_fallback', 'legacy_code')")
        batch.create_check_constraint("ck_orders_pickup_required",
            "status != 'picked_up' OR (picked_up_at IS NOT NULL AND picked_up_by IS NOT NULL "
            "AND pickup_method IS NOT NULL AND (pickup_method = 'legacy_code' "
            "OR pickup_verification_id IS NOT NULL))")
        batch.create_check_constraint("ck_orders_pickup_proof",
            "pickup_verification_id IS NULL OR (pickup_method IS NOT NULL "
            "AND pickup_method IN ('proximity', 'qr_fallback') AND picked_up_by IS NOT NULL)")
        batch.create_index("ix_orders_cook_id", ["cook_id"])

    op.create_table("order_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("availability_id", sa.String(36), sa.ForeignKey("dish_availabilities.id"), nullable=False),
        sa.Column("dish_id", sa.String(36), sa.ForeignKey("dishes.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("dish_name", sa.String(120), nullable=False),
        sa.Column("photo_url", sa.String(500), nullable=True),
        sa.UniqueConstraint("order_id", "availability_id", name="uq_order_items_availability"),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity"),
        sa.CheckConstraint("unit_price > 0", name="ck_order_items_unit_price"),
        sa.CheckConstraint("line_total > 0", name="ck_order_items_line_total"),
        sa.CheckConstraint("ROUND(line_total, 2) = ROUND(quantity * unit_price, 2)", name="ck_order_items_total"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_table("pickup_verifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("merchant_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id", "customer_id"], ["orders.id", "orders.customer_id"],
                                name="fk_pickup_verifications_order_customer"),
        sa.UniqueConstraint("id", "order_id", "customer_id", "merchant_user_id", "method",
                            name="uq_pickup_verifications_identity"),
        sa.CheckConstraint("method IN ('proximity', 'qr_fallback')", name="ck_pickup_verifications_method"),
        sa.CheckConstraint("status IN ('pending', 'verified', 'expired', 'rejected')", name="ck_pickup_verifications_status"),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_pickup_verifications_hash"),
        sa.CheckConstraint("expires_at > created_at", name="ck_pickup_verifications_expiry"),
        sa.CheckConstraint("merchant_user_id IS NULL OR merchant_user_id != customer_id", name="ck_pickup_verifications_participants"),
        sa.CheckConstraint("(status = 'verified' AND merchant_user_id IS NOT NULL AND used_at IS NOT NULL "
            "AND used_at >= created_at AND used_at < expires_at) OR (status != 'verified' AND used_at IS NULL)",
            name="ck_pickup_verifications_usage"),
    )
    op.create_index("ix_pickup_verifications_order_id", "pickup_verifications", ["order_id"])
    op.create_index("uq_pickup_verifications_verified_order", "pickup_verifications", ["order_id"], unique=True,
                    sqlite_where=sa.text("status = 'verified'"), postgresql_where=sa.text("status = 'verified'"))
    with op.batch_alter_table("orders") as batch:
        batch.create_foreign_key("fk_orders_pickup_verification", "pickup_verifications",
            ["pickup_verification_id", "id", "customer_id", "picked_up_by", "pickup_method"],
            ["id", "order_id", "customer_id", "merchant_user_id", "method"])

    bind.execute(sa.text("""UPDATE orders SET cook_id = (
        SELECT d.cook_id FROM dish_availabilities a JOIN dishes d ON d.id = a.dish_id
        WHERE a.id = orders.availability_id)"""))
    # Aucun acteur/proof invente. Le statut et la date legacy restent inchanges.
    bind.execute(sa.text("""UPDATE orders SET pickup_method = 'legacy_code', picked_up_at = completed_at
        WHERE status = 'completed'"""))
    # Nom/photo disponibles a la migration, prix historique provenant exclusivement de l'Order.
    rows = bind.execute(sa.text("""SELECT o.id AS order_id, o.availability_id, a.dish_id,
        o.quantity, o.unit_price, o.total_price AS line_total, d.name AS dish_name, d.photo_url
        FROM orders o JOIN dish_availabilities a ON a.id = o.availability_id
        JOIN dishes d ON d.id = a.dish_id""")).mappings()
    for row in rows:
        bind.execute(sa.text("""INSERT INTO order_items
            (id, order_id, availability_id, dish_id, quantity, unit_price, line_total, dish_name, photo_url)
            VALUES (:id, :order_id, :availability_id, :dish_id, :quantity, :unit_price, :line_total, :dish_name, :photo_url)"""),
            {"id": str(uuid4()), **row})
    if bind.scalar(sa.text("SELECT COUNT(*) FROM orders")) != bind.scalar(sa.text("SELECT COUNT(*) FROM order_items")):
        raise RuntimeError("Migration refusee : backfill OrderItem incomplet.")


def downgrade():
    # Aucun retrait de colonnes/tables si cela supprimerait des informations.
    bind = op.get_bind()
    if (bind.scalar(sa.text("SELECT COUNT(*) FROM order_items"))
            or bind.scalar(sa.text("SELECT COUNT(*) FROM pickup_verifications"))
            or bind.scalar(sa.text("""SELECT COUNT(*) FROM orders WHERE cook_id IS NOT NULL
                OR picked_up_at IS NOT NULL OR picked_up_by IS NOT NULL OR pickup_method IS NOT NULL
                OR pickup_verification_id IS NOT NULL OR status = 'picked_up'"""))):
        raise RuntimeError("Downgrade refuse : donnees OrderItem/retrait presentes.")
    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint("fk_orders_pickup_verification", type_="foreignkey")
    op.drop_table("pickup_verifications")
    op.drop_table("order_items")
    with op.batch_alter_table("orders") as batch:
        for name in ("ck_orders_pickup_method", "ck_orders_pickup_required", "ck_orders_pickup_proof"):
            batch.drop_constraint(name, type_="check")
        for name in ("uq_orders_customer", "uq_orders_pickup_verification"):
            batch.drop_constraint(name, type_="unique")
        for name in ("fk_orders_cook", "fk_orders_picked_up_by"):
            batch.drop_constraint(name, type_="foreignkey")
        batch.drop_index("ix_orders_cook_id")
        for name in ("cook_id", "picked_up_at", "picked_up_by", "pickup_method", "pickup_verification_id"):
            batch.drop_column(name)
