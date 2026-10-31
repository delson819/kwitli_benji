"""Ajoute la verticale principale des etablissements."""
from alembic import op
import sqlalchemy as sa

revision = "3f9a2b7c1d6e"
down_revision = "b85e3d04f129"
branch_labels = None
depends_on = None

VERTICAL_CHECK = "business_vertical IN ('food_service', 'bakery_dessert', 'local_shop')"


def upgrade():
    with op.batch_alter_table("cook_profiles") as batch:
        batch.add_column(sa.Column("business_vertical", sa.String(length=30), nullable=True))
    op.execute("UPDATE cook_profiles SET business_vertical = 'food_service' WHERE business_vertical IS NULL")
    with op.batch_alter_table("cook_profiles") as batch:
        batch.alter_column("business_vertical", existing_type=sa.String(length=30), nullable=False)
        batch.create_check_constraint("ck_cook_profiles_business_vertical", VERTICAL_CHECK)
        batch.create_index("ix_cook_profiles_business_vertical", ["business_vertical"], unique=False)


def downgrade():
    with op.batch_alter_table("cook_profiles") as batch:
        batch.drop_index("ix_cook_profiles_business_vertical")
        batch.drop_constraint("ck_cook_profiles_business_vertical", type_="check")
        batch.drop_column("business_vertical")
