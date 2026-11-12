"""
Unit and integration test suite for ProcureMind Phase 11:
- Shared auditor key dependency and match decision gating
- Payments list pagination and filters
- Consolidated reconciliation queue with transaction-level granularity and selectinload
- Invoice list with PostgreSQL-derived approval and remaining balance
- Document preview URL generation, preview security headers, and token expiration
- Extracted field listing, patch field with auditor key, and permanent audit retention on parent deletion
- Overview dashboard summary with strict currency grouping and demo breakdown
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document, ExtractedField, FieldAuditLog
from app.models.enums import (
    AllocationReviewStatus,
    DecisionType,
    DiscrepancySeverity,
    DiscrepancyStatus,
    DocumentType,
    EnvironmentLabel,
    ExtractionMethod,
    MatchStatus,
    PaymentStatus,
    ProcessingStatus,
    ReviewState,
    TargetType,
    TransactionStatus,
)
from app.models.export import ExportTransaction, Invoice
from app.models.payment import Payment
from app.models.reconciliation import Discrepancy, HumanDecision, ReconciliationMatch
from app.services.document_service import compute_sha256, create_download_token
from app.storage.interface import get_storage_service


def test_match_decision_auditor_gate(client_with_db: TestClient, db_session: Session) -> None:
    """Tests that POST /matches/{id}/decision requires configured AUDITOR_API_KEY, valid X-Auditor-Key, and non-blank notes."""
    tx = ExportTransaction(
        id=uuid.uuid4(),
        transaction_reference="EXP-TEST-DEC-1",
        exporter_name="Apex Ltd",
        buyer_name="Solaria Imports",
        status=TransactionStatus.DISCREPANT,
    )
    db_session.add(tx)
    match = ReconciliationMatch(
        id=uuid.uuid4(),
        export_transaction_id=tx.id,
        match_type="invoice_payment",
        match_status=MatchStatus.REQUIRES_HUMAN_REVIEW,
        review_status=AllocationReviewStatus.SUGGESTED,
        allocated_amount=Decimal("1000.00"),
        currency="USD",
        rule_id="RULE-EXACT-001",
        business_key="bkey-match-dec-1",
    )
    db_session.add(match)
    db_session.commit()

    # 1. Unconfigured AUDITOR_API_KEY -> 503
    orig_key = settings.AUDITOR_API_KEY
    try:
        settings.AUDITOR_API_KEY = ""
        res_unconf = client_with_db.post(
            f"/api/v1/matches/{match.id}/decision",
            headers={"X-Auditor-Key": "any-key"},
            json={
                "decision": "approved",
                "reviewer_label": "Auditor Joe",
                "notes": "Approved match",
            },
        )
        assert res_unconf.status_code == 503

        # Configure test auditor key
        settings.AUDITOR_API_KEY = "test-auditor-secret-key"

        # 2. Missing auditor key -> 401
        res_no_key = client_with_db.post(
            f"/api/v1/matches/{match.id}/decision",
            json={
                "decision": "approved",
                "reviewer_label": "Auditor Joe",
                "notes": "Approved match",
            },
        )
        assert res_no_key.status_code == 401

        # 3. Invalid auditor key -> 401
        res_bad_key = client_with_db.post(
            f"/api/v1/matches/{match.id}/decision",
            headers={"X-Auditor-Key": "wrong-key"},
            json={
                "decision": "approved",
                "reviewer_label": "Auditor Joe",
                "notes": "Approved match",
            },
        )
        assert res_bad_key.status_code == 401

        # 4. Missing notes -> 422
        res_no_notes = client_with_db.post(
            f"/api/v1/matches/{match.id}/decision",
            headers={"X-Auditor-Key": settings.AUDITOR_API_KEY},
            json={"decision": "approved", "reviewer_label": "Auditor Joe"},
        )
        assert res_no_notes.status_code == 422

        # 5. Blank notes -> 422
        res_blank_notes = client_with_db.post(
            f"/api/v1/matches/{match.id}/decision",
            headers={"X-Auditor-Key": settings.AUDITOR_API_KEY},
            json={"decision": "approved", "reviewer_label": "Auditor Joe", "notes": "   "},
        )
        assert res_blank_notes.status_code == 422

        # 6. Valid key and valid note -> 200 OK
        res_ok = client_with_db.post(
            f"/api/v1/matches/{match.id}/decision",
            headers={"X-Auditor-Key": settings.AUDITOR_API_KEY},
            json={
                "decision": "approved",
                "reviewer_label": "Auditor Joe",
                "notes": "Verified against customs documents and payment capture",
            },
        )
        assert res_ok.status_code == 200
        data = res_ok.json()
        assert data["review_status"] == "approved"

        # Verify HumanDecision row written
        decision_row = (
            db_session.query(HumanDecision)
            .filter(
                HumanDecision.target_type == TargetType.RECONCILIATION_MATCH,
                HumanDecision.target_id == match.id,
            )
            .first()
        )
        assert decision_row is not None
        assert decision_row.decision == DecisionType.APPROVED
        assert decision_row.notes == "Verified against customs documents and payment capture"
    finally:
        settings.AUDITOR_API_KEY = orig_key


def test_list_payments_pagination_and_filters(
    client_with_db: TestClient, db_session: Session
) -> None:
    """Tests GET /api/v1/payments pagination and filtering by environment and demo status."""
    for i in range(5):
        p = Payment(
            id=uuid.uuid4(),
            provider="paypal",
            provider_order_id=f"ORD-TEST-{i}",
            invoice_reference=f"INV-TEST-{i}",
            currency="USD",
            gross_amount=Decimal("500.00"),
            status=PaymentStatus.COMPLETED if i % 2 == 0 else PaymentStatus.PENDING,
            environment=EnvironmentLabel.SANDBOX if i < 3 else EnvironmentLabel.LIVE,
            is_demo=i < 2,
        )
        db_session.add(p)
    db_session.commit()

    # Pagination: limit=2
    res_limit = client_with_db.get("/api/v1/payments?limit=2&offset=0")
    assert res_limit.status_code == 200
    assert len(res_limit.json()) == 2

    # Filter: sandbox only
    res_sandbox = client_with_db.get("/api/v1/payments?environment=sandbox")
    assert res_sandbox.status_code == 200
    assert all(item["environment"] == "sandbox" for item in res_sandbox.json())

    # Filter: is_demo=true
    res_demo = client_with_db.get("/api/v1/payments?is_demo=true")
    assert res_demo.status_code == 200
    assert all(item["is_demo"] is True for item in res_demo.json())


def test_reconciliation_queue_transaction_granularity(
    client_with_db: TestClient, db_session: Session
) -> None:
    """Tests that the reconciliation queue paginates by transaction (1 row per transaction) without row multiplication."""
    tx = ExportTransaction(
        id=uuid.uuid4(),
        transaction_reference="EXP-MULTI-MATCH",
        exporter_name="Apex Ltd",
        buyer_name="Solaria Imports",
        status=TransactionStatus.DISCREPANT,
    )
    db_session.add(tx)
    inv = Invoice(
        id=uuid.uuid4(),
        invoice_number="INV-MULTI-1",
        export_transaction_id=tx.id,
        seller_name="Apex Ltd",
        buyer_name="Solaria Imports",
        issue_date=datetime.now(UTC).date(),
        currency="USD",
        total_amount=Decimal("3000.00"),
    )
    db_session.add(inv)

    m1 = ReconciliationMatch(
        id=uuid.uuid4(),
        export_transaction_id=tx.id,
        invoice_id=inv.id,
        match_type="invoice_payment",
        match_status=MatchStatus.PARTIAL,
        review_status=AllocationReviewStatus.SUGGESTED,
        allocated_amount=Decimal("1500.00"),
        currency="USD",
        rule_id="RULE-01",
        business_key="bkey-m1",
    )
    m2 = ReconciliationMatch(
        id=uuid.uuid4(),
        export_transaction_id=tx.id,
        invoice_id=inv.id,
        match_type="invoice_payment",
        match_status=MatchStatus.PARTIAL,
        review_status=AllocationReviewStatus.SUGGESTED,
        allocated_amount=Decimal("1400.00"),
        currency="USD",
        rule_id="RULE-02",
        business_key="bkey-m2",
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    res = client_with_db.get("/api/v1/reconciliation/queue?search=EXP-MULTI-MATCH")
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] == 1
    assert len(data["items"]) == 1
    row = data["items"][0]
    assert row["reference"] == "EXP-MULTI-MATCH"
    assert len(row["matches"]) == 2
    assert row["active_match_count"] == 2
    assert row["requires_human_review"] is True


def test_reconciliation_queue_zero_match_review_state(
    client_with_db: TestClient, db_session: Session
) -> None:
    """Tests that a transaction with zero matches is surfaced as 'No match yet' and requires review if discrepant."""
    tx = ExportTransaction(
        id=uuid.uuid4(),
        transaction_reference="EXP-ZERO-MATCH",
        exporter_name="Apex Ltd",
        buyer_name="Harbor Trading",
        status=TransactionStatus.DISCREPANT,
    )
    db_session.add(tx)
    disc = Discrepancy(
        id=uuid.uuid4(),
        export_transaction_id=tx.id,
        rule_id="RULE-MISSING-DOC",
        severity=DiscrepancySeverity.WARNING,
        description="Invoice present but zero payment records received",
        status=DiscrepancyStatus.OPEN,
        calculation={"shortfall": "500.00"},
        business_key="bkey-zero-disc",
    )
    db_session.add(disc)
    db_session.commit()

    res = client_with_db.get("/api/v1/reconciliation/queue?search=EXP-ZERO-MATCH")
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] == 1
    row = data["items"][0]
    assert row["status_label"] == "No match yet"
    assert row["has_matches"] is False
    assert row["matches"] == []
    # Status DISCREPANT and open discrepancy mean review is required!
    assert row["requires_human_review"] is True
    assert row["shortfall_amount"] == "500.00"


def test_list_invoices_derived_approval_and_balance(
    client_with_db: TestClient, db_session: Session
) -> None:
    """Tests GET /api/v1/invoices derives approval state and remaining balance from PostgreSQL."""
    inv = Invoice(
        id=uuid.uuid4(),
        invoice_number="INV-BALANCE-TEST",
        seller_name="Apex Ltd",
        buyer_name="Solaria Imports",
        issue_date=datetime.now(UTC).date(),
        currency="USD",
        total_amount=Decimal("2500.00"),
    )
    db_session.add(inv)
    db_session.commit()

    # 1. Unapproved initial state
    res_init = client_with_db.get("/api/v1/invoices?search=INV-BALANCE-TEST")
    assert res_init.status_code == 200
    item = res_init.json()["items"][0]
    assert item["is_approved"] is False
    assert item["remaining_balance"] == "2500.00"

    # 2. Approve invoice via decision
    decision = HumanDecision(
        id=uuid.uuid4(),
        target_type=TargetType.INVOICE,
        target_id=inv.id,
        decision="approved",
        reviewer_label="Auditor Alice",
        notes="Approved for payment",
    )
    db_session.add(decision)
    db_session.commit()

    res_approved = client_with_db.get(
        "/api/v1/invoices?search=INV-BALANCE-TEST&approval_status=approved"
    )
    assert res_approved.status_code == 200
    assert len(res_approved.json()["items"]) == 1
    item_app = res_approved.json()["items"][0]
    assert item_app["is_approved"] is True
    assert item_app["approval_details"]["reviewer_label"] == "Auditor Alice"


def test_document_preview_url_and_security(client_with_db: TestClient, db_session: Session) -> None:
    """Tests signed preview URL generation, inline Content-Disposition, and token expiration/tampering."""
    content = b"%PDF-1.4 test invoice content"
    sha = compute_sha256(content)
    storage_key = f"preview-test-{uuid.uuid4()}.pdf"
    storage = get_storage_service()
    storage.save_file(storage_key, content)

    doc = Document(
        id=uuid.uuid4(),
        original_filename="commercial_invoice.pdf",
        media_type="application/pdf",
        size_bytes=len(content),
        sha256=sha,
        storage_key=storage_key,
        document_type=DocumentType.INVOICE,
        processing_status=ProcessingStatus.UPLOADED,
    )
    db_session.add(doc)
    db_session.commit()

    # 1. Generate preview URL
    res_url = client_with_db.get(f"/api/v1/documents/{doc.id}/preview-url")
    assert res_url.status_code == 200
    data_url = res_url.json()
    assert "preview_url" in data_url
    assert "/preview?expires=" in data_url["preview_url"]

    # 2. Fetch preview with valid token -> 200 OK with inline disposition
    res_preview = client_with_db.get(data_url["preview_url"])
    assert res_preview.status_code == 200
    assert res_preview.headers["Content-Disposition"] == 'inline; filename="commercial_invoice.pdf"'
    assert res_preview.headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox allow-scripts" in res_preview.headers["Content-Security-Policy"]
    assert res_preview.content == content

    # 3. Expired token -> 403 Forbidden
    expired_ts = int((datetime.now(UTC) - timedelta(seconds=10)).timestamp())
    expired_token = create_download_token(doc.id, expired_ts)
    res_expired = client_with_db.get(
        f"/api/v1/documents/{doc.id}/preview?expires={expired_ts}&token={expired_token}"
    )
    assert res_expired.status_code == 403

    # 4. Tampered token -> 403 Forbidden
    res_tampered = client_with_db.get(
        f"/api/v1/documents/{doc.id}/preview?expires={int(datetime.now(UTC).timestamp()) + 300}&token=invalid-hmac-token"
    )
    assert res_tampered.status_code == 403


def test_extracted_field_patch_and_permanent_audit_retention(
    client_with_db: TestClient, db_session: Session
) -> None:
    """Tests PATCH field with auditor key, immutable raw_value preservation, and audit log survival upon parent field deletion."""
    doc = Document(
        id=uuid.uuid4(),
        original_filename="inv_test.pdf",
        media_type="application/pdf",
        size_bytes=100,
        sha256="a" * 64,
        storage_key="test-key",
    )
    db_session.add(doc)
    field = ExtractedField(
        id=uuid.uuid4(),
        document_id=doc.id,
        field_name="total_amount",
        raw_value="USD 2,400.00",
        normalized_value="2400.00",
        confidence=Decimal("0.8500"),
        review_state=ReviewState.PENDING,
        extraction_method=ExtractionMethod.LLM,
    )
    db_session.add(field)
    db_session.commit()

    orig_key = settings.AUDITOR_API_KEY
    try:
        settings.AUDITOR_API_KEY = "test-auditor-secret-key"

        # 1. Unauthorized PATCH -> 401
        res_unauth = client_with_db.patch(
            f"/api/v1/documents/{doc.id}/fields/{field.id}",
            json={"new_normalized_value": "2500.00", "reviewer_label": "Auditor Bob"},
        )
        assert res_unauth.status_code == 401

        # 2. Authorized PATCH -> 200 OK
        res_auth = client_with_db.patch(
            f"/api/v1/documents/{doc.id}/fields/{field.id}",
            headers={"X-Auditor-Key": settings.AUDITOR_API_KEY},
            json={
                "new_normalized_value": "2500.00",
                "reviewer_label": "Auditor Bob",
                "notes": "Corrected total based on packing slip page 2",
            },
        )
        assert res_auth.status_code == 200
        field_data = res_auth.json()["field"]
        assert field_data["normalized_value"] == "2500.00"
        # Preserves immutable source text!
        assert field_data["raw_value"] == "USD 2,400.00"
        assert field_data["extraction_method"] == "manual"
        assert field_data["review_state"] == "human_verified"

        # Verify audit log created
        field_id_snapshot = field.id
        audit_logs = (
            db_session.query(FieldAuditLog)
            .filter(FieldAuditLog.extracted_field_id_snapshot == field_id_snapshot)
            .all()
        )
        assert len(audit_logs) == 1
        assert audit_logs[0].old_normalized_value == "2400.00"
        assert audit_logs[0].new_normalized_value == "2500.00"
        assert audit_logs[0].reviewer_label == "Auditor Bob"

        # 3. Permanent Audit Retention: Delete parent extracted field
        db_session.delete(field)
        db_session.commit()

        # Confirm FieldAuditLog is NOT deleted (ondelete=SET NULL, snapshot preserved)
        audit_logs_after = (
            db_session.query(FieldAuditLog)
            .filter(FieldAuditLog.extracted_field_id_snapshot == field_id_snapshot)
            .all()
        )
        assert len(audit_logs_after) == 1
        assert audit_logs_after[0].extracted_field_id is None
        assert audit_logs_after[0].extracted_field_id_snapshot == field_id_snapshot
    finally:
        settings.AUDITOR_API_KEY = orig_key


def test_dashboard_summary_aggregates(client_with_db: TestClient, db_session: Session) -> None:
    """Tests GET /api/v1/dashboard/summary calculates authoritative counters, groups currency, and separates demo records."""
    p_usd = Payment(
        id=uuid.uuid4(),
        provider="paypal",
        invoice_reference="INV-USD",
        currency="USD",
        gross_amount=Decimal("1000.00"),
        fee_amount=Decimal("30.00"),
        net_amount=Decimal("970.00"),
        status=PaymentStatus.COMPLETED,
        environment=EnvironmentLabel.SANDBOX,
        is_demo=True,
    )
    p_eur = Payment(
        id=uuid.uuid4(),
        provider="paypal",
        invoice_reference="INV-EUR",
        currency="EUR",
        gross_amount=Decimal("2000.00"),
        fee_amount=Decimal("50.00"),
        net_amount=Decimal("1950.00"),
        status=PaymentStatus.COMPLETED,
        environment=EnvironmentLabel.SANDBOX,
        is_demo=False,
    )
    db_session.add_all([p_usd, p_eur])
    db_session.commit()

    res = client_with_db.get("/api/v1/dashboard/summary")
    assert res.status_code == 200
    data = res.json()

    assert data["sandbox_payments_count"] >= 2
    # Verify currencies are strictly separated (never cross-summed)
    currencies = {v["currency"]: v for v in data["payments_by_currency"]}
    assert "USD" in currencies
    assert "EUR" in currencies
    assert currencies["USD"]["total_gross"] == "1000.00"
    assert currencies["EUR"]["total_gross"] == "2000.00"

    # Verify demo breakdown has demo_* and non_demo_*
    breakdown = data["demo_breakdown"]
    assert "demo_payments" in breakdown
    assert "non_demo_payments" in breakdown
    assert breakdown["demo_payments"] >= 1
    assert breakdown["non_demo_payments"] >= 1
