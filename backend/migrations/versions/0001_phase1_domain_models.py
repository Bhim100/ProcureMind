"""Phase 1: Core domain models and provenance schema

Revision ID: 0001_phase1_domain_models
Revises:
Create Date: 2026-11-07 16:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_phase1_domain_models"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. documents table
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("document_type", sa.String(length=50), nullable=False, server_default="other"),
        sa.Column("upload_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "processing_status", sa.String(length=50), nullable=False, server_default="uploaded"
        ),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_id", "documents", ["id"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"], unique=True)
    op.create_index("ix_documents_processing_status", "documents", ["processing_status"])
    op.create_index("ix_documents_is_demo", "documents", ["is_demo"])

    # 2. extracted_fields table
    op.create_table(
        "extracted_fields",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_name", sa.String(length=100), nullable=False),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("normalized_value", sa.JSON(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("bounding_box", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("review_state", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("extraction_method", sa.String(length=50), nullable=False, server_default="text"),
        sa.Column("reviewed_by", sa.String(length=100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_extracted_fields_id", "extracted_fields", ["id"])
    op.create_index("ix_extracted_fields_document_id", "extracted_fields", ["document_id"])
    op.create_index("ix_extracted_fields_field_name", "extracted_fields", ["field_name"])
    op.create_index("ix_extracted_fields_review_state", "extracted_fields", ["review_state"])
    op.create_index(
        "ix_extracted_fields_doc_name", "extracted_fields", ["document_id", "field_name"]
    )

    # 3. export_transactions table
    op.create_table(
        "export_transactions",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("transaction_reference", sa.String(length=100), nullable=False),
        sa.Column("exporter_name", sa.String(length=255), nullable=False),
        sa.Column("exporter_tax_id", sa.String(length=50), nullable=True),
        sa.Column("buyer_name", sa.String(length=255), nullable=False),
        sa.Column("buyer_country", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_export_transactions_id", "export_transactions", ["id"])
    op.create_index(
        "ix_export_transactions_reference",
        "export_transactions",
        ["transaction_reference"],
        unique=True,
    )
    op.create_index("ix_export_transactions_exporter", "export_transactions", ["exporter_name"])
    op.create_index("ix_export_transactions_buyer", "export_transactions", ["buyer_name"])
    op.create_index("ix_export_transactions_is_demo", "export_transactions", ["is_demo"])

    # 4. invoices table
    op.create_table(
        "invoices",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("invoice_number", sa.String(length=100), nullable=False),
        sa.Column(
            "export_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("export_transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "document_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("seller_name", sa.String(length=255), nullable=False),
        sa.Column("buyer_name", sa.String(length=255), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("shipment_reference", sa.String(length=100), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invoices_id", "invoices", ["id"])
    op.create_index("ix_invoices_invoice_number", "invoices", ["invoice_number"])
    op.create_index("ix_invoices_export_transaction_id", "invoices", ["export_transaction_id"])
    op.create_index("ix_invoices_document_id", "invoices", ["document_id"])
    op.create_index("ix_invoices_is_demo", "invoices", ["is_demo"])
    op.create_index("ix_invoices_seller_num", "invoices", ["seller_name", "invoice_number"])

    # 5. invoice_line_items table
    op.create_table(
        "invoice_line_items",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column(
            "quantity", sa.Numeric(precision=18, scale=4), nullable=False, server_default="1.0000"
        ),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("hs_code", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_invoice_line_items_id", "invoice_line_items", ["id"])
    op.create_index("ix_invoice_line_items_invoice_id", "invoice_line_items", ["invoice_id"])

    # 6. shipping_bills table
    op.create_table(
        "shipping_bills",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("shipping_bill_number", sa.String(length=100), nullable=False),
        sa.Column(
            "export_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("export_transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "document_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("invoice_reference", sa.String(length=100), nullable=True),
        sa.Column("exporter_name", sa.String(length=255), nullable=False),
        sa.Column("buyer_name", sa.String(length=255), nullable=False),
        sa.Column("bill_date", sa.Date(), nullable=True),
        sa.Column("declared_currency", sa.String(length=3), nullable=False),
        sa.Column("declared_value", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_shipping_bills_id", "shipping_bills", ["id"])
    op.create_index(
        "ix_shipping_bills_number", "shipping_bills", ["shipping_bill_number"], unique=True
    )
    op.create_index("ix_shipping_bills_invoice_ref", "shipping_bills", ["invoice_reference"])
    op.create_index("ix_shipping_bills_is_demo", "shipping_bills", ["is_demo"])

    # 7. bank_transactions table
    op.create_table(
        "bank_transactions",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("bank_reference", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column(
            "transaction_type", sa.String(length=20), nullable=False, server_default="credit"
        ),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="posted"),
        sa.Column("remittance_reference", sa.String(length=255), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bank_transactions_id", "bank_transactions", ["id"])
    op.create_index(
        "ix_bank_transactions_bank_reference", "bank_transactions", ["bank_reference"], unique=True
    )
    op.create_index("ix_bank_transactions_date", "bank_transactions", ["transaction_date"])
    op.create_index("ix_bank_transactions_is_demo", "bank_transactions", ["is_demo"])

    # 8. settlements table
    op.create_table(
        "settlements",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_reference", sa.String(length=100), nullable=False),
        sa.Column(
            "bank_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("bank_transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="completed"),
        sa.Column("remittance_reference", sa.String(length=255), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_settlements_id", "settlements", ["id"])
    op.create_index(
        "ix_settlements_provider_reference", "settlements", ["provider_reference"], unique=True
    )
    op.create_index("ix_settlements_bank_transaction_id", "settlements", ["bank_transaction_id"])
    op.create_index("ix_settlements_is_demo", "settlements", ["is_demo"])

    # 9. payments table
    op.create_table(
        "payments",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="paypal"),
        sa.Column(
            "settlement_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("settlements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider_order_id", sa.String(length=100), nullable=True),
        sa.Column("provider_capture_id", sa.String(length=100), nullable=True),
        sa.Column("invoice_reference", sa.String(length=100), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("gross_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "fee_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0.00"
        ),
        sa.Column("net_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="completed"),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("environment", sa.String(length=50), nullable=False, server_default="sandbox"),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payments_id", "payments", ["id"])
    op.create_index("ix_payments_capture_id", "payments", ["provider_capture_id"], unique=True)
    op.create_index("ix_payments_provider_order", "payments", ["provider_order_id"])
    op.create_index("ix_payments_invoice_ref", "payments", ["invoice_reference"])
    op.create_index("ix_payments_settlement_id", "payments", ["settlement_id"])
    op.create_index("ix_payments_is_demo", "payments", ["is_demo"])
    op.create_index("ix_payments_provider_capture", "payments", ["provider", "provider_capture_id"])

    # 10. provider_webhook_events table
    op.create_table(
        "provider_webhook_events",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="paypal"),
        sa.Column("provider_event_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column(
            "payment_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("payments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="received"),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_provider_webhook_events_id", "provider_webhook_events", ["id"])
    op.create_index(
        "ix_provider_webhook_events_event_id",
        "provider_webhook_events",
        ["provider_event_id"],
        unique=True,
    )
    op.create_index(
        "ix_provider_webhook_events_payment_id", "provider_webhook_events", ["payment_id"]
    )

    # 11. allocations table with single-source check constraint
    op.create_table(
        "allocations",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "invoice_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "payment_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("payments.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "settlement_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("settlements.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "bank_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("bank_transactions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("allocated_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "allocation_method", sa.String(length=50), nullable=False, server_default="auto_exact"
        ),
        sa.Column("evidence_notes", sa.Text(), nullable=True),
        sa.Column(
            "review_status", sa.String(length=50), nullable=False, server_default="suggested"
        ),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN payment_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN settlement_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN bank_transaction_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_allocation_single_source",
        ),
    )
    op.create_index("ix_allocations_id", "allocations", ["id"])
    op.create_index("ix_allocations_invoice_id", "allocations", ["invoice_id"])
    op.create_index("ix_allocations_payment_id", "allocations", ["payment_id"])
    op.create_index("ix_allocations_settlement_id", "allocations", ["settlement_id"])
    op.create_index("ix_allocations_bank_transaction_id", "allocations", ["bank_transaction_id"])
    op.create_index("ix_allocations_is_demo", "allocations", ["is_demo"])

    # 12. discrepancies table
    op.create_table(
        "discrepancies",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_id", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=50), nullable=False, server_default="warning"),
        sa.Column("compared_fields", sa.JSON(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="open"),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discrepancies_id", "discrepancies", ["id"])
    op.create_index("ix_discrepancies_rule_id", "discrepancies", ["rule_id"])
    op.create_index("ix_discrepancies_status", "discrepancies", ["status"])
    op.create_index("ix_discrepancies_is_demo", "discrepancies", ["is_demo"])

    # 13. human_decisions table
    op.create_table(
        "human_decisions",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("reviewer_label", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_human_decisions_id", "human_decisions", ["id"])
    op.create_index("ix_human_decisions_target", "human_decisions", ["target_type", "target_id"])

    # 14. evidence_references table
    op.create_table(
        "evidence_references",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "discrepancy_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("discrepancies.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "allocation_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("allocations.id", ondelete="CASCADE"),
            nullable=True,
        ),
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
        sa.Column("source_record_type", sa.String(length=50), nullable=True),
        sa.Column("source_record_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("location_reference", sa.String(length=255), nullable=True),
        sa.Column("bounding_box", sa.JSON(), nullable=True),
        sa.Column("raw_value", sa.Text(), nullable=True),
        sa.Column("normalized_value", sa.Text(), nullable=True),
        sa.Column("extraction_method", sa.String(length=50), nullable=True),
        sa.Column("review_state", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evidence_references_id", "evidence_references", ["id"])
    op.create_index("ix_evidence_references_discrepancy", "evidence_references", ["discrepancy_id"])
    op.create_index("ix_evidence_references_allocation", "evidence_references", ["allocation_id"])


def downgrade() -> None:
    op.drop_table("evidence_references")
    op.drop_table("human_decisions")
    op.drop_table("discrepancies")
    op.drop_table("allocations")
    op.drop_table("provider_webhook_events")
    op.drop_table("payments")
    op.drop_table("settlements")
    op.drop_table("bank_transactions")
    op.drop_table("shipping_bills")
    op.drop_table("invoice_line_items")
    op.drop_table("invoices")
    op.drop_table("export_transactions")
    op.drop_table("extracted_fields")
    op.drop_table("documents")
