"""
Relationship service implementing trade record connection, ownership assignment,
exact-reference auto-discovery, manual link proposal, and human decision recording.
"""

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.core.normalization import normalize_reference_identifier
from app.models.base import utc_now
from app.models.enums import (
    DecisionType,
    ExtractionMethod,
    LinkMethod,
    LinkStatus,
    LinkType,
    ReviewState,
    TargetType,
)
from app.models.export import ExportTransaction, Invoice, ShippingBill
from app.models.payment import BankTransaction, Payment, Settlement
from app.models.reconciliation import EvidenceReference, HumanDecision
from app.models.relationship import TransactionLink
from app.schemas.relationship import (
    DiscoveryResponse,
    LinkDecisionRequest,
    RecordAssignmentResponse,
    TransactionLinkCreate,
    TransactionLinkRead,
    UnlinkedRecordReport,
)
from app.schemas.transaction import (
    BankTransactionWithLinkStatus,
    InvoiceWithLinkStatus,
    PaymentWithLinkStatus,
    SettlementWithLinkStatus,
    ShippingBillWithLinkStatus,
    TransactionDetailRead,
)


def _compute_link_status(record_id: uuid.UUID, links: list[TransactionLink]) -> str:
    """Computes the highest precedence link status for a record across transaction links."""
    matching_statuses = [
        link.status
        for link in links
        if record_id
        in (
            link.invoice_id,
            link.shipping_bill_id,
            link.payment_id,
            link.settlement_id,
            link.bank_transaction_id,
        )
    ]
    if not matching_statuses:
        return "unlinked"
    if LinkStatus.CONFIRMED in matching_statuses:
        return LinkStatus.CONFIRMED.value
    if LinkStatus.PROPOSED in matching_statuses:
        return LinkStatus.PROPOSED.value
    if LinkStatus.REJECTED in matching_statuses:
        return LinkStatus.REJECTED.value
    return "unlinked"


def _to_entity_dict(entity: Any, link_status: str) -> dict[str, Any]:
    """Helper converting SQLAlchemy entity to dictionary without internal state."""
    data = {k: v for k, v in entity.__dict__.items() if not k.startswith("_")}
    data["link_status"] = link_status
    return data


def get_transaction_with_linked_entities(
    db: Session, transaction_id: uuid.UUID
) -> TransactionDetailRead:
    """Retrieves an ExportTransaction with all associated records and their link statuses."""
    tx = (
        db.query(ExportTransaction)
        .options(
            selectinload(ExportTransaction.invoices),
            selectinload(ExportTransaction.shipping_bills),
            selectinload(ExportTransaction.payments),
            selectinload(ExportTransaction.settlements),
            selectinload(ExportTransaction.bank_transactions),
            selectinload(ExportTransaction.links).selectinload(TransactionLink.evidence_references),
        )
        .filter(ExportTransaction.id == transaction_id)
        .first()
    )
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export transaction {transaction_id} not found",
        )

    links = tx.links

    invoices_with_status = [
        InvoiceWithLinkStatus.model_validate(
            _to_entity_dict(inv, _compute_link_status(inv.id, links))
        )
        for inv in tx.invoices
    ]

    shipping_bills_with_status = [
        ShippingBillWithLinkStatus.model_validate(
            _to_entity_dict(sb, _compute_link_status(sb.id, links))
        )
        for sb in tx.shipping_bills
    ]

    payments_with_status = [
        PaymentWithLinkStatus.model_validate(
            _to_entity_dict(pay, _compute_link_status(pay.id, links))
        )
        for pay in tx.payments
    ]

    settlements_with_status = [
        SettlementWithLinkStatus.model_validate(
            _to_entity_dict(stl, _compute_link_status(stl.id, links))
        )
        for stl in tx.settlements
    ]

    bank_transactions_with_status = [
        BankTransactionWithLinkStatus.model_validate(
            _to_entity_dict(bt, _compute_link_status(bt.id, links))
        )
        for bt in tx.bank_transactions
    ]

    return TransactionDetailRead(
        id=tx.id,
        transaction_reference=tx.transaction_reference,
        exporter_name=tx.exporter_name,
        exporter_tax_id=tx.exporter_tax_id,
        buyer_name=tx.buyer_name,
        buyer_country=tx.buyer_country,
        status=tx.status,
        is_demo=tx.is_demo,
        created_at=tx.created_at,
        updated_at=tx.updated_at,
        invoices=invoices_with_status,
        shipping_bills=shipping_bills_with_status,
        payments=payments_with_status,
        settlements=settlements_with_status,
        bank_transactions=bank_transactions_with_status,
        links=[TransactionLinkRead.model_validate(lnk) for lnk in tx.links],
    )


