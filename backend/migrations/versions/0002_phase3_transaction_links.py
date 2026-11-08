"""Phase 3: Transaction relationships schema and constraints.

Revision ID: 0002_phase3_transaction_links
Revises: 0001_phase1_domain_models
Create Date: 2026-11-08 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_phase3_transaction_links"
down_revision: str | None = "0001_phase1_domain_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add export_transaction_id to payments
    op.add_column(
        "payments",
        sa.Column(
            "export_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("export_transactions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_payments_export_transaction_id", "payments", ["export_transaction_id"])

    # 2. Add export_transaction_id to settlements
    op.add_column(
        "settlements",
        sa.Column(
            "export_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("export_transactions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_settlements_export_transaction_id", "settlements", ["export_transaction_id"]
    )

    # 3. Add export_transaction_id to bank_transactions
    op.add_column(
        "bank_transactions",
        sa.Column(
            "export_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("export_transactions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_bank_transactions_export_transaction_id",
        "bank_transactions",
        ["export_transaction_id"],
    )

    # 4. Create transaction_links table
    op.create_table(
        "transaction_links",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "export_transaction_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("export_transactions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("link_type", sa.String(length=50), nullable=False),
        sa.Column("link_method", sa.String(length=50), nullable=False, server_default="auto_exact"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="proposed"),
        sa.Column(
            "invoice_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "shipping_bill_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("shipping_bills.id", ondelete="RESTRICT"),
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
        sa.Column("explicit_reference", sa.String(length=255), nullable=True),
        sa.Column("normalized_reference", sa.String(length=255), nullable=True),
        sa.Column("evidence_notes", sa.Text(), nullable=True),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(link_type = 'invoice_shipping_bill' AND invoice_id IS NOT NULL AND shipping_bill_id IS NOT NULL AND payment_id IS NULL AND settlement_id IS NULL AND bank_transaction_id IS NULL) OR "
            "(link_type = 'invoice_payment' AND invoice_id IS NOT NULL AND payment_id IS NOT NULL AND shipping_bill_id IS NULL AND settlement_id IS NULL AND bank_transaction_id IS NULL) OR "
            "(link_type = 'payment_settlement' AND payment_id IS NOT NULL AND settlement_id IS NOT NULL AND invoice_id IS NULL AND shipping_bill_id IS NULL AND bank_transaction_id IS NULL) OR "
            "(link_type = 'bank_transaction_payment' AND bank_transaction_id IS NOT NULL AND payment_id IS NOT NULL AND invoice_id IS NULL AND shipping_bill_id IS NULL AND settlement_id IS NULL) OR "
            "(link_type = 'bank_transaction_settlement' AND bank_transaction_id IS NOT NULL AND settlement_id IS NOT NULL AND invoice_id IS NULL AND shipping_bill_id IS NULL AND payment_id IS NULL)",
            name="ck_transaction_link_typed_pair",
        ),
        sa.CheckConstraint(
            "(link_method = 'auto_exact' AND explicit_reference IS NOT NULL AND normalized_reference IS NOT NULL) OR "
            "(link_method = 'manual')",
            name="ck_transaction_link_reference_required_for_auto_exact",
        ),
    )

    op.create_index("ix_transaction_links_id", "transaction_links", ["id"])
    op.create_index(
        "ix_transaction_links_export_tx_id",
        "transaction_links",
        ["export_transaction_id"],
    )
    op.create_index("ix_transaction_links_link_type", "transaction_links", ["link_type"])
    op.create_index("ix_transaction_links_status", "transaction_links", ["status"])
    op.create_index("ix_transaction_links_invoice_id", "transaction_links", ["invoice_id"])
    op.create_index(
        "ix_transaction_links_shipping_bill_id",
        "transaction_links",
        ["shipping_bill_id"],
    )
    op.create_index("ix_transaction_links_payment_id", "transaction_links", ["payment_id"])
    op.create_index(
        "ix_transaction_links_settlement_id",
        "transaction_links",
        ["settlement_id"],
    )
    op.create_index(
        "ix_transaction_links_bank_tx_id",
        "transaction_links",
        ["bank_transaction_id"],
    )
    op.create_index(
        "ix_transaction_links_norm_ref",
        "transaction_links",
        ["normalized_reference"],
    )
    op.create_index("ix_transaction_links_is_demo", "transaction_links", ["is_demo"])

    # Partial unique indexes
    op.create_index(
        "uq_tx_link_inv_sb",
        "transaction_links",
        ["export_transaction_id", "invoice_id", "shipping_bill_id"],
        unique=True,
        postgresql_where=sa.text("link_type = 'invoice_shipping_bill'"),
        sqlite_where=sa.text("link_type = 'invoice_shipping_bill'"),
    )
    op.create_index(
        "uq_tx_link_inv_pay",
        "transaction_links",
        ["export_transaction_id", "invoice_id", "payment_id"],
        unique=True,
        postgresql_where=sa.text("link_type = 'invoice_payment'"),
        sqlite_where=sa.text("link_type = 'invoice_payment'"),
    )
    op.create_index(
        "uq_tx_link_pay_set",
        "transaction_links",
        ["export_transaction_id", "payment_id", "settlement_id"],
        unique=True,
        postgresql_where=sa.text("link_type = 'payment_settlement'"),
        sqlite_where=sa.text("link_type = 'payment_settlement'"),
    )
    op.create_index(
        "uq_tx_link_bt_pay",
        "transaction_links",
        ["export_transaction_id", "bank_transaction_id", "payment_id"],
        unique=True,
        postgresql_where=sa.text("link_type = 'bank_transaction_payment'"),
        sqlite_where=sa.text("link_type = 'bank_transaction_payment'"),
    )
    op.create_index(
        "uq_tx_link_bt_set",
        "transaction_links",
        ["export_transaction_id", "bank_transaction_id", "settlement_id"],
        unique=True,
        postgresql_where=sa.text("link_type = 'bank_transaction_settlement'"),
        sqlite_where=sa.text("link_type = 'bank_transaction_settlement'"),
    )

    # 5. Add transaction_link_id to evidence_references
    op.add_column(
        "evidence_references",
        sa.Column(
            "transaction_link_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("transaction_links.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_evidence_references_transaction_link_id",
        "evidence_references",
        ["transaction_link_id"],
    )


def downgrade() -> None:
    # 1. Drop evidence_references.transaction_link_id
    op.drop_index(
        "ix_evidence_references_transaction_link_id",
        table_name="evidence_references",
    )
    op.drop_column("evidence_references", "transaction_link_id")

    # 2. Drop partial unique indexes
    op.drop_index("uq_tx_link_bt_set", table_name="transaction_links")
    op.drop_index("uq_tx_link_bt_pay", table_name="transaction_links")
    op.drop_index("uq_tx_link_pay_set", table_name="transaction_links")
    op.drop_index("uq_tx_link_inv_pay", table_name="transaction_links")
    op.drop_index("uq_tx_link_inv_sb", table_name="transaction_links")

    # 3. Drop transaction_links table
    op.drop_table("transaction_links")

    # 4. Drop export_transaction_id from bank_transactions
    op.drop_index(
        "ix_bank_transactions_export_transaction_id",
        table_name="bank_transactions",
    )
    op.drop_column("bank_transactions", "export_transaction_id")

    # 5. Drop export_transaction_id from settlements
    op.drop_index("ix_settlements_export_transaction_id", table_name="settlements")
    op.drop_column("settlements", "export_transaction_id")

    # 6. Drop export_transaction_id from payments
    op.drop_index("ix_payments_export_transaction_id", table_name="payments")
    op.drop_column("payments", "export_transaction_id")
