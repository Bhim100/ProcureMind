"""FastAPI router for commercial export invoices and auditor approval gating."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.enums import AllocationReviewStatus, TargetType
from app.models.export import Invoice
from app.models.reconciliation import Allocation, HumanDecision
from app.schemas.export import InvoiceRead

router = APIRouter()


class InvoiceApprovalRequest(BaseModel):
    """Payload submitted by an auditor to formally approve an invoice for payment."""

    reviewer_label: str = Field(..., min_length=2, max_length=100)
    notes: str | None = None


class InvoiceApprovalResponse(BaseModel):
    """Result of an invoice approval action."""

    invoice_id: uuid.UUID
    invoice_number: str
    status: str
    decision_id: uuid.UUID
    reviewer_label: str
    decided_at: datetime


class InvoiceDetailResponse(InvoiceRead):
    """Enhanced invoice details including human approval status and settlement balance."""

    is_approved: bool
    approval_details: dict[str, str] | None = None
    remaining_balance: str


def verify_auditor_key(x_auditor_key: str | None = Header(None, alias="X-Auditor-Key")) -> str:
    """
    Security dependency verifying the presence and validity of the server's configured AUDITOR_API_KEY.
    Fails closed if the secret is unconfigured or mismatched.
    """
    if not settings.AUDITOR_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auditor authorization key is unconfigured on server. Approvals are disabled until AUDITOR_API_KEY is configured.",
        )
    if not x_auditor_key or x_auditor_key != settings.AUDITOR_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing auditor authorization key (X-Auditor-Key header required).",
        )
    return x_auditor_key


@router.post(
    "/{invoice_id}/approve",
    response_model=InvoiceApprovalResponse,
    summary="Auditor approval gating for a commercial export invoice",
)
def approve_invoice(
    invoice_id: uuid.UUID,
    payload: InvoiceApprovalRequest,
    _auth: str = Depends(verify_auditor_key),
    db: Session = Depends(get_db),
) -> InvoiceApprovalResponse:
    """
    Formally records an authorized human auditor approval for an invoice.

    In accordance with AGENTS.md Rule 3, a payment can only be initiated for an invoice
    that has an explicit HumanDecision approval on record.
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    now_utc = datetime.now(UTC)
    decision = HumanDecision(
        target_type=TargetType.INVOICE,
        target_id=invoice.id,
        decision="approved",
        reviewer_label=payload.reviewer_label,
        notes=payload.notes,
        decided_at=now_utc,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)

    return InvoiceApprovalResponse(
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        status="approved",
        decision_id=decision.id,
        reviewer_label=decision.reviewer_label or payload.reviewer_label,
        decided_at=decision.decided_at,
    )


@router.get(
    "/{invoice_id}",
    response_model=InvoiceDetailResponse,
    summary="Get commercial invoice details with auditor approval status",
)
def get_invoice_detail(
    invoice_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> InvoiceDetailResponse:
    """Returns invoice details with current approval state and unsettled balance."""
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")

    # Check for approval
    approval = (
        db.query(HumanDecision)
        .filter(
            HumanDecision.target_type == TargetType.INVOICE,
            HumanDecision.target_id == invoice.id,
            HumanDecision.decision == "approved",
        )
        .order_by(HumanDecision.decided_at.desc())
        .first()
    )

    # Compute remaining balance considering approved allocations
    approved_allocs = (
        db.query(Allocation)
        .filter(
            Allocation.invoice_id == invoice.id,
            Allocation.review_status == AllocationReviewStatus.APPROVED,
        )
        .all()
    )
    total_credit = sum(
        (a.allocated_amount for a in approved_allocs if not a.is_reversal), invoice.total_amount * 0
    )
    total_reversal = sum(
        (a.allocated_amount for a in approved_allocs if a.is_reversal), invoice.total_amount * 0
    )
    rem_balance = invoice.total_amount - (total_credit - total_reversal)

    invoice_data = InvoiceRead.model_validate(invoice).model_dump()
    invoice_data["is_approved"] = approval is not None
    invoice_data["approval_details"] = (
        {
            "reviewer_label": approval.reviewer_label,
            "decided_at": approval.decided_at.isoformat(),
            "notes": approval.notes or "",
        }
        if approval
        else None
    )
    invoice_data["remaining_balance"] = str(rem_balance)
    return InvoiceDetailResponse(**invoice_data)
