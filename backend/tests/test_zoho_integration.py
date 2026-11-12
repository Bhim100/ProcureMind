"""Unit and integration tests for Zoho Books document ingestion."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.integration import ZohoIntegration


def test_zoho_status_initially_disconnected(
    client_with_db: TestClient, db_session: Session
) -> None:
    """Status endpoint correctly reports when Zoho is not connected."""
    db_session.query(ZohoIntegration).delete()
    db_session.commit()

    resp = client_with_db.get("/api/v1/integrations/zoho/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_connected"] is False
    assert data["organization_id"] is None
    assert data["synced_documents_count"] >= 0


def test_zoho_auth_url(client_with_db: TestClient) -> None:
    """Auth URL endpoint returns consent link."""
    resp = client_with_db.get("/api/v1/integrations/zoho/auth-url")
    assert resp.status_code == 200
    data = resp.json()
    assert "auth_url" in data


def test_zoho_simulate_sync(client_with_db: TestClient, db_session: Session) -> None:
    """
    Simulating a Zoho sync creates authentic documents, calculates SHA-256,
    stores the PDF, and establishes trade reconciliation records.
    """
    resp = client_with_db.post("/api/v1/integrations/zoho/simulate-sync?count=1")
    assert resp.status_code == 200
    data = resp.json()

    assert data["synced_count"] == 1
    assert len(data["invoices"]) == 1
    inv_item = data["invoices"][0]

    assert inv_item["currency"] == "USD"
    assert Decimal(str(inv_item["total_amount"])) > Decimal("0.00")
    assert inv_item["source_external_id"].startswith("zoho_inv_")

    # Verify in DB
    doc = db_session.query(Document).filter(Document.id == inv_item["document_id"]).first()
    assert doc is not None
    assert doc.source_system == "zoho_books"
    assert doc.original_filename.endswith(".pdf")
    assert len(doc.sha256) == 64

    # Check status endpoint telemetry
    status_resp = client_with_db.get("/api/v1/integrations/zoho/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["is_connected"] is True
    assert status_data["synced_documents_count"] >= 1
    assert Decimal(str(status_data["total_synced_amount"])) > Decimal("0.00")


def test_zoho_live_sync_with_mocked_api(client_with_db: TestClient, db_session: Session) -> None:
    """
    Verifies live sync fetches from Zoho Books REST API and downloads PDF
    using mocked httpx transport.
    """
    # Ensure active integration exists
    integration = (
        db_session.query(ZohoIntegration).filter(ZohoIntegration.is_active.is_(True)).first()
    )
    if not integration:
        client_with_db.post("/api/v1/integrations/zoho/simulate-sync?count=1")
        integration = (
            db_session.query(ZohoIntegration).filter(ZohoIntegration.is_active.is_(True)).first()
        )
    assert integration is not None

    mock_invoices_resp = MagicMock()
    mock_invoices_resp.status_code = 200
    mock_invoices_resp.json.return_value = {
        "invoices": [
            {
                "invoice_id": "999888111",
                "invoice_number": "INV-MOCK-ZOHO-999",
                "total": "4500.00",
                "currency_code": "USD",
            }
        ]
    }

    # Generate small sample PDF
    test_doc = pymupdf.open()
    test_page = test_doc.new_page()
    test_page.insert_text(pymupdf.Point(50, 50), "Mock Zoho Invoice PDF")
    pdf_bytes = test_doc.tobytes()
    test_doc.close()

    mock_pdf_resp = MagicMock()
    mock_pdf_resp.status_code = 200
    mock_pdf_resp.content = pdf_bytes

    def mock_get(url: str, **kwargs):
        if "accept=pdf" in url:
            return mock_pdf_resp
        return mock_invoices_resp

    with patch("httpx.Client.get", side_effect=mock_get):
        sync_resp = client_with_db.post("/api/v1/integrations/zoho/sync?limit=5")
        assert sync_resp.status_code == 200
        sync_data = sync_resp.json()
        assert sync_data["synced_count"] == 1
        assert sync_data["invoices"][0]["invoice_number"] == "INV-MOCK-ZOHO-999"

        # Verify duplicate external ID is skipped on next sync
        sync_dup_resp = client_with_db.post("/api/v1/integrations/zoho/sync?limit=5")
        assert sync_dup_resp.status_code == 200
        dup_data = sync_dup_resp.json()
        assert dup_data["synced_count"] == 0
        assert dup_data["skipped_duplicate_count"] == 1


def test_zoho_disconnect(client_with_db: TestClient, db_session: Session) -> None:
    """Disconnect endpoint sets active integrations to inactive."""
    resp = client_with_db.post("/api/v1/integrations/zoho/disconnect")
    assert resp.status_code == 200

    status_resp = client_with_db.get("/api/v1/integrations/zoho/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["is_connected"] is False
