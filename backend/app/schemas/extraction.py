"""Pydantic v2 schemas for Document Structured Extraction (Phase 8)."""

import uuid
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import Field

from app.models.enums import ExtractionMethod, ProcessingStatus, ReviewState
from app.schemas.common import ProcureMindBaseSchema
from app.schemas.document import ExtractedFieldRead


class DocumentKind(str, Enum):
    """Supported document types for structured extraction."""

    INVOICE = "invoice"
    RECEIPT = "receipt"
    FORM = "form"


class DocumentExtractionRequest(ProcureMindBaseSchema):
    """Payload for POST /api/v1/documents/{document_id}/extract."""

    document_kind: DocumentKind = Field(
        ...,
        description="Explicit document kind to extract ('invoice', 'receipt', or 'form')",
    )


class ExtractedFieldSummary(ProcureMindBaseSchema):
    """Summary of an extracted field with its server-reconstructed provenance."""

    id: uuid.UUID
    field_name: str
    field_value: Any | None = None
    raw_value: str | None = None
    confidence: Decimal | None = None
    review_state: ReviewState = ReviewState.PENDING
    extraction_method: ExtractionMethod = ExtractionMethod.LLM
    page_number: int | None = None
    row_number: int | None = None
    bounding_box: dict[str, Any] | None = None
    source_ids: list[str] = Field(default_factory=list)


class DocumentExtractionResponse(ProcureMindBaseSchema):
    """Response returned upon completion of structured extraction."""

    document_id: uuid.UUID
    document_kind: DocumentKind
    status: ProcessingStatus
    extracted_fields: list[ExtractedFieldSummary]
    warnings: list[str] = Field(default_factory=list)
    created_invoice_id: uuid.UUID | None = None


class FieldCorrectionRequest(ProcureMindBaseSchema):
    """Payload submitted by an auditor to correct a normalized extracted field."""

    new_normalized_value: Any
    reviewer_label: str = Field(..., min_length=2, max_length=100)
    notes: str | None = None


class FieldAuditLogRead(ProcureMindBaseSchema):
    """Read representation of an immutable field audit log entry."""

    id: uuid.UUID
    document_id: uuid.UUID | None = None
    extracted_field_id: uuid.UUID | None = None
    document_id_snapshot: uuid.UUID
    extracted_field_id_snapshot: uuid.UUID
    field_name: str
    old_normalized_value: Any | None = None
    new_normalized_value: Any | None = None
    reviewer_label: str
    notes: str | None = None
    created_at: Any


class ExtractedFieldCorrectionResponse(ProcureMindBaseSchema):
    """Response returned upon saving a manual field correction."""

    field: ExtractedFieldRead
    audit_log: FieldAuditLogRead
