"""Unit and integration tests for Phase 7: Deterministic Text Extraction and OCR Fallback."""

import io
import uuid
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.extraction.constants import (
    USABLE_TEXT_ALPHANUMERIC_MIN,
    USABLE_TEXT_CHAR_THRESHOLD,
    ExtractionError,
    has_usable_text,
)
from app.extraction.debug_parse import run_debug_parse
from app.extraction.image_parser import parse_image
from app.extraction.ocr_adapter import perform_ocr
from app.extraction.pdf_parser import parse_pdf
from app.extraction.spreadsheet_parser import parse_csv, parse_xlsx
from app.models.document import Document
from app.models.enums import DocumentType, ProcessingStatus
from app.schemas.parser import (
    BoundingBox,
    DocumentParseMethod,
    ParsedTextBlock,
    SourceMethod,
)
from app.services.parser_service import parse_document
from app.storage.interface import LocalStorageService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# 1. Usable text detection tests (Threshold boundary checks)
# ---------------------------------------------------------------------------


def test_usable_text_detection_boundary() -> None:
    # 38 non-whitespace characters, 35 alphanumeric characters -> True
    sample_invoice = "COMMERCIAL INVOICE NUMBER: INV-2026-001-A"
    non_ws = sum(1 for c in sample_invoice if not c.isspace())
    assert non_ws == 38
    assert non_ws >= USABLE_TEXT_CHAR_THRESHOLD
    assert has_usable_text(sample_invoice) is True

    # Punctuation / noise with low text -> False
    assert has_usable_text(" . ... ") is False

    # Short identifier (< 30 characters) -> False (should trigger OCR fallback)
    assert has_usable_text("INV-2026-001") is False

    # None and empty string -> False
    assert has_usable_text(None) is False
    assert has_usable_text("") is False

    # Exactly 30 non-whitespace with >= 10 alphanumeric -> True
    exact_30 = "ABCDEFGHIJ" + "1234567890" + "!!!!!!!!!!"  # 10 alpha + 10 digit + 10 punct = 30
    assert len(exact_30) == 30
    assert has_usable_text(exact_30) is True

    # 30 non-whitespace but only 5 alphanumeric -> False
    punct_heavy = "ABCDE" + "!" * 25
    assert len(punct_heavy) == 30
    assert sum(1 for c in punct_heavy if c.isalnum()) < USABLE_TEXT_ALPHANUMERIC_MIN
    assert has_usable_text(punct_heavy) is False


# ---------------------------------------------------------------------------
# 2. Geometry and confidence schema validation tests
# ---------------------------------------------------------------------------


def test_bounding_box_validation() -> None:
    # Valid normalized bounding box
    bbox = BoundingBox(x0=0.1, y0=0.2, x1=0.8, y1=0.9)
    assert bbox.x0 == 0.1
    assert bbox.y1 == 0.9

    # Out of bounds (> 1.0 or < 0.0)
    with pytest.raises(ValueError):
        BoundingBox(x0=-0.1, y0=0.0, x1=1.0, y1=1.0)
    with pytest.raises(ValueError):
        BoundingBox(x0=0.0, y0=0.0, x1=1.1, y1=1.0)

    # Inverted geometry (x0 > x1 or y0 > y1)
    with pytest.raises(ValueError, match="cannot exceed"):
        BoundingBox(x0=0.8, y0=0.2, x1=0.3, y1=0.9)
    with pytest.raises(ValueError, match="cannot exceed"):
        BoundingBox(x0=0.1, y0=0.9, x1=0.8, y1=0.2)

    # Non-finite float
    with pytest.raises(ValueError):
        BoundingBox(x0=float("nan"), y0=0.0, x1=1.0, y1=1.0)


def test_parsed_text_block_confidence_validation() -> None:
    # Native text confidence is None
    block_native = ParsedTextBlock(
        text="Sample Text",
        bbox=BoundingBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0),
        confidence=None,
        source=SourceMethod.TEXT,
        page_number=1,
        block_index=0,
    )
    assert block_native.confidence is None

    # OCR confidence constrained between 0.0 and 1.0
    block_ocr = ParsedTextBlock(
        text="Sample OCR",
        bbox=BoundingBox(x0=0.0, y0=0.0, x1=1.0, y1=1.0),
        confidence=0.95,
        source=SourceMethod.OCR,
        page_number=1,
        block_index=1,
    )
    assert block_ocr.confidence == 0.95

    with pytest.raises(ValueError):
        ParsedTextBlock(
            text="Invalid Conf",
            confidence=1.5,
            source=SourceMethod.OCR,
            page_number=1,
            block_index=0,
        )


