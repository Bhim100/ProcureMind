"""
Pydantic v2 schemas for Document and ExtractedField.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, field_validator

from app.models.enums import DocumentType, ExtractionMethod, ProcessingStatus, ReviewState
from app.schemas.common import ProcureMindBaseSchema, ensure_utc_datetime


class DocumentBase(ProcureMindBaseSchema):
    original_filename: str = Field(
        ..., max_length=255, description="Sanitized original document name"
    )
    media_type: str = Field(..., max_length=100, description="MIME type of the file")
    size_bytes: int = Field(..., ge=0, description="File size in bytes")
    sha256: str = Field(
        ..., min_length=64, max_length=64, description="SHA-256 hash (64 hex characters)"
    )
    storage_key: str = Field(..., max_length=500, description="Storage path or key")
    document_type: DocumentType = DocumentType.OTHER
    processing_status: ProcessingStatus = ProcessingStatus.UPLOADED
    page_count: int | None = Field(None, ge=1)
    is_demo: bool = False
    source_system: str = Field(
        default="manual_upload", max_length=50, description="Ingestion origin system"
    )
    source_external_id: str | None = Field(
        default=None, max_length=100, description="External ID in source system"
    )

    @field_validator("sha256")
    @classmethod
    def validate_sha256_hex(cls, v: str) -> str:
        clean = v.strip().lower()
        if len(clean) != 64 or not all(c in "0123456789abcdef" for c in clean):
            raise ValueError("sha256 must be a 64-character lowercase hex string")
        return clean


class DocumentCreate(DocumentBase):
    pass


class DocumentUpdate(ProcureMindBaseSchema):
    processing_status: ProcessingStatus | None = None
    page_count: int | None = Field(None, ge=1)
    document_type: DocumentType | None = None


class DocumentRead(DocumentBase):
    id: uuid.UUID
    upload_time: datetime
    created_at: datetime
    updated_at: datetime

    @field_validator("upload_time", "created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


class DocumentUploadResponse(ProcureMindBaseSchema):
    """API response returned when a document is uploaded."""

    document: DocumentRead
    is_duplicate: bool = Field(
        default=False, description="True if identical file was previously uploaded"
    )
    message: str = Field(default="Document uploaded successfully")


class DownloadUrlResponse(ProcureMindBaseSchema):
    """API response containing a short-lived download link."""

    download_url: str = Field(..., description="Short-lived signed URL for downloading document")
    expires_in_seconds: int = Field(..., description="Duration in seconds before token expires")
    expires_at: datetime = Field(..., description="Exact UTC timestamp when download link expires")

    @field_validator("expires_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


class PreviewUrlResponse(ProcureMindBaseSchema):
    """API response containing a short-lived inline preview link."""

    preview_url: str = Field(
        ..., description="Short-lived signed URL for previewing document inline"
    )
    expires_in_seconds: int = Field(..., description="Duration in seconds before token expires")
    expires_at: datetime = Field(..., description="Exact UTC timestamp when preview link expires")

    @field_validator("expires_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


class ExtractedFieldBase(ProcureMindBaseSchema):
    field_name: str = Field(..., max_length=100)
    raw_value: str | None = None
    normalized_value: Any | None = None
    page_number: int | None = Field(None, ge=1)
    row_number: int | None = Field(None, ge=1)
    bounding_box: dict[str, Any] | None = None
    confidence: Decimal | None = Field(None, ge=Decimal("0.0000"), le=Decimal("1.0000"))
    review_state: ReviewState = ReviewState.PENDING
    extraction_method: ExtractionMethod = ExtractionMethod.TEXT
    reviewed_by: str | None = Field(None, max_length=100)
    reviewed_at: datetime | None = None


class ExtractedFieldCreate(ExtractedFieldBase):
    document_id: uuid.UUID


class ExtractedFieldRead(ExtractedFieldBase):
    id: uuid.UUID
    document_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)
