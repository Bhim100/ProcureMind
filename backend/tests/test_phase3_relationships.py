"""
Comprehensive automated tests for Phase 3: PostgreSQL Transaction Relationships.

Verifies:
1. Demo transaction detail context and retrieval of all trade records with link statuses.
2. Exact-reference automated discovery creating proposed links (never confirmed).
3. Discovery idempotency (no duplicate rows on re-run).
4. Missing and conflicting references reported dynamically as unlinked without errors.
5. Ambiguous references (multiple matches) creating no link and reporting candidate IDs.
6. Manual link creation strictly creating proposed links.
7. Deduplication preventing duplicate link creation (409 Conflict).
8. Cross-transaction linking rejection (400 Bad Request).
9. Explicit, atomic human ownership assignment and rejection of reassignment.
10. Human decision endpoint confirming/rejecting links and writing HumanDecision audit records.
11. 404 error handling for non-existent transactions and records.
12. Deletion protection enforcing RESTRICT.
"""

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import (
    DecisionType,
    LinkMethod,
    LinkStatus,
    LinkType,
    TargetType,
    TransactionStatus,
)
from app.models.export import ExportTransaction, Invoice, ShippingBill
from app.models.payment import BankTransaction, Payment, Settlement
from app.models.reconciliation import HumanDecision
from app.models.relationship import TransactionLink
from app.services.seed_data import seed_demo_scenarios


# ---------------------------------------------------------------------------
# 1. Demo Context Retrieval & Unlinked Initial Status
# ---------------------------------------------------------------------------
def test_demo_seed_transaction_detail_with_linked_records(
    client_with_db: TestClient, db_session: Session
) -> None:
    """Verifies that opening a seeded transaction returns all trade records with link_status='unlinked'."""
    seed_demo_scenarios(db_session)

    tx = (
        db_session.query(ExportTransaction)
        .filter(ExportTransaction.transaction_reference == "EXP-DEMO-001")
        .first()
    )
    assert tx is not None

    resp = client_with_db.get(f"/api/v1/transactions/{tx.id}")
    assert resp.status_code == 200
    data = resp.json()

    assert data["transaction_reference"] == "EXP-DEMO-001"
    assert data["exporter_name"] == "Apex Global Exports Ltd"
    assert len(data["invoices"]) == 1
    assert data["invoices"][0]["invoice_number"] == "INV-2026-001"
    assert data["invoices"][0]["link_status"] == "unlinked"

    assert len(data["shipping_bills"]) == 1
    assert data["shipping_bills"][0]["shipping_bill_number"] == "SB-DEMO-1001"
    assert data["shipping_bills"][0]["link_status"] == "unlinked"

    assert len(data["payments"]) == 1
    assert data["payments"][0]["provider_capture_id"] == "CAP-DEMO-1001"
    assert data["payments"][0]["link_status"] == "unlinked"

    assert len(data["links"]) == 0


