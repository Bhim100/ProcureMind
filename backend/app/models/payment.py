"""
Payment, Settlement, BankTransaction, and ProviderWebhookEvent models.

This module models the financial proceeds evidence pipeline:
1. `Payment`: Represents a provider payment/capture record (gross, fee, net, status, environment).
2. `ProviderWebhookEvent`: Audit log of raw provider webhook deliveries, enforcing unique provider_event_id for deduplication.
3. `Settlement`: Provider batch payout to the merchant bank account, linking multiple payments.
4. `BankTransaction`: Direct bank statement line entry (credit or debit) evidencing bank receipt.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, JSON_VARIANT, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    BankTransactionStatus,
    BankTransactionType,
    EnvironmentLabel,
    PaymentStatus,
    SettlementStatus,
)

if TYPE_CHECKING:
    from app.models.export import ExportTransaction, Invoice
    from app.models.reconciliation import Allocation


class BankTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Represents an entry on an official bank statement.

    Acts as the final ground-truth evidence of funds received or deducted.
    """

    __tablename__ = "bank_transactions"

    bank_reference: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
        comment="Bank-assigned transaction reference or UTR (Unique Transaction Reference)",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="ISO-4217 3-letter currency code (e.g. USD, EUR, INR)",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        comment="Monetary value credited or debited on the bank statement",
    )
    transaction_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
        comment="Calendar date when value was posted in bank records (YYYY-MM-DD)",
    )
    transaction_type: Mapped[BankTransactionType] = mapped_column(
        SQLEnum(BankTransactionType, name="bank_transaction_type_enum"),
        default=BankTransactionType.CREDIT,
        nullable=False,
        comment="Credit (inflow) or debit (outflow)",
    )
    status: Mapped[BankTransactionStatus] = mapped_column(
        SQLEnum(BankTransactionStatus, name="bank_transaction_status_enum"),
        default=BankTransactionStatus.POSTED,
        nullable=False,
        comment="Reconciliation status: pending, posted, reconciled",
    )
    remittance_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Narration / description text extracted from the bank statement line",
    )
    export_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("export_transactions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Parent export deal context if explicitly assigned",
    )
    is_demo: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Flag indicating if this transaction is seeded synthetic demo data",
    )

    # Relationships
    export_transaction: Mapped["ExportTransaction | None"] = relationship(
        "ExportTransaction",
        foreign_keys=[export_transaction_id],
    )
    settlements: Mapped[list["Settlement"]] = relationship(
        "Settlement",
        back_populates="bank_transaction",
    )
    allocations: Mapped[list["Allocation"]] = relationship(
        "Allocation",
        back_populates="bank_transaction",
    )


