"""
Relationship domain model: TransactionLink.

Models authoritative, typed connections between export trade records
(ExportTransaction, Invoice, ShippingBill, Payment, Settlement, BankTransaction)
strictly within PostgreSQL.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import LinkMethod, LinkStatus, LinkType

if TYPE_CHECKING:
    from app.models.export import ExportTransaction, Invoice, ShippingBill
    from app.models.payment import BankTransaction, Payment, Settlement
    from app.models.reconciliation import EvidenceReference


class TransactionLink(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Authoritative typed relationship between trade records scoped by an ExportTransaction.

    All creations start with status='proposed'. Only an explicit human decision
    may transition status to 'confirmed' or 'rejected'.
    """

    __tablename__ = "transaction_links"

    export_transaction_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("export_transactions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Parent export deal context that scopes this relationship",
    )
    link_type: Mapped[LinkType] = mapped_column(
        SQLEnum(
            LinkType, name="link_type_enum", values_callable=lambda obj: [e.value for e in obj]
        ),
        nullable=False,
        index=True,
        comment="Typed relationship category (lowercase)",
    )
    link_method: Mapped[LinkMethod] = mapped_column(
        SQLEnum(
            LinkMethod,
            name="link_method_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=LinkMethod.AUTO_EXACT,
        nullable=False,
        comment="Discovery mechanism: auto_exact or manual",
    )
    status: Mapped[LinkStatus] = mapped_column(
        SQLEnum(
            LinkStatus,
            name="link_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=LinkStatus.PROPOSED,
        nullable=False,
        index=True,
        comment="Review state: proposed, confirmed, rejected",
    )

    # Typed Foreign Keys (exactly two populated per link_type)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Linked commercial invoice",
    )
    shipping_bill_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("shipping_bills.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Linked customs export shipping bill",
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("payments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Linked provider payment capture",
    )
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("settlements.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Linked provider payout settlement batch",
    )
    bank_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("bank_transactions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Linked bank statement line entry",
    )

    # References
    explicit_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Preserved original identifier reference string (required for auto_exact)",
    )
    normalized_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Whitespace-trimmed, case-folded reference string (required for auto_exact)",
    )
    evidence_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Provenance narrative or justification note",
    )
    is_demo: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Flag indicating synthetic demo scenario data",
    )

    # Relationships
    export_transaction: Mapped["ExportTransaction"] = relationship(
        "ExportTransaction",
        back_populates="links",
        foreign_keys=[export_transaction_id],
    )
    invoice: Mapped["Invoice | None"] = relationship(
        "Invoice",
        foreign_keys=[invoice_id],
    )
    shipping_bill: Mapped["ShippingBill | None"] = relationship(
        "ShippingBill",
        foreign_keys=[shipping_bill_id],
    )
    payment: Mapped["Payment | None"] = relationship(
        "Payment",
        foreign_keys=[payment_id],
    )
    settlement: Mapped["Settlement | None"] = relationship(
        "Settlement",
        foreign_keys=[settlement_id],
    )
    bank_transaction: Mapped["BankTransaction | None"] = relationship(
        "BankTransaction",
        foreign_keys=[bank_transaction_id],
    )
    evidence_references: Mapped[list["EvidenceReference"]] = relationship(
        "EvidenceReference",
        back_populates="transaction_link",
        foreign_keys="EvidenceReference.transaction_link_id",
    )

    __table_args__ = (
        CheckConstraint(
            "(link_type = 'invoice_shipping_bill' AND invoice_id IS NOT NULL AND shipping_bill_id IS NOT NULL AND payment_id IS NULL AND settlement_id IS NULL AND bank_transaction_id IS NULL) OR "
            "(link_type = 'invoice_payment' AND invoice_id IS NOT NULL AND payment_id IS NOT NULL AND shipping_bill_id IS NULL AND settlement_id IS NULL AND bank_transaction_id IS NULL) OR "
            "(link_type = 'payment_settlement' AND payment_id IS NOT NULL AND settlement_id IS NOT NULL AND invoice_id IS NULL AND shipping_bill_id IS NULL AND bank_transaction_id IS NULL) OR "
            "(link_type = 'bank_transaction_payment' AND bank_transaction_id IS NOT NULL AND payment_id IS NOT NULL AND invoice_id IS NULL AND shipping_bill_id IS NULL AND settlement_id IS NULL) OR "
            "(link_type = 'bank_transaction_settlement' AND bank_transaction_id IS NOT NULL AND settlement_id IS NOT NULL AND invoice_id IS NULL AND shipping_bill_id IS NULL AND payment_id IS NULL)",
            name="ck_transaction_link_typed_pair",
        ),
        CheckConstraint(
            "(link_method = 'auto_exact' AND explicit_reference IS NOT NULL AND normalized_reference IS NOT NULL) OR "
            "(link_method = 'manual')",
            name="ck_transaction_link_reference_required_for_auto_exact",
        ),
        Index(
            "uq_tx_link_inv_sb",
            "export_transaction_id",
            "invoice_id",
            "shipping_bill_id",
            unique=True,
            postgresql_where=text("link_type = 'invoice_shipping_bill'"),
            sqlite_where=text("link_type = 'invoice_shipping_bill'"),
        ),
        Index(
            "uq_tx_link_inv_pay",
            "export_transaction_id",
            "invoice_id",
            "payment_id",
            unique=True,
            postgresql_where=text("link_type = 'invoice_payment'"),
            sqlite_where=text("link_type = 'invoice_payment'"),
        ),
        Index(
            "uq_tx_link_pay_set",
            "export_transaction_id",
            "payment_id",
            "settlement_id",
            unique=True,
            postgresql_where=text("link_type = 'payment_settlement'"),
            sqlite_where=text("link_type = 'payment_settlement'"),
        ),
        Index(
            "uq_tx_link_bt_pay",
            "export_transaction_id",
            "bank_transaction_id",
            "payment_id",
            unique=True,
            postgresql_where=text("link_type = 'bank_transaction_payment'"),
            sqlite_where=text("link_type = 'bank_transaction_payment'"),
        ),
        Index(
            "uq_tx_link_bt_set",
            "export_transaction_id",
            "bank_transaction_id",
            "settlement_id",
            unique=True,
            postgresql_where=text("link_type = 'bank_transaction_settlement'"),
            sqlite_where=text("link_type = 'bank_transaction_settlement'"),
        ),
    )
