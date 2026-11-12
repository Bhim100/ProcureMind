"""FastAPI router for human decisions on reconciliation matches."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import verify_auditor_key
from app.core.database import get_db
from app.schemas.match import MatchDecisionRequest, ReconciliationMatchRead
from app.services.reconciliation_engine import apply_match_decision

router = APIRouter()


@router.post(
    "/{id}/decision",
    response_model=ReconciliationMatchRead,
    summary="Submit human decision (approved or rejected) for a proposed reconciliation match",
)
def decide_match(
    id: uuid.UUID,
    payload: MatchDecisionRequest,
    _auth: str = Depends(verify_auditor_key),
    db: Session = Depends(get_db),
) -> ReconciliationMatchRead:
    """
    Authorized human review decision endpoint.

    When approved for invoice-payment allocations or compensating reversals,
    atomically activates the official Allocation row and checks whether the transaction
    is fully reconciled. Uses pessimistic row-level locking for concurrency safety.
    """
    return apply_match_decision(db=db, match_id=id, payload=payload)
