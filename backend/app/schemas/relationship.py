"""
Pydantic v2 schemas for trade relationships (TransactionLink),
record assignment, link discovery, and human link decisions.
"""

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.models.enums import DecisionType, LinkMethod, LinkStatus, LinkType
from app.schemas.common import ProcureMindBaseSchema, ensure_utc_datetime
from app.schemas.reconciliation import EvidenceReferenceRead


class TransactionLinkBase(ProcureMindBaseSchema):
    link_type: LinkType
    link_method: LinkMethod = LinkMethod.MANUAL
    status: LinkStatus = LinkStatus.PROPOSED
    invoice_id: uuid.UUID | None = None
    shipping_bill_id: uuid.UUID | None = None
    payment_id: uuid.UUID | None = None
    settlement_id: uuid.UUID | None = None
    bank_transaction_id: uuid.UUID | None = None
    explicit_reference: str | None = None
    normalized_reference: str | None = None
    evidence_notes: str | None = None
    is_demo: bool = False


class TransactionLinkCreate(ProcureMindBaseSchema):
    """
    Manual link proposal request.

    Always creates a link with status='proposed'. Confirmation requires
    an explicit call to the human decision endpoint.
    """

    link_type: LinkType
    source_id: uuid.UUID = Field(
        ..., description="UUID of primary record (e.g. invoice_id or payment_id)"
    )
    target_id: uuid.UUID = Field(
        ..., description="UUID of secondary record (e.g. shipping_bill_id or settlement_id)"
    )
    explicit_reference: str | None = Field(
        None, max_length=255, description="Optional cited reference string"
    )
    notes: str | None = Field(
        None, description="Reviewer or operator notes explaining the proposed link"
    )


class TransactionLinkRead(TransactionLinkBase):
    id: uuid.UUID
    export_transaction_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    evidence_references: list[EvidenceReferenceRead] = Field(default_factory=list)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


class RecordAssignmentRequest(ProcureMindBaseSchema):
    """Explicit human action assigning an unowned record to a transaction."""

    record_type: str = Field(
        ..., description="One of: invoice, shipping_bill, payment, settlement, bank_transaction"
    )
    record_id: uuid.UUID = Field(..., description="UUID of the record to assign")
    notes: str | None = Field(
        None, description="Optional operator justification for assigning this record"
    )


class RecordAssignmentResponse(ProcureMindBaseSchema):
    record_type: str
    record_id: uuid.UUID
    export_transaction_id: uuid.UUID
    message: str


class LinkDecisionRequest(ProcureMindBaseSchema):
    """
    Human decision request to confirm or reject a proposed relationship.
    """

    decision: DecisionType = Field(
        ..., description="Action: approved (confirms link) or rejected (rejects link)"
    )
    reviewer_label: str | None = Field(
        None, max_length=100, description="Identifier of the reviewer"
    )
    notes: str | None = Field(None, description="Reasoning or justification for this decision")


class UnlinkedRecordReport(ProcureMindBaseSchema):
    """Transient report for records inspected during discovery that could not be linked."""

    record_type: str
    record_id: uuid.UUID
    reference: str | None = None
    reason: str
    candidate_ids: list[uuid.UUID] = Field(default_factory=list)


class DiscoveryResponse(ProcureMindBaseSchema):
    """Result of running idempotent exact-reference link discovery."""

    created_links: list[TransactionLinkRead] = Field(default_factory=list)
    existing_links: list[TransactionLinkRead] = Field(default_factory=list)
    unlinked_records: list[UnlinkedRecordReport] = Field(default_factory=list)
