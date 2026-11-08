"""Phase 4: Deterministic Matching and Reconciliation Engine Schema.

Revision ID: 0003_phase4_reconciliation
Revises: 0002_phase3_transaction_links
Create Date: 2026-11-08 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_phase4_reconciliation"
down_revision: str | None = "0002_phase3_transaction_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Widen money columns to NUMERIC(18, 4)
    money_columns = [
        ("invoices", "total_amount"),
        ("invoice_line_items", "unit_price"),
        ("invoice_line_items", "total_amount"),
        ("shipping_bills", "declared_value"),
        ("payments", "gross_amount"),
        ("payments", "fee_amount"),
        ("payments", "net_amount"),
        ("settlements", "amount"),
        ("bank_transactions", "amount"),
        ("allocations", "allocated_amount"),
    ]
    for table_name, col_name in money_columns:
        op.alter_column(
            table_name,
            col_name,
            type_=sa.Numeric(18, 4),
            existing_type=sa.Numeric(18, 2),
            nullable=False,
        )

    # 2. Add is_reversal to allocations and check constraint
    op.add_column(
        "allocations",
        sa.Column(
            "is_reversal",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_check_constraint(
        "ck_allocation_amount_positive",
        "allocations",
        "allocated_amount > 0",
    )

    # 3. Update foreign keys on allocations to RESTRICT
    if is_postgres:
        op.execute(
            "ALTER TABLE allocations DROP CONSTRAINT IF EXISTS allocations_invoice_id_fkey, "
            "ADD CONSTRAINT allocations_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE RESTRICT;"
        )
        op.execute(
            "ALTER TABLE allocations DROP CONSTRAINT IF EXISTS allocations_payment_id_fkey, "
            "ADD CONSTRAINT allocations_payment_id_fkey FOREIGN KEY (payment_id) REFERENCES payments(id) ON DELETE RESTRICT;"
        )
        op.execute(
            "ALTER TABLE allocations DROP CONSTRAINT IF EXISTS allocations_settlement_id_fkey, "
            "ADD CONSTRAINT allocations_settlement_id_fkey FOREIGN KEY (settlement_id) REFERENCES settlements(id) ON DELETE RESTRICT;"
        )
        op.execute(
            "ALTER TABLE allocations DROP CONSTRAINT IF EXISTS allocations_bank_transaction_id_fkey, "
            "ADD CONSTRAINT allocations_bank_transaction_id_fkey FOREIGN KEY (bank_transaction_id) REFERENCES bank_transactions(id) ON DELETE RESTRICT;"
        )

    # 4. Create reconciliation_matches table
    op.create_table(
        "reconciliation_matches",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "export_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("export_transactions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "invoice_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "payment_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "settlement_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("settlements.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "bank_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("bank_transactions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "shipping_bill_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("shipping_bills.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "allocation_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("allocations.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("match_type", sa.String(50), nullable=False),
        sa.Column("match_status", sa.String(50), nullable=False),
        sa.Column(
            "review_status",
            sa.String(50),
            nullable=False,
            server_default="suggested",
        ),
        sa.Column("allocated_amount", sa.Numeric(18, 4), nullable=False, server_default="0.0000"),
        sa.Column("is_reversal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("rule_id", sa.String(100), nullable=False),
        sa.Column("business_key", sa.String(64), nullable=False),
        sa.Column("reconciliation_run_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("compared_values", sa.JSON(), nullable=True),
        sa.Column("calculation", sa.JSON(), nullable=True),
        sa.Column(
            "severity",
            sa.String(50),
            nullable=False,
            server_default="info",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_reconciliation_matches_export_transaction_id",
        "reconciliation_matches",
        ["export_transaction_id"],
    )
    op.create_index(
        "ix_reconciliation_matches_invoice_id",
        "reconciliation_matches",
        ["invoice_id"],
    )
    op.create_index(
        "ix_reconciliation_matches_payment_id",
        "reconciliation_matches",
        ["payment_id"],
    )
    op.create_index(
        "ix_reconciliation_matches_rule_id",
        "reconciliation_matches",
        ["rule_id"],
    )
    op.create_index(
        "ix_reconciliation_matches_business_key",
        "reconciliation_matches",
        ["business_key"],
    )
    op.create_check_constraint(
        "ck_match_amount_non_negative",
        "reconciliation_matches",
        "allocated_amount >= 0",
    )
    if is_postgres:
        op.execute(
            "CREATE UNIQUE INDEX ix_reconciliation_matches_active_bkey "
            "ON reconciliation_matches (export_transaction_id, business_key) "
            "WHERE review_status != 'superseded';"
        )
    else:
        op.create_index(
            "ix_reconciliation_matches_active_bkey",
            "reconciliation_matches",
            ["export_transaction_id", "business_key"],
        )

    # 5. Alter discrepancies table
    op.add_column(
        "discrepancies",
        sa.Column(
            "export_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("export_transactions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column("discrepancies", sa.Column("business_key", sa.String(64), nullable=True))
    op.add_column(
        "discrepancies", sa.Column("reconciliation_run_id", sa.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("discrepancies", sa.Column("calculation", sa.JSON(), nullable=True))
    op.create_index(
        "ix_discrepancies_export_transaction_id", "discrepancies", ["export_transaction_id"]
    )
    op.create_index("ix_discrepancies_business_key", "discrepancies", ["business_key"])
    if is_postgres:
        op.execute(
            "CREATE UNIQUE INDEX ix_discrepancies_active_bkey "
            "ON discrepancies (export_transaction_id, business_key) "
            "WHERE status IN ('open', 'acknowledged');"
        )
    else:
        op.create_index(
            "ix_discrepancies_active_bkey",
            "discrepancies",
            ["export_transaction_id", "business_key"],
        )

    # 6. Alter evidence_references table
    op.add_column(
        "evidence_references",
        sa.Column(
            "match_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("reconciliation_matches.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_evidence_references_match_id", "evidence_references", ["match_id"])
    if is_postgres:
        op.execute(
            "ALTER TABLE evidence_references DROP CONSTRAINT IF EXISTS evidence_references_discrepancy_id_fkey, "
            "ADD CONSTRAINT evidence_references_discrepancy_id_fkey FOREIGN KEY (discrepancy_id) REFERENCES discrepancies(id) ON DELETE RESTRICT;"
        )
        op.execute(
            "ALTER TABLE evidence_references DROP CONSTRAINT IF EXISTS evidence_references_allocation_id_fkey, "
            "ADD CONSTRAINT evidence_references_allocation_id_fkey FOREIGN KEY (allocation_id) REFERENCES allocations(id) ON DELETE RESTRICT;"
        )
        op.execute(
            "ALTER TABLE evidence_references DROP CONSTRAINT IF EXISTS evidence_references_document_id_fkey, "
            "ADD CONSTRAINT evidence_references_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE RESTRICT;"
        )
        op.execute(
            "ALTER TABLE evidence_references DROP CONSTRAINT IF EXISTS evidence_references_extracted_field_id_fkey, "
            "ADD CONSTRAINT evidence_references_extracted_field_id_fkey FOREIGN KEY (extracted_field_id) REFERENCES extracted_fields(id) ON DELETE RESTRICT;"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. EvidenceReferences
    if is_postgres:
        op.execute(
            "ALTER TABLE evidence_references DROP CONSTRAINT IF EXISTS evidence_references_extracted_field_id_fkey, "
            "ADD CONSTRAINT evidence_references_extracted_field_id_fkey FOREIGN KEY (extracted_field_id) REFERENCES extracted_fields(id) ON DELETE SET NULL;"
        )
        op.execute(
            "ALTER TABLE evidence_references DROP CONSTRAINT IF EXISTS evidence_references_document_id_fkey, "
            "ADD CONSTRAINT evidence_references_document_id_fkey FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL;"
        )
        op.execute(
            "ALTER TABLE evidence_references DROP CONSTRAINT IF EXISTS evidence_references_allocation_id_fkey, "
            "ADD CONSTRAINT evidence_references_allocation_id_fkey FOREIGN KEY (allocation_id) REFERENCES allocations(id) ON DELETE CASCADE;"
        )
        op.execute(
            "ALTER TABLE evidence_references DROP CONSTRAINT IF EXISTS evidence_references_discrepancy_id_fkey, "
            "ADD CONSTRAINT evidence_references_discrepancy_id_fkey FOREIGN KEY (discrepancy_id) REFERENCES discrepancies(id) ON DELETE CASCADE;"
        )
    op.drop_index("ix_evidence_references_match_id", table_name="evidence_references")
    op.drop_column("evidence_references", "match_id")

    # 2. Discrepancies
    if is_postgres:
        op.execute("DROP INDEX IF EXISTS ix_discrepancies_active_bkey;")
    else:
        op.drop_index("ix_discrepancies_active_bkey", table_name="discrepancies")
    op.drop_index("ix_discrepancies_business_key", table_name="discrepancies")
    op.drop_index("ix_discrepancies_export_transaction_id", table_name="discrepancies")
    op.drop_column("discrepancies", "calculation")
    op.drop_column("discrepancies", "reconciliation_run_id")
    op.drop_column("discrepancies", "business_key")
    op.drop_column("discrepancies", "export_transaction_id")

    # 3. Reconciliation Matches
    if is_postgres:
        op.execute("DROP INDEX IF EXISTS ix_reconciliation_matches_active_bkey;")
    else:
        op.drop_index("ix_reconciliation_matches_active_bkey", table_name="reconciliation_matches")
    op.drop_constraint("ck_match_amount_non_negative", "reconciliation_matches", type_="check")
    op.drop_index("ix_reconciliation_matches_business_key", table_name="reconciliation_matches")
    op.drop_index("ix_reconciliation_matches_rule_id", table_name="reconciliation_matches")
    op.drop_index("ix_reconciliation_matches_payment_id", table_name="reconciliation_matches")
    op.drop_index("ix_reconciliation_matches_invoice_id", table_name="reconciliation_matches")
    op.drop_index(
        "ix_reconciliation_matches_export_transaction_id", table_name="reconciliation_matches"
    )
    op.drop_table("reconciliation_matches")

    # 4. Allocations
    if is_postgres:
        op.execute(
            "ALTER TABLE allocations DROP CONSTRAINT IF EXISTS allocations_bank_transaction_id_fkey, "
            "ADD CONSTRAINT allocations_bank_transaction_id_fkey FOREIGN KEY (bank_transaction_id) REFERENCES bank_transactions(id) ON DELETE CASCADE;"
        )
        op.execute(
            "ALTER TABLE allocations DROP CONSTRAINT IF EXISTS allocations_settlement_id_fkey, "
            "ADD CONSTRAINT allocations_settlement_id_fkey FOREIGN KEY (settlement_id) REFERENCES settlements(id) ON DELETE CASCADE;"
        )
        op.execute(
            "ALTER TABLE allocations DROP CONSTRAINT IF EXISTS allocations_payment_id_fkey, "
            "ADD CONSTRAINT allocations_payment_id_fkey FOREIGN KEY (payment_id) REFERENCES payments(id) ON DELETE CASCADE;"
        )
        op.execute(
            "ALTER TABLE allocations DROP CONSTRAINT IF EXISTS allocations_invoice_id_fkey, "
            "ADD CONSTRAINT allocations_invoice_id_fkey FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE;"
        )
    op.drop_constraint("ck_allocation_amount_positive", "allocations", type_="check")
    op.drop_column("allocations", "is_reversal")

    # 5. Shrink money columns back to Numeric(18, 2)
    money_columns = [
        ("invoices", "total_amount"),
        ("invoice_line_items", "unit_price"),
        ("invoice_line_items", "total_amount"),
        ("shipping_bills", "declared_value"),
        ("payments", "gross_amount"),
        ("payments", "fee_amount"),
        ("payments", "net_amount"),
        ("settlements", "amount"),
        ("bank_transactions", "amount"),
        ("allocations", "allocated_amount"),
    ]
    for table_name, col_name in money_columns:
        op.alter_column(
            table_name,
            col_name,
            type_=sa.Numeric(18, 2),
            existing_type=sa.Numeric(18, 4),
            nullable=False,
        )
