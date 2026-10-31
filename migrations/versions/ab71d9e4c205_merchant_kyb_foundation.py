"""Fondations KYB privées, distinctes de l'approbation commerciale."""

from alembic import op
import sqlalchemy as sa


revision = "ab71d9e4c205"
down_revision = "94a1c2e7d530"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "merchant_verification_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cook_profile_id", sa.String(36), sa.ForeignKey("cook_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("jurisdiction_code", sa.String(64), nullable=False),
        sa.Column("legal_entity_type", sa.String(64), nullable=False),
        sa.Column("business_activity", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("additional_requirements", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="incomplete"),
        sa.Column("legal_data_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('incomplete', 'submitted', 'under_review', 'correction_required', 'approved', 'rejected', 'suspended')", name="ck_merchant_verification_case_status"),
    )
    op.create_index("ix_merchant_verification_cases_cook_profile_id", "merchant_verification_cases", ["cook_profile_id"])
    op.create_index("ix_merchant_verification_case_cook_created", "merchant_verification_cases", ["cook_profile_id", "created_at"])
    op.create_table(
        "merchant_verification_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("merchant_verification_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requirement_code", sa.String(80), nullable=False),
        sa.Column("storage_key", sa.String(80), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("scan_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.String(36), sa.ForeignKey("merchant_verification_documents.id"), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('uploaded', 'technically_valid', 'visually_reviewed', 'under_review', 'source_verified', 'not_verifiable', 'rejected', 'replaced', 'expired')", name="ck_merchant_verification_document_status"),
        sa.CheckConstraint("scan_status IN ('pending', 'clean', 'infected', 'error')", name="ck_merchant_verification_document_scan_status"),
        sa.CheckConstraint("size_bytes > 0", name="ck_merchant_verification_document_size"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_merchant_verification_document_sha256"),
        sa.UniqueConstraint("storage_key", name="uq_merchant_verification_document_storage_key"),
    )
    op.create_index("ix_merchant_verification_documents_case_id", "merchant_verification_documents", ["case_id"])
    op.create_table(
        "merchant_verification_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("merchant_verification_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("merchant_verification_documents.id"), nullable=True),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=True),
        sa.Column("verification_method", sa.String(50), nullable=True),
        sa.Column("verification_source", sa.String(100), nullable=True),
        sa.Column("verification_result", sa.String(50), nullable=True),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("requested_requirement_code", sa.String(80), nullable=True),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_merchant_verification_events_case_id", "merchant_verification_events", ["case_id"])
    op.create_index("ix_merchant_verification_event_case_created", "merchant_verification_events", ["case_id", "created_at", "id"])
    if op.get_bind().dialect.name == "sqlite":
        for operation in ("UPDATE", "DELETE"):
            op.execute(f"""
            CREATE TRIGGER trg_merchant_verification_events_no_{operation.lower()}
            BEFORE {operation} ON merchant_verification_events
            BEGIN SELECT RAISE(ABORT, 'merchant verification events are append-only'); END
            """)
    else:
        op.execute("""
        CREATE FUNCTION prevent_merchant_verification_event_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'merchant verification events are append-only'; END;
        $$ LANGUAGE plpgsql
        """)
        op.execute("""
        CREATE TRIGGER trg_merchant_verification_events_append_only
        BEFORE UPDATE OR DELETE ON merchant_verification_events
        FOR EACH ROW EXECUTE FUNCTION prevent_merchant_verification_event_mutation()
        """)


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in ("merchant_verification_cases", "merchant_verification_documents", "merchant_verification_events"):
        if bind.execute(sa.text(f'SELECT 1 FROM "{table_name}" LIMIT 1')).first() is not None:
            raise RuntimeError("Downgrade KYB refusé : des données de vérification existent.")
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_merchant_verification_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_merchant_verification_events_no_delete")
    else:
        op.execute("DROP TRIGGER IF EXISTS trg_merchant_verification_events_append_only ON merchant_verification_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_merchant_verification_event_mutation()")
    op.drop_table("merchant_verification_events")
    op.drop_table("merchant_verification_documents")
    op.drop_table("merchant_verification_cases")
