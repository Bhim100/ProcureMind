"""FastAPI router for the consolidated Reconciliation Queue (Phase 11)."""

import math
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.models.enums import (
    AllocationReviewStatus,
    DiscrepancyStatus,
    MatchStatus,
    TransactionStatus,
)
from app.models.export import ExportTransaction
from app.models.reconciliation import Discrepancy, EvidenceReference, ReconciliationMatch
from app.models.relationship import TransactionLink
from app.schemas.reconciliation_queue import (
    DiscrepancyItemSummary,
    EvidenceItemSummary,
    MatchSummaryItem,
    ReconciliationQueueResponse,
    ReconciliationQueueRow,
    TransactionInvoiceSummary,
    TransactionPaymentSummary,
)

router = APIRouter()


@router.get(
    "/queue",
    response_model=ReconciliationQueueResponse,
    summary="Paginated consolidated reconciliation queue",
)
def get_reconciliation_queue(
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(25, ge=1, le=100, description="Items per page"),
    review_status: AllocationReviewStatus | None = Query(
        None, description="Filter transactions having matches with review status"
    ),
    match_status: MatchStatus | None = Query(
        None, description="Filter transactions having matches with match status"
    ),
    is_demo: bool | None = Query(None, description="Filter demo records"),
    search: str | None = Query(None, description="Search reference or buyer name"),
    db: Session = Depends(get_db),
) -> ReconciliationQueueResponse:
    """
    Returns consolidated transaction-level reconciliation queue rows.

    Uses two-stage pagination (paging root transactions first, then eager-loading
    child collections via selectinload) to prevent Cartesian join multiplication.
    Zero-match transactions are clearly surfaced as 'No match yet'.
    """
    base_query = db.query(ExportTransaction)

    if is_demo is not None:
        base_query = base_query.filter(ExportTransaction.is_demo == is_demo)

    if search:
        search_pattern = f"%{search.strip()}%"
        base_query = base_query.filter(
            (ExportTransaction.transaction_reference.ilike(search_pattern))
            | (ExportTransaction.buyer_name.ilike(search_pattern))
        )

    if review_status:
        match_tx_subquery = (
            db.query(ReconciliationMatch.export_transaction_id)
            .filter(
                ReconciliationMatch.review_status == review_status,
                ReconciliationMatch.review_status != AllocationReviewStatus.SUPERSEDED,
            )
            .distinct()
        )
        base_query = base_query.filter(ExportTransaction.id.in_(match_tx_subquery))

    if match_status:
        match_st_subquery = (
            db.query(ReconciliationMatch.export_transaction_id)
            .filter(
                ReconciliationMatch.match_status == match_status,
                ReconciliationMatch.review_status != AllocationReviewStatus.SUPERSEDED,
            )
            .distinct()
        )
        base_query = base_query.filter(ExportTransaction.id.in_(match_st_subquery))

    total_count = base_query.count()
    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 1

    # Stage 1 & 2: Paginate transactions with selectinload for child collections
    tx_query = (
        base_query.options(
            selectinload(ExportTransaction.invoices),
            selectinload(ExportTransaction.payments),
            selectinload(ExportTransaction.matches)
            .selectinload(ReconciliationMatch.evidence_references)
            .selectinload(EvidenceReference.document),
            selectinload(ExportTransaction.discrepancies)
            .selectinload(Discrepancy.evidence_references)
            .selectinload(EvidenceReference.document),
            selectinload(ExportTransaction.links)
            .selectinload(TransactionLink.evidence_references)
            .selectinload(EvidenceReference.document),
        )
        .order_by(
            # Discrepant transactions first, then newest
            ExportTransaction.status.desc(),
            ExportTransaction.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )

    transactions = tx_query.all()

    items: list[ReconciliationQueueRow] = []
    for tx in transactions:
        active_matches = [
            m for m in tx.matches if m.review_status != AllocationReviewStatus.SUPERSEDED
        ]
        active_discrepancies = [
            d
            for d in tx.discrepancies
            if d.status in (DiscrepancyStatus.OPEN, DiscrepancyStatus.ACKNOWLEDGED)
        ]

        # Calculate requires_human_review strictly from actual statuses
        requires_human_review = (
            tx.status == TransactionStatus.DISCREPANT
            or len(active_discrepancies) > 0
            or any(
                m.review_status == AllocationReviewStatus.SUGGESTED
                or m.match_status == MatchStatus.REQUIRES_HUMAN_REVIEW
                for m in active_matches
            )
        )

        # Determine user-friendly status label
        if not active_matches:
            status_label = "No match yet"
        elif tx.status == TransactionStatus.DISCREPANT or len(active_discrepancies) > 0:
            status_label = "Discrepant"
        elif any(m.review_status == AllocationReviewStatus.SUGGESTED for m in active_matches):
            status_label = "Suggested match"
        elif tx.status == TransactionStatus.RECONCILED:
            status_label = "Reconciled"
        else:
            status_label = tx.status.value.replace("_", " ").title()

        # Invoices summary
        invoices_summary: list[TransactionInvoiceSummary] = []
        for inv in tx.invoices:
            invoices_summary.append(
                TransactionInvoiceSummary(
                    invoice_id=inv.id,
                    invoice_number=inv.invoice_number,
                    total_amount=str(inv.total_amount),
                    currency=inv.currency,
                    is_approved=False,  # Can be checked via approval if needed
                    remaining_balance=str(inv.total_amount),
                )
            )

        # Payments summary
        payments_summary: list[TransactionPaymentSummary] = []
        for pmt in tx.payments:
            payments_summary.append(
                TransactionPaymentSummary(
                    payment_id=pmt.id,
                    provider_order_id=pmt.provider_order_id,
                    provider_capture_id=pmt.provider_capture_id,
                    gross_amount=str(pmt.gross_amount),
                    currency=pmt.currency,
                    status=pmt.status.value,
                )
            )

        # Matches summary
        matches_summary: list[MatchSummaryItem] = []
        shortfall: str | None = None
        for m in active_matches:
            matches_summary.append(
                MatchSummaryItem(
                    match_id=m.id,
                    rule_id=m.rule_id,
                    match_type=m.match_type,
                    match_status=m.match_status,
                    review_status=m.review_status,
                    allocated_amount=str(m.allocated_amount),
                    currency=m.currency,
                    severity=m.severity,
                    calculation=m.calculation,
                    compared_values=m.compared_values,
                    created_at=m.created_at,
                )
            )
            if not shortfall and m.calculation and isinstance(m.calculation, dict):
                diff = m.calculation.get("unexplained_difference") or m.calculation.get("shortfall")
                if diff:
                    shortfall = str(abs(Decimal(str(diff))))

        # Discrepancies summary
        discrepancies_summary: list[DiscrepancyItemSummary] = []
        for d in active_discrepancies:
            diff_str: str | None = None
            if d.calculation and isinstance(d.calculation, dict):
                diff = d.calculation.get("unexplained_difference") or d.calculation.get("shortfall")
                if diff:
                    diff_str = str(abs(Decimal(str(diff))))
            discrepancies_summary.append(
                DiscrepancyItemSummary(
                    discrepancy_id=d.id,
                    rule_id=d.rule_id,
                    severity=d.severity.value,
                    status=d.status.value,
                    difference_amount=diff_str,
                    description=d.description,
                    recommended_action=d.recommended_action,
                )
            )
            if not shortfall and diff_str:
                shortfall = diff_str

        # Evidence references consolidation
        evidence_dict: dict[uuid.UUID, EvidenceItemSummary] = {}
        for m in active_matches:
            for ev in m.evidence_references:
                if ev.id not in evidence_dict and ev.document:
                    evidence_dict[ev.id] = EvidenceItemSummary(
                        evidence_id=ev.id,
                        document_id=ev.document.id,
                        document_title=ev.document.original_filename,
                        document_type=ev.document.document_type.value,
                        location_reference=ev.location_reference,
                        raw_snippet=ev.raw_value,
                    )
        for d in active_discrepancies:
            for ev in d.evidence_references:
                if ev.id not in evidence_dict and ev.document:
                    evidence_dict[ev.id] = EvidenceItemSummary(
                        evidence_id=ev.id,
                        document_id=ev.document.id,
                        document_title=ev.document.original_filename,
                        document_type=ev.document.document_type.value,
                        location_reference=ev.location_reference,
                        raw_snippet=ev.raw_value,
                    )
        for link in tx.links:
            for ev in link.evidence_references:
                if ev.id not in evidence_dict and ev.document:
                    evidence_dict[ev.id] = EvidenceItemSummary(
                        evidence_id=ev.id,
                        document_id=ev.document.id,
                        document_title=ev.document.original_filename,
                        document_type=ev.document.document_type.value,
                        location_reference=ev.location_reference,
                        raw_snippet=ev.raw_value,
                    )

        # Primary currency
        primary_currency = "USD"
        if tx.invoices:
            primary_currency = tx.invoices[0].currency
        elif tx.payments:
            primary_currency = tx.payments[0].currency

        items.append(
            ReconciliationQueueRow(
                transaction_id=tx.id,
                reference=tx.transaction_reference,
                buyer_name=tx.buyer_name,
                exporter_name=tx.exporter_name,
                status=tx.status.value,
                status_label=status_label,
                is_demo=tx.is_demo,
                currency=primary_currency,
                created_at=tx.created_at,
                updated_at=tx.updated_at,
                invoices=invoices_summary,
                payments=payments_summary,
                matches=matches_summary,
                discrepancies=discrepancies_summary,
                evidence_references=list(evidence_dict.values()),
                requires_human_review=requires_human_review,
                has_matches=len(active_matches) > 0,
                shortfall_amount=shortfall,
                active_match_count=len(active_matches),
                discrepancy_count=len(active_discrepancies),
                evidence_count=len(evidence_dict),
            )
        )

    return ReconciliationQueueResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
