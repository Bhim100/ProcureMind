"""
Pydantic v2 schemas for Zoho Books Integration.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field

from app.schemas.common import ProcureMindBaseSchema


class ZohoStatusResponse(ProcureMindBaseSchema):
    """Current connection and synchronization telemetry for Zoho Books."""

    is_connected: bool = Field(..., description="Whether Zoho Books is connected and active")
    organization_id: str | None = Field(None, description="Zoho Organization ID if connected")
    organization_name: str | None = Field(None, description="Zoho Organization display name")
    api_domain: str = Field(default="https://books.zoho.com", description="Zoho API root domain")
    last_sync_at: datetime | None = Field(
        None, description="Last successful document sync timestamp"
    )
    synced_documents_count: int = Field(
        default=0, ge=0, description="Total documents ingested from Zoho"
    )
    total_synced_amount: Decimal = Field(
        default=Decimal("0.00"), description="Sum of amounts of Zoho invoices"
    )
    currency: str = Field(default="USD", description="Base reporting currency")
    has_oauth_config: bool = Field(
        default=False, description="Whether server has ZOHO_CLIENT_ID configured"
    )


class ZohoAuthUrlResponse(ProcureMindBaseSchema):
    """Response containing OAuth authorization URL."""

    auth_url: str = Field(..., description="Consent URL for initiating OAuth 2.0 flow")
    configured: bool = Field(
        ..., description="True if ZOHO_CLIENT_ID and SECRET are set in environment"
    )


class ZohoInvoiceItem(ProcureMindBaseSchema):
    """Basic metadata of an invoice synced from Zoho."""

    document_id: uuid.UUID
    invoice_number: str
    filename: str
    total_amount: Decimal
    currency: str
    status: str
    source_external_id: str


class ZohoSyncResult(ProcureMindBaseSchema):
    """Summary of a live or simulated Zoho Books synchronization."""

    synced_count: int = Field(
        default=0, description="Number of new invoices downloaded & extracted"
    )
    skipped_duplicate_count: int = Field(
        default=0, description="Number of invoices skipped because already ingested"
    )
    failed_count: int = Field(default=0, description="Number of invoices that encountered errors")
    invoices: list[ZohoInvoiceItem] = Field(
        default_factory=list, description="List of processed invoices"
    )
    message: str = Field(..., description="Human-readable result summary")
