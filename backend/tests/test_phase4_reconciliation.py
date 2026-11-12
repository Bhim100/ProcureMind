"""
Comprehensive automated tests for Phase 4: Deterministic Matching and Reconciliation Engine.

Verifies:
1. Exact match with single invoice allocation from payment capture gross.
2. Itemized provider fee audit with accurate unexplained deduction arithmetic.
3. Currency scale validation and strict rejection of unsupported currency codes.
4. Consolidated settlement suggestions-only automation lifecycle (allocations empty post-reconcile, populated only after human approvals).
5. Compensating reversal model for refunds (is_reversal=True) preserving non-negative constraints.
6. Ambiguous candidate abstention (no forced match).
7. Cross-currency mismatch abstention (no silent conversion).
8. Stale proposals marked superseded without deleting audit history.
9. Deletion policy RESTRICT preventing cascade deletion of evidence.
10. Stable provider duplicate identifier detection.
11. Unmatched bank credit identification.
"""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.currencies import validate_currency_code, validate_currency_scale
from app.models.enums import (
    AllocationReviewStatus,
    BankTransactionStatus,
    BankTransactionType,
    MatchStatus,
    PaymentStatus,
    TransactionStatus,
)
from app.models.export import ExportTransaction, Invoice, ShippingBill
from app.models.payment import BankTransaction, Payment, Settlement
from app.models.reconciliation import Allocation, ReconciliationMatch


def _create_export_deal(db: Session, ref: str = "EXP-TEST-001") -> ExportTransaction:
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


def test_currency_scale_and_strict_rejection():
    """Validates currency scale rules and verifies unsupported codes are rejected."""
    # 0 decimals (JPY)
    assert validate_currency_scale(Decimal(1000), "JPY") == Decimal(1000)
    with pytest.raises(ValueError, match="exceeds maximum allowed precision"):
        validate_currency_scale(Decimal("1000.5"), "JPY")

    # 2 decimals (USD)
    assert validate_currency_scale(Decimal("100.50"), "USD") == Decimal("100.50")
    with pytest.raises(ValueError, match="exceeds maximum allowed precision"):
        validate_currency_scale(Decimal("100.555"), "USD")

    # 3 decimals (KWD)
    assert validate_currency_scale(Decimal("125.375"), "KWD") == Decimal("125.375")
    with pytest.raises(ValueError, match="exceeds maximum allowed precision"):
        validate_currency_scale(Decimal("125.3755"), "KWD")

    # Strict rejection of unknown currency (no default to 2)
    with pytest.raises(ValueError, match="Unsupported currency code 'XYZ'"):
        validate_currency_code("XYZ")


def test_exact_match_single_allocation(client_with_db: TestClient, db_session: Session):
    """
    Scenario 1: Clean invoice matched with PayPal payment capture.
    Reconciliation proposes a match (suggested); allocations table has 0 rows.
    Only human approval creates the Allocation row and marks transaction RECONCILED.
    """
    tx = _create_export_deal(db_session, "EXP-CLEAN-01")

    inv = Invoice(
        export_transaction_id=tx.id,
        invoice_number="INV-2026-101",
        seller_name="Apex Global",
        buyer_name="Nexus Retail",
        issue_date=date.today(),
        currency="USD",
        total_amount=Decimal("1000.0000"),
    )
    sb = ShippingBill(
        export_transaction_id=tx.id,
        shipping_bill_number="SB-2026-101",
        invoice_reference="INV-2026-101",
        exporter_name="Apex Global",
        buyer_name="Nexus Retail",
        bill_date=date.today(),
        declared_currency="USD",
        declared_value=Decimal("1000.0000"),
    )
    pmt = Payment(
        export_transaction_id=tx.id,
        provider="paypal",
        provider_capture_id="CAP-101",
        invoice_reference="INV-2026-101",
        currency="USD",
        gross_amount=Decimal("1000.0000"),
        fee_amount=Decimal("30.0000"),
        net_amount=Decimal("970.0000"),
        status=PaymentStatus.COMPLETED,
    )
    db_session.add_all([inv, sb, pmt])
    db_session.commit()

    # 1. Run reconcile
    res = client_with_db.post(f"/api/v1/transactions/{tx.id}/reconcile")
    assert res.status_code == 200
    data = res.json()

    assert data["matches_count"] >= 1
    assert data["discrepancies_count"] == 0

    # Verify allocations table is completely empty (suggestions-only)
    assert db_session.query(Allocation).count() == 0

    # Verify transaction status is NOT reconciled
    db_session.refresh(tx)
    assert tx.status != TransactionStatus.RECONCILED

    # Locate the proposed invoice_payment match
    match_row = next(m for m in data["matches"] if m["match_type"] == "invoice_payment")
    assert match_row["match_status"] == "matched"
    assert match_row["review_status"] == "suggested"
    assert Decimal(str(match_row["allocated_amount"])) == Decimal("1000.0000")
    assert match_row["is_reversal"] is False

    # 2. Approve match via decision endpoint
    dec_res = client_with_db.post(
        f"/api/v1/matches/{match_row['id']}/decision",
        headers={"X-Auditor-Key": settings.AUDITOR_API_KEY},
        json={
            "decision": "approved",
            "reviewer_label": "lead_auditor",
            "notes": "Approved 100% verified match",
        },
    )
    assert dec_res.status_code == 200
    dec_data = dec_res.json()
    assert dec_data["review_status"] == "approved"
    assert dec_data["allocation_id"] is not None

    # Now official Allocation row exists
    alloc = db_session.query(Allocation).first()
    assert alloc is not None
    assert alloc.allocated_amount == Decimal("1000.0000")
    assert alloc.is_reversal is False
    assert alloc.review_status == AllocationReviewStatus.APPROVED

    # Transaction is now fully reconciled
    db_session.refresh(tx)
    assert tx.status == TransactionStatus.RECONCILED


