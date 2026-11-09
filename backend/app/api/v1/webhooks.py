"""FastAPI router for incoming payment provider webhooks (PayPal Sandbox)."""

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.enums import EnvironmentLabel, PaymentStatus
from app.models.payment import Payment, ProviderWebhookEvent
from app.services.paypal_service import paypal_client
from app.services.reconciliation_engine import reconcile_transaction

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_iso_datetime(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        return datetime.now(UTC)


@router.post(
    "/paypal",
    summary="Ingest, cryptographically verify, and process PayPal Sandbox webhook events",
)
async def receive_paypal_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Ingests and processes incoming PayPal Sandbox webhook events.

    Guarantees:
    1. Cryptographic signature verification against PayPal before processing. Rejects invalid with HTTP 400.
    2. Database-enforced deduplication on provider_event_id. Duplicate delivery returns HTTP 200 idempotently.
    3. Discrete refund event persistence under provider_refund_id without overwriting original captures.
    4. Triggers deterministic reconciliation engine.
    5. Returns HTTP 200 only after atomic database commit.
    """
    # 1. Read raw body and headers
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON body"
        ) from exc

    raw_headers = dict(request.headers)

    # 2. Cryptographic signature verification
    is_valid = paypal_client.verify_webhook_signature(headers=raw_headers, body=body)
    if not is_valid:
        logger.warning("Rejected counterfeit or unverified PayPal webhook signature.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid PayPal webhook signature.",
        )

    event_id = body.get("id")
    event_type = body.get("event_type", "UNKNOWN")
    resource = body.get("resource", {})
    create_time = _parse_iso_datetime(body.get("create_time"))

    if not event_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload missing event id.",
        )

    # 3. Database-enforced deduplication on provider_event_id using savepoint
    webhook_event = ProviderWebhookEvent(
        provider="paypal",
        provider_event_id=event_id,
        event_type=event_type,
        payload=body,
        status="received",
        event_time=create_time,
    )
    savepoint = db.begin_nested()
    try:
        db.add(webhook_event)
        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()
        logger.info(
            "Duplicate webhook event %s detected via database constraint. Returning HTTP 200.",
            event_id,
        )
        return {"status": "duplicate", "message": "Event already processed", "event_id": event_id}

    try:
        # 4. Handle events in scope
        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            capture_id = resource.get("id")
            order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")

            # Resolve payment record under lock
            payment_query = db.query(Payment)
            if order_id:
                payment = (
                    payment_query.filter(Payment.provider_order_id == order_id)
                    .with_for_update()
                    .first()
                )
            elif capture_id:
                payment = (
                    payment_query.filter(Payment.provider_capture_id == capture_id)
                    .with_for_update()
                    .first()
                )
            else:
                payment = None

            if payment:
                payment.provider_capture_id = capture_id
                payment.status = PaymentStatus.COMPLETED

                # Extract fee/net amounts if returned in breakdown (preserve None if missing; do not infer)
                breakdown = resource.get("seller_receivable_breakdown", {})
                if "paypal_fee" in breakdown and "value" in breakdown["paypal_fee"]:
                    payment.fee_amount = Decimal(str(breakdown["paypal_fee"]["value"]))
                if "net_amount" in breakdown and "value" in breakdown["net_amount"]:
                    payment.net_amount = Decimal(str(breakdown["net_amount"]["value"]))

                payment.event_time = _parse_iso_datetime(resource.get("create_time"))
                payment.updated_at = datetime.now(UTC)

                webhook_event.payment_id = payment.id
                webhook_event.status = "processed"

                if payment.export_transaction_id:
                    reconcile_transaction(db=db, transaction_id=payment.export_transaction_id)

        elif event_type in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED"):
            capture_id = resource.get("id")
            order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")

            payment = (
                db.query(Payment)
                .filter(
                    (Payment.provider_order_id == order_id)
                    | (Payment.provider_capture_id == capture_id)
                )
                .with_for_update()
                .first()
            )
            if payment:
                payment.status = PaymentStatus.FAILED
                payment.updated_at = datetime.now(UTC)
                webhook_event.payment_id = payment.id
                webhook_event.status = "processed"

        elif event_type == "PAYMENT.CAPTURE.PENDING":
            capture_id = resource.get("id")
            order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id")

            payment = (
                db.query(Payment)
                .filter(
                    (Payment.provider_order_id == order_id)
                    | (Payment.provider_capture_id == capture_id)
                )
                .with_for_update()
                .first()
            )
            if payment:
                payment.status = PaymentStatus.PENDING
                payment.updated_at = datetime.now(UTC)
                webhook_event.payment_id = payment.id
                webhook_event.status = "processed"

        elif event_type in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
            refund_id = resource.get("id")
            # Links or parent capture reference
            capture_id = resource.get("capture_id") or resource.get("supplementary_data", {}).get(
                "related_ids", {}
            ).get("capture_id")
            if not capture_id:
                for link in resource.get("links", []):
                    if link.get("rel") == "up" and "captures" in link.get("href", ""):
                        capture_id = link["href"].split("/")[-1]
                        break

            # Find original payment capture without overwriting it
            original_payment = (
                db.query(Payment)
                .filter(Payment.provider_capture_id == capture_id)
                .with_for_update()
                .first()
                if capture_id
                else None
            )

            if original_payment:
                # Check if refund payment row already exists
                existing_refund = (
                    db.query(Payment).filter(Payment.provider_refund_id == refund_id).first()
                )
                if not existing_refund:
                    ref_amount_dict = resource.get("amount", {})
                    ref_amount = Decimal(
                        str(ref_amount_dict.get("value", str(original_payment.gross_amount)))
                    )
                    ref_curr = ref_amount_dict.get("currency_code", original_payment.currency)

                    refund_payment = Payment(
                        provider="paypal",
                        provider_refund_id=refund_id,
                        provider_capture_id=None,  # Dedicated refund; never conflate with capture ID
                        parent_payment_id=original_payment.id,
                        invoice_id=original_payment.invoice_id,
                        invoice_reference=original_payment.invoice_reference,
                        currency=ref_curr,
                        gross_amount=ref_amount,
                        fee_amount=None,
                        net_amount=ref_amount,
                        status=PaymentStatus.REFUNDED,
                        environment=EnvironmentLabel.SANDBOX,
                        export_transaction_id=original_payment.export_transaction_id,
                        is_demo=original_payment.is_demo,
                        description=f"PayPal Sandbox refund event {refund_id} for capture {capture_id}",
                        event_time=_parse_iso_datetime(resource.get("create_time")),
                    )
                    db.add(refund_payment)
                    db.flush()

                    webhook_event.payment_id = refund_payment.id
                    webhook_event.status = "processed"

                    # Trigger Phase 4 reconciliation engine to propose compensating reversal
                    if original_payment.export_transaction_id:
                        reconcile_transaction(
                            db=db, transaction_id=original_payment.export_transaction_id
                        )
            else:
                webhook_event.status = "unmatched_parent"

        else:
            webhook_event.status = "ignored_event_type"

        # 5. Commit all changes atomically before returning HTTP 200
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to process PayPal webhook event %s", event_id)
        # Raising 500 prompts PayPal to automatically retry delivery per webhook spec
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Webhook processing error: {exc}",
        ) from exc

    return {"status": "processed", "event_id": event_id, "event_type": event_type}
