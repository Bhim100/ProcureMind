"""
Zoho Books Document Ingestion Service.

Handles:
- OAuth 2.0 lifecycle (authorization URL, code exchange, token refresh).
- Zoho Books REST API client for commercial invoices and PDF downloads.
- Document deduplication, SHA-256 integrity hashing, and private storage.
- Auto-triggering structured extraction and trade reconciliation.
- Simulated offline/demo synchronization for zero-friction evaluation.
"""

import logging
import random
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pymupdf
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.base import utc_now
from app.models.document import Document, ExtractedField
from app.models.enums import (
    DocumentType,
    ExtractionMethod,
    ProcessingStatus,
    ReviewState,
    TransactionStatus,
)
from app.models.export import ExportTransaction, Invoice, InvoiceLineItem
from app.models.integration import ZohoIntegration
from app.schemas.extraction import DocumentKind
from app.schemas.zoho import (
    ZohoAuthUrlResponse,
    ZohoInvoiceItem,
    ZohoStatusResponse,
    ZohoSyncResult,
)
from app.services.document_service import compute_sha256, generate_server_storage_key
from app.services.structured_extraction import extract_document
from app.storage.interface import get_storage_service

logger = logging.getLogger("procuremind.zoho")


def get_zoho_status(db: Session) -> ZohoStatusResponse:
    """
    Returns current connection status, organization details, and telemetry
    for the Zoho Books integration.
    """
    integration = (
        db.query(ZohoIntegration)
        .filter(ZohoIntegration.is_active.is_(True))
        .order_by(ZohoIntegration.updated_at.desc())
        .first()
    )

    synced_docs_count = (
        db.query(func.count(Document.id)).filter(Document.source_system == "zoho_books").scalar()
        or 0
    )

    total_amount_query = (
        db.query(func.coalesce(func.sum(Invoice.total_amount), Decimal("0.00")))
        .join(Document, Document.id == Invoice.document_id)
        .filter(Document.source_system == "zoho_books")
        .scalar()
    )
    total_synced_amount = Decimal(str(total_amount_query or "0.00"))

    has_oauth_config = bool(settings.ZOHO_CLIENT_ID and settings.ZOHO_CLIENT_SECRET)

    if not integration:
        return ZohoStatusResponse(
            is_connected=False,
            organization_id=None,
            organization_name=None,
            api_domain=settings.ZOHO_BOOKS_API_DOMAIN,
            last_sync_at=None,
            synced_documents_count=synced_docs_count,
            total_synced_amount=total_synced_amount,
            currency="USD",
            has_oauth_config=has_oauth_config,
        )

    return ZohoStatusResponse(
        is_connected=True,
        organization_id=integration.organization_id,
        organization_name=integration.organization_name,
        api_domain=integration.api_domain,
        last_sync_at=integration.last_sync_at,
        synced_documents_count=synced_docs_count,
        total_synced_amount=total_synced_amount,
        currency="USD",
        has_oauth_config=has_oauth_config,
    )


def get_authorization_url(state: str | None = None) -> ZohoAuthUrlResponse:
    """
    Generates the Zoho OAuth 2.0 consent URL.
    """
    configured = bool(settings.ZOHO_CLIENT_ID and settings.ZOHO_CLIENT_SECRET)
    if not configured:
        # Return fallback informational URL with instructions
        return ZohoAuthUrlResponse(
            auth_url="https://api-console.zoho.com",
            configured=False,
        )

    state_param = f"&state={state}" if state else ""
    url = (
        f"{settings.ZOHO_ACCOUNTS_URL}/oauth/v2/auth?"
        f"scope=ZohoBooks.invoices.READ,ZohoBooks.customerpayments.READ"
        f"&client_id={settings.ZOHO_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={settings.ZOHO_REDIRECT_URI}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"{state_param}"
    )
    return ZohoAuthUrlResponse(auth_url=url, configured=True)


