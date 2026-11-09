"""Phase 5: PayPal Sandbox Checkout and Verified Event Ingestion Schema.

Revision ID: 0004_phase5_paypal_checkout
Revises: 0003_phase4_reconciliation
Create Date: 2026-11-09 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_phase5_paypal_checkout"
down_revision: str | None = "0003_phase4_reconciliation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 1. Alter fee_amount and net_amount in payments to be nullable
    op.alter_column(
        "payments",
        "fee_amount",
        existing_type=sa.Numeric(18, 4),
        nullable=True,
    )
    op.alter_column(
        "payments",
        "net_amount",
        existing_type=sa.Numeric(18, 4),
        nullable=True,
    )

    # 2. Add description column to payments
    op.add_column(
        "payments",
        sa.Column(
            "description",
            sa.String(length=255),
            nullable=False,
            server_default="PayPal Sandbox / simulated export payment",
        ),
    )

    # 3. Add invoice_id FK to payments
    op.add_column(
        "payments",
        sa.Column(
            "invoice_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_payments_invoice_id", "payments", ["invoice_id"])

    # 4. Add provider_refund_id to payments
    op.add_column(
        "payments",
        sa.Column("provider_refund_id", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_payments_provider_refund_id",
        "payments",
        ["provider_refund_id"],
        unique=True,
    )

    # 5. Add parent_payment_id self-referential FK to payments
    op.add_column(
        "payments",
        sa.Column(
            "parent_payment_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("payments.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_payments_parent_payment_id", "payments", ["parent_payment_id"])

    # 6. Add partial unique index on provider_order_id where not null
    if is_postgres:
        op.create_index(
            "ix_payments_provider_order_id_unique",
            "payments",
            ["provider_order_id"],
            unique=True,
            postgresql_where=sa.text("provider_order_id IS NOT NULL"),
        )
        # 7. Add partial unique index to prevent multiple pending orders for one invoice
        op.create_index(
            "uq_payments_pending_invoice_order",
            "payments",
            ["invoice_id"],
            unique=True,
            postgresql_where=sa.text("status in ('pending', 'PENDING') AND provider = 'paypal'"),
        )
    else:
        op.create_index(
            "ix_payments_provider_order_id_unique",
            "payments",
            ["provider_order_id"],
            unique=False,
        )
        op.create_index(
            "uq_payments_pending_invoice_order",
            "payments",
            ["invoice_id"],
            unique=False,
        )

    # 8. Update provider_webhook_events.payment_id FK constraint to RESTRICT
    if is_postgres:
        # Inspect and drop old constraint if present
        op.execute(
            """
            DO $$
            DECLARE
                cname text;
            BEGIN
                SELECT tc.constraint_name INTO cname
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_name = 'provider_webhook_events'
                    AND kcu.column_name = 'payment_id'
                    AND tc.constraint_type = 'FOREIGN KEY'
                LIMIT 1;

                IF cname IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE provider_webhook_events DROP CONSTRAINT ' || quote_ident(cname);
                END IF;
            END $$;
            """
        )
        op.create_foreign_key(
            "fk_provider_webhook_events_payment_id_payments",
            "provider_webhook_events",
            "payments",
            ["payment_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # 8. Revert FK constraint on provider_webhook_events
    if is_postgres:
        op.drop_constraint(
            "fk_provider_webhook_events_payment_id_payments",
            "provider_webhook_events",
            type_="foreignkey",
        )
        op.create_foreign_key(
            "fk_provider_webhook_events_payment_id_payments",
            "provider_webhook_events",
            "payments",
            ["payment_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # 7 & 6. Drop partial unique indexes
    op.drop_index("uq_payments_pending_invoice_order", table_name="payments")
    op.drop_index("ix_payments_provider_order_id_unique", table_name="payments")

    # 5. Drop parent_payment_id
    op.drop_index("ix_payments_parent_payment_id", table_name="payments")
    op.drop_column("payments", "parent_payment_id")

    # 4. Drop provider_refund_id
    op.drop_index("ix_payments_provider_refund_id", table_name="payments")
    op.drop_column("payments", "provider_refund_id")

    # 3. Drop invoice_id
    op.drop_index("ix_payments_invoice_id", table_name="payments")
    op.drop_column("payments", "invoice_id")

    # 2. Drop description
    op.drop_column("payments", "description")

    # 1. Revert nullable fee_amount and net_amount
    op.alter_column(
        "payments",
        "net_amount",
        existing_type=sa.Numeric(18, 4),
        nullable=False,
    )
    op.alter_column(
        "payments",
        "fee_amount",
        existing_type=sa.Numeric(18, 4),
        nullable=False,
    )
