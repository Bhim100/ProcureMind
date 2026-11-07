"""
Pydantic v2 schemas for Allocation, Discrepancy, HumanDecision, and EvidenceReference.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.core.currencies import validate_currency_code
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
from app.schemas.common import (
    CurrencyCode,
    MoneyAmount,
    ProcureMindBaseSchema,
    ensure_utc_datetime,
    validate_money_amount,
)


# --- Allocation ---
class AllocationBase(ProcureMindBaseSchema):
    invoice_id: uuid.UUID
    payment_id: uuid.UUID | None = None
    settlement_id: uuid.UUID | None = None
    bank_transaction_id: uuid.UUID | None = None
    allocated_amount: MoneyAmount
    currency: CurrencyCode
    allocation_method: AllocationMethod = AllocationMethod.AUTO_EXACT
    evidence_notes: str | None = None
    review_status: AllocationReviewStatus = AllocationReviewStatus.SUGGESTED
    is_demo: bool = False

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v: str) -> str:
        return validate_currency_code(v)

    @field_validator("allocated_amount")
    @classmethod
    def check_amount(cls, v: Decimal) -> Decimal:
        val = validate_money_amount(v)
        if val <= Decimal("0.00"):
            raise ValueError("Allocated amount must be greater than zero")
        return val

    @model_validator(mode="after")
    def validate_single_financial_source(self) -> "AllocationBase":
        """
        Enforces mutual exclusivity: an allocation MUST link to EXACTLY ONE financial source
        (payment_id, settlement_id, or bank_transaction_id). Conflicting multi-source links are rejected.
        """
        sources = [
            ("payment_id", self.payment_id),
            ("settlement_id", self.settlement_id),
            ("bank_transaction_id", self.bank_transaction_id),
        ]
        active = [name for name, val in sources if val is not None]
        if len(active) == 0:
            raise ValueError(
                "Allocation must reference exactly one financial source record (payment_id, settlement_id, or bank_transaction_id)"
            )
        if len(active) > 1:
            raise ValueError(
                f"Conflicting financial sources provided: {', '.join(active)}. Exactly one source must be specified."
            )
        return self


class AllocationCreate(AllocationBase):
    pass


class AllocationRead(AllocationBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


# --- Discrepancy ---
class DiscrepancyBase(ProcureMindBaseSchema):
    rule_id: str = Field(..., max_length=100)
    severity: DiscrepancySeverity = DiscrepancySeverity.WARNING
    compared_fields: dict[str, Any] | None = None
    description: str
    recommended_action: str | None = None
    status: DiscrepancyStatus = DiscrepancyStatus.OPEN
    is_demo: bool = False


class DiscrepancyCreate(DiscrepancyBase):
    pass


class DiscrepancyRead(DiscrepancyBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


# --- HumanDecision ---
class HumanDecisionBase(ProcureMindBaseSchema):
    target_type: TargetType
    target_id: uuid.UUID
    decision: DecisionType
    reviewer_label: str | None = Field(None, max_length=100)
    notes: str | None = None
    decided_at: datetime | None = None


class HumanDecisionCreate(HumanDecisionBase):
    pass


class HumanDecisionRead(HumanDecisionBase):
    id: uuid.UUID
    decided_at: datetime

    @field_validator("decided_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


# --- EvidenceReference ---
class EvidenceReferenceBase(ProcureMindBaseSchema):
    discrepancy_id: uuid.UUID | None = None
    allocation_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    extracted_field_id: uuid.UUID | None = None
    source_record_type: str | None = Field(None, max_length=50)
    source_record_id: uuid.UUID | None = None
    original_filename: str | None = Field(None, max_length=255)
    location_reference: str | None = Field(None, max_length=255)
    bounding_box: dict[str, Any] | None = None
    raw_value: str | None = None
    normalized_value: str | None = None
    extraction_method: ExtractionMethod | None = None
    review_state: ReviewState | None = None


class EvidenceReferenceCreate(EvidenceReferenceBase):
    pass


class EvidenceReferenceRead(EvidenceReferenceBase):
    id: uuid.UUID
    created_at: datetime

    @field_validator("created_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)
