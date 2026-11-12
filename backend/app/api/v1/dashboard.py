"""FastAPI router for the Overview Dashboard aggregates (Phase 11)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.document import Document
from app.models.enums import (
    AllocationReviewStatus,
    DiscrepancyStatus,
    EnvironmentLabel,
    PaymentStatus,
    TransactionStatus,
)
from app.models.export import ExportTransaction
from app.models.payment import Payment
from app.models.reconciliation import Discrepancy, ReconciliationMatch
from app.schemas.dashboard import (
    ActivityDataPoint,
    CurrencyVolume,
    DashboardSummaryResponse,
    DemoBreakdown,
)

router = APIRouter()


@router.get(
    "/summary",
    response_model=DashboardSummaryResponse,
    summary="Get authoritative overview dashboard summary from PostgreSQL",
)
def get_dashboard_summary(
    db: Session = Depends(get_db),
) -> DashboardSummaryResponse:
    """
    Computes authoritative counters, currency volumes, and demo breakdown directly from PostgreSQL.
    Strictly groups monetary totals by currency; never cross-sums different currencies.
    """
    # 1. Open transactions count
    open_records = (
        db.query(func.count(ExportTransaction.id))
        .filter(ExportTransaction.status != TransactionStatus.CLOSED)
        .scalar()
        or 0
    )

    # 2. Need review count
    discrepant_tx_subquery = (
        db.query(Discrepancy.export_transaction_id)
        .filter(Discrepancy.status.in_([DiscrepancyStatus.OPEN, DiscrepancyStatus.ACKNOWLEDGED]))
        .distinct()
    )
    suggested_match_tx_subquery = (
        db.query(ReconciliationMatch.export_transaction_id)
        .filter(ReconciliationMatch.review_status == AllocationReviewStatus.SUGGESTED)
        .distinct()
    )
    need_review_count = (
        db.query(func.count(ExportTransaction.id))
        .filter(
            (ExportTransaction.status == TransactionStatus.DISCREPANT)
            | (ExportTransaction.id.in_(discrepant_tx_subquery))
            | (ExportTransaction.id.in_(suggested_match_tx_subquery))
        )
        .scalar()
        or 0
    )

    # 3. Sandbox payments count
    sandbox_payments = (
        db.query(func.count(Payment.id))
        .filter(Payment.environment == EnvironmentLabel.SANDBOX)
        .scalar()
        or 0
    )

    # 4. Documents by status
    doc_status_rows = (
        db.query(Document.processing_status, func.count(Document.id))
        .group_by(Document.processing_status)
        .all()
    )
    documents_by_status = {status.value: count for status, count in doc_status_rows}

    # 5. Payments by currency (strictly grouped by currency)
    currency_rows = (
        db.query(
            Payment.currency,
            func.count(Payment.id),
            func.sum(Payment.gross_amount),
            func.sum(func.coalesce(Payment.fee_amount, Decimal("0.0000"))),
            func.sum(func.coalesce(Payment.net_amount, Payment.gross_amount)),
        )
        .filter(Payment.status == PaymentStatus.COMPLETED)
        .group_by(Payment.currency)
        .all()
    )
    payments_by_currency: list[CurrencyVolume] = []
    for curr, count, gross, fee, net in currency_rows:
        gross_dec = Decimal(str(gross or 0))
        fee_dec = Decimal(str(fee or 0))
        net_dec = Decimal(str(net or 0))
        payments_by_currency.append(
            CurrencyVolume(
                currency=curr,
                payment_count=count,
                total_gross=f"{gross_dec:.2f}",
                total_fee=f"{fee_dec:.2f}",
                total_net=f"{net_dec:.2f}",
            )
        )

    # 6. Demo vs Non-Demo Breakdown
    demo_tx = (
        db.query(func.count(ExportTransaction.id))
        .filter(ExportTransaction.is_demo.is_(True))
        .scalar()
        or 0
    )
    non_demo_tx = (
        db.query(func.count(ExportTransaction.id))
        .filter(ExportTransaction.is_demo.is_(False))
        .scalar()
        or 0
    )

    demo_doc = db.query(func.count(Document.id)).filter(Document.is_demo.is_(True)).scalar() or 0
    non_demo_doc = (
        db.query(func.count(Document.id)).filter(Document.is_demo.is_(False)).scalar() or 0
    )

    demo_pmt = db.query(func.count(Payment.id)).filter(Payment.is_demo.is_(True)).scalar() or 0
    non_demo_pmt = db.query(func.count(Payment.id)).filter(Payment.is_demo.is_(False)).scalar() or 0

    demo_breakdown = DemoBreakdown(
        demo_transactions=demo_tx,
        non_demo_transactions=non_demo_tx,
        demo_documents=demo_doc,
        non_demo_documents=non_demo_doc,
        demo_payments=demo_pmt,
        non_demo_payments=non_demo_pmt,
    )

    # 7. Recent activity (last 7 days grouped by date)
    today = datetime.now(UTC).date()
    activity: list[ActivityDataPoint] = []
    for day_offset in range(6, -1, -1):
        target_date = today - timedelta(days=day_offset)
        date_str = target_date.isoformat()
        next_date = target_date + timedelta(days=1)

        tx_count = (
            db.query(func.count(ExportTransaction.id))
            .filter(
                ExportTransaction.created_at >= target_date,
                ExportTransaction.created_at < next_date,
            )
            .scalar()
            or 0
        )
        matches_proposed = (
            db.query(func.count(ReconciliationMatch.id))
            .filter(
                ReconciliationMatch.created_at >= target_date,
                ReconciliationMatch.created_at < next_date,
            )
            .scalar()
            or 0
        )
        matches_approved = (
            db.query(func.count(ReconciliationMatch.id))
            .filter(
                ReconciliationMatch.review_status == AllocationReviewStatus.APPROVED,
                ReconciliationMatch.updated_at >= target_date,
                ReconciliationMatch.updated_at < next_date,
            )
            .scalar()
            or 0
        )
        payments_captured = (
            db.query(func.count(Payment.id))
            .filter(
                Payment.status == PaymentStatus.COMPLETED,
                Payment.created_at >= target_date,
                Payment.created_at < next_date,
            )
            .scalar()
            or 0
        )

        activity.append(
            ActivityDataPoint(
                date=date_str,
                transactions_created=tx_count,
                matches_proposed=matches_proposed,
                matches_approved=matches_approved,
                payments_captured=payments_captured,
            )
        )

    return DashboardSummaryResponse(
        open_records_count=open_records,
        need_review_count=need_review_count,
        sandbox_payments_count=sandbox_payments,
        documents_by_status=documents_by_status,
        payments_by_currency=payments_by_currency,
        demo_breakdown=demo_breakdown,
        recent_activity=activity,
    )