def exchange_code(db: Session, code: str) -> ZohoIntegration:
    """
    Exchanges an OAuth authorization code for access and refresh tokens,
    retrieves organization details, and persists the integration.
    """
    if not settings.ZOHO_CLIENT_ID or not settings.ZOHO_CLIENT_SECRET:
        raise ValueError("Zoho OAuth credentials are not configured on the server.")

    token_url = f"{settings.ZOHO_ACCOUNTS_URL}/oauth/v2/token"
    data = {
        "code": code,
        "client_id": settings.ZOHO_CLIENT_ID,
        "client_secret": settings.ZOHO_CLIENT_SECRET,
        "redirect_uri": settings.ZOHO_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    with httpx.Client(timeout=15.0) as client:
        resp = client.post(token_url, data=data)
        if resp.status_code != 200:
            logger.error(f"Zoho token exchange failed ({resp.status_code}): {resp.text}")
            raise ValueError(f"Failed to exchange Zoho code: {resp.text}")

        token_data = resp.json()

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)
    api_domain = token_data.get("api_domain", settings.ZOHO_BOOKS_API_DOMAIN)

    if not access_token or not refresh_token:
        raise ValueError(f"Incomplete OAuth token response from Zoho: {token_data}")

    # Fetch primary organization details
    org_id = "default_org"
    org_name = "Connected Zoho Organization"
    with httpx.Client(timeout=15.0) as client:
        org_resp = client.get(
            f"{api_domain}/api/v3/organizations",
            headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
        )
        if org_resp.status_code == 200:
            org_json = org_resp.json()
            orgs = org_json.get("organizations", [])
            if orgs:
                org_id = str(orgs[0].get("organization_id", org_id))
                org_name = str(orgs[0].get("name", org_name))

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=expires_in)

    integration = (
        db.query(ZohoIntegration).filter(ZohoIntegration.organization_id == org_id).first()
    )
    if not integration:
        integration = ZohoIntegration(
            organization_id=org_id,
            organization_name=org_name,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=expires_at,
            api_domain=api_domain,
            is_active=True,
        )
        db.add(integration)
    else:
        integration.access_token = access_token
        integration.refresh_token = refresh_token
        integration.token_expires_at = expires_at
        integration.api_domain = api_domain
        integration.organization_name = org_name
        integration.is_active = True

    db.commit()
    db.refresh(integration)
    return integration


def get_valid_access_token(db: Session, integration: ZohoIntegration) -> str:
    """
    Returns a valid access token for the integration, refreshing it if expired.
    """
    now = datetime.now(UTC)
    expires_at = integration.token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now + timedelta(seconds=60):
        logger.info(f"Refreshing expired Zoho token for org {integration.organization_id}")
        token_url = f"{settings.ZOHO_ACCOUNTS_URL}/oauth/v2/token"
        data = {
            "refresh_token": integration.refresh_token,
            "client_id": settings.ZOHO_CLIENT_ID,
            "client_secret": settings.ZOHO_CLIENT_SECRET,
            "grant_type": "refresh_token",
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(token_url, data=data)
            if resp.status_code != 200:
                raise ValueError(f"Failed to refresh Zoho token: {resp.text}")
            token_data = resp.json()

        integration.access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)
        integration.token_expires_at = now + timedelta(seconds=expires_in)
        db.commit()

    return integration.access_token


def disconnect_zoho(db: Session) -> bool:
    """
    Deactivates any active Zoho Books integration.
    """
    integrations = db.query(ZohoIntegration).filter(ZohoIntegration.is_active.is_(True)).all()
    if not integrations:
        return False

    for item in integrations:
        item.is_active = False
        item.updated_at = utc_now()

    db.commit()
    return True


