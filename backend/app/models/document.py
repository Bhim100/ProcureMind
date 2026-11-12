"""
Document and ExtractedField models for ProcureMind.

This module defines:
- `Document`: Represents an uploaded document (PDF, Excel, Scan), its SHA-256 hash, storage location, and lifecycle status.
- `ExtractedField`: Represents individual fields extracted from a document, retaining full source provenance (page, bounding box, raw value, extraction method, review state).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import GUID, JSON_VARIANT, Base, TimestampMixin, UUIDPrimaryKeyMixin, utc_now
from app.models.enums import DocumentType, ExtractionMethod, ProcessingStatus, ReviewState

if TYPE_CHECKING:
    from app.models.reconciliation import EvidenceReference


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Represents an ingested commercial or financial document.

    The SHA-256 hash is uniquely indexed to guarantee duplicate file uploads
    are immediately detected and deduplicated.
    """

    __tablename__ = "documents"

    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Sanitized original filename as uploaded by the user",
    )
    media_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="MIME type of the file (e.g. application/pdf, image/png)",
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Exact size of the uploaded file in bytes",
    )
    sha256: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
        comment="Cryptographic SHA-256 checksum for deduplication and integrity check",
    )
    storage_key: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Path or key in storage backend (local disk path or S3 object key)",
    )
    document_type: Mapped[DocumentType] = mapped_column(
        SQLEnum(DocumentType, name="document_type_enum"),
        nullable=False,
        default=DocumentType.OTHER,
        comment="Class of document: invoice, shipping_bill, bank_statement, etc.",
    )
    upload_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        comment="Exact UTC timestamp when the file upload was recorded",
    )
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        SQLEnum(ProcessingStatus, name="processing_status_enum"),
        default=ProcessingStatus.UPLOADED,
        nullable=False,
        index=True,
        comment="Current processing stage: uploaded, parsed, extracted, needs_review, approved, rejected",
    )
    page_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Total page count if document is a multi-page PDF",
    )
    is_demo: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Flag indicating if this document is seeded synthetic demo data",
    )
    source_system: Mapped[str] = mapped_column(
        String(50),
        default="manual_upload",
        nullable=False,
        comment="Ingestion origin (e.g. manual_upload, zoho_books, email_ingest)",
    )
    source_external_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="External record identifier in source system (e.g. Zoho invoice_id)",
    )

    # Relationships
    extracted_fields: Mapped[list["ExtractedField"]] = relationship(
        "ExtractedField",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    evidence_references: Mapped[list["EvidenceReference"]] = relationship(
        "EvidenceReference",
        back_populates="document",
        foreign_keys="EvidenceReference.document_id",
    )
    field_audit_logs: Mapped[list["FieldAuditLog"]] = relationship(
        "FieldAuditLog",
        back_populates="document",
        foreign_keys="FieldAuditLog.document_id",
    )


class ExtractedField(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Represents an atomic field extracted from a document.

    Retains granular provenance including bounding box coordinates,
    page/row location, raw OCR/text value, normalized output, and extraction method.
    """

    __tablename__ = "extracted_fields"

    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key to the source Document",
    )
    field_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Canonical field key (e.g. invoice_number, total_amount, issue_date)",
    )
    raw_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Exact raw text snippet as found on the physical page",
    )
    normalized_value: Mapped[Any | None] = mapped_column(
        JSON_VARIANT,
        nullable=True,
        comment="Standardized typed value (Decimal string, ISO date, or parsed structure)",
    )
    page_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="1-based page index where this field was extracted",
    )
    row_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Row number if extracted from a structured spreadsheet/table",
    )
    bounding_box: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_VARIANT,
        nullable=True,
        comment="Normalized coordinates {x0, y0, x1, y1} of the field bounding box on the page",
    )
    confidence: Mapped[float | None] = mapped_column(
        Numeric(5, 4),
        nullable=True,
        comment="OCR or extraction model confidence score between 0.0000 and 1.0000",
    )
    review_state: Mapped[ReviewState] = mapped_column(
        SQLEnum(ReviewState, name="review_state_enum"),
        default=ReviewState.PENDING,
        nullable=False,
        index=True,
        comment="Audit state: pending, auto_accepted, human_verified, rejected",
    )
    extraction_method: Mapped[ExtractionMethod] = mapped_column(
        SQLEnum(ExtractionMethod, name="extraction_method_enum"),
        default=ExtractionMethod.TEXT,
        nullable=False,
        comment="Method utilized: text, ocr, llm, manual",
    )
    reviewed_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Identifier or username of human auditor if manually reviewed",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="UTC timestamp when review took place",
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="extracted_fields")
    evidence_references: Mapped[list["EvidenceReference"]] = relationship(
        "EvidenceReference",
        back_populates="extracted_field",
        foreign_keys="EvidenceReference.extracted_field_id",
    )
    field_audit_logs: Mapped[list["FieldAuditLog"]] = relationship(
        "FieldAuditLog",
        back_populates="extracted_field",
        foreign_keys="FieldAuditLog.extracted_field_id",
    )

    __table_args__ = (Index("ix_extracted_fields_doc_name", "document_id", "field_name"),)


class FieldAuditLog(Base, UUIDPrimaryKeyMixin):
    """
    Immutable audit trail recording all human corrections to extracted document fields.

    Retains full before-and-after values along with permanent snapshot identifiers.
    Foreign keys have ondelete='SET NULL' so audit logs are never cascade-deleted
    if an extracted field or document is deleted or re-extracted.
    """

    __tablename__ = "field_audit_logs"

    document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Source document foreign key (nullable if document is archived/deleted)",
    )
    extracted_field_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("extracted_fields.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Target extracted field foreign key (nullable if field is deleted)",
    )
    document_id_snapshot: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
        comment="Permanent immutable snapshot of the source document UUID",
    )
    extracted_field_id_snapshot: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
        comment="Permanent immutable snapshot of the extracted field UUID",
    )
    field_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Name of the corrected field",
    )
    old_normalized_value: Mapped[Any | None] = mapped_column(
        JSON_VARIANT,
        nullable=True,
        comment="Previous normalized value before correction",
    )
    new_normalized_value: Mapped[Any | None] = mapped_column(
        JSON_VARIANT,
        nullable=True,
        comment="New corrected normalized value",
    )
    reviewer_label: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Auditor identity or label who performed the correction",
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Optional auditor justification notes",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        comment="UTC timestamp when the field correction was recorded",
    )

    # Relationships
    document: Mapped["Document | None"] = relationship(
        "Document",
        back_populates="field_audit_logs",
        foreign_keys=[document_id],
    )
    extracted_field: Mapped["ExtractedField | None"] = relationship(
        "ExtractedField",
        back_populates="field_audit_logs",
        foreign_keys=[extracted_field_id],
    )
