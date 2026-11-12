"""
Pydantic v2 schemas for ReconciliationMatch, Match decisions, and Reconciliation runs.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, field_validator

from app.core.currencies import validate_currency_code
from app.models.enums import (
    AllocationReviewStatus,
    DecisionType,
    DiscrepancySeverity,
    MatchStatus,
    TransactionStatus,
)
from app.schemas.common import (
    CurrencyCode,
    MoneyAmount,
    ProcureMindBaseSchema,
    ensure_utc_datetime,
    validate_money_amount,
)
from app.schemas.reconciliation import DiscrepancyRead


class MatchDecisionRequest(ProcureMindBaseSchema):
    """Payload submitted by an authorized human reviewer to confirm or reject a match."""

    decision: DecisionType
    reviewer_label: str = Field(..., min_length=2, max_length=100)
    notes: str = Field(
        ..., min_length=3, max_length=1000, description="Mandatory auditor justification note"
    )

    @field_validator("decision")
    @classmethod
    def validate_allowed_decisions(cls, v: DecisionType) -> DecisionType:
        if v not in (DecisionType.APPROVED, DecisionType.REJECTED):
            raise ValueError(
                f"Invalid decision '{v}'. Matches can only be confirmed as 'approved' or 'rejected'."
            )
        return v

    @field_validator("notes")
    @classmethod
    def validate_notes_not_blank(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 3:
            raise ValueError(
                "Audit notes/comments are required and cannot be blank or whitespace-only."
            )
        return cleaned


class ReconciliationMatchRead(ProcureMindBaseSchema):
    """Full read representation of a proposed or verified trade/financial match."""

    id: uuid.UUID
    export_transaction_id: uuid.UUID
    invoice_id: uuid.UUID | None = None
    payment_id: uuid.UUID | None = None
    settlement_id: uuid.UUID | None = None
    bank_transaction_id: uuid.UUID | None = None
    shipping_bill_id: uuid.UUID | None = None
    allocation_id: uuid.UUID | None = None
    match_type: str
    match_status: MatchStatus
    review_status: AllocationReviewStatus
    allocated_amount: MoneyAmount
    is_reversal: bool = False
    currency: CurrencyCode
    rule_id: str
    business_key: str
    reconciliation_run_id: uuid.UUID | None = None
    compared_values: dict[str, Any] | None = None
    calculation: dict[str, Any] | None = None
    severity: DiscrepancySeverity
    notes: str | None = None
    is_demo: bool = False
    created_at: datetime
    updated_at: datetime

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v: str) -> str:
        return validate_currency_code(v)

    @field_validator("allocated_amount")
    @classmethod
    def check_amount(cls, v: Decimal) -> Decimal:
        val = validate_money_amount(v)
        if val < Decimal("0.0000"):
            raise ValueError("Match allocated amount cannot be negative")
        return val

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


class SettlementFlowStage(ProcureMindBaseSchema):
    """Audit verification status of a stage along the cash flow realization chain."""

    stage_name: str
    status: str  # verified, pending_settlement, pending_bank_deposit, broken_chain
    description: str
    amount: MoneyAmount | None = None
    currency: CurrencyCode | None = None
    details: dict[str, Any] | None = None


class ReconciliationRunResponse(ProcureMindBaseSchema):
    """Response returned upon executing the deterministic reconciliation engine."""

    transaction_id: uuid.UUID
    reconciliation_run_id: uuid.UUID
    reconciled_at: datetime
    status: TransactionStatus
    matches_count: int
    discrepancies_count: int
    matches: list[ReconciliationMatchRead]
    discrepancies: list[DiscrepancyRead]
    settlement_flow_chain: list[SettlementFlowStage]
    summary: dict[str, Any]

    @field_validator("reconciled_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)