# ---------------------------------------------------------------------------
# 2. Exact-Reference Automated Discovery Creates Proposed Links
# ---------------------------------------------------------------------------
def test_exact_reference_discovery_creates_proposed_links(
    client_with_db: TestClient, db_session: Session
) -> None:
    """Verifies that exact-reference discovery creates proposed links (never confirmed) and attaches evidence."""
    seed_demo_scenarios(db_session)

    tx = (
        db_session.query(ExportTransaction)
        .filter(ExportTransaction.transaction_reference == "EXP-DEMO-001")
        .first()
    )
    assert tx is not None

    disc_resp = client_with_db.post(f"/api/v1/transactions/{tx.id}/discover-links")
    assert disc_resp.status_code == 200
    disc_data = disc_resp.json()

    created_links = disc_data["created_links"]
    assert len(created_links) == 2

    link_types = {link["link_type"] for link in created_links}
    assert LinkType.INVOICE_SHIPPING_BILL.value in link_types
    assert LinkType.INVOICE_PAYMENT.value in link_types

    # Critical check: Automated discovery must ALWAYS set proposed, never confirmed
    for link in created_links:
        assert link["status"] == LinkStatus.PROPOSED.value
        assert link["link_method"] == LinkMethod.AUTO_EXACT.value
        assert link["explicit_reference"] == "INV-2026-001"
        assert link["normalized_reference"] == "INV-2026-001"

    # Verify transaction detail now reflects proposed link status
    detail_resp = client_with_db.get(f"/api/v1/transactions/{tx.id}")
    detail_data = detail_resp.json()
    assert detail_data["invoices"][0]["link_status"] == "proposed"
    assert detail_data["shipping_bills"][0]["link_status"] == "proposed"
    assert detail_data["payments"][0]["link_status"] == "proposed"

    # Verify evidence references attached
    links_resp = client_with_db.get(f"/api/v1/transactions/{tx.id}/links")
    assert links_resp.status_code == 200
    links_data = links_resp.json()
    sb_link = next(
        lnk for lnk in links_data if lnk["link_type"] == LinkType.INVOICE_SHIPPING_BILL.value
    )
    assert len(sb_link["evidence_references"]) >= 1
    ev = sb_link["evidence_references"][0]
    assert ev["raw_value"] == "INV-2026-001"
    assert ev["source_record_type"] == "shipping_bill"


# ---------------------------------------------------------------------------
# 3. Discovery Idempotency
# ---------------------------------------------------------------------------
def test_discovery_is_idempotent(client_with_db: TestClient, db_session: Session) -> None:
    """Verifies that re-running discovery creates zero duplicate rows."""
    seed_demo_scenarios(db_session)
    tx = (
        db_session.query(ExportTransaction)
        .filter(ExportTransaction.transaction_reference == "EXP-DEMO-001")
        .first()
    )
    assert tx is not None

    # First run
    client_with_db.post(f"/api/v1/transactions/{tx.id}/discover-links")
    initial_count = (
        db_session.query(TransactionLink)
        .filter(TransactionLink.export_transaction_id == tx.id)
        .count()
    )
    assert initial_count == 2

    # Second run
    disc_resp = client_with_db.post(f"/api/v1/transactions/{tx.id}/discover-links")
    assert disc_resp.status_code == 200
    disc_data = disc_resp.json()

    assert len(disc_data["created_links"]) == 0
    assert len(disc_data["existing_links"]) == 2

    final_count = (
        db_session.query(TransactionLink)
        .filter(TransactionLink.export_transaction_id == tx.id)
        .count()
    )
    assert final_count == initial_count


# ---------------------------------------------------------------------------
# 4. Missing and Conflicting Reference Handling
# ---------------------------------------------------------------------------
def test_missing_and_conflicting_references_reported_unlinked(
    client_with_db: TestClient, db_session: Session
) -> None:
    """Verifies that missing or conflicting references remain unlinked and are returned in unlinked_records."""
    seed_demo_scenarios(db_session)
    tx = (
        db_session.query(ExportTransaction)
        .filter(ExportTransaction.transaction_reference == "EXP-DEMO-001")
        .first()
    )
    assert tx is not None

    # Synthetic shipping bill with missing invoice reference
    sb_missing = ShippingBill(
        shipping_bill_number="SB-SYNTH-MISSING",
        export_transaction_id=tx.id,
        invoice_reference=None,
        exporter_name="Apex Global Exports Ltd",
        buyer_name="Nexus Retail Inc",
        declared_currency="USD",
        declared_value=Decimal("500.00"),
        is_demo=True,
    )
    # Synthetic shipping bill with conflicting reference
    sb_conflict = ShippingBill(
        shipping_bill_number="SB-SYNTH-CONFLICT",
        export_transaction_id=tx.id,
        invoice_reference="INV-NONEXISTENT-999",
        exporter_name="Apex Global Exports Ltd",
        buyer_name="Nexus Retail Inc",
        declared_currency="USD",
        declared_value=Decimal("750.00"),
        is_demo=True,
    )
    db_session.add_all([sb_missing, sb_conflict])
    db_session.commit()

    disc_resp = client_with_db.post(f"/api/v1/transactions/{tx.id}/discover-links")
    assert disc_resp.status_code == 200
    unlinked = disc_resp.json()["unlinked_records"]

    missing_report = next((u for u in unlinked if u["record_id"] == str(sb_missing.id)), None)
    assert missing_report is not None
    assert "Missing invoice reference" in missing_report["reason"]

    conflict_report = next((u for u in unlinked if u["record_id"] == str(sb_conflict.id)), None)
    assert conflict_report is not None
    assert "does not match any invoice" in conflict_report["reason"]


