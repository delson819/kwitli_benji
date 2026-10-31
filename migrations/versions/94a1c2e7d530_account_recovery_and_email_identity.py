"""Ajoute la récupération de mot de passe et l'unicité e-mail insensible à la casse."""

from alembic import op
import sqlalchemy as sa


revision = "94a1c2e7d530"
down_revision = "6d2f81a4c970"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    collision_groups = bind.scalar(sa.text(
        "SELECT count(*) FROM ("
        "SELECT lower(email) FROM users GROUP BY lower(email) HAVING count(*) > 1"
        ") AS email_collisions"
    ))
    if collision_groups:
        raise RuntimeError(
            f"Migration bloquee : {collision_groups} groupe(s) d'e-mails en collision. "
            "Resoudre les identites sans fusion automatique avant de creer l'index unique."
        )

    op.add_column(
        "users",
        sa.Column("auth_version", sa.Integer(), server_default="0", nullable=False),
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_check_constraint("ck_users_auth_version_nonnegative", "auth_version >= 0")
    op.execute("CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email))")
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_password_reset_tokens_hash_length"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])


def downgrade():
    bind = op.get_bind()
    active_tokens = bind.scalar(sa.text("SELECT count(*) FROM password_reset_tokens"))
    changed_versions = bind.scalar(sa.text("SELECT count(*) FROM users WHERE auth_version <> 0"))
    if active_tokens or changed_versions:
        raise RuntimeError("Downgrade refuse : des recuperations ou versions de session sont enregistrees.")
    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_index("uq_users_email_lower", table_name="users")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_auth_version_nonnegative", type_="check")
    op.drop_column("users", "auth_version")
