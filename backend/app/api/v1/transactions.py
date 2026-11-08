"""
FastAPI router for transactions and typed trade record relationships.

Endpoints provide:
- Transaction detail and linked record context retrieval
- Trade relationship listing
- Explicit atomic record ownership assignment
- Manual link proposal (always initialized to proposed)
- Exact-reference auto-discovery (idempotent, proposed-only)
- Human decision confirmation/rejection with immutable audit logging
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.relationship import (
    DiscoveryResponse,
    LinkDecisionRequest,
    RecordAssignmentRequest,
    RecordAssignmentResponse,
    TransactionLinkCreate,
    TransactionLinkRead,
)
from app.schemas.transaction import TransactionDetailRead
from app.services.relationship_service import (
    apply_link_decision,
    assign_record_to_transaction,
    create_manual_link,
    discover_transaction_links,
    get_transaction_links,
    get_transaction_with_linked_entities,
)

router = APIRouter()


@router.get(
    "/{id}",
    response_model=TransactionDetailRead,
    summary="Get export transaction detail with linked entities and statuses",
)
def get_transaction(
    id: uuid.UUID,
    db: Session = Depends(get_db),
) -> TransactionDetailRead:
    """Returns the export transaction details and all linked trade records."""
    return get_transaction_with_linked_entities(db=db, transaction_id=id)


@router.get(
    "/{id}/links",
    response_model=list[TransactionLinkRead],
    summary="Get all relationship links and attached evidence for a transaction",
)
def list_transaction_links(
    id: uuid.UUID,
    db: Session = Depends(get_db),
) -> list[TransactionLinkRead]:
    """Returns all typed relationship links connecting records in this transaction."""
    links = get_transaction_links(db=db, transaction_id=id)
    return [TransactionLinkRead.model_validate(link) for link in links]


@router.post(
    "/{id}/assign-record",
    response_model=RecordAssignmentResponse,
    summary="Explicit human action assigning an unowned record to a transaction",
)
def assign_record(
    id: uuid.UUID,
    payload: RecordAssignmentRequest,
    db: Session = Depends(get_db),
) -> RecordAssignmentResponse:
    """
    Explicitly assigns an unowned trade or financial record to a transaction.

    Atomic operation that records a HumanDecision audit trail.
    """
    return assign_record_to_transaction(
        db=db,
        transaction_id=id,
        record_type=payload.record_type,
        record_id=payload.record_id,
        notes=payload.notes,
    )


@router.post(
    "/{id}/links",
    response_model=TransactionLinkRead,
    status_code=status.HTTP_201_CREATED,
    summary="Manually propose a relationship link between two records",
)
def propose_link(
    id: uuid.UUID,
    payload: TransactionLinkCreate,
    db: Session = Depends(get_db),
) -> TransactionLinkRead:
    """
    Proposes a relationship link between two trade records belonging to this transaction.

    The link is always created with status='proposed'. Only the decision endpoint
    may confirm or reject it.
    """
    link = create_manual_link(db=db, transaction_id=id, payload=payload)
    return TransactionLinkRead.model_validate(link)


@router.post(
    "/{id}/discover-links",
    response_model=DiscoveryResponse,
    summary="Run exact-reference automated discovery for a transaction",
)
def discover_links(
    id: uuid.UUID,
    db: Session = Depends(get_db),
) -> DiscoveryResponse:
    """
    Scans records belonging to the transaction for exact explicit references.

    Idempotently creates proposed links for exact matches.
    Reports missing, conflicting, or ambiguous references in unlinked_records.
    """
    return discover_transaction_links(db=db, transaction_id=id)


@router.post(
    "/{id}/links/{link_id}/decision",
    response_model=TransactionLinkRead,
    summary="Confirm or reject a proposed relationship link",
)
def decide_link(
    id: uuid.UUID,
    link_id: uuid.UUID,
    payload: LinkDecisionRequest,
    db: Session = Depends(get_db),
) -> TransactionLinkRead:
    """
    Sole authorized endpoint for confirming or rejecting a relationship link.

    Transitions status to confirmed or rejected and writes an immutable HumanDecision row.
    """
    link = apply_link_decision(db=db, transaction_id=id, link_id=link_id, payload=payload)
    return TransactionLinkRead.model_validate(link)