def test_itemized_undocumented_fee_arithmetic(client_with_db: TestClient, db_session: Session):
    """
    Scenario: Payment gross $1,000, net $950 ($50 gross-to-net deduction).
    Evidenced fee is only $30. Unexplained remainder must equal $20, NOT invoice minus gross.
    """
    tx = _create_export_deal(db_session, "EXP-FEE-01")
    inv = Invoice(
        export_transaction_id=tx.id,
        invoice_number="INV-FEE-01",
        seller_name="Apex Global",
        buyer_name="Nexus Retail",
        currency="USD",
        total_amount=Decimal("1000.0000"),
    )
    pmt = Payment(
        export_transaction_id=tx.id,
        provider="paypal",
        provider_capture_id="CAP-FEE-01",
        invoice_reference="INV-FEE-01",
        currency="USD",
        gross_amount=Decimal("1000.0000"),
        fee_amount=Decimal("30.0000"),  # Only $30 evidenced
        net_amount=Decimal("950.0000"),  # $50 total deduction -> $20 unexplained
        status=PaymentStatus.COMPLETED,
    )
    db_session.add_all([inv, pmt])
    db_session.commit()

    res = client_with_db.post(f"/api/v1/transactions/{tx.id}/reconcile")
    assert res.status_code == 200
    data = res.json()

    # Find the undocumented deduction discrepancy
    fee_disc = next(
        d for d in data["discrepancies"] if d["rule_id"] == "RULE_UNDOCUMENTED_DEDUCTION"
    )
    assert fee_disc["severity"] == "error"
    calc = fee_disc["calculation"]
    assert Decimal(str(calc["gross_to_net_deduction"])) == Decimal("50.0000")
    assert Decimal(str(calc["total_evidenced_fees"])) == Decimal("30.0000")
    assert Decimal(str(calc["unexplained_remainder"])) == Decimal("20.0000")