# ---------------------------------------------------------------------------
# 3. CSV parsing tests (multiline, quotes, field/record limits)
# ---------------------------------------------------------------------------


def test_parse_csv_deterministic() -> None:
    csv_bytes = (FIXTURES_DIR / "sample_data.csv").read_bytes()
    parsed = parse_csv(
        file_bytes=csv_bytes,
        document_id=str(uuid.uuid4()),
        filename="sample_data.csv",
    )

    assert parsed.parse_method == DocumentParseMethod.TEXT
    assert parsed.page_count == 1
    assert len(parsed.sheets) == 1

    sheet = parsed.sheets[0]
    assert sheet.name == "Sheet1"
    assert sheet.row_count == 3
    # Check multiline preservation in row 2
    row2 = sheet.rows[1]
    assert "Global Imports, Inc." in row2.cells
    assert any("Batch 42" in (cell or "") for cell in row2.cells)


def test_parse_csv_record_limit_exceeded() -> None:
    # Generate CSV record that exceeds PARSER_MAX_CSV_RECORD_BYTES or field limits
    oversized_text = "A" * (settings.PARSER_MAX_CSV_RECORD_BYTES + 100)
    csv_content = f'col1,col2\n1,"{oversized_text}"\n'.encode()

    with pytest.raises(ExtractionError, match="(CSV parsing error|field larger than field limit)"):
        parse_csv(
            file_bytes=csv_content,
            document_id=str(uuid.uuid4()),
            filename="oversized.csv",
        )


# ---------------------------------------------------------------------------
# 4. XLSX pre-decompression safety tests
# ---------------------------------------------------------------------------


def test_parse_xlsx_zip_decompression_bomb_prevention() -> None:
    # Create a zip archive that contains 31MB uncompressed zeros (compresses to ~30KB)
    fake_zip = io.BytesIO()
    with zipfile.ZipFile(fake_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml", b"\x00" * (settings.PARSER_MAX_XLSX_ARCHIVE_BYTES + 1024)
        )

    with pytest.raises(ExtractionError, match="uncompressed archive size .* exceeds limit"):
        parse_xlsx(
            file_bytes=fake_zip.getvalue(),
            document_id=str(uuid.uuid4()),
            filename="bomb.xlsx",
        )


# ---------------------------------------------------------------------------
# 5. OCR adapter normalization tests
# ---------------------------------------------------------------------------


def test_ocr_adapter_data_normalization() -> None:
    mock_ocr_data = {
        "text": ["", "  ", "TOTAL", "100.00"],
        "conf": ["-1", "-1", "95.5", "85"],
        "left": [0, 0, 10, 50],
        "top": [0, 0, 20, 20],
        "width": [0, 0, 30, 40],
        "height": [0, 0, 15, 15],
    }

    mock_img = MagicMock()
    mock_img.width = 100
    mock_img.height = 100

    mock_pil = MagicMock()
    mock_pil.open.return_value = mock_img
    mock_pytess = MagicMock()
    mock_pytess.image_to_data.return_value = mock_ocr_data
    mock_pytess.Output.DICT = "dict"

    with (
        patch("app.extraction.ocr_adapter.Image", mock_pil),
        patch("app.extraction.ocr_adapter.pytesseract", mock_pytess),
    ):
        blocks = perform_ocr(b"fake_image_bytes", page_number=1)

    assert len(blocks) == 2
    # First block: "TOTAL"
    assert blocks[0].text == "TOTAL"
    assert blocks[0].confidence == 0.955
    assert blocks[0].source == SourceMethod.OCR
    assert blocks[0].bbox is not None
    assert blocks[0].bbox.x0 == 0.1
    assert blocks[0].bbox.y0 == 0.2
    assert blocks[0].bbox.x1 == 0.4
    assert blocks[0].bbox.y1 == 0.35

    # Second block: "100.00"
    assert blocks[1].text == "100.00"
    assert blocks[1].confidence == 0.85


# ---------------------------------------------------------------------------
# 6. Image parser dimension tests
# ---------------------------------------------------------------------------


