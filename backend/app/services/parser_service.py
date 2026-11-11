"""Parser service orchestrating deterministic extraction, storage retrieval, and status updates."""

import logging
import uuid
from collections.abc import Callable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.extraction.constants import ExtractionError
from app.extraction.image_parser import parse_image
from app.extraction.ocr_adapter import perform_ocr
from app.extraction.pdf_parser import parse_pdf
from app.extraction.spreadsheet_parser import parse_csv, parse_xlsx
from app.models.base import utc_now
from app.models.document import Document
from app.models.enums import ProcessingStatus
from app.schemas.parser import ParsedDocument, ParsedTextBlock
from app.storage.interface import LocalStorageService

logger = logging.getLogger(__name__)


def parse_document(
    db: Session,
    document_id: str,
    ocr_func: Callable[..., list[ParsedTextBlock]] | None = None,
) -> ParsedDocument:
    """Parse an uploaded document into structured text blocks and tables.

    Retrieves document from PostgreSQL and private storage, deterministically parses
    content using appropriate parser with selective OCR, updates document status, and returns
    structured ParsedDocument.

    Terminal status protection (Rule 3):
    - Documents in terminal states ('approved' or 'rejected') are never downgraded or mutated
      to 'parsed' or 'needs_review'.
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    doc = db.query(Document).filter(Document.id == doc_uuid).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    is_terminal = doc.processing_status in (
        ProcessingStatus.APPROVED,
        ProcessingStatus.REJECTED,
    )

    # Retrieve file bytes from storage
    storage = LocalStorageService()
    try:
        file_bytes = storage.get_file(doc.storage_key)
    except Exception as exc:
        logger.error(f"Failed to retrieve file from storage for document {doc.id}")
        if not is_terminal:
            doc.processing_status = ProcessingStatus.NEEDS_REVIEW
            doc.updated_at = utc_now()
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document storage retrieval failed",
        ) from exc

    filename = doc.original_filename or "document"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    media_type = doc.media_type or "application/octet-stream"

    parsed: ParsedDocument
    try:
        if ext == "pdf" or media_type == "application/pdf":
            parsed = parse_pdf(
                file_bytes=file_bytes,
                document_id=str(doc.id),
                filename=filename,
                media_type=media_type,
                ocr_func=ocr_func or perform_ocr,
            )
        elif (
            ext == "xlsx"
            or media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ):
            parsed = parse_xlsx(
                file_bytes=file_bytes,
                document_id=str(doc.id),
                filename=filename,
                media_type=media_type,
            )
        elif ext == "csv" or media_type == "text/csv":
            parsed = parse_csv(
                file_bytes=file_bytes,
                document_id=str(doc.id),
                filename=filename,
                media_type=media_type,
            )
        elif ext in ("png", "jpg", "jpeg") or media_type.startswith("image/"):
            parsed = parse_image(
                file_bytes=file_bytes,
                document_id=str(doc.id),
                filename=filename,
                media_type=media_type,
                ocr_func=ocr_func or perform_ocr,
            )
        else:
            logger.warning(f"Unsupported file format for parsing document {doc.id}")
            if not is_terminal:
                doc.processing_status = ProcessingStatus.NEEDS_REVIEW
                doc.updated_at = utc_now()
                db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type for parsing: {ext}",
            )
    except ExtractionError as e:
        logger.error(f"Deterministic extraction failed for document {doc.id}")
        if not is_terminal:
            doc.processing_status = ProcessingStatus.NEEDS_REVIEW
            doc.updated_at = utc_now()
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.safe_detail,
        ) from e
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Unexpected parsing failure for document {doc.id}")
        if not is_terminal:
            doc.processing_status = ProcessingStatus.NEEDS_REVIEW
            doc.updated_at = utc_now()
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document parsing failed",
        ) from exc

    # Enforce total response payload budget
    output_json_size = len(parsed.model_dump_json().encode("utf-8"))
    if output_json_size > settings.PARSER_MAX_TOTAL_OUTPUT_BYTES:
        logger.warning(f"Parsed document output {doc.id} exceeded maximum payload budget")
        if not is_terminal:
            doc.processing_status = ProcessingStatus.NEEDS_REVIEW
            doc.updated_at = utc_now()
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document parsed output exceeds maximum payload budget",
        )

    # Update document metadata in PostgreSQL
    if parsed.page_count and parsed.page_count > 0:
        doc.page_count = parsed.page_count

    doc.updated_at = utc_now()
    if not is_terminal:
        doc.processing_status = ProcessingStatus.PARSED

    db.commit()
    db.refresh(doc)

    return parsed