class Settlement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Represents a payment provider payout batch (e.g. PayPal daily payout to bank).

    Links between individual customer payments and the bank statement line credit.
    """

    __tablename__ = "settlements"

    provider_reference: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
        comment="Provider payout batch ID (e.g. PayPal payout ID)",
    )
    bank_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("bank_transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Bank statement line entry that corresponds to this payout batch",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="ISO-4217 3-letter currency code",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        comment="Net payout amount transferred to merchant bank account",
    )
    settlement_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Date provider released or deposited settlement (YYYY-MM-DD)",
    )
    status: Mapped[SettlementStatus] = mapped_column(
        SQLEnum(SettlementStatus, name="settlement_status_enum"),
        default=SettlementStatus.COMPLETED,
        nullable=False,
        comment="Status: pending, completed, failed",
    )
    remittance_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Payout reference / description on provider statement",
    )
    export_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("export_transactions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Parent export deal context if explicitly assigned",
    )
    is_demo: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Flag indicating if this settlement is seeded synthetic demo data",
    )

    # Relationships
    export_transaction: Mapped["ExportTransaction | None"] = relationship(
        "ExportTransaction",
        foreign_keys=[export_transaction_id],
    )
    bank_transaction: Mapped["BankTransaction | None"] = relationship(
        "BankTransaction",
        back_populates="settlements",
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="settlement",
    )
    allocations: Mapped[list["Allocation"]] = relationship(
        "Allocation",
        back_populates="settlement",
    )


class Payment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Represents a payment/capture transaction from a payment provider (e.g. PayPal REST API).

    Stores gross amount received, provider fee, and calculated net amount.
    Uniqueness on provider_capture_id prevents duplicate capture entries.
    """

    __tablename__ = "payments"

    provider: Mapped[str] = mapped_column(
        String(50),
        default="paypal",
        nullable=False,
        comment="Payment gateway/provider (paypal, stripe, bank_transfer)",
    )
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("settlements.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Optional payout batch in which this payment was settled",
    )
    provider_order_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Provider checkout/order reference (e.g. PayPal Order ID)",
    )
    provider_capture_id: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
        comment="Provider transaction capture ID; unique when populated",
    )
    provider_refund_id: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
        index=True,
        comment="Provider transaction refund ID; unique when populated",
    )
    parent_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Links a refund/reversal payment back to the original capture payment",
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Direct foreign key to the invoice this payment or refund belongs to",
    )
    invoice_reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Invoice number or custom ID attached by buyer/payer during checkout",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="ISO-4217 3-letter currency code",
    )
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        comment="Total gross amount paid by customer before fees",
    )
    fee_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
        comment="Payment processing fee deducted by provider; null if not yet settled",
    )
    net_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
        comment="Net proceeds credited (gross_amount - fee_amount); null if not yet settled",
    )
    description: Mapped[str] = mapped_column(
        String(255),
        default="PayPal Sandbox / simulated export payment",
        nullable=False,
        comment="Operational description and environment label",
    )
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus, name="payment_status_enum"),
        default=PaymentStatus.COMPLETED,
        nullable=False,
        index=True,
        comment="Payment status: pending, completed, refunded, failed",
    )
    event_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Provider timestamp when the capture completed in UTC",
    )
    environment: Mapped[EnvironmentLabel] = mapped_column(
        SQLEnum(EnvironmentLabel, name="environment_label_enum"),
        default=EnvironmentLabel.SANDBOX,
        nullable=False,
        comment="Environment label: sandbox, live, simulated",
    )
    export_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("export_transactions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Parent export deal context if explicitly assigned",
    )
    is_demo: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Flag indicating if this payment is seeded synthetic demo data",
    )

    # Relationships
    export_transaction: Mapped["ExportTransaction | None"] = relationship(
        "ExportTransaction",
        foreign_keys=[export_transaction_id],
    )
    invoice: Mapped["Invoice | None"] = relationship(
        "Invoice",
        foreign_keys=[invoice_id],
    )
    parent_payment: Mapped["Payment | None"] = relationship(
        "Payment",
        remote_side="Payment.id",
        foreign_keys=[parent_payment_id],
        back_populates="child_refunds",
    )
    child_refunds: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="parent_payment",
    )
    settlement: Mapped["Settlement | None"] = relationship(
        "Settlement",
        back_populates="payments",
    )
    webhook_events: Mapped[list["ProviderWebhookEvent"]] = relationship(
        "ProviderWebhookEvent",
        back_populates="payment",
    )
    allocations: Mapped[list["Allocation"]] = relationship(
        "Allocation",
        back_populates="payment",
    )

    __table_args__ = (
        Index("ix_payments_provider_capture", "provider", "provider_capture_id"),
        Index(
            "uq_payments_pending_invoice_order",
            "invoice_id",
            unique=True,
            postgresql_where=text("status in ('pending', 'PENDING') AND provider = 'paypal'"),
            sqlite_where=text("status in ('pending', 'PENDING') AND provider = 'paypal'"),
        ),
    )


class ProviderWebhookEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Audit log of incoming webhook events from payment providers.

    Guarantees duplicate delivery detection via unique provider_event_id.
    Can link to a Payment once matched or ingested.
    """

    __tablename__ = "provider_webhook_events"

    provider: Mapped[str] = mapped_column(
        String(50),
        default="paypal",
        nullable=False,
        comment="Provider source (e.g. paypal)",
    )
    provider_event_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
        comment="Unique webhook event ID provided by provider headers/body (e.g. WH-12345)",
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Provider event name (e.g. PAYMENT.CAPTURE.COMPLETED)",
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Foreign key to the Payment record created or updated by this webhook",
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_VARIANT,
        nullable=True,
        comment="Full JSON payload received with the webhook for auditability",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="received",
        nullable=False,
        comment="Webhook processing state: received, processed, duplicate, ignored, failed",
    )
    event_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp emitted by the provider in the event body (UTC)",
    )

    # Relationships
    payment: Mapped["Payment | None"] = relationship(
        "Payment",
        back_populates="webhook_events",
    )
