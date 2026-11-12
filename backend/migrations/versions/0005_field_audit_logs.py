"""Phase 11: Field Audit Logs for Permanent Audit Retention.

Revision ID: 0005_field_audit_logs
Revises: 0004_phase5_paypal_checkout
Create Date: 2026-11-12 16:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_field_audit_logs"
down_revision: str | None = "0004_phase5_paypal_checkout"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "field_audit_logs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "extracted_field_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("extracted_fields.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("document_id_snapshot", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("extracted_field_id_snapshot", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("field_name", sa.String(length=100), nullable=False),
        sa.Column("old_normalized_value", sa.JSON(), nullable=True),
        sa.Column("new_normalized_value", sa.JSON(), nullable=True),
        sa.Column("reviewer_label", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_field_audit_logs_id", "field_audit_logs", ["id"])
    op.create_index("ix_field_audit_logs_document_id", "field_audit_logs", ["document_id"])
    op.create_index(
        "ix_field_audit_logs_extracted_field_id", "field_audit_logs", ["extracted_field_id"]
    )
    op.create_index(
        "ix_field_audit_logs_doc_snapshot", "field_audit_logs", ["document_id_snapshot"]
    )
    op.create_index(
        "ix_field_audit_logs_field_snapshot", "field_audit_logs", ["extracted_field_id_snapshot"]
    )
    op.create_index("ix_field_audit_logs_field_name", "field_audit_logs", ["field_name"])


def downgrade() -> None:
    op.drop_index("ix_field_audit_logs_field_name", table_name="field_audit_logs")
    op.drop_index("ix_field_audit_logs_field_snapshot", table_name="field_audit_logs")
    op.drop_index("ix_field_audit_logs_doc_snapshot", table_name="field_audit_logs")
    op.drop_index("ix_field_audit_logs_extracted_field_id", table_name="field_audit_logs")
    op.drop_index("ix_field_audit_logs_document_id", table_name="field_audit_logs")
    op.drop_index("ix_field_audit_logs_id", table_name="field_audit_logs")
    op.drop_table("field_audit_logs")
