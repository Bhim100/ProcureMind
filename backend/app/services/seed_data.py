"""
Seed service for populating ProcureMind with fictional demo scenarios.

All generated records are explicitly flagged with `is_demo=True`.
In strict compliance with requirements:
- Scenarios are created as static records.
- No autonomous matching, AI extraction, or runtime reconciliation rules are executed.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.document import Document, ExtractedField
from app.models.enums import (
    AllocationMethod,
    AllocationReviewStatus,
    BankTransactionStatus,
    BankTransactionType,
    DecisionType,
    DiscrepancySeverity,
    DiscrepancyStatus,
    DocumentType,
    EnvironmentLabel,
    ExtractionMethod,
    PaymentStatus,
    ProcessingStatus,
    ReviewState,
    SettlementStatus,
    TargetType,
    TransactionStatus,
)
from app.models.export import ExportTransaction, Invoice, InvoiceLineItem, ShippingBill
from app.models.payment import BankTransaction, Payment, ProviderWebhookEvent, Settlement
from app.models.reconciliation import Allocation, Discrepancy, EvidenceReference, HumanDecision
from app.models.relationship import TransactionLink


def clear_demo_data(db: Session) -> None:
    """Removes any previously seeded demo records (where is_demo=True)."""
    # Delete dependent reconciliation and relationship entities
    db.query(EvidenceReference).filter(
        (EvidenceReference.discrepancy.has(Discrepancy.is_demo == True))
        | (EvidenceReference.allocation.has(Allocation.is_demo == True))
        | (EvidenceReference.transaction_link.has(TransactionLink.is_demo == True))
    ).delete(synchronize_session=False)

    db.query(TransactionLink).filter(TransactionLink.is_demo == True).delete(
        synchronize_session=False
    )

    db.query(HumanDecision).filter(HumanDecision.reviewer_label == "demo_auditor").delete(
        synchronize_session=False
    )
    db.query(Allocation).filter(Allocation.is_demo == True).delete(synchronize_session=False)
    db.query(Discrepancy).filter(Discrepancy.is_demo == True).delete(synchronize_session=False)
    db.query(ProviderWebhookEvent).filter(
        ProviderWebhookEvent.provider_event_id.like("EVT-DEMO-%")
    ).delete(synchronize_session=False)
    db.query(Payment).filter(Payment.is_demo == True).delete(synchronize_session=False)
    db.query(Settlement).filter(Settlement.is_demo == True).delete(synchronize_session=False)
    db.query(BankTransaction).filter(BankTransaction.is_demo == True).delete(
        synchronize_session=False
    )
    db.query(ShippingBill).filter(ShippingBill.is_demo == True).delete(synchronize_session=False)
    db.query(InvoiceLineItem).filter(InvoiceLineItem.invoice.has(Invoice.is_demo == True)).delete(
        synchronize_session=False
    )
    db.query(Invoice).filter(Invoice.is_demo == True).delete(synchronize_session=False)
    db.query(ExportTransaction).filter(ExportTransaction.is_demo == True).delete(
        synchronize_session=False
    )
    db.query(ExtractedField).filter(ExtractedField.document.has(Document.is_demo == True)).delete(
        synchronize_session=False
    )
    db.query(Document).filter(Document.is_demo == True).delete(synchronize_session=False)
    db.commit()


def seed_demo_scenarios(db: Session) -> dict[str, Any]:
    """
    Seeds six realistic fictional export reconciliation scenarios marked as demo data:
    1. Clean Invoice: $1,000.00 USD matched with completed PayPal payment ($970 net, $30 fee) and 100% allocation.
    2. Partial Payment: $5,000.00 USD invoice with $2,000.00 USD partial payment allocated ($3,000 open).
    3. Documented Fee: $500.00 USD payment with documented $15 fee, $485 net settlement and bank credit.
    4. Unexplained Difference: $2,500.00 USD invoice with $2,400.00 USD payment and an active mismatch discrepancy.
    5. Ambiguous Candidate: Two $750.00 USD candidate invoices and a single unallocated $750 payment.
    6. Unmatched Bank Credit: Standalone €1,250.00 EUR bank statement credit line with no matching invoice.
    """
    clear_demo_data(db)

    now_utc = datetime.now(UTC)
    today = date.today()

    results: dict[str, Any] = {}

    # -------------------------------------------------------------
    # Scenario 1: Clean Invoice
    # -------------------------------------------------------------
    exp_1 = ExportTransaction(
        transaction_reference="EXP-DEMO-001",
        exporter_name="Apex Global Exports Ltd",
        exporter_tax_id="IEC99014221A",
        buyer_name="Nexus Retail Inc",
        buyer_country="USA",
        status=TransactionStatus.RECONCILED,
        is_demo=True,
    )
    db.add(exp_1)
    db.flush()

    doc_1 = Document(
        original_filename="Apex_Invoice_1001.pdf",
        media_type="application/pdf",
        size_bytes=104857,
        sha256="1" * 64,
        storage_key="demo/Apex_Invoice_1001.pdf",
        document_type=DocumentType.INVOICE,
        upload_time=now_utc,
        processing_status=ProcessingStatus.APPROVED,
        page_count=1,
        is_demo=True,
    )
    db.add(doc_1)
    db.flush()

    field_1 = ExtractedField(
        document_id=doc_1.id,
        field_name="total_amount",
        raw_value="$1,000.00",
        normalized_value="1000.00",
        page_number=1,
        confidence=Decimal("0.9950"),
        review_state=ReviewState.AUTO_ACCEPTED,
        extraction_method=ExtractionMethod.TEXT,
    )
    db.add(field_1)

    inv_1 = Invoice(
        invoice_number="INV-2026-001",
        export_transaction_id=exp_1.id,
        document_id=doc_1.id,
        seller_name="Apex Global Exports Ltd",
        buyer_name="Nexus Retail Inc",
        issue_date=today,
        currency="USD",
        total_amount=Decimal("1000.00"),
        shipment_reference="BL-NEXUS-01",
        is_demo=True,
    )
    db.add(inv_1)
    db.flush()

    line_1 = InvoiceLineItem(
        invoice_id=inv_1.id,
        line_number=1,
        description="Precision Industrial Ball Bearings (Grade A)",
        quantity=Decimal("100.0000"),
        unit_price=Decimal("10.00"),
        total_amount=Decimal("1000.00"),
        currency="USD",
        hs_code="84821010",
    )
    db.add(line_1)

    sb_1 = ShippingBill(
        shipping_bill_number="SB-DEMO-1001",
        export_transaction_id=exp_1.id,
        document_id=doc_1.id,
        invoice_reference="INV-2026-001",
        exporter_name="Apex Global Exports Ltd",
        buyer_name="Nexus Retail Inc",
        bill_date=today,
        declared_currency="USD",
        declared_value=Decimal("1000.00"),
        is_demo=True,
    )
    db.add(sb_1)

    pmt_1 = Payment(
        export_transaction_id=exp_1.id,
        provider="paypal",
        provider_order_id="ORD-DEMO-1001",
        provider_capture_id="CAP-DEMO-1001",
        invoice_reference="INV-2026-001",
        currency="USD",
        gross_amount=Decimal("1000.00"),
        fee_amount=Decimal("30.00"),
        net_amount=Decimal("970.00"),
        status=PaymentStatus.COMPLETED,
        event_time=now_utc,
        environment=EnvironmentLabel.SANDBOX,
        is_demo=True,
    )
    db.add(pmt_1)
    db.flush()

    evt_1 = ProviderWebhookEvent(
        provider="paypal",
        provider_event_id="EVT-DEMO-001",
        event_type="PAYMENT.CAPTURE.COMPLETED",
        payment_id=pmt_1.id,
        payload={"id": "EVT-DEMO-001", "summary": "Payment capture completed"},
        status="processed",
        event_time=now_utc,
    )
    db.add(evt_1)

    alloc_1 = Allocation(
        invoice_id=inv_1.id,
        payment_id=pmt_1.id,
        allocated_amount=Decimal("1000.00"),
        currency="USD",
        allocation_method=AllocationMethod.AUTO_EXACT,
        evidence_notes="100% exact match on invoice reference and full gross amount",
        review_status=AllocationReviewStatus.APPROVED,
        is_demo=True,
    )
    db.add(alloc_1)
    db.flush()

    ev_ref_1 = EvidenceReference(
        allocation_id=alloc_1.id,
        document_id=doc_1.id,
        extracted_field_id=field_1.id,
        source_record_type="invoice",
        source_record_id=inv_1.id,
        original_filename=doc_1.original_filename,
        location_reference="page 1, total box",
        raw_value="$1,000.00",
        normalized_value="1000.00",
        extraction_method=ExtractionMethod.TEXT,
        review_state=ReviewState.AUTO_ACCEPTED,
    )
    db.add(ev_ref_1)
    results["scenario_1_clean_invoice"] = {"invoice_id": str(inv_1.id), "payment_id": str(pmt_1.id)}

    # -------------------------------------------------------------
    # Scenario 2: Partial Payment
    # -------------------------------------------------------------
    exp_2 = ExportTransaction(
        transaction_reference="EXP-DEMO-002",
        exporter_name="Apex Global Exports Ltd",
        buyer_name="Horizon Traders GmbH",
        buyer_country="Germany",
        status=TransactionStatus.IN_PROGRESS,
        is_demo=True,
    )
    db.add(exp_2)
    db.flush()

    inv_2 = Invoice(
        invoice_number="INV-2026-002",
        export_transaction_id=exp_2.id,
        seller_name="Apex Global Exports Ltd",
        buyer_name="Horizon Traders GmbH",
        issue_date=today,
        currency="USD",
        total_amount=Decimal("5000.00"),
        is_demo=True,
    )
    db.add(inv_2)
    db.flush()

    pmt_2 = Payment(
        export_transaction_id=exp_2.id,
        provider="paypal",
        provider_order_id="ORD-DEMO-2001",
        provider_capture_id="CAP-DEMO-2001",
        invoice_reference="INV-2026-002",
        currency="USD",
        gross_amount=Decimal("2000.00"),
        fee_amount=Decimal("60.00"),
        net_amount=Decimal("1940.00"),
        status=PaymentStatus.COMPLETED,
        event_time=now_utc,
        environment=EnvironmentLabel.SANDBOX,
        is_demo=True,
    )
    db.add(pmt_2)
    db.flush()

    evt_2 = ProviderWebhookEvent(
        provider="paypal",
        provider_event_id="EVT-DEMO-002",
        event_type="PAYMENT.CAPTURE.COMPLETED",
        payment_id=pmt_2.id,
        payload={"id": "EVT-DEMO-002"},
        status="processed",
        event_time=now_utc,
    )
    db.add(evt_2)

    alloc_2 = Allocation(
        invoice_id=inv_2.id,
        payment_id=pmt_2.id,
        allocated_amount=Decimal("2000.00"),
        currency="USD",
        allocation_method=AllocationMethod.AUTO_EXACT,
        evidence_notes="Partial payment installment received; open balance $3,000.00",
        review_status=AllocationReviewStatus.APPROVED,
        is_demo=True,
    )
    db.add(alloc_2)
    results["scenario_2_partial_payment"] = {
        "invoice_id": str(inv_2.id),
        "allocated": "2000.00",
        "remaining": "3000.00",
    }

    # -------------------------------------------------------------
    # Scenario 3: Documented Fee
    # -------------------------------------------------------------
    exp_3 = ExportTransaction(
        transaction_reference="EXP-DEMO-003",
        exporter_name="Apex Global Exports Ltd",
        buyer_name="Nordic Goods AB",
        buyer_country="Sweden",
        status=TransactionStatus.RECONCILED,
        is_demo=True,
    )
    db.add(exp_3)
    db.flush()

    inv_3 = Invoice(
        invoice_number="INV-2026-003",
        export_transaction_id=exp_3.id,
        seller_name="Apex Global Exports Ltd",
        buyer_name="Nordic Goods AB",
        issue_date=today,
        currency="USD",
        total_amount=Decimal("500.00"),
        is_demo=True,
    )
    db.add(inv_3)
    db.flush()

    bank_txn_3 = BankTransaction(
        export_transaction_id=exp_3.id,
        bank_reference="BANK-DEMO-301",
        currency="USD",
        amount=Decimal("485.00"),
        transaction_date=today,
        transaction_type=BankTransactionType.CREDIT,
        status=BankTransactionStatus.POSTED,
        remittance_reference="PAYPAL PAYOUT BATCH 8801",
        is_demo=True,
    )
    db.add(bank_txn_3)
    db.flush()

    settle_3 = Settlement(
        export_transaction_id=exp_3.id,
        provider_reference="SETTLE-DEMO-301",
        bank_transaction_id=bank_txn_3.id,
        currency="USD",
        amount=Decimal("485.00"),
        settlement_date=today,
        status=SettlementStatus.COMPLETED,
        remittance_reference="PAYPAL DAILY SETTLEMENT",
        is_demo=True,
    )
    db.add(settle_3)
    db.flush()

    pmt_3 = Payment(
        export_transaction_id=exp_3.id,
        provider="paypal",
        settlement_id=settle_3.id,
        provider_order_id="ORD-DEMO-3001",
        provider_capture_id="CAP-DEMO-3001",
        invoice_reference="INV-2026-003",
        currency="USD",
        gross_amount=Decimal("500.00"),
        fee_amount=Decimal("15.00"),
        net_amount=Decimal("485.00"),
        status=PaymentStatus.COMPLETED,
        event_time=now_utc,
        environment=EnvironmentLabel.SANDBOX,
        is_demo=True,
    )
    db.add(pmt_3)
    db.flush()

    alloc_3 = Allocation(
        invoice_id=inv_3.id,
        payment_id=pmt_3.id,
        allocated_amount=Decimal("500.00"),
        currency="USD",
        allocation_method=AllocationMethod.AUTO_EXACT,
        evidence_notes="Gross $500.00 settled with documented PayPal standard fee $15.00",
        review_status=AllocationReviewStatus.APPROVED,
        is_demo=True,
    )
    db.add(alloc_3)
    results["scenario_3_documented_fee"] = {
        "invoice_id": str(inv_3.id),
        "fee": "15.00",
        "net": "485.00",
    }

    # -------------------------------------------------------------
    # Scenario 4: Unexplained Difference
    # -------------------------------------------------------------
    exp_4 = ExportTransaction(
        transaction_reference="EXP-DEMO-004",
        exporter_name="Apex Global Exports Ltd",
        buyer_name="Solaria Imports LLC",
        buyer_country="USA",
        status=TransactionStatus.DISCREPANT,
        is_demo=True,
    )
    db.add(exp_4)
    db.flush()

    inv_4 = Invoice(
        invoice_number="INV-2026-004",
        export_transaction_id=exp_4.id,
        seller_name="Apex Global Exports Ltd",
        buyer_name="Solaria Imports LLC",
        issue_date=today,
        currency="USD",
        total_amount=Decimal("2500.00"),
        is_demo=True,
    )
    db.add(inv_4)
    db.flush()

    pmt_4 = Payment(
        export_transaction_id=exp_4.id,
        provider="paypal",
        provider_order_id="ORD-DEMO-4001",
        provider_capture_id="CAP-DEMO-4001",
        invoice_reference="INV-2026-004",
        currency="USD",
        gross_amount=Decimal("2400.00"),
        fee_amount=Decimal("0.00"),
        net_amount=Decimal("2400.00"),
        status=PaymentStatus.COMPLETED,
        event_time=now_utc,
        environment=EnvironmentLabel.SANDBOX,
        is_demo=True,
    )
    db.add(pmt_4)
    db.flush()

    disc_4 = Discrepancy(
        rule_id="RULE_AMOUNT_MISMATCH",
        severity=DiscrepancySeverity.ERROR,
        compared_fields={
            "invoice_number": "INV-2026-004",
            "invoice_total": "2500.00",
            "payment_gross": "2400.00",
            "shortfall": "100.00",
        },
        description="Payment of $2,400.00 is short by $100.00 against invoice $2,500.00 with no documented fee schedule",
        recommended_action="Audit buyer remittance advice or request explanation for $100.00 deduction",
        status=DiscrepancyStatus.OPEN,
        is_demo=True,
    )
    db.add(disc_4)
    db.flush()

    ev_ref_4 = EvidenceReference(
        discrepancy_id=disc_4.id,
        source_record_type="invoice",
        source_record_id=inv_4.id,
        location_reference="invoice.total_amount vs payment.gross_amount",
        raw_value="Expected 2500.00 USD, Received 2400.00 USD",
        normalized_value="Difference: -100.00 USD",
    )
    db.add(ev_ref_4)
    results["scenario_4_unexplained_diff"] = {
        "invoice_id": str(inv_4.id),
        "discrepancy_id": str(disc_4.id),
    }

    # -------------------------------------------------------------
    # Scenario 5: Ambiguous Candidate
    # -------------------------------------------------------------
    exp_5 = ExportTransaction(
        transaction_reference="EXP-DEMO-005",
        exporter_name="Apex Global Exports Ltd",
        buyer_name="Vanguard Tech Inc",
        buyer_country="USA",
        status=TransactionStatus.DISCREPANT,
        is_demo=True,
    )
    db.add(exp_5)
    db.flush()

    inv_5a = Invoice(
        invoice_number="INV-2026-005-A",
        export_transaction_id=exp_5.id,
        seller_name="Apex Global Exports Ltd",
        buyer_name="Vanguard Tech Inc",
        issue_date=today,
        currency="USD",
        total_amount=Decimal("750.00"),
        is_demo=True,
    )
    inv_5b = Invoice(
        invoice_number="INV-2026-005-B",
        export_transaction_id=exp_5.id,
        seller_name="Apex Global Exports Ltd",
        buyer_name="Vanguard Tech Inc",
        issue_date=today,
        currency="USD",
        total_amount=Decimal("750.00"),
        is_demo=True,
    )
    db.add_all([inv_5a, inv_5b])
    db.flush()

    pmt_5 = Payment(
        provider="paypal",
        provider_order_id="ORD-DEMO-5001",
        provider_capture_id="CAP-DEMO-5001",
        invoice_reference=None,  # Payer omitted invoice reference
        currency="USD",
        gross_amount=Decimal("750.00"),
        fee_amount=Decimal("22.50"),
        net_amount=Decimal("727.50"),
        status=PaymentStatus.COMPLETED,
        event_time=now_utc,
        environment=EnvironmentLabel.SANDBOX,
        is_demo=True,
    )
    db.add(pmt_5)
    db.flush()

    disc_5 = Discrepancy(
        rule_id="RULE_AMBIGUOUS_CANDIDATE",
        severity=DiscrepancySeverity.WARNING,
        compared_fields={
            "payment_id": str(pmt_5.id),
            "amount": "750.00",
            "candidate_invoices": ["INV-2026-005-A", "INV-2026-005-B"],
        },
        description="Single incoming payment of $750.00 matches two distinct active invoices of identical amounts for Vanguard Tech",
        recommended_action="Contact buyer accounts payable to verify intended invoice destination before allocating",
        status=DiscrepancyStatus.OPEN,
        is_demo=True,
    )
    db.add(disc_5)
    db.flush()

    decision_5 = HumanDecision(
        target_type=TargetType.DISCREPANCY,
        target_id=disc_5.id,
        decision=DecisionType.RE_ASSIGNED,
        reviewer_label="demo_auditor",
        notes="Held pending confirmation email from buyer Vanguard Tech accounts team",
        decided_at=now_utc,
    )
    db.add(decision_5)
    results["scenario_5_ambiguous_candidate"] = {
        "candidate_1": str(inv_5a.id),
        "candidate_2": str(inv_5b.id),
        "discrepancy_id": str(disc_5.id),
    }

    # -------------------------------------------------------------
    # Scenario 6: Unmatched Bank Credit
    # -------------------------------------------------------------
    bank_txn_6 = BankTransaction(
        bank_reference="BANK-DEMO-601",
        currency="EUR",
        amount=Decimal("1250.00"),
        transaction_date=today,
        transaction_type=BankTransactionType.CREDIT,
        status=BankTransactionStatus.POSTED,
        remittance_reference="DIRECT WIRE INFLOW REF 990142 FROM UNKNOWN REMITTER",
        is_demo=True,
    )
    db.add(bank_txn_6)
    db.flush()
    results["scenario_6_unmatched_bank_credit"] = {
        "bank_reference": bank_txn_6.bank_reference,
        "amount": "1250.00 EUR",
    }

    db.commit()
    return results
