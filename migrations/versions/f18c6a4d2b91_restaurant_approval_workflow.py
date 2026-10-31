"""Ajoute les statuts de validation des restaurants."""

from alembic import op
import sqlalchemy as sa


revision = "f18c6a4d2b91"
down_revision = "e7b4c12a9f60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cook_profiles",
        sa.Column("approval_status", sa.String(length=24), nullable=False, server_default="pending_review"),
    )
    op.add_column("cook_profiles", sa.Column("approval_reason", sa.Text(), nullable=True))
    op.add_column("cook_profiles", sa.Column("approval_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "cook_profiles",
        sa.Column("approval_reviewed_by", sa.String(length=36), nullable=True),
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("cook_profiles") as batch_op:
            batch_op.create_foreign_key(
                "fk_cook_profiles_approval_reviewed_by_users",
                "users",
                ["approval_reviewed_by"],
                ["id"],
            )
            batch_op.create_check_constraint(
                "ck_cook_profiles_approval_status",
                "approval_status IN ('draft', 'pending_review', 'approved', 'rejected', 'suspended')",
            )
    else:
        op.create_foreign_key(
            "fk_cook_profiles_approval_reviewed_by_users",
            "cook_profiles",
            "users",
            ["approval_reviewed_by"],
            ["id"],
        )
        op.create_check_constraint(
            "ck_cook_profiles_approval_status",
            "cook_profiles",
            "approval_status IN ('draft', 'pending_review', 'approved', 'rejected', 'suspended')",
        )
    op.execute(
        """
        UPDATE cook_profiles AS cp
        SET approval_status = CASE
            WHEN cp.is_verified THEN 'approved'
            WHEN lower(u.email) LIKE '%.invalid' THEN 'draft'
            ELSE 'pending_review'
        END
        FROM users AS u
        WHERE u.id = cp.user_id
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("cook_profiles") as batch_op:
            batch_op.drop_constraint("ck_cook_profiles_approval_status", type_="check")
            batch_op.drop_constraint("fk_cook_profiles_approval_reviewed_by_users", type_="foreignkey")
            batch_op.drop_column("approval_reviewed_by")
            batch_op.drop_column("approval_reviewed_at")
            batch_op.drop_column("approval_reason")
            batch_op.drop_column("approval_status")
    else:
        op.drop_constraint("ck_cook_profiles_approval_status", "cook_profiles", type_="check")
        op.drop_constraint("fk_cook_profiles_approval_reviewed_by_users", "cook_profiles", type_="foreignkey")
        op.drop_column("cook_profiles", "approval_reviewed_by")
        op.drop_column("cook_profiles", "approval_reviewed_at")
        op.drop_column("cook_profiles", "approval_reason")
        op.drop_column("cook_profiles", "approval_status")
