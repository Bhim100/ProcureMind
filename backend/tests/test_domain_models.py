"""
Comprehensive test suite for ProcureMind Phase 1 domain models, constraints, and schemas.
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.document import Document, ExtractedField
from app.models.enums import (
    AllocationMethod,
    BankTransactionStatus,
    BankTransactionType,
    DiscrepancySeverity,
    DocumentType,
    EnvironmentLabel,
    ExtractionMethod,
    PaymentStatus,
    ProcessingStatus,
    ReviewState,
    SettlementStatus,
    TransactionStatus,
)
from app.models.export import ExportTransaction, Invoice, InvoiceLineItem, ShippingBill
from app.models.payment import BankTransaction, Payment, ProviderWebhookEvent, Settlement
from app.models.reconciliation import Allocation, Discrepancy
from app.schemas.export import InvoiceCreate
from app.schemas.payment import PaymentCreate
from app.schemas.reconciliation import AllocationCreate
from app.services.seed_data import seed_demo_scenarios


# ---------------------------------------------------------------------------
# 1. Document & Extracted Field Provenance Tests
# ---------------------------------------------------------------------------
def test_document_and_extracted_field_creation(db_session: Session) -> None:
    """Verifies that Document and ExtractedField persist complete provenance."""
    doc = Document(
        original_filename="commercial_invoice_990.pdf",
        media_type="application/pdf",
        size_bytes=524288,
        sha256="a" * 64,
        storage_key="docs/commercial_invoice_990.pdf",
        document_type=DocumentType.INVOICE,
        processing_status=ProcessingStatus.PARSED,
        page_count=2,
        is_demo=False,
    )
    db_session.add(doc)
    db_session.flush()

    assert isinstance(doc.id, uuid.UUID)
    assert doc.upload_time.tzinfo is not None
    assert doc.created_at.tzinfo is not None

    field = ExtractedField(
        document_id=doc.id,
        field_name="total_amount",
        raw_value="$25,400.00",
        normalized_value="25400.00",
        page_number=1,
        row_number=12,
        bounding_box={"x0": 0.75, "y0": 0.85, "x1": 0.95, "y1": 0.88},
        confidence=Decimal("0.9850"),
        review_state=ReviewState.AUTO_ACCEPTED,
        extraction_method=ExtractionMethod.TEXT,
    )
    db_session.add(field)
    db_session.flush()

    assert field.document_id == doc.id
    assert field.document.original_filename == "commercial_invoice_990.pdf"
    assert len(doc.extracted_fields) == 1
    assert doc.extracted_fields[0].bounding_box["x0"] == 0.75


def test_document_sha256_uniqueness_constraint(db_session: Session) -> None:
    """Ensures duplicate document uploads with identical SHA-256 are rejected by database uniqueness constraint."""
    doc1 = Document(
        original_filename="file_one.pdf",
        media_type="application/pdf",
        size_bytes=1000,
        sha256="b" * 64,
        storage_key="docs/file_one.pdf",
    )
    db_session.add(doc1)
    db_session.flush()

    doc2 = Document(
        original_filename="file_two.pdf",
        media_type="application/pdf",
        size_bytes=1000,
        sha256="b" * 64,  # Duplicate SHA-256
        storage_key="docs/file_two.pdf",
    )
    db_session.add(doc2)
    with pytest.raises(IntegrityError):
        db_session.flush()


# ---------------------------------------------------------------------------
# 2. Export Transaction & Invoice Line Items Tests
# ---------------------------------------------------------------------------
def test_export_transaction_invoice_and_shipping_bill(db_session: Session) -> None:
    """Verifies relationships between export transactions, invoices, line items, and shipping bills."""
    exp = ExportTransaction(
        transaction_reference="EXP-2026-TEST",
        exporter_name="Global Steel Works",
        exporter_tax_id="GSTIN123456789",
        buyer_name="Atlantic Import Co",
        buyer_country="USA",
        status=TransactionStatus.IN_PROGRESS,
    )
    db_session.add(exp)
    db_session.flush()

    inv = Invoice(
        invoice_number="INV-STEEL-001",
        export_transaction_id=exp.id,
        seller_name="Global Steel Works",
        buyer_name="Atlantic Import Co",
        issue_date=date(2026, 11, 1),
        currency="USD",
        total_amount=Decimal("15000.00"),
    )
    db_session.add(inv)
    db_session.flush()

    line = InvoiceLineItem(
        invoice_id=inv.id,
        line_number=1,
        description="Cold Rolled Steel Coils",
        quantity=Decimal("10.0000"),
        unit_price=Decimal("1500.00"),
        total_amount=Decimal("15000.00"),
        currency="USD",
        hs_code="72091500",
    )
    db_session.add(line)

    sb = ShippingBill(
        shipping_bill_number="SB-CUSTOMS-901",
        export_transaction_id=exp.id,
        invoice_reference="INV-STEEL-001",
        exporter_name="Global Steel Works",
        buyer_name="Atlantic Import Co",
        bill_date=date(2026, 11, 2),
        declared_currency="USD",
        declared_value=Decimal("15000.00"),
    )
    db_session.add(sb)
    db_session.flush()

    assert len(exp.invoices) == 1
    assert len(exp.shipping_bills) == 1
    assert len(inv.line_items) == 1
    assert inv.line_items[0].hs_code == "72091500"


# ---------------------------------------------------------------------------
# 3. Payment & Deduplication Tests
# ---------------------------------------------------------------------------
def test_provider_webhook_event_deduplication(db_session: Session) -> None:
    """Verifies that duplicate provider event IDs are rejected via unique constraint."""
    pmt = Payment(
        provider="paypal",
        provider_capture_id="CAP-TEST-001",
        currency="USD",
        gross_amount=Decimal("100.00"),
        fee_amount=Decimal("3.00"),
        net_amount=Decimal("97.00"),
        status=PaymentStatus.COMPLETED,
        environment=EnvironmentLabel.SANDBOX,
    )
    db_session.add(pmt)
    db_session.flush()

    evt1 = ProviderWebhookEvent(
        provider="paypal",
        provider_event_id="WH-EVT-DUPE-CHECK",
        event_type="PAYMENT.CAPTURE.COMPLETED",
        payment_id=pmt.id,
    )
    db_session.add(evt1)
    db_session.flush()

    evt2 = ProviderWebhookEvent(
        provider="paypal",
        provider_event_id="WH-EVT-DUPE-CHECK",  # Duplicate event ID
        event_type="PAYMENT.CAPTURE.COMPLETED",
        payment_id=pmt.id,
    )
    db_session.add(evt2)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_payment_capture_id_uniqueness(db_session: Session) -> None:
    """Verifies that duplicate provider capture IDs are rejected."""
    pmt1 = Payment(
        provider="paypal",
        provider_capture_id="CAP-UNIQUE-123",
        currency="USD",
        gross_amount=Decimal("200.00"),
        fee_amount=Decimal("6.00"),
        net_amount=Decimal("194.00"),
    )
    db_session.add(pmt1)
    db_session.flush()

    pmt2 = Payment(
        provider="paypal",
        provider_capture_id="CAP-UNIQUE-123",  # Duplicate capture ID
        currency="USD",
        gross_amount=Decimal("200.00"),
        fee_amount=Decimal("6.00"),
        net_amount=Decimal("194.00"),
    )
    db_session.add(pmt2)
    with pytest.raises(IntegrityError):
        db_session.flush()


# ---------------------------------------------------------------------------
# 4. Proceeds Pipeline Linking Tests (Payment -> Settlement -> BankTransaction)
# ---------------------------------------------------------------------------
def test_proceeds_pipeline_stages(db_session: Session) -> None:
    """Tests multi-stage evidence tracking: Payment -> Settlement -> BankTransaction."""
    bank_txn = BankTransaction(
        bank_reference="BANK-WIRE-7701",
        currency="USD",
        amount=Decimal("970.00"),
        transaction_date=date(2026, 11, 5),
        transaction_type=BankTransactionType.CREDIT,
        status=BankTransactionStatus.POSTED,
    )
    db_session.add(bank_txn)
    db_session.flush()

    settlement = Settlement(
        provider_reference="SETTLE-BATCH-990",
        bank_transaction_id=bank_txn.id,
        currency="USD",
        amount=Decimal("970.00"),
        settlement_date=date(2026, 11, 5),
        status=SettlementStatus.COMPLETED,
    )
    db_session.add(settlement)
    db_session.flush()

    pmt = Payment(
        provider="paypal",
        settlement_id=settlement.id,
        provider_capture_id="CAP-PIPELINE-01",
        currency="USD",
        gross_amount=Decimal("1000.00"),
        fee_amount=Decimal("30.00"),
        net_amount=Decimal("970.00"),
        status=PaymentStatus.COMPLETED,
    )
    db_session.add(pmt)
    db_session.flush()

    # Verify linkable stages of proceeds
    assert pmt.settlement is not None
    assert pmt.settlement.provider_reference == "SETTLE-BATCH-990"
    assert pmt.settlement.bank_transaction is not None
    assert pmt.settlement.bank_transaction.bank_reference == "BANK-WIRE-7701"


# ---------------------------------------------------------------------------
# 5. Allocation Single-Source Mutual Exclusivity Tests
# ---------------------------------------------------------------------------
def test_allocation_single_source_check_constraint_success(db_session: Session) -> None:
    """Verifies that an allocation with exactly one source succeeds."""
    inv = Invoice(
        invoice_number="INV-ALLOC-01",
        seller_name="Seller A",
        buyer_name="Buyer B",
        currency="USD",
        total_amount=Decimal("500.00"),
    )
    pmt = Payment(
        provider="paypal",
        provider_capture_id="CAP-ALLOC-01",
        currency="USD",
        gross_amount=Decimal("500.00"),
        fee_amount=Decimal("15.00"),
        net_amount=Decimal("485.00"),
    )
    db_session.add_all([inv, pmt])
    db_session.flush()

    alloc = Allocation(
        invoice_id=inv.id,
        payment_id=pmt.id,  # Exactly one financial source
        settlement_id=None,
        bank_transaction_id=None,
        allocated_amount=Decimal("500.00"),
        currency="USD",
        allocation_method=AllocationMethod.AUTO_EXACT,
    )
    db_session.add(alloc)
    db_session.flush()
    assert alloc.id is not None


def test_allocation_single_source_check_constraint_failure_multiple_sources(
    db_session: Session,
) -> None:
    """Verifies that an allocation referencing conflicting multiple financial sources fails database check constraint."""
    inv = Invoice(
        invoice_number="INV-ALLOC-02",
        seller_name="Seller A",
        buyer_name="Buyer B",
        currency="USD",
        total_amount=Decimal("500.00"),
    )
    pmt = Payment(
        provider="paypal",
        provider_capture_id="CAP-ALLOC-02",
        currency="USD",
        gross_amount=Decimal("500.00"),
        fee_amount=Decimal("15.00"),
        net_amount=Decimal("485.00"),
    )
    settle = Settlement(
        provider_reference="SETTLE-ALLOC-02",
        currency="USD",
        amount=Decimal("485.00"),
        settlement_date=date(2026, 11, 5),
    )
    db_session.add_all([inv, pmt, settle])
    db_session.flush()

    # Conflicting sources: both payment_id AND settlement_id
    conflicting_alloc = Allocation(
        invoice_id=inv.id,
        payment_id=pmt.id,
        settlement_id=settle.id,
        bank_transaction_id=None,
        allocated_amount=Decimal("500.00"),
        currency="USD",
    )
    db_session.add(conflicting_alloc)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_allocation_single_source_check_constraint_failure_no_source(db_session: Session) -> None:
    """Verifies that an allocation with zero sources fails the check constraint."""
    inv = Invoice(
        invoice_number="INV-ALLOC-03",
        seller_name="Seller A",
        buyer_name="Buyer B",
        currency="USD",
        total_amount=Decimal("500.00"),
    )
    db_session.add(inv)
    db_session.flush()

    # No financial source provided
    empty_alloc = Allocation(
        invoice_id=inv.id,
        payment_id=None,
        settlement_id=None,
        bank_transaction_id=None,
        allocated_amount=Decimal("500.00"),
        currency="USD",
    )
    db_session.add(empty_alloc)
    with pytest.raises(IntegrityError):
        db_session.flush()


# ---------------------------------------------------------------------------
# 6. Pydantic v2 Strict Validation Tests
# ---------------------------------------------------------------------------
def test_pydantic_currency_validation() -> None:
    """Verifies that Pydantic rejects invalid or unknown currency codes."""
    # Valid ISO-4217 code
    inv_valid = InvoiceCreate(
        invoice_number="INV-VALID-01",
        seller_name="Apex Exporters",
        buyer_name="Nexus Retail",
        currency="USD",
        total_amount=Decimal("100.00"),
    )
    assert inv_valid.currency == "USD"

    # Invalid currency code
    with pytest.raises(ValidationError):
        InvoiceCreate(
            invoice_number="INV-INVALID-01",
            seller_name="Apex Exporters",
            buyer_name="Nexus Retail",
            currency="XYZ_FAKE",
            total_amount=Decimal("100.00"),
        )


def test_pydantic_monetary_precision_and_amounts() -> None:
    """Verifies that monetary amounts exceeding 2 decimals or negative amounts are rejected."""
    # Exceeding 2 decimal places (e.g. 100.999)
    with pytest.raises(ValidationError):
        InvoiceCreate(
            invoice_number="INV-PREC-01",
            seller_name="Apex Exporters",
            buyer_name="Nexus Retail",
            currency="USD",
            total_amount=Decimal("100.999"),
        )

    # Zero or negative invoice total
    with pytest.raises(ValidationError):
        InvoiceCreate(
            invoice_number="INV-NEG-01",
            seller_name="Apex Exporters",
            buyer_name="Nexus Retail",
            currency="USD",
            total_amount=Decimal("-50.00"),
        )


def test_pydantic_payment_net_calculation_validation() -> None:
    """Verifies that Payment schema rejects inconsistent net amounts."""
    # Correct calculation: 100 - 3 = 97
    pmt = PaymentCreate(
        provider="paypal",
        currency="USD",
        gross_amount=Decimal("100.00"),
        fee_amount=Decimal("3.00"),
        net_amount=Decimal("97.00"),
    )
    assert pmt.net_amount == Decimal("97.00")

    # Inconsistent calculation: 100 - 3 != 95
    with pytest.raises(ValidationError):
        PaymentCreate(
            provider="paypal",
            currency="USD",
            gross_amount=Decimal("100.00"),
            fee_amount=Decimal("3.00"),
            net_amount=Decimal("95.00"),  # False net amount
        )


def test_pydantic_allocation_mutual_exclusivity_validation() -> None:
    """Verifies that Pydantic rejects allocations without exactly one financial source."""
    inv_id = uuid.uuid4()
    pmt_id = uuid.uuid4()
    settle_id = uuid.uuid4()

    # Valid: single source
    alloc = AllocationCreate(
        invoice_id=inv_id,
        payment_id=pmt_id,
        allocated_amount=Decimal("100.00"),
        currency="USD",
    )
    assert alloc.payment_id == pmt_id

    # Invalid: conflicting multiple sources
    with pytest.raises(ValidationError):
        AllocationCreate(
            invoice_id=inv_id,
            payment_id=pmt_id,
            settlement_id=settle_id,
            allocated_amount=Decimal("100.00"),
            currency="USD",
        )

    # Invalid: zero sources
    with pytest.raises(ValidationError):
        AllocationCreate(
            invoice_id=inv_id,
            allocated_amount=Decimal("100.00"),
            currency="USD",
        )


# ---------------------------------------------------------------------------
# 7. Seed Demo Scenarios Tests
# ---------------------------------------------------------------------------
def test_seed_demo_scenarios(db_session: Session) -> None:
    """Verifies that seed_demo_scenarios successfully generates all 6 demo scenarios marked is_demo=True."""
    results = seed_demo_scenarios(db_session)

    # Confirm all 6 scenarios exist in results
    assert "scenario_1_clean_invoice" in results
    assert "scenario_2_partial_payment" in results
    assert "scenario_3_documented_fee" in results
    assert "scenario_4_unexplained_diff" in results
    assert "scenario_5_ambiguous_candidate" in results
    assert "scenario_6_unmatched_bank_credit" in results

    # Verify Scenario 1: Clean invoice
    clean_inv = db_session.query(Invoice).filter_by(invoice_number="INV-2026-001").one()
    assert clean_inv.is_demo is True
    assert clean_inv.total_amount == Decimal("1000.00")
    assert len(clean_inv.allocations) == 1
    assert clean_inv.allocations[0].allocated_amount == Decimal("1000.00")
    assert clean_inv.allocations[0].payment.fee_amount == Decimal("30.00")

    # Verify Scenario 2: Partial payment
    partial_inv = db_session.query(Invoice).filter_by(invoice_number="INV-2026-002").one()
    assert partial_inv.total_amount == Decimal("5000.00")
    assert partial_inv.allocations[0].allocated_amount == Decimal("2000.00")

    # Verify Scenario 3: Documented fee
    fee_inv = db_session.query(Invoice).filter_by(invoice_number="INV-2026-003").one()
    fee_pmt = fee_inv.allocations[0].payment
    assert fee_pmt.fee_amount == Decimal("15.00")
    assert fee_pmt.settlement is not None
    assert fee_pmt.settlement.amount == Decimal("485.00")

    # Verify Scenario 4: Unexplained difference
    mismatch_disc = db_session.query(Discrepancy).filter_by(rule_id="RULE_AMOUNT_MISMATCH").one()
    assert mismatch_disc.is_demo is True
    assert mismatch_disc.severity == DiscrepancySeverity.ERROR
    assert mismatch_disc.compared_fields["shortfall"] == "100.00"

    # Verify Scenario 5: Ambiguous candidate
    ambig_disc = db_session.query(Discrepancy).filter_by(rule_id="RULE_AMBIGUOUS_CANDIDATE").one()
    assert ambig_disc.is_demo is True
    assert len(ambig_disc.compared_fields["candidate_invoices"]) == 2

    # Verify Scenario 6: Unmatched bank credit
    unmatched_bank = (
        db_session.query(BankTransaction).filter_by(bank_reference="BANK-DEMO-601").one()
    )
    assert unmatched_bank.is_demo is True
    assert unmatched_bank.amount == Decimal("1250.00")
    assert unmatched_bank.currency == "EUR"
    assert len(unmatched_bank.allocations) == 0
