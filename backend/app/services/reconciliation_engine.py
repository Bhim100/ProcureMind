"""
Deterministic Matching & Reconciliation Engine for ProcureMind.

In strict compliance with financial source of truth requirements:
- 100% deterministic arithmetic in Python Decimal (no LLM in matching or calculations).
- Preserves exact Decimal values; validates scale per ISO-4217 currency.
- Multi-stage payment flow: Allocates invoice receivable only once from payment capture gross.
  Settlement batches and bank credits verify cash flow realization without double-counting.
- Itemizes provider fee components and classifies strictly the unsupported remainder as unexplained.
- Reversal/refund proposals use positive amounts with is_reversal=True.
- Reconciliation runs create suggestions only; official Allocation rows are created exclusively
  upon human decision approval for invoice-payment allocations or compensating reversals.
- Database business keys guarantee idempotency; reruns mark stale proposals superseded and
  resolved discrepancies as resolved without deleting audit records.
"""

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.currencies import validate_currency_amount, validate_currency_code
from app.core.normalization import normalize_reference_identifier
from app.models.enums import (
    AllocationMethod,
    AllocationReviewStatus,
    BankTransactionType,
    DecisionType,
    DiscrepancySeverity,
    DiscrepancyStatus,
    ExtractionMethod,
    MatchStatus,
    PaymentStatus,
    ReviewState,
    TargetType,
    TransactionStatus,
)
from app.models.export import ExportTransaction, Invoice, ShippingBill
from app.models.payment import BankTransaction, Payment, Settlement
from app.models.reconciliation import (
    Allocation,
    Discrepancy,
    EvidenceReference,
    HumanDecision,
    ReconciliationMatch,
)
from app.schemas.match import (
    MatchDecisionRequest,
    ReconciliationMatchRead,
    ReconciliationRunResponse,
    SettlementFlowStage,
)
from app.schemas.reconciliation import DiscrepancyRead


def _compute_match_business_key(
    tx_id: uuid.UUID,
    match_type: str,
    invoice_id: uuid.UUID | None,
    payment_id: uuid.UUID | None,
    settlement_id: uuid.UUID | None,
    bank_transaction_id: uuid.UUID | None,
    rule_id: str,
    is_reversal: bool,
) -> str:
    """Computes a deterministic 64-char SHA-256 hash for a reconciliation match candidate."""
    raw = (
        f"{tx_id}:{match_type}:{invoice_id}:{payment_id}:"
        f"{settlement_id}:{bank_transaction_id}:{rule_id}:{is_reversal}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _compute_discrepancy_business_key(
    tx_id: uuid.UUID,
    rule_id: str,
    target_record_type: str,
    target_record_id: uuid.UUID | None,
    target_field: str,
) -> str:
    """Computes a deterministic 64-char SHA-256 hash for a discrepancy finding."""
    raw = f"{tx_id}:{rule_id}:{target_record_type}:{target_record_id}:{target_field}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_provider_fee_components(
    payment: Payment,
) -> tuple[dict[str, Decimal], list[dict[str, Any]]]:
    """
    Extracts itemized provider-evidenced fee components from payment webhook events or attributes.

    Returns:
        (components_dict, evidence_details_list)
    """
    components: dict[str, Decimal] = {}
    evidence_details: list[dict[str, Any]] = []

    # Check webhook event payloads
    for evt in payment.webhook_events:
        payload = evt.payload or {}
        # PayPal payload extraction pattern: resource.seller_receivable_breakdown
        resource = payload.get("resource", {}) if isinstance(payload, dict) else {}
        breakdown = resource.get("seller_receivable_breakdown", {})
        if breakdown:
            paypal_fee = breakdown.get("paypal_fee", {}).get("value")
            if paypal_fee is not None:
                components["paypal_processing_fee"] = Decimal(str(paypal_fee))
                evidence_details.append(
                    {
                        "source": "provider_webhook_event",
                        "event_id": evt.provider_event_id,
                        "component": "paypal_processing_fee",
                        "amount": str(paypal_fee),
                    }
                )
            platform_fee = breakdown.get("platform_fees", [{}])[0].get("amount", {}).get("value")
            if platform_fee is not None:
                components["platform_fee"] = Decimal(str(platform_fee))
                evidence_details.append(
                    {
                        "source": "provider_webhook_event",
                        "event_id": evt.provider_event_id,
                        "component": "platform_fee",
                        "amount": str(platform_fee),
                    }
                )

    # Fallback to payment.fee_amount if greater than 0 and recorded by provider capture
    if not components and payment.fee_amount > Decimal("0.0000"):
        components["provider_transaction_fee"] = payment.fee_amount
        evidence_details.append(
            {
                "source": "payment_record_attribute",
                "provider_capture_id": payment.provider_capture_id,
                "component": "provider_transaction_fee",
                "amount": str(payment.fee_amount),
            }
        )

    return components, evidence_details


