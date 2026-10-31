"""Horodatage de preparation, sans inventer de dates historiques."""
from alembic import op
import sqlalchemy as sa

revision = "b85e3d04f129"
down_revision = "a74d2c93e018"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("in_progress_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT COUNT(*) FROM orders WHERE in_progress_at IS NOT NULL")):
        raise RuntimeError("Downgrade refuse : horodatages operationnels utilises.")
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("in_progress_at")
