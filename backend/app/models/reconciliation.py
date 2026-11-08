"""
Reconciliation domain models: Allocation, Discrepancy, HumanDecision, and EvidenceReference.

This module models auditability, evidence linking, and human oversight:
- `Allocation`: Explicit financial linkage between an Invoice and exactly one source record
  (Payment, Settlement, or BankTransaction). Enforced by a single-source CheckConstraint.
- `Discrepancy`: Flags rule-based mismatches (amounts, dates, currencies, fees) requiring attention.
- `HumanDecision`: Retains an immutable audit record of reviewer decisions (approve, reject, override).
- `EvidenceReference`: Complete provenance trace connecting discrepancies or allocations to physical
  source documents, bounding boxes, raw values, and extraction methods.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, JSON_VARIANT, Base, TimestampMixin, UUIDPrimaryKeyMixin, utc_now
from app.models.enums import (
    AllocationMethod,
    AllocationReviewStatus,
    DecisionType,
    DiscrepancySeverity,
    DiscrepancyStatus,
    ExtractionMethod,
    ReviewState,
    TargetType,
)

if TYPE_CHECKING:
    from app.models.document import Document, ExtractedField
    from app.models.export import Invoice
    from app.models.payment import BankTransaction, Payment, Settlement
    from app.models.relationship import TransactionLink


class Allocation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Represents an allocation connecting an Invoice to a financial settlement record.

    A strict table CheckConstraint ensures that an allocation references EXACTLY ONE of:
    - a Payment (provider capture)
    - a Settlement (provider payout batch)
    - a BankTransaction (direct bank credit)
    Conflicting multi-source allocations are forbidden at the database engine level.
    """

    __tablename__ = "allocations"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Target commercial invoice receiving this allocated settlement",
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("payments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Source Payment record if allocated directly from a provider capture",
    )
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("settlements.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Source Settlement batch if allocated from a provider payout",
    )
    bank_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("bank_transactions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Source BankTransaction if allocated from a bank statement line",
    )
    allocated_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        comment="Monetary value allocated against the invoice balance",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        comment="ISO-4217 3-letter currency code matching invoice currency",
    )
    allocation_method: Mapped[AllocationMethod] = mapped_column(
        SQLEnum(AllocationMethod, name="allocation_method_enum"),
        default=AllocationMethod.AUTO_EXACT,
        nullable=False,
        comment="Matching technique: auto_exact, rule_heuristic, manual_human",
    )
    evidence_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Summary narrative or reference numbers validating this allocation",
    )
    review_status: Mapped[AllocationReviewStatus] = mapped_column(
        SQLEnum(AllocationReviewStatus, name="allocation_review_status_enum"),
        default=AllocationReviewStatus.SUGGESTED,
        nullable=False,
        index=True,
        comment="Status: suggested (pending audit), approved, rejected",
    )
    is_demo: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Flag indicating if this allocation is seeded synthetic demo data",
    )

    # Relationships
    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="allocations")
    payment: Mapped["Payment | None"] = relationship("Payment", back_populates="allocations")
    settlement: Mapped["Settlement | None"] = relationship(
        "Settlement", back_populates="allocations"
    )
    bank_transaction: Mapped["BankTransaction | None"] = relationship(
        "BankTransaction",
        back_populates="allocations",
    )
    evidence_references: Mapped[list["EvidenceReference"]] = relationship(
        "EvidenceReference",
        back_populates="allocation",
        foreign_keys="EvidenceReference.allocation_id",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN payment_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN settlement_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN bank_transaction_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_allocation_single_source",
        ),
    )