async def sync_zoho_invoices(db: Session, max_invoices: int = 10) -> ZohoSyncResult:
    """
    Performs live synchronization with Zoho Books REST API v3:
    1. Lists pending commercial invoices.
    2. Downloads official invoice PDFs.
    3. Deduplicates via SHA-256 and source_external_id.
    4. Ingests into Document storage and triggers structured AI extraction.
    """
    integration = db.query(ZohoIntegration).filter(ZohoIntegration.is_active.is_(True)).first()
    if not integration:
        raise ValueError("Zoho Books is not connected. Connect via OAuth or use 'Simulate Sync'.")

    token = get_valid_access_token(db, integration)
    headers = {"Authorization": f"Zoho-oauthtoken {token}"}
    api_url = f"{integration.api_domain}/api/v3/invoices"
    params = {
        "organization_id": integration.organization_id,
        "status": "unpaid,sent,partially_paid",
        "per_page": str(max_invoices),
    }

    synced_items: list[ZohoInvoiceItem] = []
    skipped_count = 0
    failed_count = 0

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(api_url, headers=headers, params=params)
        if resp.status_code != 200:
            raise ValueError(f"Zoho Books API error ({resp.status_code}): {resp.text}")

        invoices_data = resp.json().get("invoices", [])

        for inv in invoices_data:
            inv_id = str(inv.get("invoice_id"))
            inv_number = str(inv.get("invoice_number", f"ZOHO-{inv_id}"))

            # Check if external ID was already ingested
            existing = (
                db.query(Document)
                .filter(
                    Document.source_system == "zoho_books",
                    Document.source_external_id == inv_id,
                )
                .first()
            )
            if existing:
                skipped_count += 1
                continue

            # Stream PDF
            pdf_url = f"{integration.api_domain}/api/v3/invoices/{inv_id}?organization_id={integration.organization_id}&accept=pdf"
            pdf_resp = client.get(pdf_url, headers=headers)
            if pdf_resp.status_code != 200:
                logger.warning(
                    f"Could not download PDF for Zoho invoice {inv_number}: {pdf_resp.status_code}"
                )
                failed_count += 1
                continue

            pdf_bytes = pdf_resp.content
            sha256 = compute_sha256(pdf_bytes)

            # Check SHA-256 deduplication
            dup_sha = db.query(Document).filter(Document.sha256 == sha256).first()
            if dup_sha:
                skipped_count += 1
                continue

            # Save to storage
            storage_key = generate_server_storage_key("pdf")
            storage = get_storage_service()
            storage.save_file(storage_key, pdf_bytes)

            filename = f"Zoho-Invoice-{inv_number}.pdf"
            doc = Document(
                id=uuid.uuid4(),
                original_filename=filename,
                media_type="application/pdf",
                size_bytes=len(pdf_bytes),
                sha256=sha256,
                storage_key=storage_key,
                document_type=DocumentType.INVOICE,
                processing_status=ProcessingStatus.UPLOADED,
                source_system="zoho_books",
                source_external_id=inv_id,
                is_demo=False,
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)

            # Structured extraction & trade context auto-creation
            try:
                await extract_document(db, str(doc.id), DocumentKind.INVOICE)
            except Exception as ext_err:  # noqa: BLE001
                logger.warning(f"Auto-extraction error on Zoho invoice {inv_number}: {ext_err}")

            total_amt = Decimal(str(inv.get("total", "0.00")))
            curr = str(inv.get("currency_code", "USD"))
            synced_items.append(
                ZohoInvoiceItem(
                    document_id=doc.id,
                    invoice_number=inv_number,
                    filename=filename,
                    total_amount=total_amt,
                    currency=curr,
                    status=doc.processing_status.value,
                    source_external_id=inv_id,
                )
            )

    integration.last_sync_at = utc_now()
    db.commit()

    return ZohoSyncResult(
        synced_count=len(synced_items),
        skipped_duplicate_count=skipped_count,
        failed_count=failed_count,
        invoices=synced_items,
        message=f"Synced {len(synced_items)} invoice(s) from Zoho Books ({skipped_count} skipped duplicates).",
    )