def get_transaction_links(db: Session, transaction_id: uuid.UUID) -> list[TransactionLink]:
    """Retrieves all TransactionLink records and attached evidence for a transaction."""
    tx = db.query(ExportTransaction).filter(ExportTransaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export transaction {transaction_id} not found",
        )

    return (
        db.query(TransactionLink)
        .options(selectinload(TransactionLink.evidence_references))
        .filter(TransactionLink.export_transaction_id == transaction_id)
        .order_by(TransactionLink.created_at.asc())
        .all()
    )


def assign_record_to_transaction(
    db: Session,
    transaction_id: uuid.UUID,
    record_type: str,
    record_id: uuid.UUID,
    notes: str | None = None,
) -> RecordAssignmentResponse:
    """Explicit, atomic human action assigning an unowned record to a transaction."""
    tx = db.query(ExportTransaction).filter(ExportTransaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export transaction {transaction_id} not found",
        )

    model_map: dict[str, Any] = {
        "invoice": Invoice,
        "shipping_bill": ShippingBill,
        "payment": Payment,
        "settlement": Settlement,
        "bank_transaction": BankTransaction,
    }

    model = model_map.get(record_type.lower())
    if not model:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported record type '{record_type}'. Must be one of: {list(model_map.keys())}",
        )

    record = db.query(model).filter(model.id == record_id).first()
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{record_type.capitalize()} with ID {record_id} not found",
        )

    # Ownership check
    if record.export_transaction_id == transaction_id:
        return RecordAssignmentResponse(
            record_type=record_type,
            record_id=record_id,
            export_transaction_id=transaction_id,
            message=f"{record_type.capitalize()} already belongs to this transaction",
        )

    if record.export_transaction_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Record {record_id} ({record_type}) belongs to a different transaction ({record.export_transaction_id})",
        )

    # Explicit atomic assignment
    record.export_transaction_id = transaction_id
    target_type_enum = TargetType(record_type.lower())
    decision = HumanDecision(
        target_type=target_type_enum,
        target_id=record_id,
        decision=DecisionType.APPROVED,
        notes=notes or f"Explicit human assignment to transaction {transaction_id}",
        decided_at=utc_now(),
    )
    db.add(decision)
    db.commit()
    db.refresh(record)

    return RecordAssignmentResponse(
        record_type=record_type,
        record_id=record_id,
        export_transaction_id=transaction_id,
        message=f"{record_type.capitalize()} assigned to transaction successfully",
    )