def test_image_parser_dimension_limit() -> None:
    mock_img = MagicMock()
    mock_img.width = settings.PARSER_MAX_IMAGE_DIMENSION + 10
    mock_img.height = 100

    mock_pil = MagicMock()
    mock_pil.open.return_value.__enter__.return_value = mock_img

    with (
        patch("app.extraction.image_parser.Image", mock_pil),
        pytest.raises(ExtractionError, match="exceed maximum allowed dimension"),
    ):
        parse_image(
            file_bytes=b"fake_image",
            document_id=str(uuid.uuid4()),
            filename="huge.png",
            media_type="image/png",
        )


# ---------------------------------------------------------------------------
# 7. PDF parser routing tests (Native text vs Selective OCR fallback)
# ---------------------------------------------------------------------------


def test_pdf_parser_native_text_routing() -> None:
    # Setup mock fitz page with usable text
    mock_page = MagicMock()
    mock_page.rect.width = 612.0
    mock_page.rect.height = 792.0
    # Text block with 38 chars
    mock_page.get_text.return_value = [
        (72.0, 700.0, 300.0, 720.0, "COMMERCIAL INVOICE NUMBER: INV-2026-001-A", 0, 0)
    ]

    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 1
    mock_doc.__getitem__.return_value = mock_page

    mock_ocr = MagicMock()
    mock_fitz = MagicMock()
    mock_fitz.open.return_value = mock_doc

    with patch("app.extraction.pdf_parser.fitz", mock_fitz):
        parsed = parse_pdf(
            file_bytes=b"fake_pdf_data",
            document_id=str(uuid.uuid4()),
            filename="digital.pdf",
            ocr_func=mock_ocr,
        )

    assert parsed.parse_method == DocumentParseMethod.TEXT
    assert parsed.page_count == 1
    assert parsed.pages[0].source == SourceMethod.TEXT
    assert len(parsed.pages[0].text_blocks) == 1
    assert parsed.pages[0].text_blocks[0].source == SourceMethod.TEXT
    assert parsed.pages[0].text_blocks[0].confidence is None
    # OCR was not called
    mock_ocr.assert_not_called()


def test_pdf_parser_ocr_fallback_on_unusable_text() -> None:
    # Setup mock fitz page with low/unusable text (" . ... ")
    mock_page = MagicMock()
    mock_page.rect.width = 612.0
    mock_page.rect.height = 792.0
    mock_page.get_text.return_value = [(72.0, 700.0, 100.0, 720.0, " . ... ", 0, 0)]

    mock_pix = MagicMock()
    mock_pix.tobytes.return_value = b"png_raster_bytes"
    mock_page.get_pixmap.return_value = mock_pix

    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 1
    mock_doc.__getitem__.return_value = mock_page

    mock_ocr = MagicMock(
        return_value=[
            ParsedTextBlock(
                text="EXTRACTED VIA OCR",
                bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.5, y1=0.2),
                confidence=0.92,
                source=SourceMethod.OCR,
                page_number=1,
                block_index=0,
            )
        ]
    )
    mock_fitz = MagicMock()
    mock_fitz.open.return_value = mock_doc

    with patch("app.extraction.pdf_parser.fitz", mock_fitz):
        parsed = parse_pdf(
            file_bytes=b"fake_scanned_pdf",
            document_id=str(uuid.uuid4()),
            filename="scanned.pdf",
            ocr_func=mock_ocr,
        )

    assert parsed.parse_method == DocumentParseMethod.OCR
    assert parsed.page_count == 1
    assert parsed.pages[0].source == SourceMethod.OCR
    assert len(parsed.pages[0].text_blocks) == 1
    assert parsed.pages[0].text_blocks[0].text == "EXTRACTED VIA OCR"
    assert parsed.pages[0].text_blocks[0].source == SourceMethod.OCR
    assert parsed.pages[0].text_blocks[0].confidence == 0.92
    # Verify OCR was called
    mock_ocr.assert_called_once()