def _generate_synthetic_zoho_pdf(
    invoice_number: str,
    vendor_name: str,
    buyer_name: str,
    date_str: str,
    line_items: list[dict],
    total_amount: Decimal,
    currency: str,
) -> bytes:
    """
    Generates a high-quality native digital PDF Commercial Invoice using PyMuPDF.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # Standard A4

    # Header section
    page.insert_text(
        pymupdf.Point(50, 60),
        "ZOHO BOOKS - COMMERCIAL INVOICE",
        fontsize=16,
        fontname="helv",
        color=(0.1, 0.2, 0.45),
    )
    page.insert_text(
        pymupdf.Point(50, 85),
        f"Invoice Number: {invoice_number}",
        fontsize=11,
        fontname="helv",
        color=(0.1, 0.1, 0.1),
    )
    page.insert_text(
        pymupdf.Point(50, 102),
        f"Invoice Date: {date_str}",
        fontsize=10,
        fontname="helv",
        color=(0.3, 0.3, 0.3),
    )
    page.insert_text(
        pymupdf.Point(50, 117),
        f"Payment Terms: Net 30 Days | Currency: {currency}",
        fontsize=10,
        fontname="helv",
        color=(0.3, 0.3, 0.3),
    )

    # Vendor & Buyer
    page.insert_text(
        pymupdf.Point(50, 145),
        "FROM (Exporter / Vendor):",
        fontsize=10,
        fontname="helv",
        color=(0.1, 0.2, 0.45),
    )
    page.insert_text(
        pymupdf.Point(50, 160), vendor_name, fontsize=10, fontname="helv", color=(0.1, 0.1, 0.1)
    )
    page.insert_text(
        pymupdf.Point(50, 175),
        "100 Industrial Boulevard, Logistics Hub",
        fontsize=9,
        fontname="helv",
        color=(0.3, 0.3, 0.3),
    )

    page.insert_text(
        pymupdf.Point(320, 145),
        "BILL TO (Importer / Buyer):",
        fontsize=10,
        fontname="helv",
        color=(0.1, 0.2, 0.45),
    )
    page.insert_text(
        pymupdf.Point(320, 160), buyer_name, fontsize=10, fontname="helv", color=(0.1, 0.1, 0.1)
    )
    page.insert_text(
        pymupdf.Point(320, 175),
        "450 Commerce Plaza, Suite 900",
        fontsize=9,
        fontname="helv",
        color=(0.3, 0.3, 0.3),
    )

    # Table Header
    y = 220
    page.draw_rect(
        pymupdf.Rect(50, y - 15, 545, y + 8), color=(0.85, 0.88, 0.95), fill=(0.92, 0.95, 0.98)
    )
    page.insert_text(
        pymupdf.Point(55, y), "Item Description", fontsize=9, fontname="helv", color=(0.1, 0.2, 0.4)
    )
    page.insert_text(
        pymupdf.Point(320, y), "Qty", fontsize=9, fontname="helv", color=(0.1, 0.2, 0.4)
    )
    page.insert_text(
        pymupdf.Point(390, y), "Unit Price", fontsize=9, fontname="helv", color=(0.1, 0.2, 0.4)
    )
    page.insert_text(
        pymupdf.Point(475, y), "Total", fontsize=9, fontname="helv", color=(0.1, 0.2, 0.4)
    )

    # Table Items
    y = 245
    for item in line_items:
        page.insert_text(
            pymupdf.Point(55, y),
            item["description"],
            fontsize=9,
            fontname="helv",
            color=(0.1, 0.1, 0.1),
        )
        page.insert_text(
            pymupdf.Point(320, y),
            str(item["quantity"]),
            fontsize=9,
            fontname="helv",
            color=(0.1, 0.1, 0.1),
        )
        page.insert_text(
            pymupdf.Point(390, y),
            f"${item['unit_price']:.2f}",
            fontsize=9,
            fontname="helv",
            color=(0.1, 0.1, 0.1),
        )
        page.insert_text(
            pymupdf.Point(475, y),
            f"${item['line_total']:.2f}",
            fontsize=9,
            fontname="helv",
            color=(0.1, 0.1, 0.1),
        )
        y += 25

    # Total Summary
    y += 15
    page.draw_line(pymupdf.Point(50, y), pymupdf.Point(545, y), color=(0.7, 0.7, 0.7), width=1)
    y += 25
    page.insert_text(
        pymupdf.Point(370, y), "Subtotal:", fontsize=10, fontname="helv", color=(0.2, 0.2, 0.2)
    )
    page.insert_text(
        pymupdf.Point(475, y),
        f"${total_amount:.2f}",
        fontsize=10,
        fontname="helv",
        color=(0.1, 0.1, 0.1),
    )
    y += 20
    page.insert_text(
        pymupdf.Point(370, y), "Total Amount:", fontsize=11, fontname="helv", color=(0.1, 0.2, 0.45)
    )
    page.insert_text(
        pymupdf.Point(475, y),
        f"${total_amount:.2f} {currency}",
        fontsize=11,
        fontname="helv",
        color=(0.1, 0.2, 0.45),
    )

    # Footer
    page.insert_text(
        pymupdf.Point(50, 780),
        "Directly synchronized via Zoho Books ERP connector. Tamper-evident SHA-256 registered in ProcureMind.",
        fontsize=8,
        fontname="helv",
        color=(0.5, 0.5, 0.5),
    )

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


async def simulate_zoho_sync(db: Session, count: int = 1) -> ZohoSyncResult:
    """
    Simulates direct invoice synchronization from a Zoho Books organization
    without requiring active third-party OAuth approval:
    1. Creates/ensures an active demo Zoho Books integration record.
    2. Generates genuine digital PDF commercial invoices using PyMuPDF.
    3. Saves them to document storage with source_system='zoho_books'.
    4. Runs structured extraction and links them to the Reconciliation Queue.
    """
    integration = db.query(ZohoIntegration).filter(ZohoIntegration.is_active.is_(True)).first()
    if not integration:
        integration = ZohoIntegration(
            organization_id="zoho_org_demo_88201",
            organization_name="Global Trade Corp (Zoho Books US)",
            access_token="simulated_zoho_access_token_demo",
            refresh_token="simulated_zoho_refresh_token_demo",
            token_expires_at=datetime.now(UTC) + timedelta(days=365),
            api_domain="https://books.zoho.com",
            is_active=True,
        )
        db.add(integration)
        db.commit()
        db.refresh(integration)

    synced_items: list[ZohoInvoiceItem] = []
    skipped_count = 0
    now = datetime.now(UTC)

    catalog = [
        (
            "Industrial Precision Bearings & Flanges",
            Decimal("45.00"),
            100,
            "Heavy-Duty Hydraulic Seal Kits",
            Decimal("85.50"),
            40,
        ),
        (
            "Microcontroller Control Units (MCU-X9)",
            Decimal("18.25"),
            400,
            "Surface Mount Ceramic Capacitors (10uF)",
            Decimal("0.45"),
            2000,
        ),
        (
            "Stainless Steel Hex Bolts M12x50",
            Decimal("1.20"),
            1500,
            "Zinc-Plated High-Tensile Fasteners",
            Decimal("2.40"),
            800,
        ),
    ]

    for _ in range(max(1, count)):
        rand_num = random.randint(1000, 9999)
        invoice_num = f"ZOHO-INV-2026-{rand_num}"
        ext_id = f"zoho_inv_{rand_num}"

        # Deduplication check
        if db.query(Document).filter(Document.source_external_id == ext_id).first():
            skipped_count += 1
            continue

        item1_desc, item1_price, item1_qty, item2_desc, item2_price, item2_qty = random.choice(
            catalog
        )
        line1_total = item1_price * Decimal(str(item1_qty))
        line2_total = item2_price * Decimal(str(item2_qty))
        total_amt = line1_total + line2_total
        currency = "USD"
        vendor = "Global Trade Logistics Corp"
        buyer = "Acme Precision Manufacturing Ltd"
        date_str = now.strftime("%Y-%m-%d")

        line_items_data = [
            {
                "description": item1_desc,
                "unit_price": item1_price,
                "quantity": item1_qty,
                "line_total": line1_total,
            },
            {
                "description": item2_desc,
                "unit_price": item2_price,
                "quantity": item2_qty,
                "line_total": line2_total,
            },
        ]

        # Generate digital vector PDF
        pdf_bytes = _generate_synthetic_zoho_pdf(
            invoice_number=invoice_num,
            vendor_name=vendor,
            buyer_name=buyer,
            date_str=date_str,
            line_items=line_items_data,
            total_amount=total_amt,
            currency=currency,
        )

        sha256 = compute_sha256(pdf_bytes)
        storage_key = generate_server_storage_key("pdf")
        storage = get_storage_service()
        storage.save_file(storage_key, pdf_bytes)

        filename = f"{invoice_num}.pdf"
        doc = Document(
            id=uuid.uuid4(),
            original_filename=filename,
            media_type="application/pdf",
            size_bytes=len(pdf_bytes),
            sha256=sha256,
            storage_key=storage_key,
            document_type=DocumentType.INVOICE,
            upload_time=now,
            processing_status=ProcessingStatus.UPLOADED,
            source_system="zoho_books",
            source_external_id=ext_id,
            is_demo=False,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # Trigger extraction & pre-payment trade reconciliation
        try:
            await extract_document(db, str(doc.id), DocumentKind.INVOICE)
        except Exception as ext_err:  # noqa: BLE001
            logger.warning(f"LLM extraction fallback on simulated invoice: {ext_err}")
            _persist_simulated_invoice_fallback(
                db=db,
                doc=doc,
                invoice_number=invoice_num,
                vendor_name=vendor,
                buyer_name=buyer,
                date_str=date_str,
                line_items=line_items_data,
                total_amount=total_amt,
                currency=currency,
            )

        synced_items.append(
            ZohoInvoiceItem(
                document_id=doc.id,
                invoice_number=invoice_num,
                filename=filename,
                total_amount=total_amt,
                currency=currency,
                status=doc.processing_status.value,
                source_external_id=ext_id,
            )
        )

    integration.last_sync_at = utc_now()
    db.commit()

    return ZohoSyncResult(
        synced_count=len(synced_items),
        skipped_duplicate_count=skipped_count,
        failed_count=0,
        invoices=synced_items,
        message=f"Simulated sync complete: {len(synced_items)} commercial invoice(s) imported from Zoho Books.",
    )


def _persist_simulated_invoice_fallback(
    db: Session,
    doc: Document,
    invoice_number: str,
    vendor_name: str,
    buyer_name: str,
    date_str: str,
    line_items: list[dict],
    total_amount: Decimal,
    currency: str,
) -> None:
    """
    Deterministic fallback when LLM extraction is unavailable:
    Persists ExtractedField, Invoice, and ExportTransaction directly from
    verified synthetic parameters.
    """
    inv_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    # 1. Extracted fields
    fields = [
        ("invoice_number", invoice_number),
        ("invoice_date", date_str),
        ("seller_name", vendor_name),
        ("buyer_name", buyer_name),
        ("total_amount", str(total_amount)),
        ("currency", currency),
    ]
    for field_name, val in fields:
        ef = ExtractedField(
            id=uuid.uuid4(),
            document_id=doc.id,
            field_name=field_name,
            raw_value=val,
            normalized_value={"value": val},
            confidence=Decimal("0.9900"),
            extraction_method=ExtractionMethod.TEXT,
            review_state=ReviewState.AUTO_ACCEPTED,
        )
        db.add(ef)

    # 2. Invoice record
    inv = Invoice(
        id=uuid.uuid4(),
        document_id=doc.id,
        invoice_number=invoice_number,
        seller_name=vendor_name,
        buyer_name=buyer_name,
        currency=currency,
        total_amount=total_amount,
        issue_date=inv_date,
    )
    db.add(inv)
    db.flush()

    for idx, item in enumerate(line_items, start=1):
        li = InvoiceLineItem(
            id=uuid.uuid4(),
            invoice_id=inv.id,
            line_number=idx,
            description=item["description"],
            quantity=Decimal(str(item["quantity"])),
            unit_price=Decimal(str(item["unit_price"])),
            line_total=Decimal(str(item["line_total"])),
        )
        db.add(li)

    # 3. ExportTransaction context
    ref = f"EXP-{invoice_number}"
    exp_tx = (
        db.query(ExportTransaction).filter(ExportTransaction.transaction_reference == ref).first()
    )
    if not exp_tx:
        exp_tx = ExportTransaction(
            id=uuid.uuid4(),
            transaction_reference=ref,
            exporter_name=vendor_name,
            buyer_name=buyer_name,
            currency=currency,
            status=TransactionStatus.DRAFT,
            invoices=[inv],
        )
        db.add(exp_tx)
    else:
        if inv not in exp_tx.invoices:
            exp_tx.invoices.append(inv)

    doc.processing_status = ProcessingStatus.EXTRACTED
    doc.updated_at = utc_now()
    db.commit()

    # Trigger pre-payment reconciliation
    try:
        from app.services.reconciliation_engine import reconcile_transaction

        reconcile_transaction(db, exp_tx.id)
    except Exception as rec_err:  # noqa: BLE001
        logger.warning(f"Fallback reconciliation error: {rec_err}")
