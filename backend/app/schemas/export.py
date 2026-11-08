"""
Pydantic v2 schemas for ExportTransaction, Invoice, InvoiceLineItem, and ShippingBill.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from app.core.currencies import validate_currency_code, validate_currency_scale
from app.models.enums import TransactionStatus
from app.schemas.common import (
    CurrencyCode,
    MoneyAmount,
    ProcureMindBaseSchema,
    ensure_utc_datetime,
    validate_money_amount,
)


# --- ExportTransaction ---
class ExportTransactionBase(ProcureMindBaseSchema):
    transaction_reference: str = Field(..., max_length=100)
    exporter_name: str = Field(..., max_length=255)
    exporter_tax_id: str | None = Field(None, max_length=50)
    buyer_name: str = Field(..., max_length=255)
    buyer_country: str | None = Field(None, max_length=100)
    status: TransactionStatus = TransactionStatus.DRAFT
    is_demo: bool = False


class ExportTransactionCreate(ExportTransactionBase):
    pass


class ExportTransactionRead(ExportTransactionBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


# --- InvoiceLineItem ---
class InvoiceLineItemBase(ProcureMindBaseSchema):
    line_number: int = Field(default=1, ge=1)
    description: str = Field(..., max_length=500)
    quantity: Decimal = Field(default=Decimal("1.0000"), gt=Decimal("0.0000"))
    unit_price: MoneyAmount
    total_amount: MoneyAmount
    currency: CurrencyCode
    hs_code: str | None = Field(None, max_length=20)

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v: str) -> str:
        return validate_currency_code(v)

    @field_validator("unit_price", "total_amount")
    @classmethod
    def check_amount(cls, v: Decimal) -> Decimal:
        return validate_money_amount(v)

    @model_validator(mode="after")
    def validate_precision(self) -> "InvoiceLineItemBase":
        if self.currency:
            if self.unit_price is not None:
                validate_currency_scale(self.unit_price, self.currency)
            if self.total_amount is not None:
                validate_currency_scale(self.total_amount, self.currency)
        return self


class InvoiceLineItemCreate(InvoiceLineItemBase):
    invoice_id: uuid.UUID | None = None


class InvoiceLineItemRead(InvoiceLineItemBase):
    id: uuid.UUID
    invoice_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


# --- Invoice ---
class InvoiceBase(ProcureMindBaseSchema):
    invoice_number: str = Field(..., max_length=100)
    export_transaction_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    seller_name: str = Field(..., max_length=255)
    buyer_name: str = Field(..., max_length=255)
    issue_date: date | None = None
    currency: CurrencyCode
    total_amount: MoneyAmount
    shipment_reference: str | None = Field(None, max_length=100)
    is_demo: bool = False

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v: str) -> str:
        return validate_currency_code(v)

    @field_validator("total_amount")
    @classmethod
    def check_amount(cls, v: Decimal) -> Decimal:
        val = validate_money_amount(v)
        if val <= Decimal("0.00"):
            raise ValueError("Invoice total_amount must be greater than zero")
        return val

    @model_validator(mode="after")
    def validate_precision(self) -> "InvoiceBase":
        if self.currency and self.total_amount is not None:
            validate_currency_scale(self.total_amount, self.currency)
        return self


class InvoiceCreate(InvoiceBase):
    line_items: list[InvoiceLineItemBase] = Field(default_factory=list)


class InvoiceRead(InvoiceBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    line_items: list[InvoiceLineItemRead] = Field(default_factory=list)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


# --- ShippingBill ---
class ShippingBillBase(ProcureMindBaseSchema):
    shipping_bill_number: str = Field(..., max_length=100)
    export_transaction_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    invoice_reference: str | None = Field(None, max_length=100)
    exporter_name: str = Field(..., max_length=255)
    buyer_name: str = Field(..., max_length=255)
    bill_date: date | None = None
    declared_currency: CurrencyCode
    declared_value: MoneyAmount
    is_demo: bool = False

    @field_validator("declared_currency")
    @classmethod
    def check_currency(cls, v: str) -> str:
        return validate_currency_code(v)

    @field_validator("declared_value")
    @classmethod
    def check_amount(cls, v: Decimal) -> Decimal:
        val = validate_money_amount(v)
        if val <= Decimal("0.00"):
            raise ValueError("Declared value must be greater than zero")
        return val

    @model_validator(mode="after")
    def validate_precision(self) -> "ShippingBillBase":
        if self.declared_currency and self.declared_value is not None:
            validate_currency_scale(self.declared_value, self.declared_currency)
        return self


class ShippingBillCreate(ShippingBillBase):
    pass


class ShippingBillRead(ShippingBillBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)