def test_pdf_parser_mixed_routing() -> None:
    # Page 1 usable, Page 2 unusable
    page1 = MagicMock()
    page1.rect.width, page1.rect.height = 612.0, 792.0
    page1.get_text.return_value = [
        (72.0, 700.0, 300.0, 720.0, "COMMERCIAL INVOICE NUMBER: INV-2026-001-A", 0, 0)
    ]

    page2 = MagicMock()
    page2.rect.width, page2.rect.height = 612.0, 792.0
    page2.get_text.return_value = [(72.0, 700.0, 100.0, 720.0, " . ... ", 0, 0)]
    mock_pix = MagicMock()
    mock_pix.tobytes.return_value = b"png_raster"
    page2.get_pixmap.return_value = mock_pix

    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 2
    mock_doc.__getitem__.side_effect = [page1, page2]

    mock_ocr = MagicMock(
        return_value=[
            ParsedTextBlock(
                text="PAGE 2 OCR",
                source=SourceMethod.OCR,
                page_number=2,
                block_index=0,
            )
        ]
    )
    mock_fitz = MagicMock()
    mock_fitz.open.return_value = mock_doc

    with patch("app.extraction.pdf_parser.fitz", mock_fitz):
        parsed = parse_pdf(
            file_bytes=b"mixed_pdf",
            document_id=str(uuid.uuid4()),
            filename="mixed.pdf",
            ocr_func=mock_ocr,
        )

    assert parsed.parse_method == DocumentParseMethod.MIXED
    assert parsed.page_count == 2
    assert parsed.pages[0].source == SourceMethod.TEXT
    assert parsed.pages[1].source == SourceMethod.OCR


def test_pdf_parser_render_pixel_budget_check() -> None:
    huge_page = MagicMock()
    # Huge dimensions that exceed PARSER_MAX_RENDER_PIXELS under 150 DPI
    huge_page.rect.width = 10000.0
    huge_page.rect.height = 10000.0
    huge_page.get_text.return_value = []

    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 1
    mock_doc.__getitem__.return_value = huge_page
    mock_fitz = MagicMock()
    mock_fitz.open.return_value = mock_doc

    with (
        patch("app.extraction.pdf_parser.fitz", mock_fitz),
        pytest.raises(ExtractionError, match="render size .* exceeds limit"),
    ):
        parse_pdf(
            file_bytes=b"huge_pdf",
            document_id=str(uuid.uuid4()),
            filename="huge.pdf",
        )


# ---------------------------------------------------------------------------
# 8. Service Layer & Terminal Status Protection Tests (Rule 3)
# ---------------------------------------------------------------------------


def test_parser_service_success_and_terminal_status_protection(db_session: Session) -> None:
    storage = LocalStorageService()
    csv_bytes = (FIXTURES_DIR / "sample_data.csv").read_bytes()

    # Case A: Normal document in UPLOADED status
    key_a = f"test/{uuid.uuid4()}.csv"
    storage.save_file(key_a, csv_bytes)

    doc_a = Document(
        id=uuid.uuid4(),
        original_filename="sample_a.csv",
        media_type="text/csv",
        size_bytes=len(csv_bytes),
        sha256=str(uuid.uuid4()),
        storage_key=key_a,
        document_type=DocumentType.INVOICE,
        processing_status=ProcessingStatus.UPLOADED,
    )
    db_session.add(doc_a)
    db_session.commit()

    parsed_a = parse_document(db_session, str(doc_a.id))
    assert parsed_a.page_count == 1
    db_session.refresh(doc_a)
    # Status transitioned to PARSED
    assert doc_a.processing_status == ProcessingStatus.PARSED
    assert doc_a.page_count == 1

    # Case B: Terminal document in APPROVED status
    key_b = f"test/{uuid.uuid4()}.csv"
    storage.save_file(key_b, csv_bytes)

    doc_b = Document(
        id=uuid.uuid4(),
        original_filename="sample_b.csv",
        media_type="text/csv",
        size_bytes=len(csv_bytes),
        sha256=str(uuid.uuid4()),
        storage_key=key_b,
        document_type=DocumentType.INVOICE,
        processing_status=ProcessingStatus.APPROVED,
    )
    db_session.add(doc_b)
    db_session.commit()

    parsed_b = parse_document(db_session, str(doc_b.id))
    assert parsed_b.page_count == 1
    db_session.refresh(doc_b)
    # Status MUST remain APPROVED (never overwritten to PARSED)
    assert doc_b.processing_status == ProcessingStatus.APPROVED
    assert doc_b.page_count == 1


