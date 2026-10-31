"""add discovery feature metadata

Revision ID: c912d44fd821
Revises: 8d76ca917ecc
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c912d44fd821"
down_revision: Union[str, Sequence[str], None] = "8d76ca917ecc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("dishes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("featured_type", sa.String(length=30), nullable=True))
        batch_op.create_check_constraint(
            "ck_dishes_featured_type",
            "featured_type IS NULL OR featured_type IN ('new', 'dish_of_month', 'discovery', 'discount')",
        )
        batch_op.create_index("ix_dishes_featured_type", ["featured_type"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("dishes", schema=None) as batch_op:
        batch_op.drop_index("ix_dishes_featured_type")
        batch_op.drop_constraint("ck_dishes_featured_type", type_="check")
        batch_op.drop_column("featured_type")
