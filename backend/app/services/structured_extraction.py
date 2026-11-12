"""Structured document extraction service for commercial invoices, receipts, and forms."""

import asyncio
import logging
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.extraction.constants import has_usable_text
from app.extraction.source_index import SourceIndex, build_source_index
from app.extraction.structured_schemas import (
    ExtractedFieldData,
    FormExtraction,
    InvoiceExtraction,
    ReceiptExtraction,
)
from app.models.base import utc_now
from app.models.document import Document, ExtractedField
from app.models.enums import ExtractionMethod, ProcessingStatus, ReviewState
from app.models.export import Invoice, InvoiceLineItem
from app.models.reconciliation import EvidenceReference
from app.schemas.extraction import (
    DocumentExtractionResponse,
    DocumentKind,
    ExtractedFieldSummary,
)
from app.services.llm.extraction_interface import (
    ExtractionProviderError,
    StructuredExtractionProviderInterface,
)
from app.services.llm.factory import get_extraction_provider
from app.services.parser_service import parse_document_bytes
from app.storage.interface import LocalStorageService

logger = logging.getLogger(__name__)

# Registry of in-memory async locks per document ID to prevent same-worker event-loop blocking
_document_locks: dict[uuid.UUID, asyncio.Lock] = {}
_document_locks_guard = asyncio.Lock()


async def get_document_lock(doc_id: uuid.UUID) -> asyncio.Lock:
    """Retrieve or create an in-process asyncio.Lock for a specific document ID."""
    async with _document_locks_guard:
        if doc_id not in _document_locks:
            _document_locks[doc_id] = asyncio.Lock()
        return _document_locks[doc_id]


def _sanitize_validation_error(exc: ValidationError) -> str:
    """Sanitize validation error messages to exclude rejected input values and PII.

    Returns only the field path, error message, and validation error type.
    """
    sanitized: list[str] = []
    for err in exc.errors():
        loc = " -> ".join(str(p) for p in err.get("loc", []))
        msg = err.get("msg", "Validation error")
        err_type = err.get("type", "value_error")
        sanitized.append(f"Field path '{loc}': {msg} (error_type: {err_type})")
    return "\n".join(sanitized)


def document_has_usable_text(parsed_doc: Any) -> bool:
    """Check if the parsed document contains sufficient text or tabular content."""
    collected_text: list[str] = []
    for page in getattr(parsed_doc, "pages", []):
        for block in page.text_blocks:
            if block.text:
                collected_text.append(block.text)
        for table in page.tables:
            for row in table.rows:
                collected_text.extend([c for c in row if c])
    for sheet in getattr(parsed_doc, "sheets", []):
        for row in sheet.rows:
            collected_text.extend([c for c in row.cells if c])

    full_text = " ".join(collected_text)
    return has_usable_text(full_text)


def _extract_provenance(
    source_ids: list[str],
    source_index: SourceIndex,
    warnings: list[str],
) -> tuple[str | None, int | None, int | None, dict[str, Any] | None, list[str]]:
    """Derive raw value, page, row, and bounding box from server-side source index."""
    valid_sids: list[str] = []
    raw_texts: list[str] = []
    page_num: int | None = None
    row_num: int | None = None
    bbox: dict[str, Any] | None = None

    for sid in source_ids:
        entry = source_index.entries.get(sid)
        if entry is None:
            warnings.append(f"Unrecognized source ID: '{sid}'")
            continue
        valid_sids.append(sid)
        raw_texts.append(entry.text)
        if page_num is None and entry.page_number is not None:
            page_num = entry.page_number
        if row_num is None and entry.row_number is not None:
            row_num = entry.row_number
        if bbox is None and entry.bbox is not None:
            bbox = entry.bbox

    raw_value = " ".join(raw_texts) if raw_texts else None
    return raw_value, page_num, row_num, bbox, valid_sids