def test_parser_service_failure_and_terminal_status_protection(db_session: Session) -> None:
    storage = LocalStorageService()
    corrupt_bytes = b"NOT_A_VALID_DOCUMENT_CONTENT"

    # Case A: Document in UPLOADED status fails parsing
    key_a = f"test/{uuid.uuid4()}.pdf"
    storage.save_file(key_a, corrupt_bytes)

    doc_a = Document(
        id=uuid.uuid4(),
        original_filename="corrupt_a.pdf",
        media_type="application/pdf",
        size_bytes=len(corrupt_bytes),
        sha256=str(uuid.uuid4()),
        storage_key=key_a,
        document_type=DocumentType.INVOICE,
        processing_status=ProcessingStatus.UPLOADED,
    )
    db_session.add(doc_a)
    db_session.commit()

    with pytest.raises(HTTPException):
        parse_document(db_session, str(doc_a.id))

    db_session.refresh(doc_a)
    # Status transitioned to NEEDS_REVIEW
    assert doc_a.processing_status == ProcessingStatus.NEEDS_REVIEW

    # Case B: Terminal document in APPROVED status fails parsing
    key_b = f"test/{uuid.uuid4()}.pdf"
    storage.save_file(key_b, corrupt_bytes)

    doc_b = Document(
        id=uuid.uuid4(),
        original_filename="corrupt_b.pdf",
        media_type="application/pdf",
        size_bytes=len(corrupt_bytes),
        sha256=str(uuid.uuid4()),
        storage_key=key_b,
        document_type=DocumentType.INVOICE,
        processing_status=ProcessingStatus.APPROVED,
    )
    db_session.add(doc_b)
    db_session.commit()

    with pytest.raises(HTTPException):
        parse_document(db_session, str(doc_b.id))

    db_session.refresh(doc_b)
    # Status MUST remain APPROVED (never downgraded to NEEDS_REVIEW)
    assert doc_b.processing_status == ProcessingStatus.APPROVED


# ---------------------------------------------------------------------------
# 9. API Endpoint Tests (POST /api/v1/documents/{document_id}/parse)
# ---------------------------------------------------------------------------


def test_api_parse_document_endpoint(client_with_db: TestClient, db_session: Session) -> None:
    storage = LocalStorageService()
    csv_bytes = (FIXTURES_DIR / "sample_data.csv").read_bytes()

    storage_key = f"test/{uuid.uuid4()}.csv"
    storage.save_file(storage_key, csv_bytes)

    doc = Document(
        id=uuid.uuid4(),
        original_filename="api_sample.csv",
        media_type="text/csv",
        size_bytes=len(csv_bytes),
        sha256=str(uuid.uuid4()),
        storage_key=storage_key,
        document_type=DocumentType.INVOICE,
        processing_status=ProcessingStatus.UPLOADED,
    )
    db_session.add(doc)
    db_session.commit()

    # Success call
    response = client_with_db.post(f"{settings.API_V1_STR}/documents/{doc.id}/parse")
    assert response.status_code == 200
    data = response.json()
    assert data["document_id"] == str(doc.id)
    assert data["parse_method"] == "text"
    assert data["page_count"] == 1
    assert len(data["sheets"]) == 1

    # Nonexistent document UUID
    fake_id = uuid.uuid4()
    resp_404 = client_with_db.post(f"{settings.API_V1_STR}/documents/{fake_id}/parse")
    assert resp_404.status_code == 404

    # Invalid UUID string
    resp_invalid = client_with_db.post(f"{settings.API_V1_STR}/documents/not-a-uuid/parse")
    assert resp_invalid.status_code == 422


# ---------------------------------------------------------------------------
# 10. CLI debug_parse test
# ---------------------------------------------------------------------------


def test_cli_debug_parse(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = LocalStorageService()
    csv_bytes = (FIXTURES_DIR / "sample_data.csv").read_bytes()

    storage_key = f"test/{uuid.uuid4()}.csv"
    storage.save_file(storage_key, csv_bytes)

    doc = Document(
        id=uuid.uuid4(),
        original_filename="cli_sample.csv",
        media_type="text/csv",
        size_bytes=len(csv_bytes),
        sha256=str(uuid.uuid4()),
        storage_key=storage_key,
        document_type=DocumentType.INVOICE,
        processing_status=ProcessingStatus.UPLOADED,
    )
    db_session.add(doc)
    db_session.commit()

    monkeypatch.setattr("app.extraction.debug_parse.SessionLocal", lambda: db_session)

    code = run_debug_parse(str(doc.id))
    assert code == 0

    # Nonexistent document returns 1
    code_missing = run_debug_parse(str(uuid.uuid4()))
    assert code_missing == 1
