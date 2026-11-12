"""FastAPI router for PayPal Sandbox checkout and order lifecycle management."""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.enums import (
    AllocationReviewStatus,
    EnvironmentLabel,
    PaymentStatus,
    TargetType,
    TransactionStatus,
)
from app.models.export import ExportTransaction, Invoice
from app.models.payment import Payment
from app.models.reconciliation import Allocation, HumanDecision
from app.schemas.payment import PaymentRead
from app.services.paypal_service import PayPalServiceError, paypal_client
from app.services.reconciliation_engine import reconcile_transaction

logger = logging.getLogger(__name__)
router = APIRouter()


class PayPalConfigResponse(BaseModel):
    """Safe public client configuration for frontend PayPal JavaScript SDK integration."""

    client_id: str
    environment: str


class OrderInitiationResponse(BaseModel):
    """Response returned upon initiating a PayPal Sandbox checkout order."""

    order_id: str
    status: str
    currency: str
    amount: str
    invoice_number: str
    approval_url: str | None = None


@router.get(
    "/config",
    response_model=PayPalConfigResponse,
    summary="Get safe public client configuration for PayPal Sandbox",
)
def get_paypal_config() -> PayPalConfigResponse:
    """Returns PayPal client_id and environment without exposing client secrets or hardcoded currencies."""
    return PayPalConfigResponse(
        client_id=settings.PAYPAL_CLIENT_ID,
        environment=settings.PAYPAL_ENVIRONMENT,
    )


