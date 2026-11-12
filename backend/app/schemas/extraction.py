"""Pydantic v2 schemas for Document Structured Extraction (Phase 8)."""

import uuid
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import Field

from app.models.enums import ExtractionMethod, ProcessingStatus, ReviewState
from app.schemas.common import ProcureMindBaseSchema


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