def _persist_field(
    db: Session,
    doc: Document,
    field_name: str,
    field_data: ExtractedFieldData[Any],
    source_index: SourceIndex,
    warnings: list[str],
) -> ExtractedFieldSummary:
    """Persist an ExtractedField and corresponding EvidenceReference row."""
    if not field_data.is_present:
        ef = ExtractedField(
            id=uuid.uuid4(),
            document_id=doc.id,
            field_name=field_name,
            raw_value=None,
            normalized_value=None,
            page_number=None,
            row_number=None,
            bounding_box=None,
            confidence=Decimal(str(field_data.confidence))
            if field_data.confidence is not None
            else None,
            review_state=ReviewState.PENDING,
            extraction_method=ExtractionMethod.LLM,
        )
        db.add(ef)
        return ExtractedFieldSummary(
            id=ef.id,
            field_name=field_name,
            field_value=None,
            raw_value=None,
            confidence=Decimal(str(field_data.confidence))
            if field_data.confidence is not None
            else None,
            review_state=ef.review_state,
            extraction_method=ef.extraction_method,
            page_number=None,
            row_number=None,
            bounding_box=None,
            source_ids=[],
        )

    raw_val, page, row, bbox, valid_sids = _extract_provenance(
        field_data.source_ids, source_index, warnings
    )

    conf_decimal = (
        Decimal(str(field_data.confidence)) if field_data.confidence is not None else None
    )
    if conf_decimal is not None and conf_decimal < Decimal("0.85"):
        warnings.append(f"Field '{field_name}' confidence ({conf_decimal}) is below threshold 0.85")

    ef = ExtractedField(
        id=uuid.uuid4(),
        document_id=doc.id,
        field_name=field_name,
        raw_value=raw_val,
        normalized_value=field_data.value,
        page_number=page,
        row_number=row,
        bounding_box=bbox,
        confidence=conf_decimal,
        review_state=ReviewState.PENDING,
        extraction_method=ExtractionMethod.LLM,
    )
    db.add(ef)

    # Attach EvidenceReference row tied strictly to document and field
    ev = EvidenceReference(
        id=uuid.uuid4(),
        document_id=doc.id,
        extracted_field_id=ef.id,
        original_filename=doc.original_filename,
        location_reference=", ".join(valid_sids) if valid_sids else None,
        bounding_box=bbox,
        raw_value=raw_val,
        normalized_value=str(field_data.value) if field_data.value is not None else None,
        extraction_method=ExtractionMethod.LLM,
        review_state=ReviewState.PENDING,
    )
    db.add(ev)

    return ExtractedFieldSummary(
        id=ef.id,
        field_name=field_name,
        field_value=field_data.value,
        raw_value=raw_val,
        confidence=conf_decimal,
        review_state=ef.review_state,
        extraction_method=ef.extraction_method,
        page_number=page,
        row_number=row,
        bounding_box=bbox,
        source_ids=valid_sids,
    )


