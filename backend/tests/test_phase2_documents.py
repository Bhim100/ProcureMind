"""
Comprehensive tests for Phase 2: Document Ingestion, Validation, Storage, and Registry.
"""

import io
import uuid
from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.main import app
from app.models.document import Document
from app.storage.interface import LocalStorageService


@pytest.fixture
def client_with_db(db_session: Session) -> Generator[TestClient, None, None]:
    """Provides a TestClient overriding get_db with the test database session."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # Set explicit test-only secret for download tokens
    original_secret = settings.STORAGE_SIGNING_SECRET
    settings.STORAGE_SIGNING_SECRET = "test-only-signing-secret-key-32bytes!!"
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        settings.STORAGE_SIGNING_SECRET = original_secret


# ---------------------------------------------------------------------------
# 1. Successful Upload Tests (PDF, XLSX, CSV, PNG, JPG)
# ---------------------------------------------------------------------------
def test_upload_valid_pdf(client_with_db: TestClient, db_session: Session) -> None:
    """Verifies that a valid PDF with %PDF- header is accepted and registered."""
    pdf_content = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    response = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("commercial_invoice.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["is_duplicate"] is False
    doc = data["document"]
    assert doc["original_filename"] == "commercial_invoice.pdf"
    assert doc["document_type"] == "invoice"
    assert doc["processing_status"] == "uploaded"
    assert doc["storage_key"].startswith("documents/")
    assert doc["size_bytes"] == len(pdf_content)

    # Verify DB persistence
    saved = db_session.get(Document, uuid.UUID(doc["id"]))
    assert saved is not None
    assert saved.sha256 == doc["sha256"]


def test_upload_valid_xlsx(client_with_db: TestClient) -> None:
    """Verifies that a valid XLSX archive with PK header is accepted."""
    xlsx_content = b"PK\x03\x04\x14\x00\x00\x00\x08\x00synthetic_xlsx_data"
    response = client_with_db.post(
        "/api/v1/documents",
        files={
            "file": (
                "packing_list.xlsx",
                io.BytesIO(xlsx_content),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 201
    assert (
        response.json()["document"]["media_type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_upload_valid_csv(client_with_db: TestClient) -> None:
    """Verifies that bounded UTF-8 CSV text content is accepted."""
    csv_content = b"invoice_num,amount,currency\nINV-001,1000.00,USD\nINV-002,2500.00,USD\n"
    response = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("bank_statement_nov.csv", io.BytesIO(csv_content), "text/csv")},
    )
    assert response.status_code == 201
    doc = response.json()["document"]
    assert doc["document_type"] == "bank_statement"


def test_upload_valid_png_and_jpg(client_with_db: TestClient) -> None:
    """Verifies image uploads with valid binary headers."""
    png_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    res_png = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("receipt.png", io.BytesIO(png_content), "image/png")},
    )
    assert res_png.status_code == 201

    jpg_content = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    res_jpg = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("shipping_declaration.jpg", io.BytesIO(jpg_content), "image/jpeg")},
    )
    assert res_jpg.status_code == 201


# ---------------------------------------------------------------------------
# 2. Validation & Security Rejection Tests
# ---------------------------------------------------------------------------
def test_upload_empty_file_rejected(client_with_db: TestClient) -> None:
    """Rejects empty (0-byte) files with HTTP 400."""
    response = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_upload_oversized_file_rejected(
    client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rejects files exceeding configured size limit with HTTP 413."""
    # Temporarily set max size to 100 bytes
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_BYTES", 100)
    oversized_content = b"%PDF-" + b"0" * 200
    response = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("huge.pdf", io.BytesIO(oversized_content), "application/pdf")},
    )
    assert response.status_code == 413
    assert "exceeds" in response.json()["detail"].lower()


def test_upload_unsupported_extension_rejected(client_with_db: TestClient) -> None:
    """Rejects disallowed file extensions (.exe, .txt) with HTTP 400."""
    response = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("malicious.exe", io.BytesIO(b"MZ\x90\x00"), "application/x-msdownload")},
    )
    assert response.status_code == 400
    assert "unsupported" in response.json()["detail"].lower()


def test_upload_magic_byte_mismatch_rejected(client_with_db: TestClient) -> None:
    """Rejects files disguised with valid extension but invalid content signature."""
    fake_pdf = b"This is plain text pretending to be a PDF."
    response = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("fake_invoice.pdf", io.BytesIO(fake_pdf), "application/pdf")},
    )
    assert response.status_code == 400
    assert "signature mismatch" in response.json()["detail"].lower()


def test_upload_csv_with_null_bytes_rejected(client_with_db: TestClient) -> None:
    """Rejects binary files disguised as CSV containing null bytes."""
    binary_csv = b"col1,col2\nval1,\x00\x01\x02\n"
    response = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("fake_data.csv", io.BytesIO(binary_csv), "text/csv")},
    )
    assert response.status_code == 400
    assert "null bytes" in response.json()["detail"].lower()


