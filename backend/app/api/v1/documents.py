"""
Document management and ingestion API endpoints for ProcureMind.

Provides:
- POST /api/v1/documents: Multipart upload, format/signature validation, SHA-256 deduplication.
- GET /api/v1/documents: Registry listing ordered by upload time.
- GET /api/v1/documents/{id}: Document metadata inspection.
- GET /api/v1/documents/{id}/download-url: Generates short-lived signed download link.
- GET /api/v1/documents/{id}/download: Validates signed token in constant time, fetches from Postgres, and streams file.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import verify_auditor_key
from app.core.config import settings
from app.core.database import get_db
from app.models.document import Document, ExtractedField, FieldAuditLog
from app.models.enums import ExtractionMethod, ProcessingStatus, ReviewState
from app.schemas.document import (
    DocumentRead,
    DocumentUploadResponse,
    DownloadUrlResponse,
    ExtractedFieldRead,
    PreviewUrlResponse,
)
from app.schemas.extraction import (
    DocumentExtractionRequest,
    DocumentExtractionResponse,
    ExtractedFieldCorrectionResponse,
    FieldAuditLogRead,
    FieldCorrectionRequest,
)
from app.schemas.parser import ParsedDocument
from app.services.document_service import (
    compute_sha256,
    create_download_token,
    generate_server_storage_key,
    validate_uploaded_document,
    verify_download_token,
)
from app.services.llm.extraction_interface import StructuredExtractionProviderInterface
from app.services.llm.factory import get_extraction_provider
from app.services.parser_service import parse_document
from app.services.structured_extraction import extract_document
from app.storage.interface import get_storage_service

router = APIRouter()


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and register a document",
)
async def upload_document(
    response: Response,
    file: UploadFile = File(..., description="Uploaded document (PDF, XLSX, CSV, PNG, JPG)"),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """
    Accepts multipart document uploads:
    - Validates file size, non-empty content, and allowed extensions.
    - Validates binary magic-byte signatures (or bounded UTF-8 text for CSV).
    - Computes cryptographic SHA-256 digest.
    - Performs duplicate detection: if identical file was previously uploaded,
      returns existing document ID with HTTP 200 OK (no duplicate storage/DB records).
    - Otherwise, saves to private storage under server-generated key and registers document.
    """
    filename = file.filename or "unknown"
    content = await file.read()

    # 1. Validate content format & sanitize name
    sanitized_name, ext, media_type, doc_type = validate_uploaded_document(filename, content)

    # 2. Compute SHA-256
    sha256 = compute_sha256(content)

    # 3. Duplicate check in PostgreSQL
    existing_doc = db.query(Document).filter(Document.sha256 == sha256).first()
    if existing_doc:
        response.status_code = status.HTTP_200_OK
        return DocumentUploadResponse(
            document=DocumentRead.model_validate(existing_doc),
            is_duplicate=True,
            message="Document already exists with identical SHA-256 content",
        )

    # 4. Generate safe server storage key & write to private storage
    storage_key = generate_server_storage_key(ext)
    storage = get_storage_service()
    storage.save_file(storage_key, content)

    # 5. Persist Document record
    now_utc = datetime.now(UTC)
    new_doc = Document(
        id=uuid.uuid4(),
        original_filename=sanitized_name,
        media_type=media_type,
        size_bytes=len(content),
        sha256=sha256,
        storage_key=storage_key,
        document_type=doc_type,
        upload_time=now_utc,
        processing_status=ProcessingStatus.UPLOADED,
        is_demo=False,
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)

    return DocumentUploadResponse(
        document=DocumentRead.model_validate(new_doc),
        is_duplicate=False,
        message="Document uploaded and registered successfully",
    )


@router.get(
    "",
    response_model=list[DocumentRead],
    summary="List all registered documents",
)
def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[DocumentRead]:
    """Retrieves all registered documents ordered by upload time descending."""
    docs = db.query(Document).order_by(Document.upload_time.desc()).offset(skip).limit(limit).all()
    return [DocumentRead.model_validate(d) for d in docs]


@router.get(
    "/{document_id}",
    response_model=DocumentRead,
    summary="Get document details by ID",
)
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> DocumentRead:
    """Retrieves metadata for a specific document."""
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found",
        )
    return DocumentRead.model_validate(doc)


@router.get(
    "/{document_id}/download-url",
    response_model=DownloadUrlResponse,
    summary="Generate short-lived signed download URL",
)
def get_document_download_url(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> DownloadUrlResponse:
    """
    Generates a temporary signed download link for an authorized document.
    Link expires after configured duration (default: 300 seconds).
    """
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found",
        )

    duration = settings.DOWNLOAD_URL_EXPIRES_SECONDS
    expires_at = datetime.now(UTC) + timedelta(seconds=duration)
    expires_ts = int(expires_at.timestamp())

    token = create_download_token(doc.id, expires_ts)
    download_url = (
        f"{settings.API_V1_STR}/documents/{doc.id}/download?expires={expires_ts}&token={token}"
    )

    return DownloadUrlResponse(
        download_url=download_url,
        expires_in_seconds=duration,
        expires_at=expires_at,
    )


@router.get(
    "/{document_id}/download",
    summary="Download document using signed token",
)
def download_document(
    document_id: uuid.UUID,
    expires: int = Query(..., description="UTC expiration timestamp"),
    token: str = Query(..., description="HMAC-SHA256 download authorization token"),
    db: Session = Depends(get_db),
) -> Response:
    """
    Validates short-lived download token in constant time, looks up the document's
    server storage key from PostgreSQL, and streams file bytes.
    """
    # 1. Constant-time token verification & expiration check
    if not verify_download_token(document_id, expires, token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download link is invalid or has expired",
        )

    # 2. Look up storage key from PostgreSQL
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found",
        )

    # 3. Retrieve file from private storage
    storage = get_storage_service()
    try:
        content = storage.get_file(doc.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file data not found in storage",
        ) from exc

    return Response(
        content=content,
        media_type=doc.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.original_filename}"',
            "Cache-Control": "private, no-cache, no-store, must-revalidate",
        },
    )


@router.get(
    "/{document_id}/preview-url",
    response_model=PreviewUrlResponse,
    summary="Generate short-lived signed preview URL",
)
def get_document_preview_url(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> PreviewUrlResponse:
    """
    Generates a temporary signed preview link for an authorized document.
    Link expires after configured duration (default: 300 seconds).
    """
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found",
        )

    duration = settings.DOWNLOAD_URL_EXPIRES_SECONDS
    expires_at = datetime.now(UTC) + timedelta(seconds=duration)
    expires_ts = int(expires_at.timestamp())

    token = create_download_token(doc.id, expires_ts)
    preview_url = (
        f"{settings.API_V1_STR}/documents/{doc.id}/preview?expires={expires_ts}&token={token}"
    )

    return PreviewUrlResponse(
        preview_url=preview_url,
        expires_in_seconds=duration,
        expires_at=expires_at,
    )


@router.get(
    "/{document_id}/preview",
    summary="Preview document inline using signed token",
)
def preview_document(
    document_id: uuid.UUID,
    expires: int = Query(..., description="UTC expiration timestamp"),
    token: str = Query(..., description="HMAC-SHA256 authorization token"),
    db: Session = Depends(get_db),
) -> Response:
    """
    Validates short-lived signed token in constant time, looks up document storage key,
    and returns content with Content-Disposition: inline and security headers for safe sandboxed iframe rendering.
    """
    if not verify_download_token(document_id, expires, token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Preview link is invalid or has expired",
        )

    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found",
        )

    storage = get_storage_service()
    try:
        content = storage.get_file(doc.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document file data not found in storage",
        ) from exc

    return Response(
        content=content,
        media_type=doc.media_type,
        headers={
            "Content-Disposition": f'inline; filename="{doc.original_filename}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox allow-scripts",
            "Cache-Control": "private, no-cache, no-store, must-revalidate",
        },
    )


@router.post(
    "/{document_id}/parse",
    response_model=ParsedDocument,
    summary="Deterministically parse document text and tables with selective OCR fallback",
)
def parse_document_endpoint(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> ParsedDocument:
    """Deterministically parses text and tables from an uploaded document in private storage.

    Selectively invokes OCR only for image documents or PDF pages without usable embedded text.
    Updates processing_status to 'parsed' and sets page_count upon success.
    Protects terminal states ('approved', 'rejected') from modification.
    """
    return parse_document(db=db, document_id=str(document_id))


@router.post(
    "/{document_id}/extract",
    response_model=DocumentExtractionResponse,
    summary="Extract structured data (invoice, receipt, or form) using validated LLM",
)
async def extract_document_endpoint(
    document_id: uuid.UUID,
    payload: DocumentExtractionRequest,
    db: Session = Depends(get_db),
    provider: StructuredExtractionProviderInterface = Depends(get_extraction_provider),
) -> DocumentExtractionResponse:
    """Extract structured data from a parsed document using LLM.

    Accepts an explicit document_kind ('invoice', 'receipt', or 'form').
    Reconstructs provenance from Phase 7 source index.
    Enforces schema validation, retry safety, arithmetic verification, and idempotency.
    Protects terminal states ('approved', 'rejected') and serializes concurrent requests.
    """
    return await extract_document(
        db=db,
        document_id=str(document_id),
        document_kind=payload.document_kind,
        provider=provider,
    )


@router.get(
    "/{document_id}/fields",
    response_model=list[ExtractedFieldRead],
    summary="List all extracted fields for a document with bounding boxes and review states",
)
def list_document_fields(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[ExtractedFieldRead]:
    """Retrieves all extracted fields belonging to a document ordered by page and location."""
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID '{document_id}' not found",
        )

    fields = (
        db.query(ExtractedField)
        .filter(ExtractedField.document_id == document_id)
        .order_by(ExtractedField.page_number.asc().nullsfirst(), ExtractedField.field_name.asc())
        .all()
    )
    return [ExtractedFieldRead.model_validate(f) for f in fields]


@router.patch(
    "/{document_id}/fields/{field_id}",
    response_model=ExtractedFieldCorrectionResponse,
    summary="Auditor correction of an extracted field value with immutable audit logging",
)
def correct_extracted_field(
    document_id: uuid.UUID,
    field_id: uuid.UUID,
    payload: FieldCorrectionRequest,
    _auth: str = Depends(verify_auditor_key),
    db: Session = Depends(get_db),
) -> ExtractedFieldCorrectionResponse:
    """
    Applies an auditor manual correction to an extracted field:
    - Retains original raw_value as immutable source text.
    - Updates normalized_value to the auditor's corrected input.
    - Sets extraction_method to 'manual' and review_state to 'human_verified'.
    - Stamped with reviewer_label and UTC timestamp.
    - Creates an append-only FieldAuditLog entry preserving full before/after values and snapshot IDs.
    """
    field = (
        db.query(ExtractedField)
        .filter(
            ExtractedField.id == field_id,
            ExtractedField.document_id == document_id,
        )
        .first()
    )
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Extracted field '{field_id}' not found on document '{document_id}'",
        )

    now_utc = datetime.now(UTC)
    old_val = field.normalized_value

    audit_entry = FieldAuditLog(
        id=uuid.uuid4(),
        document_id=field.document_id,
        extracted_field_id=field.id,
        document_id_snapshot=field.document_id,
        extracted_field_id_snapshot=field.id,
        field_name=field.field_name,
        old_normalized_value=old_val,
        new_normalized_value=payload.new_normalized_value,
        reviewer_label=payload.reviewer_label,
        notes=payload.notes,
        created_at=now_utc,
    )
    db.add(audit_entry)

    field.normalized_value = payload.new_normalized_value
    field.extraction_method = ExtractionMethod.MANUAL
    field.review_state = ReviewState.HUMAN_VERIFIED
    field.reviewed_by = payload.reviewer_label
    field.reviewed_at = now_utc

    db.commit()
    db.refresh(field)
    db.refresh(audit_entry)

    return ExtractedFieldCorrectionResponse(
        field=ExtractedFieldRead.model_validate(field),
        audit_log=FieldAuditLogRead.model_validate(audit_entry),
    )


@router.get(
    "/{document_id}/fields/{field_id}/audit-trail",
    response_model=list[FieldAuditLogRead],
    summary="Get permanent audit history of corrections for an extracted field",
)
def get_field_audit_trail(
    document_id: uuid.UUID,
    field_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[FieldAuditLogRead]:
    """Returns all audit log records for the field, ordered chronologically."""
    logs = (
        db.query(FieldAuditLog)
        .filter(FieldAuditLog.extracted_field_id_snapshot == field_id)
        .order_by(FieldAuditLog.created_at.asc())
        .all()
    )
    return [FieldAuditLogRead.model_validate(log) for log in logs]
