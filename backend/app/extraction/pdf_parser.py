"""Deterministic PDF parser using PyMuPDF (fitz) and pdfplumber with selective OCR fallback."""

import io
import logging
from collections.abc import Callable

from app.core.config import settings
from app.extraction.constants import ExtractionError, has_usable_text
from app.extraction.ocr_adapter import perform_ocr
from app.schemas.parser import (
    BoundingBox,
    DocumentParseMethod,
    ParsedDocument,
    ParsedPage,
    ParsedTable,
    ParsedTextBlock,
    SourceMethod,
)

logger = logging.getLogger(__name__)

try:
    import fitz  # type: ignore[import-untyped,import-not-found]
except ImportError:
    fitz = None

try:
    import pdfplumber  # type: ignore[import-untyped,import-not-found]
except ImportError:
    pdfplumber = None  # type: ignore[assignment]


def parse_pdf(
    file_bytes: bytes,
    document_id: str,
    filename: str,
    media_type: str = "application/pdf",
    ocr_func: Callable[..., list[ParsedTextBlock]] | None = None,
) -> ParsedDocument:
    """Parse a PDF document into structured text blocks and tables with selective OCR fallback.

    - Uses PyMuPDF for native text and block geometry.
    - Uses pdfplumber for table extraction.
    - Selectively invokes OCR only for pages lacking usable embedded text.
    """
    if fitz is None:
        raise ExtractionError(
            "PyMuPDF is not installed",
            safe_detail="PDF parser dependency unavailable",
        )

    ocr_handler = ocr_func or perform_ocr

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        logger.error("Failed to open PDF document with PyMuPDF")
        raise ExtractionError("Corrupted or unreadable PDF document") from exc

    page_count = len(doc)
    if page_count > settings.PARSER_MAX_PAGES:
        raise ExtractionError(
            f"PDF page count ({page_count}) exceeds limit of {settings.PARSER_MAX_PAGES} pages",
            safe_detail="PDF exceeds maximum allowed pages",
        )

    # Attempt to open with pdfplumber for table extraction if available
    plumber_doc = None
    if pdfplumber is not None:
        try:
            plumber_doc = pdfplumber.open(io.BytesIO(file_bytes))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"pdfplumber failed to open PDF; proceeding without table extraction: {exc}"
            )
            plumber_doc = None

    parsed_pages: list[ParsedPage] = []
    has_text_page = False
    has_ocr_page = False
    total_blocks_count = 0
    total_tables_count = 0
    warnings: list[str] = []

    try:
        for page_idx in range(page_count):
            page = doc[page_idx]
            page_num = page_idx + 1
            width = float(page.rect.width)
            height = float(page.rect.height)

            if width <= 0 or height <= 0:
                width, height = 595.0, 842.0  # Fallback to standard A4 dimensions

            # Extract native text blocks: (x0, y0, x1, y1, text, block_no, block_type)
            native_blocks_raw = page.get_text("blocks")
            extracted_text_blocks: list[ParsedTextBlock] = []
            page_text_accumulator: list[str] = []

            block_counter = 0
            for b in native_blocks_raw:
                if len(b) >= 7 and b[6] != 0:
                    # Non-text block (e.g. image)
                    continue
                bx0, by0, bx1, by1, btext = b[0], b[1], b[2], b[3], b[4]
                stripped_text = str(btext).strip()
                if not stripped_text:
                    continue

                page_text_accumulator.append(stripped_text)

                nx0 = max(0.0, min(1.0, round(float(bx0) / width, 4)))
                ny0 = max(0.0, min(1.0, round(float(by0) / height, 4)))
                nx1 = max(nx0, min(1.0, round(float(bx1) / width, 4)))
                ny1 = max(ny0, min(1.0, round(float(by1) / height, 4)))
                bbox = BoundingBox(x0=nx0, y0=ny0, x1=nx1, y1=ny1)

                extracted_text_blocks.append(
                    ParsedTextBlock(
                        text=stripped_text,
                        bbox=bbox,
                        confidence=None,  # Native text has no OCR confidence
                        source=SourceMethod.TEXT,
                        page_number=page_num,
                        block_index=block_counter,
                    )
                )
                block_counter += 1

            full_page_text = "\n".join(page_text_accumulator)
            is_usable = has_usable_text(full_page_text)

            # Extract tables for this page if pdfplumber is active
            page_tables: list[ParsedTable] = []
            if plumber_doc and page_idx < len(plumber_doc.pages):
                try:
                    raw_tables = plumber_doc.pages[page_idx].extract_tables() or []
                    for t in raw_tables:
                        # Clean cell values
                        cleaned_rows: list[list[str]] = [
                            [str(cell).strip() if cell is not None else "" for cell in row]
                            for row in t
                        ]
                        if cleaned_rows:
                            page_tables.append(
                                ParsedTable(
                                    page_number=page_num,
                                    rows=cleaned_rows,
                                    bbox=None,
                                )
                            )
                except (ValueError, TypeError, OSError) as exc:
                    logger.warning(f"Failed extracting tables on page {page_num}: {exc}")

            if is_usable:
                # Use native text
                has_text_page = True
                page_source = SourceMethod.TEXT
                final_page_blocks = extracted_text_blocks
            else:
                # Fall back to OCR for this page
                has_ocr_page = True
                page_source = SourceMethod.OCR

                # Check expected render size before rasterizing
                dpi = settings.PARSER_PDF_OCR_DPI
                scale = dpi / 72.0
                render_w = width * scale
                render_h = height * scale
                expected_pixels = render_w * render_h

                if expected_pixels > settings.PARSER_MAX_RENDER_PIXELS:
                    raise ExtractionError(
                        f"PDF page {page_num} render size ({int(expected_pixels)} px) exceeds limit",
                        safe_detail="PDF page render exceeds maximum pixel budget",
                    )

                # Render page to image
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                pix_bytes = pix.tobytes("png")

                # Perform OCR
                ocr_blocks = ocr_handler(pix_bytes, page_number=page_num)
                final_page_blocks = ocr_blocks

            total_blocks_count += len(final_page_blocks)
            if total_blocks_count > settings.PARSER_MAX_TEXT_BLOCKS:
                raise ExtractionError(
                    f"PDF total text blocks exceeded limit of {settings.PARSER_MAX_TEXT_BLOCKS}",
                    safe_detail="Document text density exceeds limits",
                )

            total_tables_count += len(page_tables)

            parsed_pages.append(
                ParsedPage(
                    page_number=page_num,
                    width=round(width, 2),
                    height=round(height, 2),
                    source=page_source,
                    text_blocks=final_page_blocks,
                    tables=page_tables,
                )
            )
    finally:
        doc.close()
        if plumber_doc is not None:
            try:
                plumber_doc.close()
            except (ValueError, OSError) as exc:
                logger.warning(f"Error closing pdfplumber doc: {exc}")

    # Determine document-level parse method
    if has_text_page and has_ocr_page:
        doc_parse_method = DocumentParseMethod.MIXED
    elif has_ocr_page:
        doc_parse_method = DocumentParseMethod.OCR
    else:
        doc_parse_method = DocumentParseMethod.TEXT

    return ParsedDocument(
        document_id=document_id,
        filename=filename,
        media_type=media_type,
        parse_method=doc_parse_method,
        page_count=page_count,
        pages=parsed_pages,
        sheets=[],
        total_text_blocks=total_blocks_count,
        total_tables=total_tables_count,
        warnings=warnings,
    )
