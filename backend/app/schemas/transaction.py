"""
Pydantic v2 schemas for ExportTransaction retrieval and enriched context.
"""

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.models.enums import LinkStatus, TransactionStatus
from app.schemas.common import ProcureMindBaseSchema, ensure_utc_datetime
from app.schemas.export import InvoiceRead, ShippingBillRead
from app.schemas.payment import BankTransactionRead, PaymentRead, SettlementRead
from app.schemas.relationship import TransactionLinkRead


class LinkedEntityStatusMixin(ProcureMindBaseSchema):
    """Adds relationship link status to a retrieved trade record."""

    link_status: LinkStatus | str = Field(
        default="unlinked",
        description="Relationship status in this transaction: unlinked, proposed, confirmed, rejected",
    )


class InvoiceWithLinkStatus(InvoiceRead, LinkedEntityStatusMixin):
    pass


class ShippingBillWithLinkStatus(ShippingBillRead, LinkedEntityStatusMixin):
    pass


class PaymentWithLinkStatus(PaymentRead, LinkedEntityStatusMixin):
    pass


class SettlementWithLinkStatus(SettlementRead, LinkedEntityStatusMixin):
    pass


class BankTransactionWithLinkStatus(BankTransactionRead, LinkedEntityStatusMixin):
    pass


class TransactionDetailRead(ProcureMindBaseSchema):
    """Full detail of an ExportTransaction with all associated records and their link statuses."""

    id: uuid.UUID
    transaction_reference: str
    exporter_name: str
    exporter_tax_id: str | None = None
    buyer_name: str
    buyer_country: str | None = None
    status: TransactionStatus
    is_demo: bool = False
    created_at: datetime
    updated_at: datetime

    invoices: list[InvoiceWithLinkStatus] = Field(default_factory=list)
    shipping_bills: list[ShippingBillWithLinkStatus] = Field(default_factory=list)
    payments: list[PaymentWithLinkStatus] = Field(default_factory=list)
    settlements: list[SettlementWithLinkStatus] = Field(default_factory=list)
    bank_transactions: list[BankTransactionWithLinkStatus] = Field(default_factory=list)
    links: list[TransactionLinkRead] = Field(default_factory=list)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)
