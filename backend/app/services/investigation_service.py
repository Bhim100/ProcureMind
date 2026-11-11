"""
Investigation service for Phase 6: Grounded AI explanations strictly derived from
persisted PostgreSQL trade and financial records.

Guarantees:
- Strict transaction isolation: only records belonging to the requested transaction are queried.
- PII & security data minimization: no passwords, tokens, or raw unmasked account numbers sent.
- Discrepancy ownership verification: rejects foreign discrepancies with HTTP 400.
- Currency safety: pairs every financial value with currency; flags currency mismatches.
- Citation integrity: validates every cited UUID against the supplied context; filters hallucinations.
- Pure read-only execution: does not commit, add, or alter any database entity.
- Safe fallback: returns structured 'unavailable' response if LLM provider is unconfigured or fails.
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.models.enums import DiscrepancyStatus, TransactionStatus
from app.models.export import ExportTransaction, Invoice, ShippingBill
from app.models.payment import BankTransaction, Payment, Settlement
from app.models.reconciliation import Discrepancy, ReconciliationMatch
from app.schemas.investigation import (
    AuthoritativeFinancialFacts,
    InvestigationResponse,
    LLMInvestigationOutput,
    MonetaryAmount,
)
from app.services.llm.factory import get_llm_provider
from app.services.llm.interface import LLMProviderInterface
from app.services.relationship_service import get_transaction_by_id_or_reference

logger = logging.getLogger(__name__)


def _mask_account(raw: str | None) -> str | None:
    """Masks financial account references, leaving only the last 4 digits visible."""
    if not raw:
        return None
    clean = str(raw).strip()
    if len(clean) <= 4:
        return "****"
    return f"****{clean[-4:]}"


def build_transaction_context(
    db: Session, tx: ExportTransaction
) -> tuple[dict[str, Any], set[uuid.UUID], AuthoritativeFinancialFacts]:
    """
    Extracts transaction-isolated records from PostgreSQL, sanitizes sensitive data,
    computes authoritative financial facts, and catalogs all valid entity UUIDs.
    """
    valid_context_ids: set[uuid.UUID] = {tx.id}

    # 1. Query records strictly scoped to this transaction
    invoices = (
        db.query(Invoice)
        .filter(Invoice.export_transaction_id == tx.id)
        .order_by(Invoice.created_at.asc())
        .all()
    )
    shipping_bills = (
        db.query(ShippingBill)
        .filter(ShippingBill.export_transaction_id == tx.id)
        .order_by(ShippingBill.created_at.asc())
        .all()
    )
    payments = (
        db.query(Payment)
        .filter(Payment.export_transaction_id == tx.id)
        .order_by(Payment.created_at.asc())
        .all()
    )
    settlements = (
        db.query(Settlement)
        .filter(Settlement.export_transaction_id == tx.id)
        .order_by(Settlement.created_at.asc())
        .all()
    )
    bank_txs = (
        db.query(BankTransaction)
        .filter(BankTransaction.export_transaction_id == tx.id)
        .order_by(BankTransaction.created_at.asc())
        .all()
    )
    matches = (
        db.query(ReconciliationMatch)
        .filter(ReconciliationMatch.export_transaction_id == tx.id)
        .order_by(ReconciliationMatch.created_at.asc())
        .all()
    )
    discrepancies = (
        db.query(Discrepancy)
        .options(selectinload(Discrepancy.evidence_references))
        .filter(Discrepancy.export_transaction_id == tx.id)
        .order_by(Discrepancy.created_at.asc())
        .all()
    )

    # 2. Record IDs cataloging
    for inv in invoices:
        valid_context_ids.add(inv.id)
    for sb in shipping_bills:
        valid_context_ids.add(sb.id)
    for pay in payments:
        valid_context_ids.add(pay.id)
    for stl in settlements:
        valid_context_ids.add(stl.id)
    for bt in bank_txs:
        valid_context_ids.add(bt.id)
    for m in matches:
        valid_context_ids.add(m.id)
    for d in discrepancies:
        valid_context_ids.add(d.id)
        for ev in d.evidence_references:
            valid_context_ids.add(ev.id)

    # 3. Currency-safe Authoritative Financial Facts extraction
    currencies_found: set[str] = set()
    invoice_currency: str | None = None
    payment_currency: str | None = None

    inv_total_amount: Decimal | None = None
    if invoices:
        primary_inv = invoices[0]
        inv_total_amount = primary_inv.total_amount
        invoice_currency = primary_inv.currency
        currencies_found.add(primary_inv.currency)

    pay_gross_amount: Decimal | None = None
    fee_amount: Decimal | None = None
    net_amount: Decimal | None = None
    if payments:
        primary_pay = payments[0]
        pay_gross_amount = primary_pay.gross_amount
        fee_amount = primary_pay.fee_amount
        net_amount = primary_pay.net_amount
        payment_currency = primary_pay.currency
        currencies_found.add(primary_pay.currency)

    for sb in shipping_bills:
        currencies_found.add(sb.declared_currency)
    for bt in bank_txs:
        currencies_found.add(bt.currency)

    currencies_match = len(currencies_found) <= 1
    mismatch_warning: str | None = None
    if not currencies_match:
        mismatch_warning = (
            f"Cross-currency detected in transaction: {sorted(currencies_found)}. "
            f"ProcureMind strictly prohibits silent currency arithmetic or subtraction across currencies."
        )

    # Unexplained difference from active discrepancy
    unexplained_diff: Decimal | None = None
    calc_breakdown: dict[str, Any] | None = None
    open_disc_count = 0

    for d in discrepancies:
        if d.status in (DiscrepancyStatus.OPEN, DiscrepancyStatus.ACKNOWLEDGED):
            open_disc_count += 1
            persisted_calculation = d.calculation or d.compared_fields or {}
            remainder_value = persisted_calculation.get(
                "unexplained_remainder", persisted_calculation.get("shortfall")
            )
            if remainder_value is not None:
                try:
                    unexplained_diff = Decimal(str(remainder_value))
                    calc_breakdown = persisted_calculation
                except (InvalidOperation, TypeError, ValueError):
                    pass

    is_reconciled = tx.status == TransactionStatus.RECONCILED and open_disc_count == 0

    auth_facts = AuthoritativeFinancialFacts(
        invoice_total=(
            MonetaryAmount(amount=inv_total_amount, currency=invoice_currency or "USD")
            if inv_total_amount is not None
            else None
        ),
        payment_gross=(
            MonetaryAmount(amount=pay_gross_amount, currency=payment_currency or "USD")
            if pay_gross_amount is not None
            else None
        ),
        fee_amount=(
            MonetaryAmount(amount=fee_amount, currency=payment_currency or "USD")
            if fee_amount is not None
            else None
        ),
        net_amount=(
            MonetaryAmount(amount=net_amount, currency=payment_currency or "USD")
            if net_amount is not None
            else None
        ),
        unexplained_difference=(
            MonetaryAmount(
                amount=unexplained_diff,
                currency=str(
                    (calc_breakdown or {}).get("currency")
                    or invoice_currency
                    or payment_currency
                    or "USD"
                ),
            )
            if unexplained_diff is not None
            else None
        ),
        currencies_match=currencies_match,
        currency_mismatch_warning=mismatch_warning,
        calculation_breakdown=calc_breakdown,
        is_reconciled=is_reconciled,
        open_discrepancy_count=open_disc_count,
    )

    # 4. Assembled sanitized context for LLM prompt
    context: dict[str, Any] = {
        "transaction_id": str(tx.id),
        "transaction_reference": tx.transaction_reference,
        "exporter_name": tx.exporter_name,
        "buyer_name": tx.buyer_name,
        "status": tx.status.value,
        "invoices": [
            {
                "id": str(i.id),
                "invoice_number": i.invoice_number,
                "currency": i.currency,
                "total_amount": str(i.total_amount),
                "issue_date": str(i.issue_date) if i.issue_date else None,
            }
            for i in invoices
        ],
        "shipping_bills": [
            {
                "id": str(sb.id),
                "shipping_bill_number": sb.shipping_bill_number,
                "declared_currency": sb.declared_currency,
                "declared_value": str(sb.declared_value),
                "bill_date": str(sb.bill_date) if sb.bill_date else None,
            }
            for sb in shipping_bills
        ],
        "payments": [
            {
                "id": str(p.id),
                "provider": p.provider,
                "currency": p.currency,
                "gross_amount": str(p.gross_amount),
                "fee_amount": str(p.fee_amount) if p.fee_amount is not None else None,
                "net_amount": str(p.net_amount) if p.net_amount is not None else None,
                "status": p.status.value,
                "environment": p.environment.value,
                "description": p.description,
            }
            for p in payments
        ],
        "settlements": [
            {
                "id": str(s.id),
                "currency": s.currency,
                "amount": str(s.amount),
                "settlement_date": str(s.settlement_date) if s.settlement_date else None,
                "status": s.status,
            }
            for s in settlements
        ],
        "bank_transactions": [
            {
                "id": str(b.id),
                "currency": b.currency,
                "amount": str(b.amount),
                "transaction_date": str(b.transaction_date) if b.transaction_date else None,
                "status": b.status.value,
                "remittance_reference": _mask_account(b.remittance_reference),
            }
            for b in bank_txs
        ],
        "reconciliation_matches": [
            {
                "id": str(m.id),
                "match_type": m.match_type,
                "match_status": m.match_status.value,
                "review_status": m.review_status.value,
                "allocated_amount": str(m.allocated_amount),
                "is_reversal": m.is_reversal,
            }
            for m in matches
        ],
        "discrepancies": [
            {
                "id": str(d.id),
                "severity": d.severity.value,
                "status": d.status.value,
                "description": d.description,
                "compared_fields": d.compared_fields,
                "calculation": d.calculation,
                "recommended_action": d.recommended_action,
                "evidence_references": [
                    {
                        "id": str(ev.id),
                        "source_record_type": ev.source_record_type,
                        "location_reference": ev.location_reference,
                    }
                    for ev in d.evidence_references
                ],
            }
            for d in discrepancies
        ],
    }

    return context, valid_context_ids, auth_facts


async def investigate_transaction(
    db: Session,
    identifier: str | uuid.UUID,
    question: str,
    discrepancy_id: uuid.UUID | None = None,
    provider_override: LLMProviderInterface | None = None,
) -> InvestigationResponse:
    """
    Sole authorized handler for transaction investigation inquiries.
    Executes in pure read-only mode and guarantees safety constraints.
    """
    # 1. Resolve transaction by UUID or reference (404 if not found)
    tx = get_transaction_by_id_or_reference(db, identifier)

    # 2. Validate discrepancy ownership if discrepancy_id supplied
    if discrepancy_id is not None:
        disc = (
            db.query(Discrepancy)
            .filter(
                Discrepancy.id == discrepancy_id,
                Discrepancy.export_transaction_id == tx.id,
            )
            .first()
        )
        if not disc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Discrepancy '{discrepancy_id}' does not belong to transaction "
                    f"'{tx.transaction_reference}' ({tx.id})"
                ),
            )

    # 3. Extract transaction context, valid citation IDs, and authoritative facts
    context, valid_context_ids, auth_facts = build_transaction_context(db, tx)

    warnings: list[str] = []
    if auth_facts.currency_mismatch_warning:
        warnings.append(auth_facts.currency_mismatch_warning)

    # 4. Resolve provider
    provider = provider_override or get_llm_provider()
    provider_name = (
        getattr(provider, "provider_name", type(provider).__name__) if provider else "unavailable"
    )

    # 5. Safe unavailable fallback if provider is unconfigured
    if provider is None:
        return InvestigationResponse(
            transaction_id=tx.id,
            transaction_reference=tx.transaction_reference,
            discrepancy_id=discrepancy_id,
            status="unavailable",
            explanation=(
                f"AI explanation service is currently unavailable for transaction {tx.transaction_reference}. "
                f"No LLM provider credentials are configured. Please review the authoritative financial calculations "
                f"and persisted records directly."
            ),
            authoritative_facts=auth_facts,
            cited_record_ids=[],
            missing_information=["AI provider credentials (LLM_API_KEY)"],
            suggested_next_action="Inspect the authoritative financial facts and discrepancies directly in the workspace.",
            draft_clarification_message=None,
            requires_human_review=True,
            provider="unavailable",
            warnings=warnings,
        )

    # 6. Execute model call with safe error capture
    try:
        model_output: LLMInvestigationOutput = await provider.investigate(
            question=question,
            context=context,
            discrepancy_id=discrepancy_id,
        )
    except Exception as exc:  # noqa: BLE001 - provider failures must return a safe fallback
        # Exception text can contain request URLs, credentials, or response bodies.
        logger.warning(
            "Investigation provider failed for transaction %s (%s)",
            tx.id,
            type(exc).__name__,
        )
        return InvestigationResponse(
            transaction_id=tx.id,
            transaction_reference=tx.transaction_reference,
            discrepancy_id=discrepancy_id,
            status="unavailable",
            explanation=(
                f"The AI investigation provider encountered an error while analyzing transaction "
                f"{tx.transaction_reference}: {type(exc).__name__}. Authoritative records remain secure."
            ),
            authoritative_facts=auth_facts,
            cited_record_ids=[],
            missing_information=["External AI service response"],
            suggested_next_action="Review discrepancies and reconciliation calculations manually.",
            draft_clarification_message=None,
            requires_human_review=True,
            provider=provider_name,
            warnings=warnings + [f"Provider failure ({type(exc).__name__}); details omitted."],
        )

    # 7. Citation validation: filter cited UUIDs strictly against valid_context_ids
    validated_cited_uuids: list[uuid.UUID] = []
    dropped_citations: list[str] = []

    for raw_id in model_output.cited_record_ids:
        try:
            parsed_uuid = uuid.UUID(str(raw_id).strip())
            if parsed_uuid in valid_context_ids:
                if parsed_uuid not in validated_cited_uuids:
                    validated_cited_uuids.append(parsed_uuid)
            else:
                dropped_citations.append(str(raw_id))
        except ValueError:
            dropped_citations.append(str(raw_id))

    if dropped_citations:
        warnings.append(
            f"Omitted {len(dropped_citations)} unrecognized or unverified citation(s) returned by model."
        )

    # 8. Determine final resolution status
    response_status = "refusal" if model_output.policy_refusal else "success"

    return InvestigationResponse(
        transaction_id=tx.id,
        transaction_reference=tx.transaction_reference,
        discrepancy_id=discrepancy_id,
        status=response_status,
        explanation=model_output.explanation,
        authoritative_facts=auth_facts,
        cited_record_ids=validated_cited_uuids,
        missing_information=model_output.missing_information,
        suggested_next_action=model_output.suggested_next_action,
        draft_clarification_message=model_output.draft_clarification_message,
        requires_human_review=True,  # Always enforced by governance rule 3
        provider=provider_name,
        warnings=warnings,
    )