def create_manual_link(
    db: Session, transaction_id: uuid.UUID, payload: TransactionLinkCreate
) -> TransactionLink:
    """
    Manually proposes a typed relationship between two records in a transaction.

    Always creates a link with status='proposed'.
    """
    tx = db.query(ExportTransaction).filter(ExportTransaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export transaction {transaction_id} not found",
        )

    # Resolve and validate source/target records based on link_type
    inv_id: uuid.UUID | None = None
    sb_id: uuid.UUID | None = None
    pay_id: uuid.UUID | None = None
    stl_id: uuid.UUID | None = None
    bt_id: uuid.UUID | None = None

    source_record: Any = None
    target_record: Any = None

    if payload.link_type == LinkType.INVOICE_SHIPPING_BILL:
        source_record = db.query(Invoice).filter(Invoice.id == payload.source_id).first()
        target_record = db.query(ShippingBill).filter(ShippingBill.id == payload.target_id).first()
        inv_id = payload.source_id
        sb_id = payload.target_id
    elif payload.link_type == LinkType.INVOICE_PAYMENT:
        source_record = db.query(Invoice).filter(Invoice.id == payload.source_id).first()
        target_record = db.query(Payment).filter(Payment.id == payload.target_id).first()
        inv_id = payload.source_id
        pay_id = payload.target_id
    elif payload.link_type == LinkType.PAYMENT_SETTLEMENT:
        source_record = db.query(Payment).filter(Payment.id == payload.source_id).first()
        target_record = db.query(Settlement).filter(Settlement.id == payload.target_id).first()
        pay_id = payload.source_id
        stl_id = payload.target_id
    elif payload.link_type == LinkType.BANK_TRANSACTION_PAYMENT:
        source_record = (
            db.query(BankTransaction).filter(BankTransaction.id == payload.source_id).first()
        )
        target_record = db.query(Payment).filter(Payment.id == payload.target_id).first()
        bt_id = payload.source_id
        pay_id = payload.target_id
    elif payload.link_type == LinkType.BANK_TRANSACTION_SETTLEMENT:
        source_record = (
            db.query(BankTransaction).filter(BankTransaction.id == payload.source_id).first()
        )
        target_record = db.query(Settlement).filter(Settlement.id == payload.target_id).first()
        bt_id = payload.source_id
        stl_id = payload.target_id
    else:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported link_type '{payload.link_type}'",
        )

    if not source_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source record {payload.source_id} not found",
        )
    if not target_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Target record {payload.target_id} not found",
        )

    # Ownership validation: both records must belong to this transaction
    if getattr(source_record, "export_transaction_id", None) != transaction_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Source record {payload.source_id} does not belong to transaction {transaction_id}",
        )
    if getattr(target_record, "export_transaction_id", None) != transaction_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Target record {payload.target_id} does not belong to transaction {transaction_id}",
        )

    # Duplicate link check
    existing_link = (
        db.query(TransactionLink)
        .filter(
            TransactionLink.export_transaction_id == transaction_id,
            TransactionLink.link_type == payload.link_type,
            TransactionLink.invoice_id == inv_id,
            TransactionLink.shipping_bill_id == sb_id,
            TransactionLink.payment_id == pay_id,
            TransactionLink.settlement_id == stl_id,
            TransactionLink.bank_transaction_id == bt_id,
            TransactionLink.status != LinkStatus.REJECTED,
        )
        .first()
    )
    if existing_link:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A relationship already exists between these records in this transaction",
        )

    norm_ref = normalize_reference_identifier(payload.explicit_reference)

    link = TransactionLink(
        export_transaction_id=transaction_id,
        link_type=payload.link_type,
        link_method=LinkMethod.MANUAL,
        status=LinkStatus.PROPOSED,
        invoice_id=inv_id,
        shipping_bill_id=sb_id,
        payment_id=pay_id,
        settlement_id=stl_id,
        bank_transaction_id=bt_id,
        explicit_reference=payload.explicit_reference,
        normalized_reference=norm_ref,
        evidence_notes=payload.notes,
        is_demo=bool(
            getattr(source_record, "is_demo", False) or getattr(target_record, "is_demo", False)
        ),
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def discover_transaction_links(db: Session, transaction_id: uuid.UUID) -> DiscoveryResponse:
    """
    Scans records belonging to transaction for exact explicit references.

    Strictly read-only regarding ownership.
    Creates proposed links for single exact matches.
    Returns ambiguous/missing reference records in unlinked_records.
    """
    tx = db.query(ExportTransaction).filter(ExportTransaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export transaction {transaction_id} not found",
        )

    invoices = db.query(Invoice).filter(Invoice.export_transaction_id == transaction_id).all()
    shipping_bills = (
        db.query(ShippingBill).filter(ShippingBill.export_transaction_id == transaction_id).all()
    )
    payments = db.query(Payment).filter(Payment.export_transaction_id == transaction_id).all()

    created_links: list[TransactionLink] = []
    existing_links: list[TransactionLink] = []
    unlinked_records: list[UnlinkedRecordReport] = []

    # Build normalized invoice lookup
    invoices_by_norm: dict[str, list[Invoice]] = {}
    for inv in invoices:
        norm = normalize_reference_identifier(inv.invoice_number)
        if norm:
            invoices_by_norm.setdefault(norm, []).append(inv)

    # 1. Match ShippingBill -> Invoice (invoice_number == invoice_reference)
    for sb in shipping_bills:
        norm_ref = normalize_reference_identifier(sb.invoice_reference)
        if not norm_ref:
            unlinked_records.append(
                UnlinkedRecordReport(
                    record_type="shipping_bill",
                    record_id=sb.id,
                    reference=sb.invoice_reference,
                    reason="Missing invoice reference on shipping bill",
                )
            )
            continue

        candidates = invoices_by_norm.get(norm_ref, [])
        if not candidates:
            unlinked_records.append(
                UnlinkedRecordReport(
                    record_type="shipping_bill",
                    record_id=sb.id,
                    reference=sb.invoice_reference,
                    reason=f"Reference '{sb.invoice_reference}' does not match any invoice in this transaction",
                )
            )
        elif len(candidates) > 1:
            unlinked_records.append(
                UnlinkedRecordReport(
                    record_type="shipping_bill",
                    record_id=sb.id,
                    reference=sb.invoice_reference,
                    reason="Ambiguous match: reference matches multiple candidate invoices in this transaction",
                    candidate_ids=[c.id for c in candidates],
                )
            )
        else:
            inv = candidates[0]
            existing = (
                db.query(TransactionLink)
                .filter(
                    TransactionLink.export_transaction_id == transaction_id,
                    TransactionLink.link_type == LinkType.INVOICE_SHIPPING_BILL,
                    TransactionLink.invoice_id == inv.id,
                    TransactionLink.shipping_bill_id == sb.id,
                )
                .first()
            )
            if existing:
                existing_links.append(existing)
            else:
                link = TransactionLink(
                    export_transaction_id=transaction_id,
                    link_type=LinkType.INVOICE_SHIPPING_BILL,
                    link_method=LinkMethod.AUTO_EXACT,
                    status=LinkStatus.PROPOSED,
                    invoice_id=inv.id,
                    shipping_bill_id=sb.id,
                    explicit_reference=sb.invoice_reference,
                    normalized_reference=norm_ref,
                    evidence_notes=f"Exact match on invoice reference '{sb.invoice_reference}'",
                    is_demo=bool(inv.is_demo or sb.is_demo),
                )
                db.add(link)
                db.flush()

                # Preserve physical provenance if source document exists
                if sb.document_id:
                    evidence = EvidenceReference(
                        transaction_link_id=link.id,
                        document_id=sb.document_id,
                        source_record_type="shipping_bill",
                        source_record_id=sb.id,
                        raw_value=sb.invoice_reference,
                        normalized_value=norm_ref,
                        extraction_method=ExtractionMethod.TEXT,
                        review_state=ReviewState.PENDING,
                    )
                    db.add(evidence)

                created_links.append(link)

    # 2. Match Payment -> Invoice (invoice_number == invoice_reference)
    for pay in payments:
        norm_ref = normalize_reference_identifier(pay.invoice_reference)
        if not norm_ref:
            unlinked_records.append(
                UnlinkedRecordReport(
                    record_type="payment",
                    record_id=pay.id,
                    reference=pay.invoice_reference,
                    reason="Missing invoice reference on payment",
                )
            )
            continue

        candidates = invoices_by_norm.get(norm_ref, [])
        if not candidates:
            unlinked_records.append(
                UnlinkedRecordReport(
                    record_type="payment",
                    record_id=pay.id,
                    reference=pay.invoice_reference,
                    reason=f"Reference '{pay.invoice_reference}' does not match any invoice in this transaction",
                )
            )
        elif len(candidates) > 1:
            unlinked_records.append(
                UnlinkedRecordReport(
                    record_type="payment",
                    record_id=pay.id,
                    reference=pay.invoice_reference,
                    reason="Ambiguous match: reference matches multiple candidate invoices in this transaction",
                    candidate_ids=[c.id for c in candidates],
                )
            )
        else:
            inv = candidates[0]
            existing = (
                db.query(TransactionLink)
                .filter(
                    TransactionLink.export_transaction_id == transaction_id,
                    TransactionLink.link_type == LinkType.INVOICE_PAYMENT,
                    TransactionLink.invoice_id == inv.id,
                    TransactionLink.payment_id == pay.id,
                )
                .first()
            )
            if existing:
                existing_links.append(existing)
            else:
                link = TransactionLink(
                    export_transaction_id=transaction_id,
                    link_type=LinkType.INVOICE_PAYMENT,
                    link_method=LinkMethod.AUTO_EXACT,
                    status=LinkStatus.PROPOSED,
                    invoice_id=inv.id,
                    payment_id=pay.id,
                    explicit_reference=pay.invoice_reference,
                    normalized_reference=norm_ref,
                    evidence_notes=f"Exact match on payment invoice reference '{pay.invoice_reference}'",
                    is_demo=bool(inv.is_demo or pay.is_demo),
                )
                db.add(link)
                created_links.append(link)

    db.commit()

    for lnk in created_links:
        db.refresh(lnk)

    return DiscoveryResponse(
        created_links=[TransactionLinkRead.model_validate(lnk) for lnk in created_links],
        existing_links=[TransactionLinkRead.model_validate(lnk) for lnk in existing_links],
        unlinked_records=unlinked_records,
    )


def apply_link_decision(
    db: Session,
    transaction_id: uuid.UUID,
    link_id: uuid.UUID,
    payload: LinkDecisionRequest,
) -> TransactionLink:
    """
    Sole authorized endpoint for confirming or rejecting a proposed link.

    Persists an immutable HumanDecision row.
    """
    link = (
        db.query(TransactionLink)
        .options(selectinload(TransactionLink.evidence_references))
        .filter(
            TransactionLink.id == link_id,
            TransactionLink.export_transaction_id == transaction_id,
        )
        .first()
    )
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Relationship link {link_id} not found in transaction {transaction_id}",
        )

    if payload.decision == DecisionType.APPROVED:
        link.status = LinkStatus.CONFIRMED
    elif payload.decision == DecisionType.REJECTED:
        link.status = LinkStatus.REJECTED
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Decision must be approved or rejected, got '{payload.decision}'",
        )

    decision = HumanDecision(
        target_type=TargetType.TRANSACTION_LINK,
        target_id=link.id,
        decision=payload.decision,
        reviewer_label=payload.reviewer_label,
        notes=payload.notes,
        decided_at=utc_now(),
    )
    db.add(decision)
    db.commit()
    db.refresh(link)
    return link
