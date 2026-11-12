"""Pydantic v2 schemas for LLM structured document extraction.

Compatible with Python 3.11 generic syntax (TypeVar / Generic[T]).
All schemas enforce extra='forbid' to prevent unvalidated fields.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T")


class ExtractedFieldData(BaseModel, Generic[T]):
    """Generic atomic container for an extracted field with strict presence rules."""

    model_config = ConfigDict(extra="forbid")

    value: T | None = None
    is_present: bool = True
    null_reason: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_presence_and_nullability(self) -> "ExtractedFieldData[T]":
        if not self.is_present:
            if self.value is not None:
                raise ValueError("When 'is_present' is False, 'value' must be None")
            if self.source_ids:
                raise ValueError("When 'is_present' is False, 'source_ids' must be empty")
            if not self.null_reason or not self.null_reason.strip():
                raise ValueError(
                    "When 'is_present' is False, a non-empty 'null_reason' is required"
                )
        else:
            if self.value is None:
                raise ValueError(
                    "When 'is_present' is True, 'value' cannot be None (set is_present=False if absent)"
                )
            if not self.source_ids:
                raise ValueError(
                    "When 'is_present' is True, at least one 'source_ids' citation is required"
                )
            if self.null_reason is not None:
                raise ValueError("When 'is_present' is True, 'null_reason' must be None")
        return self


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------


class InvoiceLineItemExtraction(BaseModel):
    """Structured extraction of an itemized invoice line item."""

    model_config = ConfigDict(extra="forbid")

    line_number: int = Field(ge=1, description="1-based sequence index")
    description: ExtractedFieldData[str]
    quantity: ExtractedFieldData[str] = Field(
        description="Decimal string representation (e.g. '10.0000')"
    )
    unit_price: ExtractedFieldData[str] = Field(
        description="Decimal string representation (e.g. '15.50')"
    )
    line_total: ExtractedFieldData[str] = Field(
        description="Decimal string representation (e.g. '155.00')"
    )
    hs_code: ExtractedFieldData[str] | None = None


class InvoiceExtraction(BaseModel):
    """Structured extraction output for commercial invoices."""

    model_config = ConfigDict(extra="forbid")

    invoice_number: ExtractedFieldData[str]
    seller_name: ExtractedFieldData[str]
    buyer_name: ExtractedFieldData[str]
    issue_date: ExtractedFieldData[str] = Field(description="ISO-8601 calendar date YYYY-MM-DD")
    due_date: ExtractedFieldData[str] | None = None
    currency: ExtractedFieldData[str] = Field(
        description="3-letter uppercase ISO-4217 code (USD, EUR, etc.)"
    )
    subtotal: ExtractedFieldData[str] | None = None
    tax: ExtractedFieldData[str] | None = None
    charges: ExtractedFieldData[str] | None = None
    discounts: ExtractedFieldData[str] | None = None
    total_amount: ExtractedFieldData[str] = Field(
        description="Decimal string representation (e.g. '1250.00')"
    )
    line_items: list[InvoiceLineItemExtraction] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


class ReceiptLineItemExtraction(BaseModel):
    """Itemized receipt line item."""

    model_config = ConfigDict(extra="forbid")

    description: ExtractedFieldData[str]
    line_total: ExtractedFieldData[str] = Field(description="Decimal string representation")
    quantity: ExtractedFieldData[str] | None = None


class ReceiptExtraction(BaseModel):
    """Structured extraction output for retail receipts and point-of-sale slips."""

    model_config = ConfigDict(extra="forbid")

    merchant_name: ExtractedFieldData[str]
    date: ExtractedFieldData[str] = Field(description="ISO-8601 calendar date YYYY-MM-DD")
    currency: ExtractedFieldData[str] = Field(description="3-letter uppercase ISO-4217 code")
    subtotal: ExtractedFieldData[str] | None = None
    tax: ExtractedFieldData[str] | None = None
    total_amount: ExtractedFieldData[str] = Field(description="Decimal string representation")
    line_items: list[ReceiptLineItemExtraction] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Forms & Key-Value Entities
# ---------------------------------------------------------------------------


class FormEntityExtraction(BaseModel):
    """An individual key-value entity extracted from a generic document or form."""

    model_config = ConfigDict(extra="forbid")

    field_key: str = Field(
        description="Normalized snake_case identifier (e.g. 'tax_id', 'permit_number')"
    )
    entity_type: str = Field(
        description="Entity classification: text, date, amount, identifier, address"
    )
    data: ExtractedFieldData[str]


class FormRelationshipExtraction(BaseModel):
    """A semantic relationship between two extracted entities."""

    model_config = ConfigDict(extra="forbid")

    source_key: str = Field(description="field_key of the subject entity")
    target_key: str = Field(description="field_key of the object entity")
    relationship_type: str = Field(
        description="Predicate e.g. 'issued_by', 'located_at', 'applies_to'"
    )


class FormExtraction(BaseModel):
    """Structured extraction output for generic documents, forms, and custom filings."""

    model_config = ConfigDict(extra="forbid")

    entities: list[FormEntityExtraction] = Field(default_factory=list)
    relationships: list[FormRelationshipExtraction] = Field(default_factory=list)