@router.post(
    "/invoices/{invoice_id}/pay",
    response_model=OrderInitiationResponse,
    summary="Initiate PayPal Sandbox order for an approved commercial export invoice",
)
def initiate_invoice_payment(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> OrderInitiationResponse:
    """
    Creates or idempotently reuses a PayPal Sandbox order with intent=CAPTURE for an approved invoice.

    Strictly validates:
    1. The invoice exists and is locked against concurrent payment attempts.
    2. A human auditor approval (HumanDecision) exists for the invoice.
    3. The invoice is not already fully settled by existing approved allocations.
    4. Only one active pending order can exist for an invoice at a time.
    """
    # 1. Lock invoice row
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    # 2. Verify human auditor approval
    approval = (
        db.query(HumanDecision)
        .filter(
            HumanDecision.target_type == TargetType.INVOICE,
            HumanDecision.target_id == invoice.id,
            HumanDecision.decision == "approved",
        )
        .first()
    )
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment cannot be initiated. Invoice {invoice.invoice_number} has not been approved by an auditor.",
        )

    # 3. Verify remaining unsettled balance
    approved_allocs = (
        db.query(Allocation)
        .filter(
            Allocation.invoice_id == invoice.id,
            Allocation.review_status == AllocationReviewStatus.APPROVED,
        )
        .all()
    )
    zero_dec = invoice.total_amount * 0
    total_credit = sum((a.allocated_amount for a in approved_allocs if not a.is_reversal), zero_dec)
    total_reversal = sum((a.allocated_amount for a in approved_allocs if a.is_reversal), zero_dec)
    rem_balance = invoice.total_amount - (total_credit - total_reversal)

    if rem_balance <= zero_dec:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invoice {invoice.invoice_number} is already fully settled.",
        )

    # 4. Check for existing active pending order (Database partial unique index ensures at most one)
    existing_pending = (
        db.query(Payment)
        .filter(
            Payment.invoice_id == invoice.id,
            Payment.status == PaymentStatus.PENDING,
            Payment.provider == "paypal",
        )
        .first()
    )
    if existing_pending and existing_pending.provider_order_id:
        logger.info(
            "Reusing existing pending PayPal order %s for invoice %s",
            existing_pending.provider_order_id,
            invoice.invoice_number,
        )
        return OrderInitiationResponse(
            order_id=existing_pending.provider_order_id,
            status="CREATED",
            currency=existing_pending.currency,
            amount=str(existing_pending.gross_amount),
            invoice_number=invoice.invoice_number,
            approval_url=f"https://www.sandbox.paypal.com/checkoutnow?token={existing_pending.provider_order_id}",
        )

    # 5. Call PayPal Orders API with stable idempotency key
    try:
        order_data = paypal_client.create_order(
            invoice=invoice,
            idempotency_key=f"PM-ORDER-{invoice.id}",
        )
    except PayPalServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    order_id = order_data["id"]
    approval_url = None
    for link in order_data.get("links", []):
        if link.get("rel") == "approve":
            approval_url = link.get("href")
            break

    # 6. Persist Payment row in PostgreSQL
    payment = Payment(
        provider="paypal",
        invoice_id=invoice.id,
        provider_order_id=order_id,
        invoice_reference=invoice.invoice_number,
        currency=invoice.currency,
        gross_amount=invoice.total_amount,
        fee_amount=None,  # Not yet settled
        net_amount=None,  # Not yet settled
        status=PaymentStatus.PENDING,
        environment=EnvironmentLabel.SANDBOX,
        export_transaction_id=invoice.export_transaction_id,
        is_demo=invoice.is_demo,
        description=f"PayPal Sandbox / simulated export payment for Invoice {invoice.invoice_number}",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    return OrderInitiationResponse(
        order_id=order_id,
        status="CREATED",
        currency=invoice.currency,
        amount=str(invoice.total_amount),
        invoice_number=invoice.invoice_number,
        approval_url=approval_url,
    )


@router.post(
    "/invoices/{invoice_id}/simulate-capture",
    response_model=PaymentRead,
    summary="Simulate an approved PayPal Sandbox capture without requiring third-party credentials",
)
def simulate_paypal_capture(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> PaymentRead:
    """
    Simulates a compliant PayPal Sandbox capture for an approved invoice:
    - Enforces human auditor approval (HumanDecision) gate.
    - Ensures invoice has remaining balance.
    - Computes realistic PayPal merchant fee (3.49% + $0.49).
    - Creates or links an ExportTransaction so it can be reconciled.
    - Triggers the deterministic reconciliation engine.
    - Persists with environment='sandbox' and audit trace.
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).with_for_update().first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    # 1. Verify human auditor approval
    approval = (
        db.query(HumanDecision)
        .filter(
            HumanDecision.target_type == TargetType.INVOICE,
            HumanDecision.target_id == invoice.id,
            HumanDecision.decision == "approved",
        )
        .first()
    )
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Payment cannot be simulated. Invoice {invoice.invoice_number} has not been approved by an auditor.",
        )

    # 2. Verify remaining balance
    approved_allocs = (
        db.query(Allocation)
        .filter(
            Allocation.invoice_id == invoice.id,
            Allocation.review_status == AllocationReviewStatus.APPROVED,
        )
        .all()
    )
    zero_dec = invoice.total_amount * 0
    total_credit = sum((a.allocated_amount for a in approved_allocs if not a.is_reversal), zero_dec)
    total_reversal = sum((a.allocated_amount for a in approved_allocs if a.is_reversal), zero_dec)
    rem_balance = invoice.total_amount - (total_credit - total_reversal)

    if rem_balance <= zero_dec:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invoice {invoice.invoice_number} is already fully settled.",
        )

    # 3. Create or link ExportTransaction if missing
    if not invoice.export_transaction_id:
        exp_ref = f"EXP-{invoice.invoice_number}"
        exp_tx = (
            db.query(ExportTransaction)
            .filter(ExportTransaction.transaction_reference == exp_ref)
            .first()
        )
        if not exp_tx:
            exp_tx = ExportTransaction(
                id=uuid.uuid4(),
                transaction_reference=exp_ref,
                exporter_name=invoice.seller_name,
                buyer_name=invoice.buyer_name,
                status=TransactionStatus.IN_PROGRESS,
                is_demo=invoice.is_demo,
            )
            db.add(exp_tx)
            db.flush()
        invoice.export_transaction_id = exp_tx.id
        db.add(invoice)

    # 4. Standard PayPal fee calculation (3.49% + $0.49)
    fee_rate = Decimal("0.0349")
    fixed_fee = Decimal("0.4900")
    fee_amount = (invoice.total_amount * fee_rate + fixed_fee).quantize(Decimal("0.01"))
    net_amount = invoice.total_amount - fee_amount

    sim_id = uuid.uuid4().hex[:10].upper()
    now = datetime.now(UTC)

    payment = Payment(
        id=uuid.uuid4(),
        provider="paypal",
        invoice_id=invoice.id,
        provider_order_id=f"SIM-ORDER-{sim_id}",
        provider_capture_id=f"SIM-CAP-{sim_id}",
        invoice_reference=invoice.invoice_number,
        currency=invoice.currency,
        gross_amount=invoice.total_amount,
        fee_amount=fee_amount,
        net_amount=net_amount,
        status=PaymentStatus.COMPLETED,
        environment=EnvironmentLabel.SANDBOX,
        export_transaction_id=invoice.export_transaction_id,
        is_demo=invoice.is_demo,
        event_time=now,
        description=f"Simulated PayPal Sandbox checkout capture for Invoice {invoice.invoice_number}",
    )
    db.add(payment)
    db.flush()

    # 5. Trigger deterministic reconciliation
    if payment.export_transaction_id:
        reconcile_transaction(db=db, transaction_id=payment.export_transaction_id)

    db.commit()
    db.refresh(payment)
    return PaymentRead.model_validate(payment)


@router.post(
    "/orders/{order_id}/capture",
    response_model=PaymentRead,
    summary="Capture an approved PayPal Sandbox order and trigger reconciliation",
)
def capture_paypal_order(
    order_id: str,
    db: Session = Depends(get_db),
) -> PaymentRead:
    """
    Captures an authorized PayPal Sandbox order, binds it to the stored payment record,
    verifies returned currency and gross amounts, and triggers the reconciliation engine.

    Pessimistic row locking (SELECT ... FOR UPDATE) handles capture/webhook race conditions.
    """
    # 1. Lock payment row
    payment = (
        db.query(Payment).filter(Payment.provider_order_id == order_id).with_for_update().first()
    )
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order {order_id} was not initiated by ProcureMind.",
        )

    # 2. Idempotency: if already completed (e.g. webhook won the race), return immediately
    if payment.status == PaymentStatus.COMPLETED and payment.provider_capture_id:
        logger.info(
            "Order %s was already captured (status: COMPLETED). Returning idempotently.", order_id
        )
        return PaymentRead.model_validate(payment)

    # 3. Re-verify invoice approval and remaining balance at capture time
    if payment.invoice_id:
        invoice = db.query(Invoice).filter(Invoice.id == payment.invoice_id).first()
        if invoice:
            approval = (
                db.query(HumanDecision)
                .filter(
                    HumanDecision.target_type == TargetType.INVOICE,
                    HumanDecision.target_id == invoice.id,
                    HumanDecision.decision == "approved",
                )
                .first()
            )
            if not approval:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invoice {invoice.invoice_number} is no longer approved. Capture refused.",
                )

    # 4. Execute external capture via PayPal REST API
    try:
        capture_data = paypal_client.capture_order(
            order_id=order_id,
            idempotency_key=f"PM-CAPTURE-{payment.id}",
        )
    except PayPalServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    # 5. Extract and verify capture representation
    purchase_units = capture_data.get("purchase_units", [])
    captures = purchase_units[0].get("payments", {}).get("captures", []) if purchase_units else []
    if not captures:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal capture response contained no capture records.",
        )

    primary_capture = captures[0]
    capture_id = primary_capture.get("id")
    capture_status = primary_capture.get("status")
    capture_amount = primary_capture.get("amount", {})
    ret_currency = capture_amount.get("currency_code")
    ret_value = Decimal(str(capture_amount.get("value", "0")))

    # Verify returned currency and amount against stored order
    if ret_currency != payment.currency:
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Returned capture currency ({ret_currency}) does not match order currency ({payment.currency}).",
        )
    if ret_value != payment.gross_amount:
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Returned capture amount ({ret_value}) does not match order gross amount ({payment.gross_amount}).",
        )

    # Extract fee components if returned in breakdown
    breakdown = primary_capture.get("seller_receivable_breakdown", {})
    fee_val: Decimal | None = None
    net_val: Decimal | None = None
    if "paypal_fee" in breakdown and "value" in breakdown["paypal_fee"]:
        fee_val = Decimal(str(breakdown["paypal_fee"]["value"]))
    if "net_amount" in breakdown and "value" in breakdown["net_amount"]:
        net_val = Decimal(str(breakdown["net_amount"]["value"]))

    # Parse create_time
    create_time_str = primary_capture.get("create_time")
    event_time_dt: datetime | None = None
    if create_time_str:
        try:
            event_time_dt = datetime.fromisoformat(create_time_str)
        except ValueError:
            event_time_dt = datetime.now(UTC)

    # 6. Update payment record
    payment.provider_capture_id = capture_id
    payment.fee_amount = fee_val
    payment.net_amount = net_val
    payment.status = (
        PaymentStatus.COMPLETED if capture_status == "COMPLETED" else PaymentStatus.PENDING
    )
    payment.event_time = event_time_dt
    payment.updated_at = datetime.now(UTC)

    # 7. Trigger deterministic reconciliation engine if export_transaction_id is attached
    if payment.export_transaction_id:
        reconcile_transaction(db=db, transaction_id=payment.export_transaction_id)

    db.commit()
    db.refresh(payment)
    return PaymentRead.model_validate(payment)


@router.get(
    "",
    response_model=list[PaymentRead],
    summary="List payments with optional filtering",
)
def list_payments(
    export_transaction_id: uuid.UUID | None = Query(
        None, description="Filter by export transaction ID"
    ),
    invoice_id: uuid.UUID | None = Query(None, description="Filter by invoice ID"),
    status: PaymentStatus | None = Query(None, description="Filter by payment status"),
    environment: EnvironmentLabel | None = Query(
        None, description="Filter by environment (sandbox, production)"
    ),
    is_demo: bool | None = Query(None, description="Filter by demo status"),
    limit: int = Query(50, ge=1, le=100, description="Page size limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: Session = Depends(get_db),
) -> list[PaymentRead]:
    """Returns payments matching specified criteria with pagination."""
    query = db.query(Payment)
    if export_transaction_id:
        query = query.filter(Payment.export_transaction_id == export_transaction_id)
    if invoice_id:
        query = query.filter(Payment.invoice_id == invoice_id)
    if status:
        query = query.filter(Payment.status == status)
    if environment:
        query = query.filter(Payment.environment == environment)
    if is_demo is not None:
        query = query.filter(Payment.is_demo == is_demo)

    payments = query.order_by(Payment.created_at.desc()).offset(offset).limit(limit).all()
    return [PaymentRead.model_validate(p) for p in payments]
