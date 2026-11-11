"""Deterministic parser for image documents (PNG, JPG, JPEG) using OCR fallback."""

import io
import logging
from collections.abc import Callable

from app.core.config import settings
from app.extraction.constants import ExtractionError
from app.extraction.ocr_adapter import perform_ocr
from app.schemas.parser import (
    DocumentParseMethod,
    ParsedDocument,
    ParsedPage,
    ParsedTextBlock,
    SourceMethod,
)

logger = logging.getLogger(__name__)

try:
    from PIL import Image  # type: ignore[import-untyped,import-not-found]
except ImportError:
    Image = None


def parse_image(
    file_bytes: bytes,
    document_id: str,
    filename: str,
    media_type: str,
    ocr_func: Callable[..., list[ParsedTextBlock]] | None = None,
) -> ParsedDocument:
    """Parse an image document using OCR with dimension and pixel bounds checks."""
    if Image is None:
        raise ExtractionError(
            "Pillow is not installed",
            safe_detail="Image parser dependency unavailable",
        )

    ocr_handler = ocr_func or perform_ocr

    # Check image dimensions from header
    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            w, h = img.width, img.height
    except Exception as exc:
        logger.error("Failed to read image header")
        raise ExtractionError("Corrupted or unsupported image file") from exc

    if w > settings.PARSER_MAX_IMAGE_DIMENSION or h > settings.PARSER_MAX_IMAGE_DIMENSION:
        raise ExtractionError(
            f"Image dimensions ({w}x{h}) exceed maximum allowed dimension ({settings.PARSER_MAX_IMAGE_DIMENSION})",
            safe_detail="Image dimensions exceed maximum limit",
        )

    total_pixels = w * h
    if total_pixels > settings.PARSER_MAX_IMAGE_PIXELS:
        raise ExtractionError(
            f"Image pixel count ({total_pixels}) exceeds maximum limit ({settings.PARSER_MAX_IMAGE_PIXELS})",
            safe_detail="Image pixel count exceeds maximum limit",
        )

    # Perform OCR
    blocks = ocr_handler(file_bytes, page_number=1)

    page = ParsedPage(
        page_number=1,
        width=float(w),
        height=float(h),
        source=SourceMethod.OCR,
        text_blocks=blocks,
        tables=[],
    )

    return ParsedDocument(
        document_id=document_id,
        filename=filename,
        media_type=media_type,
        parse_method=DocumentParseMethod.OCR,
        page_count=1,
        pages=[page],
        sheets=[],
        total_text_blocks=len(blocks),
        total_tables=0,
        warnings=[],
    )
