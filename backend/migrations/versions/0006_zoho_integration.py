"""Phase 12: Zoho Books Integration and Document Source Tracking.

Revision ID: 0006_zoho_integration
Revises: 0005_field_audit_logs
Create Date: 2026-11-13 00:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_zoho_integration"
down_revision: str | None = "0005_field_audit_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add source tracking columns to documents
    op.add_column(
        "documents",
        sa.Column(
            "source_system",
            sa.String(length=50),
            nullable=False,
            server_default="manual_upload",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "source_external_id",
            sa.String(length=100),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_documents_source_external_id",
        "documents",
        ["source_external_id"],
    )

    # 2. Create zoho_integrations table
    op.create_table(
        "zoho_integrations",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.String(length=100), nullable=False, unique=True),
        sa.Column("organization_name", sa.String(length=255), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "api_domain",
            sa.String(length=100),
            nullable=False,
            server_default="https://books.zoho.com",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_zoho_integrations_id", "zoho_integrations", ["id"])
    op.create_index(
        "ix_zoho_integrations_organization_id",
        "zoho_integrations",
        ["organization_id"],
        unique=True,
    )
    op.create_index(
        "ix_zoho_integrations_active",
        "zoho_integrations",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_zoho_integrations_active", table_name="zoho_integrations")
    op.drop_index("ix_zoho_integrations_organization_id", table_name="zoho_integrations")
    op.drop_index("ix_zoho_integrations_id", table_name="zoho_integrations")
    op.drop_table("zoho_integrations")

    op.drop_index("ix_documents_source_external_id", table_name="documents")
    op.drop_column("documents", "source_external_id")
    op.drop_column("documents", "source_system")