# ---------------------------------------------------------------------------
# 5. Ambiguous Reference Handling (Multiple Candidates)
# ---------------------------------------------------------------------------
def test_ambiguous_reference_discovery(client_with_db: TestClient, db_session: Session) -> None:
    """Verifies that if a reference matches multiple candidate invoices, no link is created and candidate IDs are returned."""
    tx = ExportTransaction(
        transaction_reference="EXP-AMBIGUOUS-01",
        exporter_name="Test Exporter",
        buyer_name="Test Buyer",
        status=TransactionStatus.DRAFT,
    )
    db_session.add(tx)
    db_session.flush()

    inv_1 = Invoice(
        invoice_number="INV-DUP-100",
        export_transaction_id=tx.id,
        seller_name="Test Exporter",
        buyer_name="Test Buyer",
        currency="USD",
        total_amount=Decimal("100.00"),
    )
    inv_2 = Invoice(
        invoice_number=" inv-dup-100 ",  # Identical normalized reference
        export_transaction_id=tx.id,
        seller_name="Test Exporter",
        buyer_name="Test Buyer",
        currency="USD",
        total_amount=Decimal("100.00"),
    )
    sb = ShippingBill(
        shipping_bill_number="SB-AMBIGUOUS-01",
        export_transaction_id=tx.id,
        invoice_reference="INV-DUP-100",
        exporter_name="Test Exporter",
        buyer_name="Test Buyer",
        declared_currency="USD",
        declared_value=Decimal("100.00"),
    )
    db_session.add_all([inv_1, inv_2, sb])
    db_session.commit()

    disc_resp = client_with_db.post(f"/api/v1/transactions/{tx.id}/discover-links")
    assert disc_resp.status_code == 200
    disc_data = disc_resp.json()

    # No link should be formed
    assert len(disc_data["created_links"]) == 0

    # Ambiguous report must be returned with candidates
    unlinked = disc_data["unlinked_records"]
    assert len(unlinked) == 1
    report = unlinked[0]
    assert report["record_id"] == str(sb.id)
    assert "Ambiguous match" in report["reason"]
    assert set(report["candidate_ids"]) == {str(inv_1.id), str(inv_2.id)}


