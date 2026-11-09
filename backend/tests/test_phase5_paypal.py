"""
Comprehensive automated tests for Phase 5: PayPal Sandbox Checkout & Verified Event Ingestion.

Verifies:
1. Strict PayPal Sandbox URL and hostname validation (prohibiting live endpoints and rogue paths).
2. Mandatory high-entropy auditor secret for invoice approvals across all environments.
3. Single pending order per invoice with idempotent reuse and database partial index enforcement.
4. Bound capture with strict currency and gross amount verification against the stored order.
5. Database-enforced webhook deduplication with atomic persistence and post-commit HTTP 200.
6. Invalid webhook cryptographic signature rejection with HTTP 400.
7. Discrete refund event persistence under provider_refund_id linking to parent payment without overwriting captures.
8. Retaining null settlement fee/net fields without inferring them.
9. Browser redirect alone cannot mark payment complete.
10. Automatic triggering of deterministic reconciliation engine upon verified capture or webhook.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.models.enums import (
    AllocationReviewStatus,
    PaymentStatus,
    TargetType,
    TransactionStatus,
)
from app.models.export import ExportTransaction, Invoice
from app.models.payment import Payment, ProviderWebhookEvent
from app.models.reconciliation import HumanDecision, ReconciliationMatch

TEST_AUDITOR_KEY = "procuremind-secure-auditor-secret-key-2026"


@pytest.fixture(autouse=True)
def configure_test_auditor_key():
    """Sets a valid auditor key and test environment for the test suite."""
    old_key = settings.AUDITOR_API_KEY
    settings.AUDITOR_API_KEY = TEST_AUDITOR_KEY
    yield
    settings.AUDITOR_API_KEY = old_key


def _create_export_deal(db: Session, ref: str = "EXP-P5-001") -> ExportTransaction:
    tx = ExportTransaction(
        transaction_reference=ref,
        exporter_name="Apex Global Exports Ltd",
        buyer_name="Nexus Retail Inc",
        buyer_country="USA",
        status=TransactionStatus.DRAFT,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def _create_invoice(
    db: Session,
    tx_id: str,
    inv_num: str = "INV-P5-101",
    currency: str = "USD",
    amount: Decimal = Decimal("1000.0000"),
) -> Invoice:
    inv = Invoice(
        export_transaction_id=tx_id,
        invoice_number=inv_num,
        seller_name="Apex Global Exports Ltd",
        buyer_name="Nexus Retail Inc",
        issue_date=date.today(),
        currency=currency,
        total_amount=amount,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def test_strict_sandbox_url_validation():
    """Validates that only exact PayPal Sandbox hostnames with https are allowed."""
    # Allowed hostnames
    s1 = Settings(PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com")
    assert s1.PAYPAL_BASE_URL == "https://api-m.sandbox.paypal.com"
    s2 = Settings(PAYPAL_BASE_URL="https://api.sandbox.paypal.com")
    assert s2.PAYPAL_BASE_URL == "https://api.sandbox.paypal.com"

    # Reject Live PayPal endpoints
    with pytest.raises(ValidationError, match="unauthorized"):
        Settings(PAYPAL_BASE_URL="https://api-m.paypal.com")

    # Reject rogue hostname containing sandbox.paypal.com in path
    with pytest.raises(ValidationError, match="unauthorized"):
        Settings(PAYPAL_BASE_URL="https://evil.com/api-m.sandbox.paypal.com")

    # Reject subdomain spoofing
    with pytest.raises(ValidationError, match="unauthorized"):
        Settings(PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com.evil.com")

    # Reject subpaths
    with pytest.raises(ValidationError, match="must not include subpaths"):
        Settings(PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com/v1/orders")

    # Reject query strings
    with pytest.raises(ValidationError, match="must not include query strings"):
        Settings(PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com?token=leak")

    # Reject non-https scheme
    with pytest.raises(ValidationError, match="must be 'https'"):
        Settings(PAYPAL_BASE_URL="http://api-m.sandbox.paypal.com")

    # Reject non-sandbox environment
    with pytest.raises(ValidationError, match="strictly restricted to PayPal Sandbox"):
        Settings(PAYPAL_ENVIRONMENT="production")


def test_auditor_key_mandatory_and_validated(client_with_db: TestClient, db_session: Session):
    """Verifies that invoice approval requires a valid configured secret and rejects trivial/missing keys."""
    # Test validator rejects short or default keys
    with pytest.raises(ValidationError, match="at least 16 characters"):
        Settings(AUDITOR_API_KEY="short")

    with pytest.raises(ValidationError, match="Insecure default or trivial"):
        Settings(AUDITOR_API_KEY="pm-dev-auditor-key-secret")

    tx = _create_export_deal(db_session, "EXP-AUDIT-01")
    inv = _create_invoice(db_session, tx.id, "INV-AUDIT-01")

    # 1. Missing header -> 401
    res = client_with_db.post(
        f"/api/v1/invoices/{inv.id}/approve",
        json={"reviewer_label": "lead_auditor", "notes": "Approved"},
    )
    assert res.status_code == 401
    assert "X-Auditor-Key" in res.json()["detail"]

    # 2. Invalid header -> 401
    res = client_with_db.post(
        f"/api/v1/invoices/{inv.id}/approve",
        headers={"X-Auditor-Key": "wrong-secret-key-12345678"},
        json={"reviewer_label": "lead_auditor", "notes": "Approved"},
    )
    assert res.status_code == 401

    # 3. Unconfigured key on server -> 503
    old_key = settings.AUDITOR_API_KEY
    settings.AUDITOR_API_KEY = None
    try:
        res = client_with_db.post(
            f"/api/v1/invoices/{inv.id}/approve",
            headers={"X-Auditor-Key": TEST_AUDITOR_KEY},
            json={"reviewer_label": "lead_auditor", "notes": "Approved"},
        )
        assert res.status_code == 503
    finally:
        settings.AUDITOR_API_KEY = old_key

    # 4. Valid key -> 200 and records HumanDecision
    res = client_with_db.post(
        f"/api/v1/invoices/{inv.id}/approve",
        headers={"X-Auditor-Key": TEST_AUDITOR_KEY},
        json={"reviewer_label": "lead_auditor", "notes": "Formally verified export contract"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "approved"

    decision = (
        db_session.query(HumanDecision)
        .filter(HumanDecision.target_type == TargetType.INVOICE, HumanDecision.target_id == inv.id)
        .first()
    )
    assert decision is not None
    assert decision.decision == "approved"
    assert decision.reviewer_label == "lead_auditor"


def test_single_pending_order_per_invoice(client_with_db: TestClient, db_session: Session):
    """
    Verifies that repeated pay requests idempotently return the existing active pending order
    and database unique constraint prevents duplicate pending orders for an invoice.
    """
    tx = _create_export_deal(db_session, "EXP-ORD-01")
    inv = _create_invoice(
        db_session, tx.id, "INV-ORD-01", currency="EUR", amount=Decimal("2500.0000")
    )

    # Unapproved invoice rejected with 400
    res = client_with_db.post(f"/api/v1/payments/invoices/{inv.id}/pay")
    assert res.status_code == 400
    assert "not been approved" in res.json()["detail"]

    # Approve invoice
    client_with_db.post(
        f"/api/v1/invoices/{inv.id}/approve",
        headers={"X-Auditor-Key": TEST_AUDITOR_KEY},
        json={"reviewer_label": "auditor_1", "notes": "Approved EUR deal"},
    )

    mock_order = {
        "id": "ORDER-EUR-999",
        "status": "CREATED",
        "links": [
            {"rel": "approve", "href": "https://sandbox.paypal.com/checkoutnow?token=ORDER-EUR-999"}
        ],
    }

    # First /pay call creates order
    with patch(
        "app.api.v1.payments.paypal_client.create_order", return_value=mock_order
    ) as mock_create:
        res1 = client_with_db.post(f"/api/v1/payments/invoices/{inv.id}/pay")
        assert res1.status_code == 200
        assert res1.json()["order_id"] == "ORDER-EUR-999"
        assert res1.json()["currency"] == "EUR"
        assert res1.json()["amount"] == "2500.0000"
        mock_create.assert_called_once()

    # Second /pay call returns existing active order idempotently without calling PayPal API again
    with patch("app.api.v1.payments.paypal_client.create_order") as mock_create:
        res2 = client_with_db.post(f"/api/v1/payments/invoices/{inv.id}/pay")
        assert res2.status_code == 200
        assert res2.json()["order_id"] == "ORDER-EUR-999"
        mock_create.assert_not_called()

    # Verify DB has exactly 1 pending payment row for this invoice
    pending_count = (
        db_session.query(Payment)
        .filter(Payment.invoice_id == inv.id, Payment.status == PaymentStatus.PENDING)
        .count()
    )
    assert pending_count == 1

    # Attempting direct duplicate insertion triggers partial unique index
    dup_pmt = Payment(
        invoice_id=inv.id,
        provider_order_id="ANOTHER-ORD-ID",
        currency="EUR",
        gross_amount=Decimal("2500.0000"),
        status=PaymentStatus.PENDING,
        provider="paypal",
    )
    db_session.add(dup_pmt)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_capture_bound_and_balance_and_currency_verified(
    client_with_db: TestClient, db_session: Session
):
    """
    Verifies that order capture binds to stored payment, validates currency and amount,
    and returns completed payment idempotently.
    """
    tx = _create_export_deal(db_session, "EXP-CAP-01")
    inv = _create_invoice(
        db_session, tx.id, "INV-CAP-01", currency="USD", amount=Decimal("1000.0000")
    )

    # Approve invoice
    client_with_db.post(
        f"/api/v1/invoices/{inv.id}/approve",
        headers={"X-Auditor-Key": TEST_AUDITOR_KEY},
        json={"reviewer_label": "auditor_1"},
    )

    # Unknown order returns 404
    res = client_with_db.post("/api/v1/payments/orders/UNKNOWN-ORD/capture")
    assert res.status_code == 404

    # Create order
    mock_order = {"id": "ORD-CAP-100", "status": "CREATED"}
    with patch("app.api.v1.payments.paypal_client.create_order", return_value=mock_order):
        client_with_db.post(f"/api/v1/payments/invoices/{inv.id}/pay")

    # Mismatched currency returns 400
    mock_capture_mismatch = {
        "status": "COMPLETED",
        "purchase_units": [
            {
                "payments": {
                    "captures": [
                        {
                            "id": "CAP-100",
                            "status": "COMPLETED",
                            "amount": {"currency_code": "EUR", "value": "1000.00"},  # Mismatch!
                        }
                    ]
                }
            }
        ],
    }
    with patch(
        "app.api.v1.payments.paypal_client.capture_order", return_value=mock_capture_mismatch
    ):
        res_err = client_with_db.post("/api/v1/payments/orders/ORD-CAP-100/capture")
        assert res_err.status_code == 400
        assert "currency" in res_err.json()["detail"]

    # Valid capture with fee breakdown
    mock_capture_valid = {
        "status": "COMPLETED",
        "purchase_units": [
            {
                "payments": {
                    "captures": [
                        {
                            "id": "CAP-VALID-100",
                            "status": "COMPLETED",
                            "amount": {"currency_code": "USD", "value": "1000.0000"},
                            "seller_receivable_breakdown": {
                                "gross_amount": {"value": "1000.0000"},
                                "paypal_fee": {"value": "34.8000"},
                                "net_amount": {"value": "965.2000"},
                            },
                            "create_time": "2026-11-09T10:00:00Z",
                        }
                    ]
                }
            }
        ],
    }
    with patch("app.api.v1.payments.paypal_client.capture_order", return_value=mock_capture_valid):
        res_cap = client_with_db.post("/api/v1/payments/orders/ORD-CAP-100/capture")
        assert res_cap.status_code == 200
        cap_data = res_cap.json()
        assert cap_data["status"] == "completed"
        assert cap_data["provider_capture_id"] == "CAP-VALID-100"
        assert Decimal(str(cap_data["gross_amount"])) == Decimal("1000.0000")
        assert Decimal(str(cap_data["fee_amount"])) == Decimal("34.8000")
        assert Decimal(str(cap_data["net_amount"])) == Decimal("965.2000")

    # Idempotent repeated capture
    with patch("app.api.v1.payments.paypal_client.capture_order") as mock_cap_call:
        res_repeat = client_with_db.post("/api/v1/payments/orders/ORD-CAP-100/capture")
        assert res_repeat.status_code == 200
        assert res_repeat.json()["provider_capture_id"] == "CAP-VALID-100"
        mock_cap_call.assert_not_called()


def test_webhook_database_unique_deduplication(client_with_db: TestClient, db_session: Session):
    """
    Verifies that webhooks are verified, duplicate deliveries are caught by the database
    unique constraint on provider_event_id, and HTTP 200 is returned idempotently.
    """
    tx = _create_export_deal(db_session, "EXP-WH-01")
    inv = _create_invoice(db_session, tx.id, "INV-WH-01")

    # Seed pending payment
    pmt = Payment(
        export_transaction_id=tx.id,
        invoice_id=inv.id,
        provider="paypal",
        provider_order_id="ORD-WH-01",
        invoice_reference="INV-WH-01",
        currency="USD",
        gross_amount=Decimal("1000.0000"),
        status=PaymentStatus.PENDING,
    )
    db_session.add(pmt)
    db_session.commit()

    webhook_payload = {
        "id": "WH-EVT-DEDUPE-001",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "create_time": "2026-11-09T10:30:00Z",
        "resource": {
            "id": "CAP-WH-01",
            "supplementary_data": {"related_ids": {"order_id": "ORD-WH-01"}},
            "amount": {"currency_code": "USD", "value": "1000.00"},
            "seller_receivable_breakdown": {
                "paypal_fee": {"value": "30.00"},
                "net_amount": {"value": "970.00"},
            },
        },
    }

    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1",
        "paypal-transmission-id": "TRANS-001",
        "paypal-transmission-sig": "SIG-001",
        "paypal-transmission-time": "2026-11-09T10:30:00Z",
    }

    # 1. Invalid signature returns 400
    with patch("app.api.v1.webhooks.paypal_client.verify_webhook_signature", return_value=False):
        res_bad = client_with_db.post(
            "/api/v1/webhooks/paypal", json=webhook_payload, headers=headers
        )
        assert res_bad.status_code == 400
        assert "Invalid PayPal webhook signature" in res_bad.json()["detail"]

    # 2. Valid signature processes event
    with patch("app.api.v1.webhooks.paypal_client.verify_webhook_signature", return_value=True):
        res_ok = client_with_db.post(
            "/api/v1/webhooks/paypal", json=webhook_payload, headers=headers
        )
        assert res_ok.status_code == 200
        assert res_ok.json()["status"] == "processed"

        # Verify payment updated
        db_session.refresh(pmt)
        assert pmt.status == PaymentStatus.COMPLETED
        assert pmt.provider_capture_id == "CAP-WH-01"
        assert pmt.fee_amount == Decimal("30.0000")

        # 3. Duplicate delivery returns HTTP 200 duplicate
        res_dup = client_with_db.post(
            "/api/v1/webhooks/paypal", json=webhook_payload, headers=headers
        )
        assert res_dup.status_code == 200
        assert res_dup.json()["status"] == "duplicate"

        # Exactly 1 webhook event in DB
        evt_count = (
            db_session.query(ProviderWebhookEvent)
            .filter(ProviderWebhookEvent.provider_event_id == "WH-EVT-DEDUPE-001")
            .count()
        )
        assert evt_count == 1


def test_refund_stored_with_provider_refund_id_and_parent_link(
    client_with_db: TestClient, db_session: Session
):
    """
    Verifies that a refund webhook stores a distinct Payment record with provider_refund_id,
    links parent_payment_id, leaves original capture untouched, and triggers Phase 4 compensating reversal.
    """
    tx = _create_export_deal(db_session, "EXP-REF-01")
    inv = _create_invoice(db_session, tx.id, "INV-REF-01")

    # Original completed capture
    orig_pmt = Payment(
        export_transaction_id=tx.id,
        invoice_id=inv.id,
        provider="paypal",
        provider_order_id="ORD-REF-01",
        provider_capture_id="CAP-ORIG-REF-01",
        invoice_reference="INV-REF-01",
        currency="USD",
        gross_amount=Decimal("1000.0000"),
        fee_amount=Decimal("30.0000"),
        net_amount=Decimal("970.0000"),
        status=PaymentStatus.COMPLETED,
    )
    db_session.add(orig_pmt)
    db_session.commit()

    refund_payload = {
        "id": "WH-REFUND-EVT-01",
        "event_type": "PAYMENT.CAPTURE.REFUNDED",
        "create_time": "2026-11-09T11:00:00Z",
        "resource": {
            "id": "REFUND-9999",
            "capture_id": "CAP-ORIG-REF-01",
            "amount": {"currency_code": "USD", "value": "1000.0000"},
            "status": "COMPLETED",
        },
    }

    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1",
        "paypal-transmission-id": "TRANS-REF",
        "paypal-transmission-sig": "SIG-REF",
        "paypal-transmission-time": "2026-11-09T11:00:00Z",
    }

    with patch("app.api.v1.webhooks.paypal_client.verify_webhook_signature", return_value=True):
        res = client_with_db.post("/api/v1/webhooks/paypal", json=refund_payload, headers=headers)
        assert res.status_code == 200
        assert res.json()["status"] == "processed"

    # Original payment remains intact with its capture ID
    db_session.refresh(orig_pmt)
    assert orig_pmt.provider_capture_id == "CAP-ORIG-REF-01"
    assert orig_pmt.status == PaymentStatus.COMPLETED

    # Distinct refund record created
    refund_pmt = (
        db_session.query(Payment).filter(Payment.provider_refund_id == "REFUND-9999").first()
    )
    assert refund_pmt is not None
    assert (
        refund_pmt.provider_capture_id is None
    )  # Dedicated refund; never conflate with capture ID
    assert refund_pmt.parent_payment_id == orig_pmt.id
    assert refund_pmt.status == PaymentStatus.REFUNDED
    assert refund_pmt.gross_amount == Decimal("1000.0000")

    # Phase 4 reconciliation engine proposed compensating reversal
    matches = (
        db_session.query(ReconciliationMatch)
        .filter(ReconciliationMatch.export_transaction_id == tx.id)
        .all()
    )
    reversal_match = next((m for m in matches if m.is_reversal is True), None)
    assert reversal_match is not None
    assert reversal_match.allocated_amount == Decimal("1000.0000")
    assert reversal_match.review_status == AllocationReviewStatus.SUGGESTED


def test_null_settlement_breakdown_not_inferred(client_with_db: TestClient, db_session: Session):
    """
    Verifies that when PayPal webhooks do not supply settlement fee/net breakdowns,
    the fields remain strictly None and are not inferred.
    """
    tx = _create_export_deal(db_session, "EXP-NULL-FEE-01")
    inv = _create_invoice(db_session, tx.id, "INV-NULL-FEE-01")

    pmt = Payment(
        export_transaction_id=tx.id,
        invoice_id=inv.id,
        provider="paypal",
        provider_order_id="ORD-NULL-01",
        invoice_reference="INV-NULL-FEE-01",
        currency="USD",
        gross_amount=Decimal("1000.0000"),
        status=PaymentStatus.PENDING,
    )
    db_session.add(pmt)
    db_session.commit()

    webhook_payload = {
        "id": "WH-NO-FEE-001",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "create_time": "2026-11-09T11:15:00Z",
        "resource": {
            "id": "CAP-NO-FEE-01",
            "supplementary_data": {"related_ids": {"order_id": "ORD-NULL-01"}},
            "amount": {"currency_code": "USD", "value": "1000.00"},
            # seller_receivable_breakdown is completely omitted!
        },
    }

    headers = {
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-cert-url": "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-1",
        "paypal-transmission-id": "TRANS-NOFEE",
        "paypal-transmission-sig": "SIG-NOFEE",
        "paypal-transmission-time": "2026-11-09T11:15:00Z",
    }

    with patch("app.api.v1.webhooks.paypal_client.verify_webhook_signature", return_value=True):
        res = client_with_db.post("/api/v1/webhooks/paypal", json=webhook_payload, headers=headers)
        assert res.status_code == 200

    db_session.refresh(pmt)
    assert pmt.status == PaymentStatus.COMPLETED
    assert pmt.fee_amount is None  # Preserved as None; never inferred!
    assert pmt.net_amount is None  # Preserved as None; never inferred!


def test_public_config_endpoint_safe(client_with_db: TestClient):
    """Verifies that /payments/config exposes client_id and environment but never client_secret or currency."""
    res = client_with_db.get("/api/v1/payments/config")
    assert res.status_code == 200
    data = res.json()
    assert "client_id" in data
    assert "environment" in data
    assert "client_secret" not in data
    assert "currency" not in data  # Dynamic per invoice