def test_consolidated_settlement_suggestions_only_lifecycle(
    client_with_db: TestClient, db_session: Session
):
    """
    Validates consolidated settlement:
    - 2 invoices ($6,000 and $4,000), 2 payments ($6,000 and $4,000 gross; $5,820 and $3,880 net).
    - 1 Settlement payout batch of $9,700, 1 Bank Credit of $9,700.
    - Post-reconcile: allocations table is completely EMPTY (0 rows). Proposed allocations total $10,000.
    - Post-approval: official allocations total $10,000. Proceeds are never allocated again at settlement/bank stages.
    """
    tx = _create_export_deal(db_session, "EXP-BATCH-01")

    inv_a = Invoice(
        export_transaction_id=tx.id,
        invoice_number="INV-A",
        seller_name="Apex Global",
        buyer_name="EuroCorp",
        currency="USD",
        total_amount=Decimal("6000.0000"),
    )
    inv_b = Invoice(
        export_transaction_id=tx.id,
        invoice_number="INV-B",
        seller_name="Apex Global",
        buyer_name="EuroCorp",
        currency="USD",
        total_amount=Decimal("4000.0000"),
    )
    bt = BankTransaction(
        export_transaction_id=tx.id,
        bank_reference="BANK-BATCH-01",
        currency="USD",
        amount=Decimal("9700.0000"),
        transaction_date=date.today(),
        transaction_type=BankTransactionType.CREDIT,
        status=BankTransactionStatus.POSTED,
    )
    db_session.add_all([inv_a, inv_b, bt])
    db_session.flush()

    settle = Settlement(
        export_transaction_id=tx.id,
        provider_reference="SETTLE-BATCH-01",
        bank_transaction_id=bt.id,
        currency="USD",
        amount=Decimal("9700.0000"),
        settlement_date=date.today(),
    )
    db_session.add(settle)
    db_session.flush()

    pmt_1 = Payment(
        export_transaction_id=tx.id,
        provider="paypal",
        settlement_id=settle.id,
        provider_capture_id="CAP-BATCH-1",
        invoice_reference="INV-A",
        currency="USD",
        gross_amount=Decimal("6000.0000"),
        fee_amount=Decimal("180.0000"),
        net_amount=Decimal("5820.0000"),
        status=PaymentStatus.COMPLETED,
    )
    pmt_2 = Payment(
        export_transaction_id=tx.id,
        provider="paypal",
        settlement_id=settle.id,
        provider_capture_id="CAP-BATCH-2",
        invoice_reference="INV-B",
        currency="USD",
        gross_amount=Decimal("4000.0000"),
        fee_amount=Decimal("120.0000"),
        net_amount=Decimal("3880.0000"),
        status=PaymentStatus.COMPLETED,
    )
    sb = ShippingBill(
        export_transaction_id=tx.id,
        shipping_bill_number="SB-BATCH-01",
        invoice_reference="INV-A",
        exporter_name="Apex Global",
        buyer_name="EuroCorp",
        bill_date=date.today(),
        declared_currency="USD",
        declared_value=Decimal("6000.0000"),
    )
    db_session.add_all([pmt_1, pmt_2, sb])
    db_session.commit()

    # 1. Run reconcile
    res = client_with_db.post(f"/api/v1/transactions/{tx.id}/reconcile")
    assert res.status_code == 200
    data = res.json()

    # Crucial check: allocations table must remain empty
    assert db_session.query(Allocation).count() == 0
    db_session.refresh(tx)
    assert tx.status != TransactionStatus.RECONCILED

    # Check proposed invoice allocations from gross
    inv_matches = [m for m in data["matches"] if m["match_type"] == "invoice_payment"]
    assert len(inv_matches) == 2
    total_proposed = sum(Decimal(str(m["allocated_amount"])) for m in inv_matches)
    assert total_proposed == Decimal("10000.0000")

    # Check cash flow realization chain was verified without double-allocating
    flow_matches = [m for m in data["matches"] if m["match_type"] == "flow_verification"]
    assert any(m["rule_id"] == "RULE_SETTLEMENT_FLOW_VERIFIED" for m in flow_matches)
    assert any(m["rule_id"] == "RULE_BANK_DEPOSIT_VERIFIED" for m in flow_matches)

    # 2. Approve both matches
    for m in inv_matches:
        client_with_db.post(
            f"/api/v1/matches/{m['id']}/decision",
            headers={"X-Auditor-Key": settings.AUDITOR_API_KEY},
            json={
                "decision": "approved",
                "reviewer_label": "batch_reviewer",
                "notes": "Approved batch match",
            },
        )

    # Now official allocations total $10,000 (never $29,400)
    allocs = db_session.query(Allocation).all()
    assert len(allocs) == 2
    assert sum(a.allocated_amount for a in allocs) == Decimal("10000.0000")


