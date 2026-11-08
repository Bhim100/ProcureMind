"""
Pydantic v2 schemas for Payment, ProviderWebhookEvent, Settlement, and BankTransaction.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.core.currencies import validate_currency_code, validate_currency_scale
from app.models.enums import (
    BankTransactionStatus,
    BankTransactionType,
    EnvironmentLabel,
    PaymentStatus,
    SettlementStatus,
)
from app.schemas.common import (
    CurrencyCode,
    MoneyAmount,
    ProcureMindBaseSchema,
    ensure_utc_datetime,
    validate_money_amount,
)


# --- BankTransaction ---
class BankTransactionBase(ProcureMindBaseSchema):
    bank_reference: str = Field(..., max_length=100)
    currency: CurrencyCode
    amount: MoneyAmount
    transaction_date: date
    transaction_type: BankTransactionType = BankTransactionType.CREDIT
    status: BankTransactionStatus = BankTransactionStatus.POSTED
    remittance_reference: str | None = Field(None, max_length=255)
    export_transaction_id: uuid.UUID | None = None
    is_demo: bool = False

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v: str) -> str:
        return validate_currency_code(v)

    @field_validator("amount")
    @classmethod
    def check_amount(cls, v: Decimal) -> Decimal:
        val = validate_money_amount(v)
        if val <= Decimal("0.00"):
            raise ValueError("Bank transaction amount must be greater than zero")
        return val

    @model_validator(mode="after")
    def validate_precision(self) -> "BankTransactionBase":
        if self.currency and self.amount is not None:
            validate_currency_scale(self.amount, self.currency)
        return self


class BankTransactionCreate(BankTransactionBase):
    pass


class BankTransactionRead(BankTransactionBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


# --- Settlement ---
class SettlementBase(ProcureMindBaseSchema):
    provider_reference: str = Field(..., max_length=100)
    bank_transaction_id: uuid.UUID | None = None
    currency: CurrencyCode
    amount: MoneyAmount
    settlement_date: date
    status: SettlementStatus = SettlementStatus.COMPLETED
    remittance_reference: str | None = Field(None, max_length=255)
    export_transaction_id: uuid.UUID | None = None
    is_demo: bool = False

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v: str) -> str:
        return validate_currency_code(v)

    @field_validator("amount")
    @classmethod
    def check_amount(cls, v: Decimal) -> Decimal:
        val = validate_money_amount(v)
        if val <= Decimal("0.00"):
            raise ValueError("Settlement amount must be greater than zero")
        return val

    @model_validator(mode="after")
    def validate_precision(self) -> "SettlementBase":
        if self.currency and self.amount is not None:
            validate_currency_scale(self.amount, self.currency)
        return self


class SettlementCreate(SettlementBase):
    pass


class SettlementRead(SettlementBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return ensure_utc_datetime(v)


# --- Payment ---
class PaymentBase(ProcureMindBaseSchema):
    provider: str = Field(default="paypal", max_length=50)
    settlement_id: uuid.UUID | None = None
    provider_order_id: str | None = Field(None, max_length=100)
    provider_capture_id: str | None = Field(None, max_length=100)
    invoice_reference: str | None = Field(None, max_length=100)
    currency: CurrencyCode
    gross_amount: MoneyAmount
    fee_amount: Decimal = Field(default=Decimal("0.00"), ge=Decimal("0.00"))
    net_amount: MoneyAmount
    status: PaymentStatus = PaymentStatus.COMPLETED
    event_time: datetime | None = None
    environment: EnvironmentLabel = EnvironmentLabel.SANDBOX
    export_transaction_id: uuid.UUID | None = None
    is_demo: bool = False

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v: str) -> str:
        return validate_currency_code(v)

    @field_validator("gross_amount", "fee_amount", "net_amount")
    @classmethod
    def check_amounts(cls, v: Decimal) -> Decimal:
        return validate_money_amount(v)

    @model_validator(mode="after")
    def validate_net_calculation(self) -> "PaymentBase":
        if self.gross_amount <= Decimal("0.00"):
            raise ValueError("Payment gross_amount must be greater than zero")
        calculated_net = self.gross_amount - self.fee_amount
        if self.net_amount != calculated_net:
            raise ValueError(
                f"Net amount ({self.net_amount}) does not equal gross ({self.gross_amount}) minus fee ({self.fee_amount}) = {calculated_net}"
            )
        if self.currency:
            if self.gross_amount is not None:
                validate_currency_scale(self.gross_amount, self.currency)
            if self.fee_amount is not None:
                validate_currency_scale(self.fee_amount, self.currency)
            if self.net_amount is not None:
                validate_currency_scale(self.net_amount, self.currency)
        return self


class PaymentCreate(PaymentBase):
    pass


class PaymentRead(PaymentBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("event_time", "created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc_datetime(v) if v is not None else None


# --- ProviderWebhookEvent ---
class ProviderWebhookEventBase(ProcureMindBaseSchema):
    provider: str = Field(default="paypal", max_length=50)
    provider_event_id: str = Field(
        ..., max_length=100, description="Unique webhook event ID for deduplication"
    )
    event_type: str = Field(..., max_length=100)
    payment_id: uuid.UUID | None = None
    payload: dict[str, Any] | None = None
    status: str = Field(default="received", max_length=50)
    event_time: datetime | None = None


class ProviderWebhookEventCreate(ProviderWebhookEventBase):
    pass


class ProviderWebhookEventRead(ProviderWebhookEventBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @field_validator("event_time", "created_at", "updated_at", mode="after")
    @classmethod
    def ensure_utc(cls, v: datetime | None) -> datetime | None:
        return ensure_utc_datetime(v) if v is not None else None
