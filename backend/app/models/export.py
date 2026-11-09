"""
Export domain models: ExportTransaction, Invoice, InvoiceLineItem, and ShippingBill.

This module models the core cross-border trade entities:
- `ExportTransaction`: Represents the high-level trade transaction linking exporters and overseas buyers.
- `Invoice`: Commercial invoice issued for the sale of goods/services.
- `InvoiceLineItem`: Itemized lines on the commercial invoice (quantities, HS codes, unit prices).
- `ShippingBill`: Official customs export declaration verifying goods exported and declared monetary value.
"""

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import TransactionStatus

if TYPE_CHECKING:
    from app.models.payment import BankTransaction, Payment, Settlement
    from app.models.reconciliation import Allocation, Discrepancy, ReconciliationMatch
    from app.models.relationship import TransactionLink


class ExportTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Represents an export transaction covering commercial commitments and customs filings.
    """

    __tablename__ = "export_transactions"

    transaction_reference: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
        comment="Human-readable export deal reference (e.g. EXP-2026-001)",
    )
    exporter_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Legal entity name of the exporter/seller",
    )
    exporter_tax_id: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Tax ID, GSTIN, or IEC (Import Export Code) of the exporter",
    )
    buyer_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Legal entity or trading name of the overseas buyer",
    )
    buyer_country: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Country of the overseas buyer",
    )
    status: Mapped[TransactionStatus] = mapped_column(
        SQLEnum(TransactionStatus, name="transaction_status_enum"),
        default=TransactionStatus.DRAFT,
        nullable=False,
        index=True,
        comment="Reconciliation status: draft, in_progress, reconciled, discrepant, closed",
    )
    is_demo: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Flag indicating if this transaction is seeded synthetic demo data",
    )

    # Relationships
    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice",
        back_populates="export_transaction",
        cascade="all, delete-orphan",
    )
    shipping_bills: Mapped[list["ShippingBill"]] = relationship(
        "ShippingBill",
        back_populates="export_transaction",
        cascade="all, delete-orphan",
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="export_transaction",
    )
    settlements: Mapped[list["Settlement"]] = relationship(
        "Settlement",
        back_populates="export_transaction",
    )
    bank_transactions: Mapped[list["BankTransaction"]] = relationship(
        "BankTransaction",
        back_populates="export_transaction",
    )
    links: Mapped[list["TransactionLink"]] = relationship(
        "TransactionLink",
        back_populates="export_transaction",
    )
    matches: Mapped[list["ReconciliationMatch"]] = relationship(
        "ReconciliationMatch",
        back_populates="export_transaction",
    )
    discrepancies: Mapped[list["Discrepancy"]] = relationship(
        "Discrepancy",
        back_populates="export_transaction",
    )


class Invoice(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Commercial invoice issued by the exporter to the buyer.

    All monetary amounts are stored as NUMERIC(18, 2) accompanied by an explicit
    ISO-4217 3-letter currency code. Binary floats are never used.
    """

    __tablename__ = "invoices"

    invoice_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Commercial invoice identifier as printed on the document",
    )
    export_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("export_transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Optional foreign key linking this invoice to an overall export deal",
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Source document from which this invoice was uploaded or extracted",
    )
    seller_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Seller / exporter entity name",
    )
    buyer_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Buyer / customer entity name",
    )
    issue_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="Invoice issuance calendar date (YYYY-MM-DD)",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="Uppercase 3-letter ISO-4217 currency code (e.g. USD, EUR, INR)",
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        comment="Gross invoice total payable in the specified currency",
    )
    shipment_reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Bill of Lading, Air Waybill, or logistics tracking reference",
    )
    is_demo: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Flag indicating if this invoice is seeded synthetic demo data",
    )

    # Relationships
    export_transaction: Mapped["ExportTransaction | None"] = relationship(
        "ExportTransaction",
        back_populates="invoices",
    )
    line_items: Mapped[list["InvoiceLineItem"]] = relationship(
        "InvoiceLineItem",
        back_populates="invoice",
        cascade="all, delete-orphan",
    )
    allocations: Mapped[list["Allocation"]] = relationship(
        "Allocation",
        back_populates="invoice",
        cascade="all, delete-orphan",
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment",
        back_populates="invoice",
    )

    __table_args__ = (Index("ix_invoices_seller_num", "seller_name", "invoice_number"),)


class InvoiceLineItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Individual itemized line of an invoice.

    Persisted to enable granular cross-checking against customs declarations
    (quantities, HS codes, unit prices) in downstream phases.
    """

    __tablename__ = "invoice_line_items"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key linking to parent Invoice",
    )
    line_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="1-based sequence position on the invoice",
    )
    description: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Description of product, merchandise, or service billed",
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("1.0000"),
        comment="Quantity of units billed (supports fractional amounts)",
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        comment="Unit price in the invoice currency",
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        comment="Line item subtotal (quantity * unit_price)",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="Currency code matching parent invoice",
    )
    hs_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="Harmonized System (HS) tariff classification code",
    )

    # Relationships
    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="line_items")


class ShippingBill(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Customs export declaration document (e.g. Indian Customs Shipping Bill).

    Verifies that goods were cleared for export and records declared value.
    """

    __tablename__ = "shipping_bills"

    shipping_bill_number: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
        comment="Unique customs filing reference number",
    )
    export_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("export_transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Foreign key linking to overall export deal",
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Source document from which this shipping bill was parsed",
    )
    invoice_reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="Invoice number cited on the shipping bill declaration",
    )
    exporter_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Exporter name on customs records",
    )
    buyer_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Consignee / buyer name on customs records",
    )
    bill_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        comment="Customs export declaration date (YYYY-MM-DD)",
    )
    declared_currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="Currency of value declared to customs (ISO-4217)",
    )
    declared_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        comment="Total value of goods declared to customs authorities",
    )
    is_demo: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Flag indicating if this shipping bill is seeded synthetic demo data",
    )

    # Relationships
    export_transaction: Mapped["ExportTransaction | None"] = relationship(
        "ExportTransaction",
        back_populates="shipping_bills",
    )