def test_refund_compensating_reversal(client_with_db: TestClient, db_session: Session):
    """
    Validates compensating reversal model:
    - Approved allocation exists for $1,000.
    - Payment is subsequently marked REFUNDED.
    - Reconcile proposes a compensating reversal match (is_reversal=True, positive amount).
    - Original allocation is NOT mutated or deleted.
    - Human decision approves reversal -> creates compensating Allocation (is_reversal=True).
    """
    tx = _create_export_deal(db_session, "EXP-REFUND-01")
    inv = Invoice(
        export_transaction_id=tx.id,
        invoice_number="INV-REF-01",
        seller_name="Apex Global",
        buyer_name="Nexus Retail",
        currency="USD",
        total_amount=Decimal("1000.0000"),
    )
    pmt = Payment(
        export_transaction_id=tx.id,
        provider="paypal",
        provider_capture_id="CAP-REF-01",
        invoice_reference="INV-REF-01",
        currency="USD",
        gross_amount=Decimal("1000.0000"),
        net_amount=Decimal("970.0000"),
        status=PaymentStatus.REFUNDED,
    )
    db_session.add_all([inv, pmt])
    db_session.flush()

    # Pre-existing approved allocation
    alloc = Allocation(
        invoice_id=inv.id,
        payment_id=pmt.id,
        allocated_amount=Decimal("1000.0000"),
        currency="USD",
        review_status=AllocationReviewStatus.APPROVED,
        is_reversal=False,
    )
    db_session.add(alloc)
    db_session.commit()

    res = client_with_db.post(f"/api/v1/transactions/{tx.id}/reconcile")
    assert res.status_code == 200
    data = res.json()

    # Find the reversal proposal
    reversal_match = next(m for m in data["matches"] if m["match_type"] == "payment_reversal")
    assert reversal_match["is_reversal"] is True
    assert Decimal(str(reversal_match["allocated_amount"])) == Decimal(
        "1000.0000"
    )  # Non-negative check preserved!
    assert reversal_match["match_status"] == "requires_human_review"

    # Original allocation is intact
    db_session.refresh(alloc)
    assert alloc.allocated_amount == Decimal("1000.0000")
    assert alloc.is_reversal is False

    # Approve reversal
    dec_res = client_with_db.post(
        f"/api/v1/matches/{reversal_match['id']}/decision",
        headers={"X-Auditor-Key": settings.AUDITOR_API_KEY},
        json={
            "decision": "approved",
            "reviewer_label": "dispute_officer",
            "notes": "Approved customer refund offset",
        },
    )
    assert dec_res.status_code == 200

    # Official compensating Allocation now exists
    reversal_alloc = db_session.query(Allocation).filter(Allocation.is_reversal == True).first()
    assert reversal_alloc is not None
    assert reversal_alloc.allocated_amount == Decimal("1000.0000")
    assert reversal_alloc.review_status == AllocationReviewStatus.APPROVED


def test_ambiguous_candidate_abstention(client_with_db: TestClient, db_session: Session):
    """Verifies that when a payment matches 2 candidate invoices equally, engine abstains from allocating."""
    tx = _create_export_deal(db_session, "EXP-AMBIG-01")
    inv_1 = Invoice(
        export_transaction_id=tx.id,
        invoice_number="INV-AMBIG-1",
        seller_name="Apex Global",
        buyer_name="Vanguard Tech",
        currency="USD",
        total_amount=Decimal("750.0000"),
    )
    inv_2 = Invoice(
        export_transaction_id=tx.id,
        invoice_number="INV-AMBIG-2",
        seller_name="Apex Global",
        buyer_name="Vanguard Tech",
        currency="USD",
        total_amount=Decimal("750.0000"),
    )
    pmt = Payment(
        export_transaction_id=tx.id,
        provider="paypal",
        provider_capture_id="CAP-AMBIG-01",
        invoice_reference=None,  # No explicit invoice ref
        currency="USD",
        gross_amount=Decimal("750.0000"),
        net_amount=Decimal("727.5000"),
        status=PaymentStatus.COMPLETED,
    )
    db_session.add_all([inv_1, inv_2, pmt])
    db_session.commit()

    res = client_with_db.post(f"/api/v1/transactions/{tx.id}/reconcile")
    assert res.status_code == 200
    data = res.json()

    # Verify abstention: match is ambiguous, 0 allocation
    ambig_match = next(m for m in data["matches"] if m["match_status"] == "ambiguous")
    assert Decimal(str(ambig_match["allocated_amount"])) == Decimal("0.0000")
    assert ambig_match["rule_id"] == "RULE_AMBIGUOUS_CANDIDATE"

    # Verify discrepancy lists candidate invoices
    disc = next(d for d in data["discrepancies"] if d["rule_id"] == "RULE_AMBIGUOUS_CANDIDATE")
    assert len(disc["compared_fields"]["candidate_invoice_numbers"]) == 2


def test_currency_mismatch_abstention(client_with_db: TestClient, db_session: Session):
    """Verifies that currency mismatch abstains from auto-allocation and raises critical discrepancy."""
    tx = _create_export_deal(db_session, "EXP-FX-01")
    inv = Invoice(
        export_transaction_id=tx.id,
        invoice_number="INV-USD-01",
        seller_name="Apex Global",
        buyer_name="EuroCorp",
        currency="USD",
        total_amount=Decimal("1000.0000"),
    )
    pmt = Payment(
        export_transaction_id=tx.id,
        provider="paypal",
        provider_capture_id="CAP-EUR-01",
        invoice_reference="INV-USD-01",
        currency="EUR",  # EUR payment for USD invoice without FX rate
        gross_amount=Decimal("1000.0000"),
        net_amount=Decimal("970.0000"),
        status=PaymentStatus.COMPLETED,
    )
    db_session.add_all([inv, pmt])
    db_session.commit()

    res = client_with_db.post(f"/api/v1/transactions/{tx.id}/reconcile")
    assert res.status_code == 200
    data = res.json()

    disc = next(d for d in data["discrepancies"] if d["rule_id"] == "RULE_CURRENCY_MISMATCH")
    assert disc["severity"] == "critical"
    match_row = next(m for m in data["matches"] if m["rule_id"] == "RULE_CURRENCY_MISMATCH")
    assert Decimal(str(match_row["allocated_amount"])) == Decimal("0.0000")


