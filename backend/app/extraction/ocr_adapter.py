"""Injectable OCR adapter using Tesseract via pytesseract and Pillow."""

import io
import logging
from typing import Any

from app.core.config import settings
from app.extraction.constants import ExtractionError
from app.schemas.parser import BoundingBox, ParsedTextBlock, SourceMethod

logger = logging.getLogger(__name__)

try:
    import pytesseract  # type: ignore[import-untyped,import-not-found]
    from PIL import Image  # type: ignore[import-untyped,import-not-found]
except ImportError:
    pytesseract = None
    Image = None  # type: ignore[assignment]


def perform_ocr(
    image_bytes: bytes,
    page_number: int = 1,
    tesseract_cmd: str | None = None,
) -> list[ParsedTextBlock]:
    """Execute Tesseract OCR on raw image bytes.

    Returns a list of ParsedTextBlock items with normalized coordinates (0.0 to 1.0)
    and normalized confidence (0.0 to 1.0).
    """
    if Image is None or pytesseract is None:
        raise ExtractionError(
            "OCR dependencies (pytesseract or Pillow) are not installed",
            safe_detail="OCR dependency unavailable",
        )

    cmd = tesseract_cmd or settings.OCR_TESSERACT_CMD
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd

    try:
        image = Image.open(io.BytesIO(image_bytes))
        img_w, img_h = float(image.width), float(image.height)
        if img_w <= 0 or img_h <= 0:
            return []

        ocr_data: dict[str, list[Any]] = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:
        logger.error("OCR execution error occurred during processing")
        raise ExtractionError("OCR processing failed", safe_detail="OCR execution failure") from exc

    blocks: list[ParsedTextBlock] = []
    texts = ocr_data.get("text", [])
    confs = ocr_data.get("conf", [])
    lefts = ocr_data.get("left", [])
    tops = ocr_data.get("top", [])
    widths = ocr_data.get("width", [])
    heights = ocr_data.get("height", [])

    block_idx = 0
    for i, raw_text in enumerate(texts):
        if not raw_text or not str(raw_text).strip():
            continue
        text_str = str(raw_text).strip()

        # Confidence handling: Tesseract uses -1 for layout markers/unknown
        conf_val: float | None = None
        if i < len(confs):
            try:
                raw_c = float(confs[i])
                if raw_c >= 0:
                    conf_val = max(0.0, min(1.0, round(raw_c / 100.0, 4)))
            except (ValueError, TypeError):
                conf_val = None

        # Normalized bounding box coordinates [0.0, 1.0]
        bbox: BoundingBox | None = None
        if i < len(lefts) and i < len(tops) and i < len(widths) and i < len(heights):
            try:
                l_val = float(lefts[i])
                t_val = float(tops[i])
                w_val = float(widths[i])
                h_val = float(heights[i])
                x0 = max(0.0, min(1.0, round(l_val / img_w, 4)))
                y0 = max(0.0, min(1.0, round(t_val / img_h, 4)))
                x1 = max(x0, min(1.0, round((l_val + w_val) / img_w, 4)))
                y1 = max(y0, min(1.0, round((t_val + h_val) / img_h, 4)))
                bbox = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
            except (ValueError, TypeError):
                bbox = None

        blocks.append(
            ParsedTextBlock(
                text=text_str,
                bbox=bbox,
                confidence=conf_val,
                source=SourceMethod.OCR,
                page_number=page_number,
                block_index=block_idx,
            )
        )
        block_idx += 1

    return blocks