def reconcile_transaction(db: Session, transaction_id: uuid.UUID) -> ReconciliationRunResponse:
    """
    Executes the deterministic matching and reconciliation engine for an export transaction.

    In accordance with hard constraints:
    - Creates suggestion matches (review_status='suggested').
    - Allocates invoice receivables only once from primary payment capture gross.
    - Zero rows are written to the allocations table during this run.
    - Transaction status is never marked RECONCILED autonomously.
    - Idempotently updates unchanged proposals, supersedes stale proposals, and resolves cleared discrepancies.
    """
    tx = db.query(ExportTransaction).filter(ExportTransaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export transaction '{transaction_id}' not found.",
        )

    now_utc = datetime.now(UTC)
    run_id = uuid.uuid4()

    # Load all associated trade records
    invoices: list[Invoice] = tx.invoices
    shipping_bills: list[ShippingBill] = tx.shipping_bills
    payments: list[Payment] = tx.payments
    settlements: list[Settlement] = tx.settlements
    bank_txns: list[BankTransaction] = tx.bank_transactions

    # Fetch existing matches and discrepancies
    existing_matches = (
        db.query(ReconciliationMatch)
        .filter(ReconciliationMatch.export_transaction_id == transaction_id)
        .all()
    )
    existing_discrepancies = (
        db.query(Discrepancy).filter(Discrepancy.export_transaction_id == transaction_id).all()
    )

    # Track approved allocations from official ledger (never modified during reconcile)
    approved_allocations = (
        db.query(Allocation)
        .join(Invoice, Invoice.id == Allocation.invoice_id)
        .filter(
            Invoice.export_transaction_id == transaction_id,
            Allocation.review_status == AllocationReviewStatus.APPROVED,
        )
        .all()
    )

    # Calculate current effective invoice remaining balances considering approved allocations
    invoice_balances: dict[uuid.UUID, Decimal] = {}
    for inv in invoices:
        inv_curr = validate_currency_code(inv.currency)
        total_credit = sum(
            (
                a.allocated_amount
                for a in approved_allocations
                if a.invoice_id == inv.id and not a.is_reversal
            ),
            Decimal("0.0000"),
        )
        total_reversal = sum(
            (
                a.allocated_amount
                for a in approved_allocations
                if a.invoice_id == inv.id and a.is_reversal
            ),
            Decimal("0.0000"),
        )
        net_settled = total_credit - total_reversal
        rem = inv.total_amount - net_settled
        invoice_balances[inv.id] = validate_currency_amount(rem, inv_curr)

    # Track consumed payment gross amounts from approved allocations
    consumed_payment_gross: dict[uuid.UUID, Decimal] = {}
    for p in payments:
        p_curr = validate_currency_code(p.currency)
        alloc_gross = sum(
            (
                a.allocated_amount
                for a in approved_allocations
                if a.payment_id == p.id and not a.is_reversal
            ),
            Decimal("0.0000"),
        )
        consumed_payment_gross[p.id] = validate_currency_amount(alloc_gross, p_curr)

    # Collection for results generated in this run
    generated_match_keys: set[str] = set()
    generated_disc_keys: set[str] = set()
    active_matches: list[ReconciliationMatch] = []
    active_discrepancies: list[Discrepancy] = []
    flow_stages: list[SettlementFlowStage] = []

    # Map existing active matches/discrepancies by business key for idempotent update
    match_by_key = {
        m.business_key: m
        for m in existing_matches
        if m.review_status != AllocationReviewStatus.SUPERSEDED
    }
    disc_by_key = {
        d.business_key: d
        for d in existing_discrepancies
        if d.status in (DiscrepancyStatus.OPEN, DiscrepancyStatus.ACKNOWLEDGED)
    }

    # Helper to record or update a proposed match
    def propose_match(
        match_type: str,
        match_status: MatchStatus,
        rule_id: str,
        allocated_amount: Decimal,
        currency: str,
        is_reversal: bool = False,
        invoice_id: uuid.UUID | None = None,
        payment_id: uuid.UUID | None = None,
        settlement_id: uuid.UUID | None = None,
        bank_transaction_id: uuid.UUID | None = None,
        shipping_bill_id: uuid.UUID | None = None,
        compared_values: dict[str, Any] | None = None,
        calculation: dict[str, Any] | None = None,
        severity: DiscrepancySeverity = DiscrepancySeverity.INFO,
        notes: str | None = None,
    ) -> ReconciliationMatch:
        bkey = _compute_match_business_key(
            tx_id=transaction_id,
            match_type=match_type,
            invoice_id=invoice_id,
            payment_id=payment_id,
            settlement_id=settlement_id,
            bank_transaction_id=bank_transaction_id,
            rule_id=rule_id,
            is_reversal=is_reversal,
        )
        generated_match_keys.add(bkey)

        clean_currency = validate_currency_code(currency)
        val_amount = validate_currency_amount(allocated_amount, clean_currency)

        existing = match_by_key.get(bkey)
        if existing:
            # If already approved or rejected by human, preserve state untouched
            if existing.review_status in (
                AllocationReviewStatus.APPROVED,
                AllocationReviewStatus.REJECTED,
            ):
                active_matches.append(existing)
                return existing
            # Update proposed suggestion with latest calculation
            existing.reconciliation_run_id = run_id
            existing.allocated_amount = val_amount
            existing.is_reversal = is_reversal
            existing.compared_values = compared_values
            existing.calculation = calculation
            existing.severity = severity
            existing.notes = notes
            existing.updated_at = now_utc
            active_matches.append(existing)
            return existing

        # Create new proposal
        match_obj = ReconciliationMatch(
            export_transaction_id=transaction_id,
            invoice_id=invoice_id,
            payment_id=payment_id,
            settlement_id=settlement_id,
            bank_transaction_id=bank_transaction_id,
            shipping_bill_id=shipping_bill_id,
            match_type=match_type,
            match_status=match_status,
            review_status=AllocationReviewStatus.SUGGESTED,
            allocated_amount=val_amount,
            is_reversal=is_reversal,
            currency=clean_currency,
            rule_id=rule_id,
            business_key=bkey,
            reconciliation_run_id=run_id,
            compared_values=compared_values,
            calculation=calculation,
            severity=severity,
            notes=notes,
            is_demo=tx.is_demo,
            created_at=now_utc,
            updated_at=now_utc,
        )
        db.add(match_obj)
        match_by_key[bkey] = match_obj
        active_matches.append(match_obj)
        return match_obj

    # Helper to record or update a discrepancy finding
    def flag_discrepancy(
        rule_id: str,
        severity: DiscrepancySeverity,
        target_record_type: str,
        target_record_id: uuid.UUID | None,
        target_field: str,
        description: str,
        compared_fields: dict[str, Any] | None = None,
        calculation: dict[str, Any] | None = None,
        recommended_action: str | None = None,
    ) -> Discrepancy:
        bkey = _compute_discrepancy_business_key(
            tx_id=transaction_id,
            rule_id=rule_id,
            target_record_type=target_record_type,
            target_record_id=target_record_id,
            target_field=target_field,
        )
        generated_disc_keys.add(bkey)

        existing = disc_by_key.get(bkey)
        if existing:
            # Update open discrepancy with latest calculation
            existing.reconciliation_run_id = run_id
            existing.compared_fields = compared_fields
            existing.calculation = calculation
            existing.description = description
            existing.recommended_action = recommended_action
            existing.severity = severity
            existing.updated_at = now_utc
            active_discrepancies.append(existing)
            return existing

        disc_obj = Discrepancy(
            export_transaction_id=transaction_id,
            rule_id=rule_id,
            business_key=bkey,
            reconciliation_run_id=run_id,
            severity=severity,
            compared_fields=compared_fields,
            calculation=calculation,
            description=description,
            recommended_action=recommended_action,
            status=DiscrepancyStatus.OPEN,
            is_demo=tx.is_demo,
            created_at=now_utc,
            updated_at=now_utc,
        )
        db.add(disc_obj)
        disc_by_key[bkey] = disc_obj
        active_discrepancies.append(disc_obj)
        return disc_obj

    # -------------------------------------------------------------------------
    # Tier 1: Trade Document Cross-Checks (Invoice vs Shipping Bill)
    # -------------------------------------------------------------------------
    if invoices and not shipping_bills:
        flag_discrepancy(
            rule_id="RULE_MISSING_SHIPPING_BILL",
            severity=DiscrepancySeverity.WARNING,
            target_record_type="export_transaction",
            target_record_id=transaction_id,
            target_field="shipping_bills",
            description="Export transaction has commercial invoices but no customs shipping bill declaration.",
            recommended_action="Upload customs shipping bill to ensure cross-border regulatory compliance.",
        )

    for inv in invoices:
        inv_ref_norm = normalize_reference_identifier(inv.invoice_number)
        matching_sbs = [
            sb
            for sb in shipping_bills
            if sb.invoice_reference
            and normalize_reference_identifier(sb.invoice_reference) == inv_ref_norm
        ]
        if not matching_sbs and shipping_bills:
            flag_discrepancy(
                rule_id="RULE_CUSTOMS_REFERENCE_MISMATCH",
                severity=DiscrepancySeverity.ERROR,
                target_record_type="invoice",
                target_record_id=inv.id,
                target_field="invoice_number",
                description=f"Invoice '{inv.invoice_number}' does not match any customs shipping bill declaration reference.",
                compared_fields={
                    "invoice_number": inv.invoice_number,
                    "available_shipping_bills": [sb.shipping_bill_number for sb in shipping_bills],
                },
                recommended_action="Verify customs declaration with shipping agent or customs broker.",
            )
        for sb in matching_sbs:
            # Check declared currency
            if sb.declared_currency.upper() != inv.currency.upper():
                flag_discrepancy(
                    rule_id="RULE_CUSTOMS_CURRENCY_MISMATCH",
                    severity=DiscrepancySeverity.CRITICAL,
                    target_record_type="shipping_bill",
                    target_record_id=sb.id,
                    target_field="declared_currency",
                    description=(
                        f"Customs currency mismatch: Shipping bill {sb.shipping_bill_number} declared in "
                        f"{sb.declared_currency}, but invoice {inv.invoice_number} is in {inv.currency}."
                    ),
                    compared_fields={
                        "shipping_bill_number": sb.shipping_bill_number,
                        "declared_currency": sb.declared_currency,
                        "invoice_number": inv.invoice_number,
                        "invoice_currency": inv.currency,
                    },
                    recommended_action="Customs declaration currency divergence requires regulatory customs rectification.",
                )
            # Check declared value
            if sb.declared_value != inv.total_amount:
                variance = sb.declared_value - inv.total_amount
                flag_discrepancy(
                    rule_id="RULE_CUSTOMS_VALUE_MISMATCH",
                    severity=DiscrepancySeverity.ERROR,
                    target_record_type="shipping_bill",
                    target_record_id=sb.id,
                    target_field="declared_value",
                    description=(
                        f"Customs declared value mismatch: Shipping bill {sb.shipping_bill_number} value "
                        f"({sb.declared_value} {sb.declared_currency}) differs from invoice ({inv.total_amount} {inv.currency})."
                    ),
                    compared_fields={
                        "shipping_bill_number": sb.shipping_bill_number,
                        "declared_value": str(sb.declared_value),
                        "invoice_number": inv.invoice_number,
                        "invoice_total": str(inv.total_amount),
                    },
                    calculation={
                        "declared_value": str(sb.declared_value),
                        "invoice_total": str(inv.total_amount),
                        "variance": str(variance),
                    },
                    recommended_action="Reconcile customs FOB/CIF value adjustments or file revised export declaration.",
                )

    # -------------------------------------------------------------------------
    # Tier 2: Payment Duplicate & Validity Checks
    # -------------------------------------------------------------------------
    seen_capture_ids: dict[str, Payment] = {}
    for p in payments:
        if p.provider_capture_id:
            cap_id = p.provider_capture_id.strip()
            if cap_id in seen_capture_ids:
                flag_discrepancy(
                    rule_id="RULE_DUPLICATE_PROVIDER_IDENTIFIER",
                    severity=DiscrepancySeverity.CRITICAL,
                    target_record_type="payment",
                    target_record_id=p.id,
                    target_field="provider_capture_id",
                    description=f"Duplicate provider capture identifier detected: '{cap_id}'.",
                    compared_fields={
                        "colliding_capture_id": cap_id,
                        "first_payment_id": str(seen_capture_ids[cap_id].id),
                        "duplicate_payment_id": str(p.id),
                    },
                    recommended_action="Audit provider API logs. Duplicate capture ID must not be processed.",
                )
            else:
                seen_capture_ids[cap_id] = p

    # Heuristic suspect duplicates (same amount + close date, but distinct capture IDs)
    for i, p1 in enumerate(payments):
        for p2 in payments[i + 1 :]:
            if (
                p1.gross_amount == p2.gross_amount
                and p1.currency == p2.currency
                and p1.provider_capture_id != p2.provider_capture_id
                and p1.event_time
                and p2.event_time
                and abs((p1.event_time - p2.event_time).total_seconds()) <= 86400 * 2
            ):
                flag_discrepancy(
                    rule_id="RULE_SUSPECTED_DUPLICATE_CANDIDATE",
                    severity=DiscrepancySeverity.WARNING,
                    target_record_type="payment",
                    target_record_id=p2.id,
                    target_field="gross_amount",
                    description=(
                        f"Suspected duplicate payment candidate: Payment {p2.id} ({p2.gross_amount} {p2.currency}) "
                        f"posted within 48h of Payment {p1.id} with identical amount."
                    ),
                    compared_fields={
                        "payment_1_id": str(p1.id),
                        "payment_1_capture": p1.provider_capture_id,
                        "payment_2_id": str(p2.id),
                        "payment_2_capture": p2.provider_capture_id,
                        "amount": str(p1.gross_amount),
                    },
                    recommended_action="Review payment batch to verify whether this represents a distinct installment or duplicate.",
                )

    # -------------------------------------------------------------------------
    # Tier 3: Primary Allocations & Refund Reversals (Stage 1 -> Stage 2)
    # -------------------------------------------------------------------------
    # Allocate invoice receivable strictly once from Payment capture gross
    for p in payments:
        p_curr = validate_currency_code(p.currency)

        # Handle refunds / reversals
        if p.status == PaymentStatus.REFUNDED:
            refund_amt = validate_currency_amount(p.gross_amount, p_curr)
            # Find matching invoice by reference
            matching_inv = next(
                (
                    inv
                    for inv in invoices
                    if inv.invoice_number
                    and p.invoice_reference
                    and normalize_reference_identifier(inv.invoice_number)
                    == normalize_reference_identifier(p.invoice_reference)
                ),
                None,
            )
            propose_match(
                match_type="payment_reversal",
                match_status=MatchStatus.REQUIRES_HUMAN_REVIEW,
                rule_id="RULE_PAYMENT_REFUND_OR_REVERSAL",
                allocated_amount=refund_amt,
                currency=p_curr,
                is_reversal=True,
                invoice_id=matching_inv.id if matching_inv else None,
                payment_id=p.id,
                compared_values={
                    "payment_capture_id": p.provider_capture_id,
                    "refund_amount": str(refund_amt),
                    "invoice_reference": p.invoice_reference,
                },
                calculation={
                    "original_gross": str(p.gross_amount),
                    "refund_amount": str(refund_amt),
                    "reversal_direction": "DEBIT",
                },
                severity=DiscrepancySeverity.WARNING,
                notes="Payment was refunded by provider. Proposes compensating reversal offset requiring human approval.",
            )
            continue

        # Check provider gross-to-net deduction audit
        gross_to_net_deduction = p.gross_amount - p.net_amount
        fee_components, fee_evidence = _extract_provider_fee_components(p)
        total_evidenced_fees = sum(fee_components.values(), Decimal("0.0000"))
        unsupported_remainder = gross_to_net_deduction - total_evidenced_fees

        if unsupported_remainder > Decimal("0.0000"):
            flag_discrepancy(
                rule_id="RULE_UNDOCUMENTED_DEDUCTION",
                severity=DiscrepancySeverity.ERROR,
                target_record_type="payment",
                target_record_id=p.id,
                target_field="net_amount",
                description=(
                    f"Payment capture {p.provider_capture_id or p.id} gross-to-net deduction of "
                    f"{gross_to_net_deduction} {p.currency} has unsupported remainder of {unsupported_remainder} {p.currency}."
                ),
                compared_fields={
                    "payment_id": str(p.id),
                    "provider_capture_id": p.provider_capture_id,
                    "gross_amount": str(p.gross_amount),
                    "net_amount": str(p.net_amount),
                },
                calculation={
                    "gross_amount": str(p.gross_amount),
                    "net_amount": str(p.net_amount),
                    "gross_to_net_deduction": str(gross_to_net_deduction),
                    "evidenced_fee_components": {k: str(v) for k, v in fee_components.items()},
                    "total_evidenced_fees": str(total_evidenced_fees),
                    "unexplained_remainder": str(unsupported_remainder),
                    "fee_evidence_sources": fee_evidence,
                },
                recommended_action="Audit provider fee schedule or request revised settlement statement.",
            )
        elif gross_to_net_deduction > Decimal("0.0000") and unsupported_remainder == Decimal(
            "0.0000"
        ):
            # Record verified documented fee
            propose_match(
                match_type="documented_fee_verification",
                match_status=MatchStatus.MATCHED,
                rule_id="RULE_DOCUMENTED_FEE",
                allocated_amount=total_evidenced_fees,
                currency=p_curr,
                is_reversal=False,
                payment_id=p.id,
                compared_values={
                    "gross_amount": str(p.gross_amount),
                    "net_amount": str(p.net_amount),
                },
                calculation={
                    "gross_amount": str(p.gross_amount),
                    "net_amount": str(p.net_amount),
                    "evidenced_fee_components": {k: str(v) for k, v in fee_components.items()},
                    "total_documented_fees": str(total_evidenced_fees),
                },
                severity=DiscrepancySeverity.INFO,
                notes="Provider payment processing fee verified against evidence.",
            )

        # Match payment to invoice receivable
        avail_payment_gross = p.gross_amount - consumed_payment_gross.get(p.id, Decimal("0.0000"))
        if avail_payment_gross <= Decimal("0.0000"):
            flag_discrepancy(
                rule_id="RULE_DUPLICATE_ALLOCATION",
                severity=DiscrepancySeverity.CRITICAL,
                target_record_type="payment",
                target_record_id=p.id,
                target_field="gross_amount",
                description=f"Payment {p.provider_capture_id or p.id} gross proceeds are already fully consumed by approved allocations.",
                compared_fields={
                    "payment_gross": str(p.gross_amount),
                    "already_consumed": str(consumed_payment_gross.get(p.id, Decimal("0.0000"))),
                },
                recommended_action="Reject duplicate allocation attempt.",
            )
            continue

        # Find matching invoice by exact reference
        exact_matches = [
            inv
            for inv in invoices
            if p.invoice_reference
            and normalize_reference_identifier(p.invoice_reference)
            == normalize_reference_identifier(inv.invoice_number)
        ]

        if exact_matches:
            target_inv = exact_matches[0]
            # Currency mismatch check
            if target_inv.currency.upper() != p.currency.upper():
                flag_discrepancy(
                    rule_id="RULE_CURRENCY_MISMATCH",
                    severity=DiscrepancySeverity.CRITICAL,
                    target_record_type="payment",
                    target_record_id=p.id,
                    target_field="currency",
                    description=(
                        f"Currency mismatch: Payment {p.id} received in {p.currency}, but invoice "
                        f"{target_inv.invoice_number} is billed in {target_inv.currency}. No sourced FX rate provided."
                    ),
                    compared_fields={
                        "payment_currency": p.currency,
                        "invoice_currency": target_inv.currency,
                    },
                    recommended_action="Do not allocate across currencies without explicit authorized exchange rate.",
                )
                propose_match(
                    match_type="invoice_payment",
                    match_status=MatchStatus.REQUIRES_HUMAN_REVIEW,
                    rule_id="RULE_CURRENCY_MISMATCH",
                    allocated_amount=Decimal("0.0000"),
                    currency=p_curr,
                    invoice_id=target_inv.id,
                    payment_id=p.id,
                    compared_values={
                        "payment_currency": p.currency,
                        "invoice_currency": target_inv.currency,
                    },
                    severity=DiscrepancySeverity.CRITICAL,
                    notes="Cross-currency match held for human review.",
                )
                continue

            rem_bal = invoice_balances.get(target_inv.id, target_inv.total_amount)
            if rem_bal <= Decimal("0.0000"):
                # Invoice already fully settled; payment is an overpayment / excess credit
                flag_discrepancy(
                    rule_id="RULE_OVERPAYMENT",
                    severity=DiscrepancySeverity.ERROR,
                    target_record_type="payment",
                    target_record_id=p.id,
                    target_field="gross_amount",
                    description=f"Payment of {avail_payment_gross} {p.currency} received for already settled invoice {target_inv.invoice_number}.",
                    compared_fields={
                        "payment_amount": str(avail_payment_gross),
                        "invoice_remaining_balance": "0.00",
                    },
                    recommended_action="Hold excess payment as customer credit or issue refund.",
                )
                continue

            # Determine allocation amount (capped at invoice remaining balance)
            alloc_amt = min(rem_bal, avail_payment_gross)
            if alloc_amt == rem_bal and avail_payment_gross == rem_bal:
                # 100% exact match
                propose_match(
                    match_type="invoice_payment",
                    match_status=MatchStatus.MATCHED,
                    rule_id="RULE_EXACT_REFERENCE_MATCH",
                    allocated_amount=alloc_amt,
                    currency=p_curr,
                    invoice_id=target_inv.id,
                    payment_id=p.id,
                    compared_values={
                        "invoice_number": target_inv.invoice_number,
                        "payment_invoice_reference": p.invoice_reference,
                        "allocated_amount": str(alloc_amt),
                    },
                    calculation={
                        "invoice_total": str(target_inv.total_amount),
                        "payment_gross": str(p.gross_amount),
                        "allocated_amount": str(alloc_amt),
                        "remaining_invoice_balance": "0.00",
                    },
                    severity=DiscrepancySeverity.INFO,
                    notes="Exact reference match with full receivable allocation.",
                )
                invoice_balances[target_inv.id] = Decimal("0.0000")
            elif alloc_amt < rem_bal:
                # Partial payment
                rem_after = rem_bal - alloc_amt
                propose_match(
                    match_type="invoice_payment",
                    match_status=MatchStatus.PARTIAL,
                    rule_id="RULE_PARTIAL_PAYMENT",
                    allocated_amount=alloc_amt,
                    currency=p_curr,
                    invoice_id=target_inv.id,
                    payment_id=p.id,
                    compared_values={
                        "invoice_number": target_inv.invoice_number,
                        "payment_invoice_reference": p.invoice_reference,
                        "allocated_amount": str(alloc_amt),
                    },
                    calculation={
                        "invoice_total": str(target_inv.total_amount),
                        "allocated_amount": str(alloc_amt),
                        "remaining_invoice_balance": str(rem_after),
                    },
                    severity=DiscrepancySeverity.INFO,
                    notes=f"Partial payment installment: remaining balance {rem_after} {target_inv.currency}.",
                )
                invoice_balances[target_inv.id] = rem_after
            else:
                # Overpayment on invoice (payment gross > invoice remaining balance)
                excess = avail_payment_gross - rem_bal
                propose_match(
                    match_type="invoice_payment",
                    match_status=MatchStatus.MATCHED,
                    rule_id="RULE_EXACT_REFERENCE_MATCH",
                    allocated_amount=alloc_amt,
                    currency=p_curr,
                    invoice_id=target_inv.id,
                    payment_id=p.id,
                    compared_values={
                        "invoice_number": target_inv.invoice_number,
                        "payment_invoice_reference": p.invoice_reference,
                        "allocated_amount": str(alloc_amt),
                    },
                    calculation={
                        "invoice_total": str(target_inv.total_amount),
                        "payment_gross": str(avail_payment_gross),
                        "allocated_amount": str(alloc_amt),
                        "excess_unallocated_payment": str(excess),
                    },
                    severity=DiscrepancySeverity.INFO,
                    notes=f"Invoice fully covered; excess unallocated payment {excess} {p.currency}.",
                )
                invoice_balances[target_inv.id] = Decimal("0.0000")
                flag_discrepancy(
                    rule_id="RULE_OVERPAYMENT",
                    severity=DiscrepancySeverity.ERROR,
                    target_record_type="payment",
                    target_record_id=p.id,
                    target_field="gross_amount",
                    description=f"Payment gross {p.gross_amount} {p.currency} exceeds invoice {target_inv.invoice_number} balance by {excess} {p.currency}.",
                    compared_fields={
                        "invoice_number": target_inv.invoice_number,
                        "payment_gross": str(p.gross_amount),
                        "excess": str(excess),
                    },
                    recommended_action="Retain unallocated excess as customer credit or process refund.",
                )
        else:
            # Payment has no exact invoice reference - use heuristic supporting evidence
            candidate_invoices = [
                inv
                for inv in invoices
                if invoice_balances.get(inv.id, inv.total_amount) > Decimal("0.0000")
                and inv.currency.upper() == p.currency.upper()
                and (
                    invoice_balances.get(inv.id, inv.total_amount) == avail_payment_gross
                    or (
                        inv.buyer_name
                        and p.provider_order_id
                        and inv.buyer_name.lower() in p.provider_order_id.lower()
                    )
                )
            ]
            if len(candidate_invoices) > 1:
                # Multiple candidates match equally -> Abstain from auto-allocation!
                flag_discrepancy(
                    rule_id="RULE_AMBIGUOUS_CANDIDATE",
                    severity=DiscrepancySeverity.WARNING,
                    target_record_type="payment",
                    target_record_id=p.id,
                    target_field="gross_amount",
                    description=(
                        f"Ambiguous match: Payment {p.id} ({avail_payment_gross} {p.currency}) matches "
                        f"{len(candidate_invoices)} candidate invoices with identical criteria."
                    ),
                    compared_fields={
                        "payment_id": str(p.id),
                        "candidate_invoice_numbers": [
                            inv.invoice_number for inv in candidate_invoices
                        ],
                    },
                    recommended_action="Review buyer remittance advice to confirm intended invoice destination before allocating.",
                )
                propose_match(
                    match_type="invoice_payment",
                    match_status=MatchStatus.AMBIGUOUS,
                    rule_id="RULE_AMBIGUOUS_CANDIDATE",
                    allocated_amount=Decimal("0.0000"),
                    currency=p_curr,
                    payment_id=p.id,
                    compared_values={
                        "payment_amount": str(avail_payment_gross),
                        "candidate_invoices": [inv.invoice_number for inv in candidate_invoices],
                    },
                    severity=DiscrepancySeverity.WARNING,
                    notes="Ambiguous match abstention: 2+ candidate invoices match without distinguishing reference.",
                )
            elif len(candidate_invoices) == 1:
                # Single heuristic match candidate -> Propose with requires_human_review
                single_inv = candidate_invoices[0]
                propose_match(
                    match_type="invoice_payment",
                    match_status=MatchStatus.REQUIRES_HUMAN_REVIEW,
                    rule_id="RULE_HEURISTIC_MATCH",
                    allocated_amount=avail_payment_gross,
                    currency=p_curr,
                    invoice_id=single_inv.id,
                    payment_id=p.id,
                    compared_values={
                        "invoice_number": single_inv.invoice_number,
                        "payment_amount": str(avail_payment_gross),
                    },
                    severity=DiscrepancySeverity.WARNING,
                    notes="Heuristic match proposed based on amount/buyer similarity without explicit invoice reference.",
                )

    # -------------------------------------------------------------------------
    # Tier 4: Cash Flow Realization Chain Verification (Stages 2 -> 3 -> 4)
    # -------------------------------------------------------------------------
    # Stage 2 -> 3: Payments to Settlement Payout Batches
    for settle in settlements:
        settle_curr = validate_currency_code(settle.currency)
        batch_payments = [p for p in payments if p.settlement_id == settle.id]
        if batch_payments:
            sum_net_captures = sum((p.net_amount for p in batch_payments), Decimal("0.0000"))
            if sum_net_captures == settle.amount:
                flow_stages.append(
                    SettlementFlowStage(
                        stage_name="stage_2_to_3_provider_settlement",
                        status="verified",
                        description=f"Settlement batch {settle.provider_reference} ({settle.amount} {settle.currency}) matches sum of net captures.",
                        amount=settle.amount,
                        currency=settle_curr,
                        details={
                            "settlement_id": str(settle.id),
                            "payments_count": len(batch_payments),
                        },
                    )
                )
                propose_match(
                    match_type="flow_verification",
                    match_status=MatchStatus.MATCHED,
                    rule_id="RULE_SETTLEMENT_FLOW_VERIFIED",
                    allocated_amount=settle.amount,
                    currency=settle_curr,
                    settlement_id=settle.id,
                    compared_values={
                        "settlement_amount": str(settle.amount),
                        "sum_net_captures": str(sum_net_captures),
                    },
                    severity=DiscrepancySeverity.INFO,
                    notes="Settlement batch total verified against net captures.",
                )
            else:
                var = settle.amount - sum_net_captures
                flow_stages.append(
                    SettlementFlowStage(
                        stage_name="stage_2_to_3_provider_settlement",
                        status="mismatch",
                        description=f"Settlement batch {settle.provider_reference} variance of {var} {settle.currency}.",
                        amount=settle.amount,
                        currency=settle_curr,
                        details={"variance": str(var)},
                    )
                )
                flag_discrepancy(
                    rule_id="RULE_SETTLEMENT_BATCH_MISMATCH",
                    severity=DiscrepancySeverity.ERROR,
                    target_record_type="settlement",
                    target_record_id=settle.id,
                    target_field="amount",
                    description=f"Settlement batch {settle.provider_reference} amount ({settle.amount} {settle.currency}) does not equal sum of net captures ({sum_net_captures} {settle.currency}).",
                    calculation={
                        "settlement_amount": str(settle.amount),
                        "sum_net_captures": str(sum_net_captures),
                        "variance": str(var),
                    },
                    recommended_action="Audit provider payout breakdown report.",
                )

        # Stage 3 -> 4: Settlement to Bank Statement Line Credit
        if settle.bank_transaction_id:
            bank_line = next((bt for bt in bank_txns if bt.id == settle.bank_transaction_id), None)
            if bank_line:
                if (
                    bank_line.amount == settle.amount
                    and bank_line.currency.upper() == settle.currency.upper()
                ):
                    flow_stages.append(
                        SettlementFlowStage(
                            stage_name="stage_3_to_4_bank_deposit",
                            status="verified",
                            description=f"Bank statement line {bank_line.bank_reference} ({bank_line.amount} {bank_line.currency}) verifies settlement deposit.",
                            amount=bank_line.amount,
                            currency=settle_curr,
                            details={"bank_reference": bank_line.bank_reference},
                        )
                    )
                    propose_match(
                        match_type="flow_verification",
                        match_status=MatchStatus.MATCHED,
                        rule_id="RULE_BANK_DEPOSIT_VERIFIED",
                        allocated_amount=bank_line.amount,
                        currency=settle_curr,
                        settlement_id=settle.id,
                        bank_transaction_id=bank_line.id,
                        compared_values={
                            "bank_amount": str(bank_line.amount),
                            "settlement_amount": str(settle.amount),
                        },
                        severity=DiscrepancySeverity.INFO,
                        notes="Bank deposit clearance verified against settlement payout batch.",
                    )
                else:
                    var = bank_line.amount - settle.amount
                    flag_discrepancy(
                        rule_id="RULE_SETTLEMENT_BANK_AMOUNT_MISMATCH",
                        severity=DiscrepancySeverity.ERROR,
                        target_record_type="bank_transaction",
                        target_record_id=bank_line.id,
                        target_field="amount",
                        description=f"Bank statement credit ({bank_line.amount} {bank_line.currency}) differs from settlement batch ({settle.amount} {settle.currency}).",
                        calculation={
                            "bank_amount": str(bank_line.amount),
                            "settlement_amount": str(settle.amount),
                            "variance": str(var),
                        },
                        recommended_action="Audit intermediate bank wire fees or FX conversion spread.",
                    )

    # -------------------------------------------------------------------------
    # Tier 5: Bank Statement Unmatched Credit Check
    # -------------------------------------------------------------------------
    for bt in bank_txns:
        if bt.transaction_type == BankTransactionType.CREDIT:
            bt_curr = validate_currency_code(bt.currency)
            # Check if linked to settlement or payment
            is_linked = any(s.bank_transaction_id == bt.id for s in settlements)
            if not is_linked:
                flag_discrepancy(
                    rule_id="RULE_UNMATCHED_BANK_CREDIT",
                    severity=DiscrepancySeverity.WARNING,
                    target_record_type="bank_transaction",
                    target_record_id=bt.id,
                    target_field="amount",
                    description=f"Standalone bank statement credit of {bt.amount} {bt.currency} (ref: {bt.bank_reference}) has no matching settlement or invoice payment.",
                    compared_fields={
                        "bank_reference": bt.bank_reference,
                        "amount": str(bt.amount),
                        "remittance_reference": bt.remittance_reference,
                    },
                    recommended_action="Reconcile with pending export transactions or identify wire remitter.",
                )
                propose_match(
                    match_type="bank_credit_unmatched",
                    match_status=MatchStatus.UNMATCHED,
                    rule_id="RULE_UNMATCHED_BANK_CREDIT",
                    allocated_amount=Decimal("0.0000"),
                    currency=bt_curr,
                    bank_transaction_id=bt.id,
                    compared_values={
                        "bank_reference": bt.bank_reference,
                        "amount": str(bt.amount),
                    },
                    severity=DiscrepancySeverity.WARNING,
                    notes="Unmatched bank credit: no corresponding settlement batch found.",
                )

    # -------------------------------------------------------------------------
    # Tier 6: Final Remaining Unexplained Receivables Check
    # -------------------------------------------------------------------------
    for inv in invoices:
        rem = invoice_balances.get(inv.id, inv.total_amount)
        if rem > Decimal("0.0000"):
            flag_discrepancy(
                rule_id="RULE_REMAINING_UNEXPLAINED_BALANCE",
                severity=DiscrepancySeverity.WARNING,
                target_record_type="invoice",
                target_record_id=inv.id,
                target_field="total_amount",
                description=f"Invoice '{inv.invoice_number}' has remaining unsettled receivable balance of {rem} {inv.currency}.",
                compared_fields={
                    "invoice_number": inv.invoice_number,
                    "invoice_total": str(inv.total_amount),
                    "remaining_balance": str(rem),
                },
                recommended_action="Follow up with buyer for pending payment or file credit memo.",
            )

    # -------------------------------------------------------------------------
    # Tier 7: Supersede Stale Proposals & Resolve Cleared Discrepancies
    # -------------------------------------------------------------------------
    # Stale proposed matches no longer generated in this run: mark SUPERSEDED (no deletion)
    for m in existing_matches:
        if (
            m.business_key not in generated_match_keys
            and m.review_status == AllocationReviewStatus.SUGGESTED
        ):
            m.review_status = AllocationReviewStatus.SUPERSEDED
            m.notes = f"Superseded by reconciliation run {run_id}."
            m.updated_at = now_utc

    # Stale open discrepancies resolved by new data: mark RESOLVED (no deletion)
    for d in existing_discrepancies:
        if d.business_key not in generated_disc_keys and d.status == DiscrepancyStatus.OPEN:
            d.status = DiscrepancyStatus.RESOLVED
            d.recommended_action = f"Resolved automatically by reconciliation run {run_id}."
            d.updated_at = now_utc

    # Commit all state changes atomically
    db.commit()

    # Re-fetch active records to produce response
    refreshed_matches = (
        db.query(ReconciliationMatch)
        .filter(
            ReconciliationMatch.export_transaction_id == transaction_id,
            ReconciliationMatch.review_status != AllocationReviewStatus.SUPERSEDED,
        )
        .all()
    )
    refreshed_discrepancies = (
        db.query(Discrepancy)
        .filter(
            Discrepancy.export_transaction_id == transaction_id,
            Discrepancy.status.in_([DiscrepancyStatus.OPEN, DiscrepancyStatus.ACKNOWLEDGED]),
        )
        .all()
    )

    # Construct summary
    total_invoice_amount = sum((inv.total_amount for inv in invoices), Decimal("0.0000"))
    total_approved_allocated = sum(
        (a.allocated_amount for a in approved_allocations if not a.is_reversal),
        Decimal("0.0000"),
    ) - sum(
        (a.allocated_amount for a in approved_allocations if a.is_reversal),
        Decimal("0.0000"),
    )

    summary = {
        "invoices_count": len(invoices),
        "payments_count": len(payments),
        "total_invoice_receivable": str(total_invoice_amount),
        "total_approved_allocated": str(total_approved_allocated),
        "open_discrepancies_count": len(refreshed_discrepancies),
        "has_critical_errors": any(
            d.severity in (DiscrepancySeverity.ERROR, DiscrepancySeverity.CRITICAL)
            for d in refreshed_discrepancies
        ),
    }

    return ReconciliationRunResponse(
        transaction_id=transaction_id,
        reconciliation_run_id=run_id,
        reconciled_at=now_utc,
        status=tx.status,
        matches_count=len(refreshed_matches),
        discrepancies_count=len(refreshed_discrepancies),
        matches=[ReconciliationMatchRead.model_validate(m) for m in refreshed_matches],
        discrepancies=[DiscrepancyRead.model_validate(d) for d in refreshed_discrepancies],
        settlement_flow_chain=flow_stages,
        summary=summary,
    )