async def extract_document(
    db: Session,
    document_id: str,
    document_kind: DocumentKind,
    provider: StructuredExtractionProviderInterface | None = None,
) -> DocumentExtractionResponse:
    """Extract structured data from an uploaded/parsed document.

    Serializes requests per document using an async lock and database row locking.
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    doc_lock = await get_document_lock(doc_uuid)

    async with doc_lock:
        # Acquire row lock across database sessions
        doc = db.query(Document).filter(Document.id == doc_uuid).with_for_update().first()
        if not doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        # 1. Terminal documents protection
        if doc.processing_status in (
            ProcessingStatus.APPROVED,
            ProcessingStatus.REJECTED,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot extract document in terminal status '{doc.processing_status.value}'.",
            )

        # 2. Duplicate extraction protection for NEEDS_REVIEW documents
        if doc.processing_status == ProcessingStatus.NEEDS_REVIEW:
            existing_llm_fields = (
                db.query(ExtractedField)
                .filter(
                    ExtractedField.document_id == doc.id,
                    ExtractedField.extraction_method == ExtractionMethod.LLM,
                )
                .count()
            )
            if existing_llm_fields > 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Document is in needs_review status and already contains extracted fields. Cannot duplicate or overwrite prior extraction.",
                )

        # 3. Idempotent return for already EXTRACTED documents
        if doc.processing_status == ProcessingStatus.EXTRACTED:
            existing_fields = (
                db.query(ExtractedField).filter(ExtractedField.document_id == doc.id).all()
            )
            existing_invoice = db.query(Invoice).filter(Invoice.document_id == doc.id).first()
            existing_summaries: list[ExtractedFieldSummary] = []
            for ef in existing_fields:
                evs = (
                    db.query(EvidenceReference)
                    .filter(EvidenceReference.extracted_field_id == ef.id)
                    .all()
                )
                sids: list[str] = []
                for ev in evs:
                    if ev.location_reference:
                        sids.extend(
                            [s.strip() for s in ev.location_reference.split(",") if s.strip()]
                        )
                existing_summaries.append(
                    ExtractedFieldSummary(
                        id=ef.id,
                        field_name=ef.field_name,
                        field_value=ef.normalized_value,
                        raw_value=ef.raw_value,
                        confidence=Decimal(str(ef.confidence))
                        if ef.confidence is not None
                        else None,
                        review_state=ef.review_state,
                        extraction_method=ef.extraction_method,
                        page_number=ef.page_number,
                        row_number=ef.row_number,
                        bounding_box=ef.bounding_box,
                        source_ids=sids,
                    )
                )
            return DocumentExtractionResponse(
                document_id=doc.id,
                document_kind=document_kind,
                status=doc.processing_status,
                extracted_fields=existing_summaries,
                warnings=["Document was previously extracted; returning existing records."],
                created_invoice_id=existing_invoice.id if existing_invoice else None,
            )

        # 4. Storage retrieval and in-memory parsing (no DB commit, lock maintained)
        storage = LocalStorageService()
        try:
            file_bytes = storage.get_file(doc.storage_key)
        except Exception as exc:
            logger.error(f"Storage retrieval failed for document {doc.id}")
            doc.processing_status = ProcessingStatus.NEEDS_REVIEW
            doc.updated_at = utc_now()
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document storage retrieval failed",
            ) from exc

        try:
            parsed_doc = parse_document_bytes(
                file_bytes=file_bytes,
                document_id=str(doc.id),
                filename=doc.original_filename or "document",
                media_type=doc.media_type or "application/octet-stream",
            )
        except Exception as exc:
            logger.error(f"Document parsing failed for document {doc.id}")
            doc.processing_status = ProcessingStatus.NEEDS_REVIEW
            doc.updated_at = utc_now()
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Document parsing failed",
            ) from exc

        if not document_has_usable_text(parsed_doc):
            logger.warning(f"No usable text found in document {doc.id}")
            doc.processing_status = ProcessingStatus.NEEDS_REVIEW
            doc.updated_at = utc_now()
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No usable text found in document",
            )

        # 5. Build source index and prepare prompt
        source_index = build_source_index(parsed_doc)

        kind_str = document_kind.value if hasattr(document_kind, "value") else str(document_kind)
        prompt_file = f"{kind_str}_v1.md"
        prompt_path = (
            Path(__file__).resolve().parent.parent / "extraction" / "prompts" / prompt_file
        )
        if not prompt_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Extraction prompt template '{prompt_file}' not found",
            )

        prompt_template = prompt_path.read_text(encoding="utf-8")
        prompt = prompt_template.replace("{document_content}", source_index.format_for_prompt())

        target_schema: type[BaseModel]
        if document_kind == DocumentKind.INVOICE:
            target_schema = InvoiceExtraction
        elif document_kind == DocumentKind.RECEIPT:
            target_schema = ReceiptExtraction
        elif document_kind == DocumentKind.FORM:
            target_schema = FormExtraction
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported document kind '{document_kind}'",
            )

        # 6. Execute extraction with provider & sanitized retry on validation error
        if provider is None:
            provider = get_extraction_provider()

        raw_data: dict[str, Any]
        try:
            raw_data = await provider.extract_structured(
                prompt=prompt,
                response_schema=target_schema,
            )
        except ExtractionProviderError as exc:
            if exc.status_code == 503:
                raise HTTPException(
                    status_code=503, detail="Structured extraction provider is unconfigured"
                )
            logger.warning(
                f"First provider call failed with status {exc.status_code}; retrying once"
            )
            try:
                raw_data = await provider.extract_structured(
                    prompt=prompt,
                    response_schema=target_schema,
                )
            except ExtractionProviderError as retry_exc:
                logger.error(f"Provider retry failed: {retry_exc.message}")
                raise HTTPException(status_code=retry_exc.status_code, detail=retry_exc.message)

        validated_output: Any
        try:
            validated_output = target_schema.model_validate(raw_data)
        except ValidationError as val_err:
            logger.warning(
                "Extraction output failed schema validation; retrying with sanitized error"
            )
            sanitized_err = _sanitize_validation_error(val_err)
            retry_prompt = (
                f"{prompt}\n\n"
                "CRITICAL SCHEMA VALIDATION ERROR IN PREVIOUS ATTEMPT:\n"
                f"{sanitized_err}\n\n"
                "Please fix the schema validation errors and return only valid JSON according strictly to the schema."
            )
            try:
                retry_raw_data = await provider.extract_structured(
                    prompt=retry_prompt,
                    response_schema=target_schema,
                )
                validated_output = target_schema.model_validate(retry_raw_data)
            except (ExtractionProviderError, ValidationError):
                logger.error(f"Second extraction attempt failed for document {doc.id}")
                doc.processing_status = ProcessingStatus.NEEDS_REVIEW
                doc.updated_at = utc_now()
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Extraction output failed schema validation after retry; document marked as needs_review.",
                )

        # 7. Persistence and domain entity creation
        warnings: list[str] = []
        field_summaries: list[ExtractedFieldSummary] = []
        low_confidence = False
        created_invoice_id: uuid.UUID | None = None

        if document_kind == DocumentKind.INVOICE:
            inv_data: InvoiceExtraction = validated_output

            # Persist header fields
            fields_to_persist = [
                ("invoice_number", inv_data.invoice_number),
                ("seller_name", inv_data.seller_name),
                ("buyer_name", inv_data.buyer_name),
                ("issue_date", inv_data.issue_date),
            ]
            if inv_data.due_date is not None:
                fields_to_persist.append(("due_date", inv_data.due_date))
            fields_to_persist.append(("currency", inv_data.currency))
            if inv_data.subtotal is not None and inv_data.subtotal.is_present:
                fields_to_persist.append(("subtotal", inv_data.subtotal))
            if inv_data.tax is not None and inv_data.tax.is_present:
                fields_to_persist.append(("tax", inv_data.tax))
            if inv_data.charges is not None and inv_data.charges.is_present:
                fields_to_persist.append(("charges", inv_data.charges))
            if inv_data.discounts is not None and inv_data.discounts.is_present:
                fields_to_persist.append(("discounts", inv_data.discounts))
            fields_to_persist.append(("total_amount", inv_data.total_amount))

            for fname, fdata in fields_to_persist:
                fs = _persist_field(db, doc, fname, fdata, source_index, warnings)
                field_summaries.append(fs)
                if fs.confidence is not None and fs.confidence < Decimal("0.85"):
                    low_confidence = True

            # Persist line items
            for item in inv_data.line_items:
                i = item.line_number
                for iname, ifield in [
                    (f"line_item_{i}_description", item.description),
                    (f"line_item_{i}_quantity", item.quantity),
                    (f"line_item_{i}_unit_price", item.unit_price),
                    (f"line_item_{i}_line_total", item.line_total),
                ]:
                    lfs = _persist_field(db, doc, iname, ifield, source_index, warnings)
                    field_summaries.append(lfs)
                    if lfs.confidence is not None and lfs.confidence < Decimal("0.85"):
                        low_confidence = True
                if item.hs_code and item.hs_code.is_present:
                    lfs_hs = _persist_field(
                        db, doc, f"line_item_{i}_hs_code", item.hs_code, source_index, warnings
                    )
                    field_summaries.append(lfs_hs)

            # Check required fields
            req_checks = [
                ("invoice_number", inv_data.invoice_number),
                ("seller_name", inv_data.seller_name),
                ("buyer_name", inv_data.buyer_name),
                ("currency", inv_data.currency),
                ("total_amount", inv_data.total_amount),
            ]
            for rname, rdata in req_checks:
                if not rdata.is_present or not rdata.value or not str(rdata.value).strip():
                    warnings.append(f"Required invoice field '{rname}' is missing")
                    low_confidence = True

            # Arithmetic verification
            arithmetic_mismatch = False
            total_amt: Decimal | None = None
            try:
                total_amt = Decimal(str(inv_data.total_amount.value))
            except (InvalidOperation, TypeError):
                warnings.append("total_amount is not a valid Decimal")
                arithmetic_mismatch = True

            # Derive base subtotal for math check
            base_subtotal: Decimal | None = None
            if inv_data.subtotal and inv_data.subtotal.is_present and inv_data.subtotal.value:
                try:
                    base_subtotal = Decimal(str(inv_data.subtotal.value))
                except (InvalidOperation, TypeError):
                    warnings.append("subtotal is not a valid Decimal")
                    arithmetic_mismatch = True
            elif inv_data.line_items:
                try:
                    computed_subtotal: Decimal = sum(
                        (Decimal(str(it.line_total.value)) for it in inv_data.line_items),
                        start=Decimal(0),
                    )
                    base_subtotal = computed_subtotal
                except (InvalidOperation, TypeError):
                    warnings.append("One or more line items have invalid line_total")
                    arithmetic_mismatch = True

            tax_amt: Decimal = Decimal(0)
            if inv_data.tax and inv_data.tax.is_present and inv_data.tax.value:
                try:
                    tax_amt = Decimal(str(inv_data.tax.value))
                except (InvalidOperation, TypeError):
                    warnings.append("tax is not a valid Decimal")
                    arithmetic_mismatch = True

            charges_amt: Decimal = Decimal(0)
            if inv_data.charges and inv_data.charges.is_present and inv_data.charges.value:
                try:
                    charges_amt = Decimal(str(inv_data.charges.value))
                except (InvalidOperation, TypeError):
                    warnings.append("charges is not a valid Decimal")
                    arithmetic_mismatch = True

            discounts_amt: Decimal = Decimal(0)
            if inv_data.discounts and inv_data.discounts.is_present and inv_data.discounts.value:
                try:
                    discounts_amt = Decimal(str(inv_data.discounts.value))
                except (InvalidOperation, TypeError):
                    warnings.append("discounts is not a valid Decimal")
                    arithmetic_mismatch = True

            if base_subtotal is not None and total_amt is not None:
                expected_total = base_subtotal + tax_amt + charges_amt - discounts_amt
                if expected_total != total_amt:
                    arithmetic_mismatch = True
                    warnings.append(
                        f"Arithmetic mismatch: expected total {expected_total} "
                        f"(subtotal {base_subtotal} + tax {tax_amt} + charges {charges_amt} - discounts {discounts_amt}) "
                        f"does not match extracted total {total_amt}"
                    )

            issue_date_val = None
            if inv_data.issue_date.is_present and inv_data.issue_date.value:
                try:
                    issue_date_val = datetime.strptime(inv_data.issue_date.value, "%Y-%m-%d").date()
                except ValueError:
                    warnings.append(
                        f"Invalid date format for issue_date: '{inv_data.issue_date.value}'"
                    )

            if low_confidence or arithmetic_mismatch or total_amt is None:
                doc.processing_status = ProcessingStatus.NEEDS_REVIEW
                created_invoice_id = None
            else:
                doc.processing_status = ProcessingStatus.EXTRACTED
                invoice = Invoice(
                    id=uuid.uuid4(),
                    invoice_number=str(inv_data.invoice_number.value),
                    seller_name=str(inv_data.seller_name.value),
                    buyer_name=str(inv_data.buyer_name.value),
                    issue_date=issue_date_val,
                    currency=str(inv_data.currency.value).upper(),
                    total_amount=total_amt,
                    document_id=doc.id,
                    is_demo=doc.is_demo,
                )
                db.add(invoice)

                for item in inv_data.line_items:
                    line_item = InvoiceLineItem(
                        id=uuid.uuid4(),
                        invoice_id=invoice.id,
                        line_number=item.line_number,
                        description=str(item.description.value or ""),
                        quantity=Decimal(str(item.quantity.value))
                        if item.quantity.value
                        else Decimal("1.0000"),
                        unit_price=Decimal(str(item.unit_price.value))
                        if item.unit_price.value
                        else Decimal("0.0000"),
                        total_amount=Decimal(str(item.line_total.value))
                        if item.line_total.value
                        else Decimal("0.0000"),
                        currency=str(inv_data.currency.value).upper(),
                        hs_code=str(item.hs_code.value)
                        if (item.hs_code and item.hs_code.is_present and item.hs_code.value)
                        else None,
                    )
                    db.add(line_item)

                created_invoice_id = invoice.id

        elif document_kind == DocumentKind.RECEIPT:
            rcpt_data: ReceiptExtraction = validated_output
            r_fields = [
                ("merchant_name", rcpt_data.merchant_name),
                ("date", rcpt_data.date),
                ("currency", rcpt_data.currency),
            ]
            if rcpt_data.subtotal and rcpt_data.subtotal.is_present:
                r_fields.append(("subtotal", rcpt_data.subtotal))
            if rcpt_data.tax and rcpt_data.tax.is_present:
                r_fields.append(("tax", rcpt_data.tax))
            r_fields.append(("total_amount", rcpt_data.total_amount))

            for rname, rdata in r_fields:
                rfs = _persist_field(db, doc, rname, rdata, source_index, warnings)
                field_summaries.append(rfs)
                if rfs.confidence is not None and rfs.confidence < Decimal("0.85"):
                    low_confidence = True

            for idx, rcpt_item in enumerate(rcpt_data.line_items, 1):
                lfs_desc = _persist_field(
                    db,
                    doc,
                    f"line_item_{idx}_description",
                    rcpt_item.description,
                    source_index,
                    warnings,
                )
                field_summaries.append(lfs_desc)
                lfs_tot = _persist_field(
                    db,
                    doc,
                    f"line_item_{idx}_line_total",
                    rcpt_item.line_total,
                    source_index,
                    warnings,
                )
                field_summaries.append(lfs_tot)
                if rcpt_item.quantity and rcpt_item.quantity.is_present:
                    lfs_qty = _persist_field(
                        db,
                        doc,
                        f"line_item_{idx}_quantity",
                        rcpt_item.quantity,
                        source_index,
                        warnings,
                    )
                    field_summaries.append(lfs_qty)

            if low_confidence:
                doc.processing_status = ProcessingStatus.NEEDS_REVIEW
            else:
                doc.processing_status = ProcessingStatus.EXTRACTED
            created_invoice_id = None

        elif document_kind == DocumentKind.FORM:
            form_data: FormExtraction = validated_output
            for entity in form_data.entities:
                efs = _persist_field(db, doc, entity.field_key, entity.data, source_index, warnings)
                field_summaries.append(efs)
                if efs.confidence is not None and efs.confidence < Decimal("0.85"):
                    low_confidence = True

            for rel in form_data.relationships:
                rel_name = f"rel_{rel.source_key}_{rel.relationship_type}_{rel.target_key}"
                rel_val = {
                    "source": rel.source_key,
                    "target": rel.target_key,
                    "type": rel.relationship_type,
                }
                # Form relationships don't need source IDs verification
                ef = ExtractedField(
                    id=uuid.uuid4(),
                    document_id=doc.id,
                    field_name=rel_name,
                    raw_value=None,
                    normalized_value=rel_val,
                    page_number=None,
                    row_number=None,
                    bounding_box=None,
                    confidence=Decimal("1.0000"),
                    review_state=ReviewState.PENDING,
                    extraction_method=ExtractionMethod.LLM,
                )
                db.add(ef)
                field_summaries.append(
                    ExtractedFieldSummary(
                        id=ef.id,
                        field_name=rel_name,
                        field_value=rel_val,
                        raw_value=None,
                        confidence=Decimal("1.0000"),
                        review_state=ReviewState.PENDING,
                        extraction_method=ExtractionMethod.LLM,
                        page_number=None,
                        row_number=None,
                        bounding_box=None,
                        source_ids=[],
                    )
                )

            if low_confidence:
                doc.processing_status = ProcessingStatus.NEEDS_REVIEW
            else:
                doc.processing_status = ProcessingStatus.EXTRACTED
            created_invoice_id = None

        doc.updated_at = utc_now()
        db.commit()

        return DocumentExtractionResponse(
            document_id=doc.id,
            document_kind=document_kind,
            status=doc.processing_status,
            extracted_fields=field_summaries,
            warnings=warnings,
            created_invoice_id=created_invoice_id,
        )