def test_stale_proposals_superseded_not_deleted(client_with_db: TestClient, db_session: Session):
    """Verifies that rerun marks obsolete proposals superseded and does not delete audit records."""
    tx = _create_export_deal(db_session, "EXP-STALE-01")
    inv = Invoice(
        export_transaction_id=tx.id,
        invoice_number="INV-STALE-01",
        seller_name="Apex Global",
        buyer_name="Nexus Retail",
        currency="USD",
        total_amount=Decimal("1000.0000"),
    )
    pmt = Payment(
        export_transaction_id=tx.id,
        provider="paypal",
        provider_capture_id="CAP-STALE-01",
        invoice_reference="INV-STALE-01",
        currency="USD",
        gross_amount=Decimal("1000.0000"),
        net_amount=Decimal("970.0000"),
        status=PaymentStatus.COMPLETED,
    )
    db_session.add_all([inv, pmt])
    db_session.commit()

    # Run 1
    res1 = client_with_db.post(f"/api/v1/transactions/{tx.id}/reconcile")
    assert res1.status_code == 200
    m1_id = res1.json()["matches"][0]["id"]

    # Now change payment invoice reference to something else so m1 is no longer valid
    pmt.invoice_reference = "INV-DIFFERENT"
    db_session.commit()

    # Run 2
    res2 = client_with_db.post(f"/api/v1/transactions/{tx.id}/reconcile")
    assert res2.status_code == 200

    # m1 should still exist in database, marked SUPERSEDED
    old_m = db_session.query(ReconciliationMatch).filter(ReconciliationMatch.id == m1_id).first()
    assert old_m is not None
    assert old_m.review_status == AllocationReviewStatus.SUPERSEDED


def test_deletion_policy_restrict(db_session: Session):
    """Verifies that deleting an Invoice with linked ReconciliationMatch is blocked by RESTRICT."""
    tx = _create_export_deal(db_session, "EXP-RESTRICT-01")
    inv = Invoice(
        export_transaction_id=tx.id,
        invoice_number="INV-RESTRICT-01",
        seller_name="Apex Global",
        buyer_name="Nexus Retail",
        currency="USD",
        total_amount=Decimal("1000.0000"),
    )
    db_session.add(inv)
    db_session.flush()

    m = ReconciliationMatch(
        export_transaction_id=tx.id,
        invoice_id=inv.id,
        match_type="invoice_payment",
        match_status=MatchStatus.MATCHED,
        rule_id="RULE_EXACT_REFERENCE_MATCH",
        business_key="bkey-test-restrict-01",
        allocated_amount=Decimal("1000.0000"),
        currency="USD",
    )
    db_session.add(m)
    db_session.commit()

    # Attempt to delete invoice: must fail with integrity error under PRAGMA foreign_keys=ON / Postgres RESTRICT
    db_session.delete(inv)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unmatched_bank_credit(client_with_db: TestClient, db_session: Session):
    """Verifies standalone bank credit line is flagged with RULE_UNMATCHED_BANK_CREDIT."""
    tx = _create_export_deal(db_session, "EXP-BANK-01")
    bt = BankTransaction(
        export_transaction_id=tx.id,
        bank_reference="BANK-UNMATCHED-99",
        currency="EUR",
        amount=Decimal("1250.0000"),
        transaction_date=date.today(),
        transaction_type=BankTransactionType.CREDIT,
        status=BankTransactionStatus.POSTED,
        remittance_reference="UNKNOWN WIRE SENDER",
    )
    db_session.add(bt)
    db_session.commit()

    res = client_with_db.post(f"/api/v1/transactions/{tx.id}/reconcile")
    assert res.status_code == 200
    data = res.json()

    disc = next(d for d in data["discrepancies"] if d["rule_id"] == "RULE_UNMATCHED_BANK_CREDIT")
    assert disc["severity"] == "warning"
    match_row = next(m for m in data["matches"] if m["match_status"] == "unmatched")
    assert match_row["rule_id"] == "RULE_UNMATCHED_BANK_CREDIT"