def apply_match_decision(
    db: Session,
    match_id: uuid.UUID,
    payload: MatchDecisionRequest,
) -> ReconciliationMatchRead:
    """
    Applies an authorized human reviewer decision to a proposed reconciliation match.

    Enforces strict concurrency and accounting rules:
    - Row-level SELECT ... FOR UPDATE locks on both Match and Invoice.
    - Constraint 1: Creates official Allocation rows ONLY for approved invoice-payment allocations
      or approved compensating reversals (match_type in ("invoice_payment", "payment_reversal")).
      Approving a flow-check or document-consistency match does NOT create an Allocation.
    - Re-evaluates remaining invoice balance under the lock to prevent over-allocation.
    - Writes an immutable HumanDecision audit entry.
    - Transitions ExportTransaction.status to RECONCILED only when all required invoices are
      100% satisfied with approved allocations and zero error discrepancies remain.
    """
    now_utc = datetime.now(UTC)

    # 1. Acquire row lock on match
    match = (
        db.query(ReconciliationMatch)
        .filter(ReconciliationMatch.id == match_id)
        .with_for_update()
        .first()
    )
    if not match:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reconciliation match '{match_id}' not found.",
        )

    # Idempotent check
    if match.review_status == AllocationReviewStatus.APPROVED:
        if payload.decision == DecisionType.APPROVED:
            return ReconciliationMatchRead.model_validate(match)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Match is already approved. Conflicting decision rejected.",
        )
    if match.review_status == AllocationReviewStatus.REJECTED:
        if payload.decision == DecisionType.REJECTED:
            return ReconciliationMatchRead.model_validate(match)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Match is already rejected. Conflicting decision rejected.",
        )
    if match.review_status == AllocationReviewStatus.SUPERSEDED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot apply decision to a superseded match proposal. Please review the latest reconciliation run.",
        )

    # 2. Acquire row lock on invoice if this match targets an invoice
    target_inv: Invoice | None = None
    if match.invoice_id:
        target_inv = (
            db.query(Invoice).filter(Invoice.id == match.invoice_id).with_for_update().first()
        )
        if not target_inv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Target invoice '{match.invoice_id}' not found.",
            )

    # 3. Process approval or rejection
    if payload.decision == DecisionType.APPROVED:
        match.review_status = AllocationReviewStatus.APPROVED
        match.notes = payload.notes

        # Constraint 1: Create Allocation rows ONLY for approved invoice-payment allocations or approved compensating reversals
        if (
            match.match_type in ("invoice_payment", "payment_reversal")
            and target_inv
            and match.allocated_amount > Decimal("0.0000")
        ):
            # Re-verify remaining balance under the lock to prevent concurrent over-allocation
            existing_inv_allocs = [
                a
                for a in target_inv.allocations
                if a.review_status == AllocationReviewStatus.APPROVED
            ]
            current_credit = sum(
                (a.allocated_amount for a in existing_inv_allocs if not a.is_reversal),
                Decimal("0.0000"),
            )
            current_reversal = sum(
                (a.allocated_amount for a in existing_inv_allocs if a.is_reversal),
                Decimal("0.0000"),
            )
            net_settled = current_credit - current_reversal

            if not match.is_reversal and (
                net_settled + match.allocated_amount > target_inv.total_amount
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Approved allocation of {match.allocated_amount} {match.currency} would exceed "
                        f"remaining balance on invoice {target_inv.invoice_number} (net settled: {net_settled}, total: {target_inv.total_amount})."
                    ),
                )

            # Create official Allocation row
            alloc = Allocation(
                invoice_id=target_inv.id,
                payment_id=match.payment_id,
                settlement_id=match.settlement_id,
                bank_transaction_id=match.bank_transaction_id,
                allocated_amount=match.allocated_amount,
                is_reversal=match.is_reversal,
                currency=match.currency,
                allocation_method=AllocationMethod.AUTO_EXACT
                if match.rule_id == "RULE_EXACT_REFERENCE_MATCH"
                else AllocationMethod.MANUAL_HUMAN,
                evidence_notes=payload.notes
                or f"Human decision approval by {payload.reviewer_label}",
                review_status=AllocationReviewStatus.APPROVED,
                is_demo=match.is_demo,
            )
            db.add(alloc)
            db.flush()
            match.allocation_id = alloc.id

            # Create evidence reference connecting allocation to match
            ev_ref = EvidenceReference(
                allocation_id=alloc.id,
                match_id=match.id,
                source_record_type="reconciliation_match",
                source_record_id=match.id,
                raw_value=str(match.allocated_amount),
                normalized_value=str(match.allocated_amount),
                extraction_method=ExtractionMethod.MANUAL,
                review_state=ReviewState.HUMAN_VERIFIED,
            )
            db.add(ev_ref)

    else:
        # Rejected
        match.review_status = AllocationReviewStatus.REJECTED
        match.notes = payload.notes

    # 4. Record immutable HumanDecision audit entry
    decision_log = HumanDecision(
        target_type=TargetType.RECONCILIATION_MATCH,
        target_id=match.id,
        decision=payload.decision,
        reviewer_label=payload.reviewer_label,
        notes=payload.notes,
        decided_at=now_utc,
    )
    db.add(decision_log)

    # 5. Evaluate if transaction should transition to RECONCILED
    tx = (
        db.query(ExportTransaction)
        .filter(ExportTransaction.id == match.export_transaction_id)
        .first()
    )
    if tx:
        # Check all invoices for transaction
        all_invoices = tx.invoices
        all_settled = True
        for inv in all_invoices:
            inv_allocs = (
                db.query(Allocation)
                .filter(
                    Allocation.invoice_id == inv.id,
                    Allocation.review_status == AllocationReviewStatus.APPROVED,
                )
                .all()
            )
            tot_cr = sum(
                (a.allocated_amount for a in inv_allocs if not a.is_reversal), Decimal("0.0000")
            )
            tot_rev = sum(
                (a.allocated_amount for a in inv_allocs if a.is_reversal), Decimal("0.0000")
            )
            if tot_cr - tot_rev < inv.total_amount:
                all_settled = False
                break

        # Check for open error or critical discrepancies
        open_errors = (
            db.query(Discrepancy)
            .filter(
                Discrepancy.export_transaction_id == tx.id,
                Discrepancy.status.in_([DiscrepancyStatus.OPEN, DiscrepancyStatus.ACKNOWLEDGED]),
                Discrepancy.severity.in_([DiscrepancySeverity.ERROR, DiscrepancySeverity.CRITICAL]),
            )
            .count()
        )

        if all_settled and open_errors == 0 and len(all_invoices) > 0:
            tx.status = TransactionStatus.RECONCILED
        elif open_errors > 0:
            tx.status = TransactionStatus.DISCREPANT
        else:
            tx.status = TransactionStatus.IN_PROGRESS

    match.updated_at = now_utc
    db.commit()
    db.refresh(match)
    return ReconciliationMatchRead.model_validate(match)
