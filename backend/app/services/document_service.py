"""
Document ingestion, validation, and download token service for ProcureMind.

This module provides:
- Content and signature validation (bounded UTF-8 for CSV, magic bytes for binaries).
- Server-generated storage keys (never using client filenames as filesystem paths).
- Cryptographic SHA-256 calculation for deduplication.
- HMAC-SHA256 download token generation and constant-time verification with fail-closed secret checks.
"""

import hashlib
import hmac
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, status

from app.core.config import settings
from app.models.enums import DocumentType

# Binary magic bytes signatures
MAGIC_BYTES: dict[str, bytes] = {
    "pdf": b"%PDF-",
    "xlsx": b"PK\x03\x04",
    "png": b"\x89PNG\r\n\x1a\n",
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
}

# Standard MIME types for allowed formats
MIME_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes an untrusted filename:
    - Strips directory path traversal characters (../ or \\).
    - Removes control characters and limits length to 200 characters.
    """
    base_name = Path(filename).name
    # Remove any characters other than alphanumeric, dots, underscores, dashes, and spaces
    cleaned = re.sub(r"[^\w\s\.-]", "_", base_name).strip()
    return cleaned[:200] if cleaned else "document"


def validate_file_content(ext: str, content: bytes) -> None:
    """
    Validates file content:
    - For CSV: Bounded UTF-8 text/content validation (rejects null bytes and binary content).
    - For binary formats (PDF, XLSX, PNG, JPG): Magic byte header verification.

    Raises:
        HTTPException(400): If content violates format rules.
    """
    if ext == "csv":
        # CSV must not contain null bytes (indicates binary file disguised as text)
        if b"\x00" in content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed CSV file: binary null bytes detected in text content",
            )
        try:
            # Validate decodeable as UTF-8 / ASCII
            sample = content[:65536].decode("utf-8")
            if not sample.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Malformed CSV file: content contains no readable text lines",
                )
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed CSV file: content is not valid UTF-8 text",
            ) from exc
    elif ext in MAGIC_BYTES:
        expected_sig = MAGIC_BYTES[ext]
        if not content.startswith(expected_sig):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File signature mismatch: file content does not match expected {ext.upper()} header signature",
            )


def detect_document_type(filename: str, ext: str) -> DocumentType:
    """Infers document category based on filename conventions or default."""
    name_lower = filename.lower()
    if any(k in name_lower for k in ["invoice", "inv_", "inv-", "commercial_invoice"]):
        return DocumentType.INVOICE
    if any(k in name_lower for k in ["shipping", "shipping_bill", "sb-", "bill_of_lading", "bl-"]):
        return DocumentType.SHIPPING_BILL
    if any(k in name_lower for k in ["statement", "bank", "settlement", "remittance"]):
        return DocumentType.BANK_STATEMENT
    if any(k in name_lower for k in ["customs", "declaration"]):
        return DocumentType.CUSTOMS_DECLARATION
    return DocumentType.OTHER


def validate_uploaded_document(filename: str, content: bytes) -> tuple[str, str, str, DocumentType]:
    """
    Validates an incoming uploaded file according to Phase 2 gate rules:
    - Rejects empty files (size == 0).
    - Enforces configured size limit.
    - Rejects unsupported extensions.
    - Validates binary magic bytes or bounded UTF-8 CSV content.
    - Sanitizes filename for safe display.

    Returns:
        tuple of (sanitized_filename, extension, media_type, document_type)
    """
    if not content or len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes received)",
        )

    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size ({len(content)} bytes) exceeds configured limit ({settings.MAX_UPLOAD_SIZE_BYTES} bytes)",
        )

    # Extract and check extension
    raw_ext = Path(filename).suffix.lower().lstrip(".")
    if not raw_ext or raw_ext not in settings.ALLOWED_FILE_EXTENSIONS:
        allowed = ", ".join(sorted(settings.ALLOWED_FILE_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{raw_ext}'. Allowed formats: {allowed}",
        )

    # Validate content signature / text encoding
    validate_file_content(raw_ext, content)

    sanitized_name = sanitize_filename(filename)
    media_type = MIME_TYPES.get(raw_ext, "application/octet-stream")
    doc_type = detect_document_type(sanitized_name, raw_ext)

    return sanitized_name, raw_ext, media_type, doc_type


def generate_server_storage_key(extension: str) -> str:
    """
    Generates a server-managed storage key partitioned by UTC date and UUID.
    Never uses untrusted user filenames as filesystem paths.
    """
    clean_ext = extension.lstrip(".").lower()
    date_path = datetime.now(UTC).strftime("%Y/%m/%d")
    unique_id = uuid.uuid4().hex
    return f"documents/{date_path}/{unique_id}.{clean_ext}"


def compute_sha256(content: bytes) -> str:
    """Computes SHA-256 cryptographic hex digest of file bytes."""
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Short-Lived Download Token Service (Fail-Closed)
# ---------------------------------------------------------------------------
def _get_signing_secret() -> str:
    """
    Retrieves the configured signing secret.
    Fails closed with HTTP 500 if the secret is None or empty.
    """
    secret = settings.STORAGE_SIGNING_SECRET
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="STORAGE_SIGNING_SECRET is not configured on the server. Download tokens cannot be signed.",
        )
    return secret


def create_download_token(document_id: uuid.UUID, expires_at: int) -> str:
    """
    Generates an HMAC-SHA256 signature for a document download link.
    Token binds: document_id and expiration timestamp.
    """
    secret = _get_signing_secret()
    payload = f"{document_id}:{expires_at}".encode()
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_download_token(document_id: uuid.UUID, expires_at: int, token: str) -> bool:
    """
    Verifies a download token in constant time and checks expiration.

    Returns:
        True if token is valid and unexpired; False otherwise.
    """
    # 1. Expiration check
    current_ts = int(datetime.now(UTC).timestamp())
    if current_ts > expires_at:
        return False

    # 2. Signature verification in constant time
    secret = _get_signing_secret()
    expected_payload = f"{document_id}:{expires_at}".encode()
    expected_token = hmac.new(secret.encode("utf-8"), expected_payload, hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected_token, token)
