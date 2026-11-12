"""
Zoho Books Integration Endpoints.

Provides REST API routes for:
- Checking connection state and sync metrics.
- Generating OAuth 2.0 authorization URL.
- OAuth redirect callback handler.
- Triggering live invoice document synchronization.
- Simulating Zoho Books document ingestion (zero credentials needed).
- Disconnecting the Zoho organization.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.zoho import (
    ZohoAuthUrlResponse,
    ZohoStatusResponse,
    ZohoSyncResult,
)
from app.services.zoho_service import (
    disconnect_zoho,
    exchange_code,
    get_authorization_url,
    get_zoho_status,
    simulate_zoho_sync,
    sync_zoho_invoices,
)

logger = logging.getLogger("procuremind.zoho.api")

router = APIRouter(prefix="/integrations/zoho", tags=["Zoho Books Integration"])


@router.get(
    "/status",
    response_model=ZohoStatusResponse,
    summary="Get Zoho Books integration status",
)
def get_status(db: Session = Depends(get_db)) -> ZohoStatusResponse:
    """Returns whether Zoho Books is connected, organization telemetry, and sync counts."""
    return get_zoho_status(db)


@router.get(
    "/auth-url",
    response_model=ZohoAuthUrlResponse,
    summary="Get Zoho OAuth authorization URL",
)
def get_auth_url(state: str | None = Query(None)) -> ZohoAuthUrlResponse:
    """Generates the consent URL for the Zoho OAuth 2.0 flow."""
    return get_authorization_url(state)


@router.get(
    "/callback",
    summary="OAuth callback handler for Zoho Books",
)
def oauth_callback(
    code: str = Query(..., description="Authorization code from Zoho"),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """
    Exchanges the OAuth authorization code for tokens and registers the organization.
    """
    try:
        integration = exchange_code(db, code)
        return {
            "status": "connected",
            "organization_id": integration.organization_id,
            "organization_name": integration.organization_name,
        }
    except Exception as exc:
        logger.error(f"Zoho callback failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth code exchange failed: {exc}",
        ) from exc


@router.post(
    "/sync",
    response_model=ZohoSyncResult,
    summary="Synchronize live invoices from Zoho Books",
)
async def sync_invoices(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> ZohoSyncResult:
    """
    Downloads unpaid/sent commercial invoices and official PDFs from Zoho Books,
    stores them in private document storage, and runs structured extraction.
    """
    try:
        return await sync_zoho_invoices(db, max_invoices=limit)
    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        ) from val_err
    except Exception as exc:
        logger.error(f"Zoho live sync failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Zoho synchronization error: {exc}",
        ) from exc


@router.post(
    "/simulate-sync",
    response_model=ZohoSyncResult,
    summary="Simulate Zoho Books invoice import without third-party credentials",
)
async def simulate_sync(
    count: int = Query(1, ge=1, le=5),
    db: Session = Depends(get_db),
) -> ZohoSyncResult:
    """
    Generates genuine PDF commercial invoices, saves them to Document storage with
    source_system='zoho_books', extracts line items, and surfaces them in the
    Reconciliation Queue.
    """
    try:
        return await simulate_zoho_sync(db, count=count)
    except Exception as exc:
        logger.error(f"Simulate Zoho sync failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Simulation failed: {exc}",
        ) from exc


@router.post(
    "/disconnect",
    summary="Disconnect Zoho Books organization",
)
def disconnect(db: Session = Depends(get_db)) -> dict[str, str]:
    """Deactivates the Zoho Books integration connection."""
    disconnected = disconnect_zoho(db)
    if not disconnected:
        return {
            "status": "already_disconnected",
            "message": "No active Zoho Books integration found.",
        }
    return {
        "status": "disconnected",
        "message": "Zoho Books organization disconnected successfully.",
    }