# ---------------------------------------------------------------------------
# 6. Manual Link Creation Is Always Proposed
# ---------------------------------------------------------------------------
def test_manual_link_creation_is_always_proposed(
    client_with_db: TestClient, db_session: Session
) -> None:
    """Verifies that manually creating a link always creates status='proposed'."""
    seed_demo_scenarios(db_session)
    tx = (
        db_session.query(ExportTransaction)
        .filter(ExportTransaction.transaction_reference == "EXP-DEMO-003")
        .first()
    )
    assert tx is not None

    pay = db_session.query(Payment).filter(Payment.export_transaction_id == tx.id).first()
    settle = db_session.query(Settlement).filter(Settlement.export_transaction_id == tx.id).first()
    assert pay is not None and settle is not None

    payload = {
        "link_type": "payment_settlement",
        "source_id": str(pay.id),
        "target_id": str(settle.id),
        "explicit_reference": "SETTLE-DEMO-301",
        "notes": "Verified manual link proposal",
    }
    resp = client_with_db.post(f"/api/v1/transactions/{tx.id}/links", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    assert data["status"] == "proposed"
    assert data["link_method"] == "manual"
    assert data["payment_id"] == str(pay.id)
    assert data["settlement_id"] == str(settle.id)

    # Repeating should reject duplicate
    dup_resp = client_with_db.post(f"/api/v1/transactions/{tx.id}/links", json=payload)
    assert dup_resp.status_code == 409


# ---------------------------------------------------------------------------
# 7. Cross-Transaction Link Rejection
# ---------------------------------------------------------------------------
def test_cross_transaction_link_rejection(client_with_db: TestClient, db_session: Session) -> None:
    """Verifies that attempting to link records from different transactions is rejected with HTTP 400."""
    seed_demo_scenarios(db_session)
    tx1 = (
        db_session.query(ExportTransaction)
        .filter(ExportTransaction.transaction_reference == "EXP-DEMO-001")
        .first()
    )
    tx2 = (
        db_session.query(ExportTransaction)
        .filter(ExportTransaction.transaction_reference == "EXP-DEMO-002")
        .first()
    )
    assert tx1 is not None and tx2 is not None

    inv_tx1 = db_session.query(Invoice).filter(Invoice.export_transaction_id == tx1.id).first()
    pay_tx2 = db_session.query(Payment).filter(Payment.export_transaction_id == tx2.id).first()
    assert inv_tx1 is not None and pay_tx2 is not None

    payload = {
        "link_type": "invoice_payment",
        "source_id": str(inv_tx1.id),
        "target_id": str(pay_tx2.id),
    }
    resp = client_with_db.post(f"/api/v1/transactions/{tx1.id}/links", json=payload)
    assert resp.status_code == 400
    assert "does not belong to transaction" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 8. Explicit Record Assignment
# ---------------------------------------------------------------------------
def test_explicit_record_assignment(client_with_db: TestClient, db_session: Session) -> None:
    """Verifies explicit human action assigning an unowned record to a transaction."""
    seed_demo_scenarios(db_session)
    tx1 = (
        db_session.query(ExportTransaction)
        .filter(ExportTransaction.transaction_reference == "EXP-DEMO-001")
        .first()
    )
    assert tx1 is not None

    # Unowned bank transaction from scenario 6
    unowned_bt = (
        db_session.query(BankTransaction)
        .filter(BankTransaction.bank_reference == "BANK-DEMO-601")
        .first()
    )
    assert unowned_bt is not None
    assert unowned_bt.export_transaction_id is None

    assign_payload = {
        "record_type": "bank_transaction",
        "record_id": str(unowned_bt.id),
        "notes": "Assigned unallocated bank credit to transaction 1",
    }
    resp = client_with_db.post(f"/api/v1/transactions/{tx1.id}/assign-record", json=assign_payload)
    assert resp.status_code == 200

    db_session.refresh(unowned_bt)
    assert unowned_bt.export_transaction_id == tx1.id

    # Verify HumanDecision audit entry
    decision = (
        db_session.query(HumanDecision)
        .filter(
            HumanDecision.target_id == unowned_bt.id,
            HumanDecision.target_type == TargetType.BANK_TRANSACTION,
        )
        .first()
    )
    assert decision is not None
    assert decision.decision == DecisionType.APPROVED

    # Attempting to assign an already-owned record to a DIFFERENT transaction is rejected
    tx2 = (
        db_session.query(ExportTransaction)
        .filter(ExportTransaction.transaction_reference == "EXP-DEMO-002")
        .first()
    )
    assert tx2 is not None

    bad_assign = client_with_db.post(
        f"/api/v1/transactions/{tx2.id}/assign-record", json=assign_payload
    )
    assert bad_assign.status_code == 400
    assert "belongs to a different transaction" in bad_assign.json()["detail"]


# ---------------------------------------------------------------------------
# 9. Human Decision Confirms or Rejects Link
# ---------------------------------------------------------------------------
def test_human_decision_confirms_or_rejects_link(
    client_with_db: TestClient, db_session: Session
) -> None:
    """Verifies that the decision endpoint is the sole mechanism to confirm/reject and write audit history."""
    seed_demo_scenarios(db_session)
    tx = (
        db_session.query(ExportTransaction)
        .filter(ExportTransaction.transaction_reference == "EXP-DEMO-001")
        .first()
    )
    assert tx is not None

    # Discover links to get a proposed link
    disc_resp = client_with_db.post(f"/api/v1/transactions/{tx.id}/discover-links")
    link_id = disc_resp.json()["created_links"][0]["id"]

    # Confirm link via decision endpoint
    confirm_payload = {
        "decision": "approved",
        "reviewer_label": "auditor_alice@example.com",
        "notes": "Verified against customs bill",
    }
    conf_resp = client_with_db.post(
        f"/api/v1/transactions/{tx.id}/links/{link_id}/decision", json=confirm_payload
    )
    assert conf_resp.status_code == 200
    assert conf_resp.json()["status"] == "confirmed"

    # Verify HumanDecision row
    decision_row = (
        db_session.query(HumanDecision)
        .filter(
            HumanDecision.target_id == uuid.UUID(link_id),
            HumanDecision.target_type == TargetType.TRANSACTION_LINK,
        )
        .first()
    )
    assert decision_row is not None
    assert decision_row.decision == DecisionType.APPROVED
    assert decision_row.reviewer_label == "auditor_alice@example.com"

    # Reject link
    reject_payload = {
        "decision": "rejected",
        "reviewer_label": "auditor_bob@example.com",
        "notes": "Customs discrepancy identified",
    }
    rej_resp = client_with_db.post(
        f"/api/v1/transactions/{tx.id}/links/{link_id}/decision", json=reject_payload
    )
    assert rej_resp.status_code == 200
    assert rej_resp.json()["status"] == "rejected"


# ---------------------------------------------------------------------------
# 10. 404 Error Handling
# ---------------------------------------------------------------------------
def test_404_handling(client_with_db: TestClient) -> None:
    """Verifies 404 responses for non-existent transactions and records."""
    random_id = uuid.uuid4()
    resp = client_with_db.get(f"/api/v1/transactions/{random_id}")
    assert resp.status_code == 404

    resp = client_with_db.get(f"/api/v1/transactions/{random_id}/links")
    assert resp.status_code == 404

    resp = client_with_db.post(
        f"/api/v1/transactions/{random_id}/links",
        json={
            "link_type": "invoice_shipping_bill",
            "source_id": str(uuid.uuid4()),
            "target_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 11. Deletion Protection (RESTRICT)
# ---------------------------------------------------------------------------
def test_deletion_policy_restrict(db_session: Session) -> None:
    """Verifies that an invoice with an active relationship cannot be deleted (ondelete=RESTRICT)."""
    tx = ExportTransaction(
        transaction_reference="EXP-RESTRICT-01",
        exporter_name="Exp",
        buyer_name="Buy",
        status=TransactionStatus.DRAFT,
    )
    db_session.add(tx)
    db_session.flush()

    inv = Invoice(
        invoice_number="INV-RESTRICT-01",
        export_transaction_id=tx.id,
        seller_name="Exp",
        buyer_name="Buy",
        currency="USD",
        total_amount=Decimal("100.00"),
    )
    sb = ShippingBill(
        shipping_bill_number="SB-RESTRICT-01",
        export_transaction_id=tx.id,
        invoice_reference="INV-RESTRICT-01",
        exporter_name="Exp",
        buyer_name="Buy",
        declared_currency="USD",
        declared_value=Decimal("100.00"),
    )
    db_session.add_all([inv, sb])
    db_session.flush()

    link = TransactionLink(
        export_transaction_id=tx.id,
        link_type=LinkType.INVOICE_SHIPPING_BILL,
        link_method=LinkMethod.MANUAL,
        status=LinkStatus.PROPOSED,
        invoice_id=inv.id,
        shipping_bill_id=sb.id,
    )
    db_session.add(link)
    db_session.commit()

    # Attempt to delete the invoice should fail due to RESTRICT constraint
    db_session.delete(inv)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
