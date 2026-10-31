"""Ajoute les demandes de resolution et le marqueur admin."""
from alembic import op
import sqlalchemy as sa


revision = "4c1a7f9e2b63"
down_revision = "3f9a2b7c1d6e"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "order_resolution_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("order_id", sa.String(length=36), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("requester_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requester_role", sa.String(length=20), nullable=False),
        sa.Column("request_type", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="submitted"),
        sa.Column("reviewed_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("requester_role IN ('customer', 'merchant')", name="ck_order_resolution_request_role"),
        sa.CheckConstraint(
            "request_type IN ('client_cancellation', 'client_claim', 'merchant_cancellation')",
            name="ck_order_resolution_request_type",
        ),
        sa.CheckConstraint(
            "status IN ('submitted', 'approved', 'rejected', 'resolution_requested')",
            name="ck_order_resolution_request_status",
        ),
        sa.CheckConstraint("length(reason) > 0 AND length(description) > 0", name="ck_order_resolution_request_justification"),
    )
    op.create_index("ix_order_resolution_requests_order_id", "order_resolution_requests", ["order_id"])
    op.create_index("ix_order_resolution_requests_requester_id", "order_resolution_requests", ["requester_id"])
    op.create_index("ix_order_resolution_requests_status", "order_resolution_requests", ["status"])
    op.create_index(
        "ix_order_resolution_requests_order_status",
        "order_resolution_requests",
        ["order_id", "status"],
    )
    op.create_index(
        "uq_order_resolution_open_requester",
        "order_resolution_requests",
        ["order_id", "requester_id"],
        unique=True,
        sqlite_where=sa.text("status = 'submitted'"),
        postgresql_where=sa.text("status = 'submitted'"),
    )


def downgrade():
    op.drop_index("uq_order_resolution_open_requester", table_name="order_resolution_requests")
    op.drop_index("ix_order_resolution_requests_order_status", table_name="order_resolution_requests")
    op.drop_index("ix_order_resolution_requests_status", table_name="order_resolution_requests")
    op.drop_index("ix_order_resolution_requests_requester_id", table_name="order_resolution_requests")
    op.drop_index("ix_order_resolution_requests_order_id", table_name="order_resolution_requests")
    op.drop_table("order_resolution_requests")
    op.drop_column("users", "is_admin")
