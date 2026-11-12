"""Schemas for the consolidated Reconciliation Queue (Phase 11)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import AllocationReviewStatus, DiscrepancySeverity, MatchStatus


class MatchSummaryItem(BaseModel):
    """Summary of an active reconciliation match under a transaction."""

    match_id: uuid.UUID
    rule_id: str
    match_type: str
    match_status: MatchStatus
    review_status: AllocationReviewStatus
    allocated_amount: str
    currency: str
    severity: DiscrepancySeverity
    calculation: dict[str, Any] | None = None
    compared_values: dict[str, Any] | None = None
    created_at: datetime


class TransactionInvoiceSummary(BaseModel):
    """Summary of a commercial invoice attached to a transaction."""

    invoice_id: uuid.UUID
    invoice_number: str
    total_amount: str
    currency: str
    is_approved: bool
    remaining_balance: str


class TransactionPaymentSummary(BaseModel):
    """Summary of a financial payment/capture attached to a transaction."""

    payment_id: uuid.UUID
    provider_order_id: str | None = None
    provider_capture_id: str | None = None
    gross_amount: str
    currency: str
    status: str


class DiscrepancyItemSummary(BaseModel):
    """Summary of an audit discrepancy flagged for a transaction."""

    discrepancy_id: uuid.UUID
    rule_id: str
    severity: str
    status: str
    difference_amount: str | None = None
    description: str
    recommended_action: str | None = None


class EvidenceItemSummary(BaseModel):
    """Grounded evidence citation linking back to source physical documents."""

    evidence_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    document_type: str
    location_reference: str | None = None
    raw_snippet: str | None = None


class ReconciliationQueueRow(BaseModel):
    """
    Consolidated transaction-level row for the Reconciliation Queue.
    Granularity is strictly 1 row per ExportTransaction to prevent row multiplication.
    """

    transaction_id: uuid.UUID
    reference: str
    buyer_name: str
    exporter_name: str
    status: str
    status_label: str
    is_demo: bool
    currency: str
    created_at: datetime
    updated_at: datetime

    # Associated collections loaded via selectinload
    invoices: list[TransactionInvoiceSummary] = Field(default_factory=list)
    payments: list[TransactionPaymentSummary] = Field(default_factory=list)
    matches: list[MatchSummaryItem] = Field(default_factory=list)
    discrepancies: list[DiscrepancyItemSummary] = Field(default_factory=list)
    evidence_references: list[EvidenceItemSummary] = Field(default_factory=list)

    # Deterministic summary flags for high-density AG Grid rendering
    requires_human_review: bool
    has_matches: bool
    shortfall_amount: str | None = None
    active_match_count: int = 0
    discrepancy_count: int = 0
    evidence_count: int = 0


class ReconciliationQueueResponse(BaseModel):
    """Paginated response containing reconciliation queue rows."""

    items: list[ReconciliationQueueRow]
    total_count: int
    page: int
    page_size: int
    total_pages: int
