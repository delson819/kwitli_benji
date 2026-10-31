"""Zones commerciales persistantes, isolées par environnement."""

from alembic import op
import sqlalchemy as sa


revision = "c73e9f4a2b10"
down_revision = "ab71d9e4c205"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_area_configs",
        sa.Column("row_id", sa.String(36), primary_key=True),
        sa.Column("area_id", sa.String(80), nullable=False),
        sa.Column("environment", sa.String(20), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("country", sa.String(100), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("center_latitude", sa.Float(), nullable=True),
        sa.Column("center_longitude", sa.Float(), nullable=True),
        sa.Column("radius_km", sa.Float(), nullable=True),
        sa.Column("geometry_type", sa.String(16), nullable=False, server_default="circle"),
        sa.Column("geometry_metadata", sa.JSON(), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("locale", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("distance_unit", sa.String(8), nullable=False, server_default="km"),
        sa.Column("status", sa.String(16), nullable=False, server_default="planned"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("environment", "area_id", name="uq_service_area_environment_id"),
        sa.UniqueConstraint("environment", "code", name="uq_service_area_environment_code"),
        sa.CheckConstraint("environment IN ('development', 'test', 'staging', 'production')", name="ck_service_area_environment"),
        sa.CheckConstraint("status IN ('planned', 'recruiting', 'active', 'suspended')", name="ck_service_area_status"),
        sa.CheckConstraint("geometry_type IN ('circle', 'polygon')", name="ck_service_area_geometry_type"),
        sa.CheckConstraint("center_latitude IS NULL OR center_latitude BETWEEN -90 AND 90", name="ck_service_area_latitude"),
        sa.CheckConstraint("center_longitude IS NULL OR center_longitude BETWEEN -180 AND 180", name="ck_service_area_longitude"),
        sa.CheckConstraint("radius_km IS NULL OR (radius_km > 0 AND radius_km <= 100)", name="ck_service_area_radius"),
        sa.CheckConstraint(
            "(geometry_type = 'circle' AND center_latitude IS NOT NULL AND center_longitude IS NOT NULL AND radius_km IS NOT NULL) OR "
            "(geometry_type = 'polygon' AND geometry_metadata IS NOT NULL)",
            name="ck_service_area_geometry_data",
        ),
        sa.CheckConstraint("version > 0", name="ck_service_area_version"),
    )
    op.create_index("ix_service_area_configs_environment", "service_area_configs", ["environment"])
    op.create_table(
        "service_area_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("service_area_row_id", sa.String(36), sa.ForeignKey("service_area_configs.row_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("from_version", sa.Integer(), nullable=True),
        sa.Column("to_version", sa.Integer(), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_service_area_events_service_area_row_id", "service_area_events", ["service_area_row_id"])
    op.create_index("ix_service_area_events_actor_user_id", "service_area_events", ["actor_user_id"])
    op.create_index(
        "ix_service_area_events_config_created", "service_area_events",
        ["service_area_row_id", "created_at", "id"],
    )
    if op.get_bind().dialect.name == "sqlite":
        op.execute("""
        CREATE TRIGGER trg_service_area_events_no_update
        BEFORE UPDATE ON service_area_events
        BEGIN SELECT RAISE(ABORT, 'service area events are append-only'); END
        """)
        op.execute("""
        CREATE TRIGGER trg_service_area_events_no_delete
        BEFORE DELETE ON service_area_events
        BEGIN SELECT RAISE(ABORT, 'service area events are append-only'); END
        """)
    else:
        op.execute("""
        CREATE FUNCTION prevent_service_area_event_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'service area events are append-only'; END;
        $$ LANGUAGE plpgsql
        """)
        op.execute("""
        CREATE TRIGGER trg_service_area_events_append_only
        BEFORE UPDATE OR DELETE ON service_area_events
        FOR EACH ROW EXECUTE FUNCTION prevent_service_area_event_mutation()
        """)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in ("service_area_events", "service_area_configs"):
        if bind.execute(sa.text(f'SELECT 1 FROM "{table_name}" LIMIT 1')).first() is not None:
            raise RuntimeError("Downgrade des zones refusé : une configuration ou un historique existe.")
    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_service_area_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_service_area_events_no_delete")
    else:
        op.execute("DROP TRIGGER IF EXISTS trg_service_area_events_append_only ON service_area_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_service_area_event_mutation()")
    op.drop_table("service_area_events")
    op.drop_table("service_area_configs")