class Discrepancy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Represents an audit finding or reconciliation mismatch.

    Identifies discrepancy severity, compared field values, and recommended human action.
    """

    __tablename__ = "discrepancies"

    rule_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Identifier of the reconciliation rule that triggered (e.g. RULE_AMOUNT_MISMATCH)",
    )
    severity: Mapped[DiscrepancySeverity] = mapped_column(
        SQLEnum(DiscrepancySeverity, name="discrepancy_severity_enum"),
        default=DiscrepancySeverity.WARNING,
        nullable=False,
        index=True,
        comment="Severity: info, warning, error, critical",
    )
    compared_fields: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_VARIANT,
        nullable=True,
        comment="Snapshot dictionary of conflicting field values (e.g. {'invoice_total': '100.00', 'payment_gross': '90.00'})",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Clear narrative explanation of the observed discrepancy",
    )
    recommended_action: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Suggested human remediation (e.g. 'Request revised fee invoice' or 'Audit bank charges')",
    )
    status: Mapped[DiscrepancyStatus] = mapped_column(
        SQLEnum(DiscrepancyStatus, name="discrepancy_status_enum"),
        default=DiscrepancyStatus.OPEN,
        nullable=False,
        index=True,
        comment="Resolution status: open, acknowledged, resolved, dismissed",
    )
    is_demo: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Flag indicating if this discrepancy is seeded synthetic demo data",
    )

    # Relationships
    evidence_references: Mapped[list["EvidenceReference"]] = relationship(
        "EvidenceReference",
        back_populates="discrepancy",
        foreign_keys="EvidenceReference.discrepancy_id",
        cascade="all, delete-orphan",
    )


class HumanDecision(Base, UUIDPrimaryKeyMixin):
    """
    Records an immutable audit trace of human intervention on a Discrepancy or Allocation.

    In accordance with hard rule 3, AI never autonomously disburses or approves transactions.
    All human approvals, overrides, and rejections are logged here.
    """

    __tablename__ = "human_decisions"

    target_type: Mapped[TargetType] = mapped_column(
        SQLEnum(TargetType, name="target_type_enum"),
        nullable=False,
        index=True,
        comment="Entity type affected: discrepancy, allocation, document",
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
        comment="UUID of the targeted Discrepancy or Allocation",
    )
    decision: Mapped[DecisionType] = mapped_column(
        SQLEnum(DecisionType, name="decision_type_enum"),
        nullable=False,
        comment="Action executed: approved, rejected, overridden, re_assigned",
    )
    reviewer_label: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Identifier or email of the authenticated human reviewer",
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Human explanation or justification for the decision",
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        comment="Exact UTC timestamp when the human decision was submitted",
    )


class EvidenceReference(Base, UUIDPrimaryKeyMixin):
    """
    Links a Discrepancy or Allocation to its concrete physical evidence.

    Stores pointers to the source document, extracted field, physical coordinates,
    bounding box, and raw text snapshot to ensure 100% auditability.
    """

    __tablename__ = "evidence_references"

    discrepancy_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("discrepancies.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Optional parent Discrepancy supported by this evidence",
    )
    allocation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("allocations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Optional parent Allocation supported by this evidence",
    )
    transaction_link_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("transaction_links.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Optional parent TransactionLink supported by this evidence",
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Source physical document",
    )
    extracted_field_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("extracted_fields.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Granular extracted field row",
    )
    source_record_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Domain entity type referenced (invoice, shipping_bill, payment, bank_transaction)",
    )
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        comment="ID of the referenced domain record",
    )
    original_filename: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Snapshot of original filename for audit display",
    )
    location_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Page/row/event location (e.g. 'page 1, header', 'row 42')",
    )
    bounding_box: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_VARIANT,
        nullable=True,
        comment="Coordinates {x0, y0, x1, y1} on the physical document page",
    )
    raw_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Snapshot of raw value as read from source",
    )
    normalized_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Normalized value string representation",
    )
    extraction_method: Mapped[ExtractionMethod | None] = mapped_column(
        SQLEnum(ExtractionMethod, name="extraction_method_evidence_enum"),
        nullable=True,
        comment="Extraction method used: text, ocr, llm, manual",
    )
    review_state: Mapped[ReviewState | None] = mapped_column(
        SQLEnum(ReviewState, name="review_state_evidence_enum"),
        nullable=True,
        comment="Review state of this evidence: pending, auto_accepted, human_verified, rejected",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        comment="UTC creation timestamp",
    )

    # Relationships
    discrepancy: Mapped["Discrepancy | None"] = relationship(
        "Discrepancy",
        back_populates="evidence_references",
    )
    allocation: Mapped["Allocation | None"] = relationship(
        "Allocation",
        back_populates="evidence_references",
    )
    transaction_link: Mapped["TransactionLink | None"] = relationship(
        "TransactionLink",
        back_populates="evidence_references",
        foreign_keys=[transaction_link_id],
    )
    document: Mapped["Document | None"] = relationship(
        "Document",
        back_populates="evidence_references",
        foreign_keys=[document_id],
    )
    extracted_field: Mapped["ExtractedField | None"] = relationship(
        "ExtractedField",
        back_populates="evidence_references",
        foreign_keys=[extracted_field_id],
    )
