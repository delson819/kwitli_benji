"""Ajoute les horaires hebdomadaires aux fiches commerce."""
from alembic import op
import sqlalchemy as sa


revision = "e7b4c12a9f60"
down_revision = "c2f4a8b19d30"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cook_profile_hours",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("cook_profile_id", sa.String(length=36), sa.ForeignKey("cook_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False),
        sa.Column("opens_at", sa.Time(), nullable=True),
        sa.Column("closes_at", sa.Time(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_cook_profile_hours_weekday"),
        sa.CheckConstraint(
            "(is_closed AND opens_at IS NULL AND closes_at IS NULL) OR "
            "(NOT is_closed AND opens_at IS NOT NULL AND closes_at IS NOT NULL AND opens_at < closes_at)",
            name="ck_cook_profile_hours_times",
        ),
        sa.UniqueConstraint("cook_profile_id", "weekday", name="uq_cook_profile_hours_weekday"),
    )
    op.create_index("ix_cook_profile_hours_cook_profile_id", "cook_profile_hours", ["cook_profile_id"])


def downgrade():
    op.drop_index("ix_cook_profile_hours_cook_profile_id", table_name="cook_profile_hours")
    op.drop_table("cook_profile_hours")