def test_upload_path_traversal_filename_sanitized(client_with_db: TestClient) -> None:
    """Verifies that path traversal filenames like '../../evil.pdf' are sanitized safely."""
    pdf_content = b"%PDF-1.4\nsafe content"
    response = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("../../evil.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert response.status_code == 201
    doc = response.json()["document"]
    # Path separators must be stripped
    assert ".." not in doc["original_filename"]
    assert "/" not in doc["original_filename"]
    assert "\\" not in doc["original_filename"]
    assert doc["original_filename"] == "evil.pdf"
    # Storage key must be server-generated
    assert doc["storage_key"].startswith("documents/")
    assert "evil.pdf" not in doc["storage_key"]


# ---------------------------------------------------------------------------
# 3. Deduplication Tests
# ---------------------------------------------------------------------------
def test_duplicate_upload_detection(client_with_db: TestClient, db_session: Session) -> None:
    """Verifies that uploading the identical file twice returns the original ID without duplicating rows."""
    pdf_content = b"%PDF-1.4\nunique deduplication content stream"

    # First upload
    res1 = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("doc_first.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert res1.status_code == 201
    doc1 = res1.json()["document"]
    assert res1.json()["is_duplicate"] is False

    # Count rows before second upload
    initial_count = db_session.query(Document).count()

    # Second upload with identical content
    res2 = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("doc_copy.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    assert res2.status_code == 200  # Duplicate recognized
    data2 = res2.json()
    assert data2["is_duplicate"] is True
    assert data2["document"]["id"] == doc1["id"]
    assert data2["document"]["sha256"] == doc1["sha256"]

    # Verify database row count did not grow
    final_count = db_session.query(Document).count()
    assert final_count == initial_count


# ---------------------------------------------------------------------------
# 4. Registry Listing & Detail Retrieval Tests
# ---------------------------------------------------------------------------
def test_list_and_get_documents(client_with_db: TestClient) -> None:
    """Verifies GET /api/v1/documents and GET /api/v1/documents/{id}."""
    pdf_content = b"%PDF-1.4\ncontent for retrieval testing"
    res_upload = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("retrieval_test.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    doc_id = res_upload.json()["document"]["id"]

    # 1. List
    res_list = client_with_db.get("/api/v1/documents")
    assert res_list.status_code == 200
    docs = res_list.json()
    assert any(d["id"] == doc_id for d in docs)

    # 2. Get by ID
    res_get = client_with_db.get(f"/api/v1/documents/{doc_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == doc_id

    # 3. Not found
    fake_id = str(uuid.uuid4())
    res_404 = client_with_db.get(f"/api/v1/documents/{fake_id}")
    assert res_404.status_code == 404


# ---------------------------------------------------------------------------
# 5. Short-Lived Download Token & Expiry Tests
# ---------------------------------------------------------------------------
def test_download_url_and_successful_stream(client_with_db: TestClient) -> None:
    """Verifies download URL generation and verified streaming of document bytes."""
    pdf_content = b"%PDF-1.4\ndownloadable file payload"
    res_upload = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("invoice_download.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    doc_id = res_upload.json()["document"]["id"]

    # Request short-lived download URL
    res_url = client_with_db.get(f"/api/v1/documents/{doc_id}/download-url")
    assert res_url.status_code == 200
    data = res_url.json()
    assert "download_url" in data
    assert data["expires_in_seconds"] == 300

    # Follow download URL
    download_url = data["download_url"]
    res_download = client_with_db.get(download_url)
    assert res_download.status_code == 200
    assert res_download.content == pdf_content
    assert "attachment" in res_download.headers["Content-Disposition"]
    assert "invoice_download.pdf" in res_download.headers["Content-Disposition"]


def test_download_expired_token_rejected(client_with_db: TestClient) -> None:
    """Verifies that an expired token is rejected with HTTP 403 Forbidden."""
    pdf_content = b"%PDF-1.4\nfile payload"
    res_upload = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("invoice_expired.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    doc_id = res_upload.json()["document"]["id"]

    # Use an expired timestamp (100 seconds in the past)
    past_ts = int(datetime.now(UTC).timestamp()) - 100
    fake_token = "0" * 64

    res_download = client_with_db.get(
        f"/api/v1/documents/{doc_id}/download?expires={past_ts}&token={fake_token}"
    )
    assert res_download.status_code == 403
    assert "expired" in res_download.json()["detail"].lower()


def test_download_tampered_token_rejected(client_with_db: TestClient) -> None:
    """Verifies that a tampered signature token is rejected with HTTP 403."""
    pdf_content = b"%PDF-1.4\nfile payload"
    res_upload = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("invoice_tampered.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    doc_id = res_upload.json()["document"]["id"]

    future_ts = int(datetime.now(UTC).timestamp()) + 300
    tampered_token = "bad_signature_abc123"

    res_download = client_with_db.get(
        f"/api/v1/documents/{doc_id}/download?expires={future_ts}&token={tampered_token}"
    )
    assert res_download.status_code == 403


def test_download_fails_closed_when_secret_unset(
    client_with_db: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verifies that download URL creation fails closed (HTTP 500) if STORAGE_SIGNING_SECRET is None."""
    pdf_content = b"%PDF-1.4\nfile for secret check"
    res_upload = client_with_db.post(
        "/api/v1/documents",
        files={"file": ("secret_check.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    doc_id = res_upload.json()["document"]["id"]

    monkeypatch.setattr(settings, "STORAGE_SIGNING_SECRET", None)
    res_fail = client_with_db.get(f"/api/v1/documents/{doc_id}/download-url")
    assert res_fail.status_code == 500
    assert "not configured" in res_fail.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 6. Storage Path Containment Test
# ---------------------------------------------------------------------------
def test_storage_containment_violation_rejected() -> None:
    """Verifies that LocalStorageService rejects any path traversal storage key."""
    service = LocalStorageService(base_dir="./local_storage")
    with pytest.raises(ValueError, match="Path containment violation"):
        service._resolve_contained_path("../../escaped_file.txt")
