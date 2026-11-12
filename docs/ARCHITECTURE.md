# ProcureMind: Technical Architecture Reference

ProcureMind is an autonomous financial reconciliation engine designed for international trade, three-way document matching, automated discrepancy resolution, and governed sandbox disbursements.

This document serves as the persistent technical architecture reference for all data models, security boundaries, and operational pipelines.

> Canonical roadmap note: the original architecture draft used a different phase order. Under the
> current roadmap, PostgreSQL relationships are Phase 3, deterministic reconciliation is Phase 4,
> PayPal Sandbox is Phase 5, and grounded AI investigation is Phase 6. See `docs/PHASES.md` for the
> authoritative phase list.

---

## 1. High-Level System Architecture

```mermaid
flowchart TD
    subgraph ClientTier ["Client Tier (Browser)"]
        UI["Next.js App Router (TypeScript, Tailwind, shadcn/ui)"]
        QueryClient["TanStack Query (Client-side Cache & Polling)"]
        UI --> QueryClient
    end

    subgraph APITier ["FastAPI Application Backend (Python 3.11+)"]
        Router["FastAPI API Router (/api/v1)"]
        CORSMiddleware["Strict CORS Middleware"]
        AuthStorageService["ObjectStorageInterface (Local / S3)"]
        DownloadTokenService["Download Token Service (HMAC-SHA256)"]
        ExtractorService["Extraction Service Interface (PyMuPDF / OpenPyXL)"]
        ReconciliationEngine["Reconciliation & Discrepancy Engine (Future Phases)"]
        
        CORSMiddleware --> Router
        Router --> AuthStorageService
        Router --> DownloadTokenService
        Router --> ExtractorService
        Router --> ReconciliationEngine
    end

    subgraph AuthoritativePersistence ["Authoritative Single Source of Truth"]
        Postgres[("PostgreSQL 16 (Neon Cloud / Local Docker)
        - Sole authority for all balances, ledgers, & matches
        - NUMERIC(18, 2) fixed precision (No floats)
        - Timezone-aware UTC timestamps
        - 14 Normalized relational tables")]
    end

    subgraph SecureStorage ["Private Document Storage"]
        LocalStorage["Local Private Directory (./local_storage/private)
        - Strictly path-contained
        - Server-generated UUID keys
        - Inaccessible via public static web server"]
        S3Storage["Private S3 Bucket (Hosted Cloud Deployment)
        - Short-lived signed URLs only"]
    end

    subgraph SecondaryStores ["Optional & Secondary Services (Non-Blocking)"]
        FalkorDB[("FalkorDB (Knowledge Graph)
        - Graph traversals keyed by Postgres ID
        - Outages never roll back Postgres transactions")]
        Chroma[("Chroma (Vector Embeddings)
        - Unstructured similarity search")]
        PayPalSandbox["PayPal REST API (Sandbox Simulation Only)
        - Idempotent webhook processing
        - Mandatory human review for disbursements"]
    end

    QueryClient -->|HTTPS REST| CORSMiddleware
    Router -->|SQLAlchemy 2.0 / Alembic| Postgres
    AuthStorageService --> LocalStorage
    AuthStorageService -.-> S3Storage
    Router -.-> FalkorDB
    Router -.-> Chroma
    ReconciliationEngine -.-> PayPalSandbox
```

## Grounded AI Investigation & Reconciliation Explanations (Canonical Phase 6)

The feature exposes `POST /api/v1/transactions/{id}/investigate`. The path resolver accepts either
the transaction UUID or its case-insensitive human-readable reference, then the service canonicalizes
to the PostgreSQL UUID before querying child records. An optional discrepancy ID must belong to the
same transaction or the request fails with HTTP 400.

```mermaid
sequenceDiagram
    autonumber
    actor Reviewer as Human Reviewer
    participant UI as Payments / Investigation Panel
    participant API as FastAPI Investigation Route
    participant Service as Read-only Investigation Service
    participant DB as PostgreSQL (Source of Truth)
    participant LLM as Configured LLM Provider

    Reviewer->>UI: Ask about EXP-DEMO-004
    UI->>API: POST /transactions/{reference}/investigate
    API->>Service: Resolve reference; validate request
    Service->>DB: SELECT transaction-scoped invoices, payments, matches, discrepancies, evidence
    DB-->>Service: Persisted records only
    Service->>Service: Build exact financial facts + valid citation ID set
    Service->>LLM: Send minimized JSON context and question
    LLM-->>Service: Structured candidate explanation
    Service->>Service: Pydantic validation; filter unrecognized citation UUIDs
    Service-->>API: Facts + explanation + warnings; requires_human_review=true
    API-->>UI: Read-only investigation result
    UI-->>Reviewer: Show sources, financial facts, missing information, and optional draft
```

### Phase 6 boundaries

- PostgreSQL remains the only authority for amounts, currencies, transaction state, and reconciliation
  verdicts. The model supplies explanatory text only; financial facts are assembled from persisted
  records and existing Phase 4 results.
- All database reads are filtered by the canonical transaction ID. Model citation IDs are retained
  only when they are UUIDs in that request's context. Free text from persisted records is untrusted
  data, never instructions.
- Monetary facts preserve the currency attached to the source invoice, payment, fee, net proceeds, or
  discrepancy calculation. Cross-currency values are not subtracted. The response identifies the
  mismatch for reviewer attention.
- The service performs no database writes and cannot approve/reject matches, mutate balances, create
  allocations, initiate PayPal actions, or send clarification drafts. Every response requires a
  human reviewer. Requests for unauthorized actions are refused.
- Provider configuration comes from backend environment variables. Gemini uses the REST API through
  `httpx`; the API key is sent in a header. Missing keys, timeouts, HTTP failures, or invalid output
  return a safe unavailable response. Logs contain transaction IDs and error classes, never provider
  response bodies, prompts, keys, or full document text.
- Automated tests inject deterministic mocked providers. They verify isolation, ownership checks,
  refusal handling, citation filtering, currency labeling, failure fallback, and unchanged persisted
  rows. No live LLM or PayPal call is part of automated verification.

---

## 2. Normalized Relational Domain Model (Entity-Relationship Diagram)

PostgreSQL is the single source of truth. Every financial amount uses `NUMERIC(18, 2)` accompanied by an explicit uppercase 3-letter ISO-4217 currency code. All primary keys use native `UUIDv4`.

```mermaid
erDiagram
    Document ||--o{ ExtractedField : "contains"
    Document ||--o{ EvidenceReference : "source_document"
    Document ||--o{ Invoice : "source_file"
    Document ||--o{ ShippingBill : "source_file"
    
    ExportTransaction ||--o{ Invoice : "covers"
    ExportTransaction ||--o{ ShippingBill : "declares"
    ExportTransaction ||--o{ Payment : "receives"
    ExportTransaction ||--o{ Settlement : "settles"
    ExportTransaction ||--o{ BankTransaction : "deposits"
    ExportTransaction ||--o{ TransactionLink : "scopes"
    Invoice ||--o{ InvoiceLineItem : "contains"
    Invoice ||--o{ Payment : "receives"
    
    Settlement ||--o{ Payment : "batches"
    BankTransaction ||--o{ Settlement : "settles"
    
    Payment ||--o{ ProviderWebhookEvent : "triggers"
    Payment ||--o| Payment : "refunds_parent"
    
    TransactionLink ||--o| Invoice : "invoice_id"
    TransactionLink ||--o| ShippingBill : "shipping_bill_id"
    TransactionLink ||--o| Payment : "payment_id"
    TransactionLink ||--o| Settlement : "settlement_id"
    TransactionLink ||--o| BankTransaction : "bank_transaction_id"
    TransactionLink ||--o{ EvidenceReference : "supported_by"
    TransactionLink ||--o{ HumanDecision : "decided_by"

    Invoice ||--o{ Allocation : "settled_by"
    Payment ||--o{ Allocation : "allocates_from"
    Settlement ||--o{ Allocation : "allocates_from"
    BankTransaction ||--o{ Allocation : "allocates_from"
    
    Discrepancy ||--o{ EvidenceReference : "supported_by"
    Allocation ||--o{ EvidenceReference : "supported_by"
    EvidenceReference }o--|| TransactionLink : "proves"
    
    Discrepancy ||--o{ HumanDecision : "adjudicated_by"
    Allocation ||--o{ HumanDecision : "adjudicated_by"

    Document {
        uuid id PK
        string original_filename
        string media_type
        bigint size_bytes
        string sha256 UK
        string storage_key
        string document_type
        timestamptz upload_time
        string processing_status
        int page_count
        boolean is_demo
    }

    ExtractedField {
        uuid id PK
        uuid document_id FK
        string field_name
        text raw_value
        json normalized_value
        int page_number
        int row_number
        json bounding_box
        numeric confidence
        string review_state
        string extraction_method
        string reviewed_by
        timestamptz reviewed_at
    }

    ExportTransaction {
        uuid id PK
        string transaction_reference UK
        string exporter_name
        string exporter_tax_id
        string buyer_name
        string buyer_country
        string status
        boolean is_demo
    }

    Invoice {
        uuid id PK
        string invoice_number
        uuid export_transaction_id FK
        uuid document_id FK
        string seller_name
        string buyer_name
        date issue_date
        string currency
        numeric total_amount
        string shipment_reference
        boolean is_demo
    }

    InvoiceLineItem {
        uuid id PK
        uuid invoice_id FK
        int line_number
        string description
        numeric quantity
        numeric unit_price
        numeric total_amount
        string currency
        string hs_code
    }

    ShippingBill {
        uuid id PK
        string shipping_bill_number UK
        uuid export_transaction_id FK
        uuid document_id FK
        string invoice_reference
        string exporter_name
        string buyer_name
        date bill_date
        string declared_currency
        numeric declared_value
        boolean is_demo
    }

    BankTransaction {
        uuid id PK
        uuid export_transaction_id FK
        string bank_reference UK
        string currency
        numeric amount
        date transaction_date
        string transaction_type
        string status
        string remittance_reference
        boolean is_demo
    }

    Settlement {
        uuid id PK
        uuid export_transaction_id FK
        string provider_reference UK
        uuid bank_transaction_id FK
        string currency
        numeric amount
        date settlement_date
        string status
        string remittance_reference
        boolean is_demo
    }

    Payment {
        uuid id PK
        uuid export_transaction_id FK
        uuid invoice_id FK
        string provider
        uuid settlement_id FK
        string provider_order_id
        string provider_capture_id UK
        string provider_refund_id UK
        uuid parent_payment_id FK
        string invoice_reference
        string currency
        numeric gross_amount
        numeric fee_amount
        numeric net_amount
        string description
        string status
        timestamptz event_time
        string environment
        boolean is_demo
    }

    ProviderWebhookEvent {
        uuid id PK
        string provider
        string provider_event_id UK
        string event_type
        uuid payment_id FK
        json payload
        string status
        timestamptz event_time
    }

    Allocation {
        uuid id PK
        uuid invoice_id FK
        uuid payment_id FK
        uuid settlement_id FK
        uuid bank_transaction_id FK
        numeric allocated_amount
        string currency
        string allocation_method
        text evidence_notes
        string review_status
        boolean is_demo
    }

    Discrepancy {
        uuid id PK
        string rule_id
        string severity
        json compared_fields
        text description
        text recommended_action
        string status
        boolean is_demo
    }

    HumanDecision {
        uuid id PK
        string target_type
        uuid target_id
        string decision
        string reviewer_label
        text notes
        timestamptz decided_at
    }

    EvidenceReference {
        uuid id PK
        uuid discrepancy_id FK
        uuid allocation_id FK
        uuid transaction_link_id FK
        uuid document_id FK
        uuid extracted_field_id FK
        string source_record_type
        uuid source_record_id
        string original_filename
        string location_reference
        json bounding_box
        text raw_value
        text normalized_value
        string extraction_method
        string review_state
    }

    TransactionLink {
        uuid id PK
        uuid export_transaction_id FK
        string link_type
        string link_method
        string status
        uuid invoice_id FK
        uuid shipping_bill_id FK
        uuid payment_id FK
        uuid settlement_id FK
        uuid bank_transaction_id FK
        string explicit_reference
        string normalized_reference
        text evidence_notes
        boolean is_demo
    }
```

---

## 3. Financial Proceeds Pipeline & Allocation Architecture

The proceeds pipeline represents the lifecycle of funds received through payment providers and banking channels:

```mermaid
flowchart LR
    subgraph Stage1 ["Stage 1: Payer Transaction"]
        CustomerPayment["Payment Record
        - Provider: PayPal
        - Gross: $1,000.00 USD
        - Fee: $30.00 USD
        - Net: $970.00 USD"]
        Webhook["ProviderWebhookEvent
        - Unique Event ID
        - Deduplication Guard"]
        Webhook -.-> CustomerPayment
    end

    subgraph Stage2 ["Stage 2: Provider Settlement"]
        BatchSettlement["Settlement Record
        - Provider Reference: Payout Batch
        - Net Payout: $970.00 USD"]
        CustomerPayment -->|Batched into| BatchSettlement
    end

    subgraph Stage3 ["Stage 3: Bank Verification"]
        BankLine["BankTransaction Record
        - Type: Credit (Inflow)
        - UTR / Bank Ref: Wire Transfer
        - Verified Deposit: $970.00 USD"]
        BatchSettlement -->|Deposited into| BankLine
    end

    subgraph AllocationGate ["Stage 4: Governed Allocation"]
        AllocationNode["Allocation
        - Single Source Constraint
        - CheckConstraint enforces:
          exactly 1 of (Payment | Settlement | Bank)"]
        CommercialInvoice["Invoice Record
        - Total: $1,000.00 USD
        - Balance Due: $0.00 USD"]
        
        CustomerPayment -->|Option A: Direct Capture Link| AllocationNode
        BatchSettlement -.->|Option B: Batch Link| AllocationNode
        BankLine -.->|Option C: Direct Bank Link| AllocationNode
        AllocationNode -->|Applies to| CommercialInvoice
    end
```

---

## 4. Document Ingestion, Security & Storage Pipeline

```mermaid
flowchart TD
    ClientUpload["Client File Upload (POST /api/v1/documents)"] --> SizeCheck{"File Size <= 15 MB?"}
    SizeCheck -->|No| RejectSize["413 Payload Too Large"]
    SizeCheck -->|Yes| EmptyCheck{"File > 0 Bytes?"}
    EmptyCheck -->|No| RejectEmpty["400 Bad Request: Empty File"]
    EmptyCheck -->|Yes| ExtensionCheck{"Extension Allowed?<br/>(pdf, xlsx, csv, png, jpg)"}
    ExtensionCheck -->|No| RejectExt["400 Bad Request: Unsupported Type"]
    ExtensionCheck -->|Yes| TypeInspection{"Format Type Inspection"}

    subgraph FormatInspection ["Content & Signature Validation"]
        TypeInspection -->|CSV| CSVValidation["Bounded UTF-8 Validation
        - Decode text lines
        - Reject if null bytes \\x00 detected"]
        TypeInspection -->|PDF / Image / Excel| MagicBytes["Binary Magic Bytes Check
        - PDF: %PDF-
        - XLSX: PK\\x03\\x04
        - PNG: \\x89PNG
        - JPG: \\xff\\xd8\\xff"]
    end

    CSVValidation -->|Invalid| RejectContent["400 Bad Request: Malformed Content"]
    MagicBytes -->|Mismatch| RejectContent
    CSVValidation -->|Valid| HashGen["Compute SHA-256 Digest"]
    MagicBytes -->|Valid| HashGen

    HashGen --> DupeQuery{"SHA-256 exists in<br/>documents table?"}
    DupeQuery -->|Yes| ReturnExisting["200 OK: Return existing Document ID<br/>(is_duplicate = true; zero disk/DB bloat)"]
    
    DupeQuery -->|No| GenKey["Generate Server Storage Key<br/>documents/YYYY/MM/DD/{uuid4}.ext<br/>(Never use client filename on disk)"]
    GenKey --> ContainmentCheck{"Path Containment Check<br/>target_path.is_relative_to(base_dir)"}
    ContainmentCheck -->|Path Traversal Attempt| RejectTraversal["400 Bad Request: Path Traversal Blocked"]
    ContainmentCheck -->|Safe| WriteDisk["Write to Private Storage"]
    WriteDisk --> InsertDoc["Insert Document Record into Postgres<br/>(Status: 'uploaded')"]
    InsertDoc --> ReturnCreated["201 Created: Return DocumentRead Schema"]
```

---

## 5. Short-Lived Download Token & File Retrieval Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as User / Frontend UI
    participant API as FastAPI Backend (/api/v1/documents)
    participant TokenService as Download Token Service
    participant DB as PostgreSQL Database
    participant Storage as LocalStorageService

    User->>API: GET /api/v1/documents/{id}/download-url
    API->>DB: Query Document by ID
    DB-->>API: Document record (id, storage_key, original_filename)
    API->>TokenService: create_download_token(doc_id, expires_at)
    TokenService-->>API: HMAC-SHA256 Token
    API-->>User: 200 OK with download_url

    Note over User,API: User clicks or browser follows signed URL

    User->>API: GET /api/v1/documents/{id}/download?expires=...&token=...
    API->>TokenService: verify_download_token(doc_id, expires, token)
    alt Token Expired or HMAC Tampered
        TokenService-->>API: Invalid or Expired
        API-->>User: 403 Forbidden - Invalid or expired link
    else Token Valid
        TokenService-->>API: Valid
        API->>DB: Lookup Document by ID
        DB-->>API: Document (storage_key, filename)
        API->>Storage: get_file(document.storage_key)
        Storage->>Storage: Verify path containment
        Storage-->>API: Raw file bytes
        API-->>User: 200 OK with file attachment stream
    end
```

---

## 6. Transaction Relationships & Link Discovery Architecture (Phase 3)

Phase 3 establishes typed, verifiable relationships connecting commercial invoices, customs shipping bills, payment captures, provider payout settlements, and bank statement credits strictly within PostgreSQL (deferring FalkorDB entirely).

```mermaid
flowchart TD
    subgraph DealContext ["ExportTransaction Scope"]
        Deal["ExportTransaction (EXP-2026-001)"]
        Inv["Invoice (INV-2026-001)"]
        SB["ShippingBill (SB-1001)"]
        Pay["Payment (CAP-1001)"]
        
        Deal -->|export_transaction_id| Inv
        Deal -->|export_transaction_id| SB
        Deal -->|export_transaction_id| Pay
    end

    subgraph AutoDiscovery ["Exact-Reference Auto-Discovery (/discover-links)"]
        Norm{"normalize(invoice_number) == normalize(invoice_reference)?"}
        Inv -.-> Norm
        SB -.-> Norm
        
        Norm -->|Exact Single Match| CreateProposed["Create TransactionLink (status: proposed, method: auto_exact)"]
        Norm -->|Ambiguous Match >1| AmbiguousReport["Return Candidate IDs in unlinked_records (0 links created)"]
        Norm -->|Missing or Conflicting| UnlinkedReport["Return Explanatory Reason in unlinked_records"]
    end

    subgraph DBIntegrity ["PostgreSQL Engine Guarantees"]
        CK1["CHECK ck_transaction_link_typed_pair (Exactly 2 FKs populated)"]
        CK2["CHECK ck_transaction_link_reference_required_for_auto_exact"]
        UQ["Partial Unique Indexes (uq_tx_link_inv_sb, etc.)"]
        Restrict["ondelete RESTRICT (Audit history cannot be cascade-deleted)"]
    end

    subgraph Governance ["Human Oversight Gate (/decision)"]
        Reviewer["Human Auditor"] -->|POST decision| Decide{"Decision"}
        Decide -->|Approved| Confirmed["status: confirmed + HumanDecision Row"]
        Decide -->|Rejected| Rejected["status: rejected + HumanDecision Row"]
    end

    CreateProposed --> DBIntegrity
    CreateProposed --> Governance
```

### Relationship Discovery & Human Decision Sequence Flow

```mermaid
sequenceDiagram
    autonumber
    actor Auditor as Human Auditor
    participant UI as Web Client / Swagger UI
    participant API as FastAPI Backend (/api/v1/transactions)
    participant RelService as Relationship Service
    participant DB as PostgreSQL (Sole Authority)

    Note over Auditor,DB: 1. Automated Link Discovery
    Auditor->>UI: Triggers Link Discovery
    UI->>API: POST /api/v1/transactions/{id}/discover-links
    API->>RelService: discover_transaction_links(tx_id)
    RelService->>DB: Query owned Invoices, ShippingBills, Payments
    DB-->>RelService: Records belonging to transaction
    RelService->>RelService: Compare normalized references
    RelService->>DB: Insert proposed TransactionLink (status: proposed)
    DB-->>RelService: Created links
    RelService-->>API: DiscoveryResponse (created, existing, unlinked)
    API-->>UI: 200 OK with proposed links

    Note over Auditor,DB: 2. Human Review & Decision
    Auditor->>UI: Reviews proposed link and evidence
    UI->>API: POST /api/v1/transactions/{id}/links/{link_id}/decision
    API->>RelService: apply_link_decision(link_id, decision: approved)
    RelService->>DB: Update TransactionLink status to confirmed
    RelService->>DB: Insert HumanDecision audit record
    DB-->>RelService: Confirmed link & audit row
    RelService-->>API: Updated TransactionLink
    API-->>UI: 200 OK with confirmed link
```

---

## 7. End-to-End Trade Lifecycle Sequence

```mermaid
sequenceDiagram
    autonumber
    actor Exporter as Exporter / Payer
    participant NextJS as Next.js UI
    participant Backend as FastAPI Engine
    participant DB as PostgreSQL
    actor Auditor as Human Auditor

    Note over Exporter,NextJS: Phase 2: Ingestion & Registration
    Exporter->>NextJS: Uploads Commercial Invoice (PDF)
    NextJS->>Backend: POST /api/v1/documents (multipart)
    Backend->>Backend: Validate format, hash SHA-256, write private storage
    Backend->>DB: Insert Document with status uploaded
    Backend-->>NextJS: 201 Created with Document ID

    Note over Backend,DB: Phase 7: Deterministic parsing and OCR fallback
    Backend->>Backend: Parse document text and tables; OCR only pages without usable text
    Note over Backend,DB: Phase 8: Validated structured extraction (upcoming)
    Backend->>DB: Persist reviewed extracted fields and domain records

    Note over Backend,DB: Phase 4: Deterministic Reconciliation (implemented)
    Backend->>DB: Match Invoice against ShippingBill & PayPal Payment
    alt Perfect 3-Way Match
        Backend->>DB: Create suggested match; do not approve allocation automatically
        Auditor->>Backend: Review and approve through the human decision endpoint
    else Discrepancy Found (Amount or Fee variance)
        Backend->>DB: Create Discrepancy with severity error & EvidenceReferences
        Backend->>NextJS: Flag in Review Workspace
        Auditor->>NextJS: Inspects side-by-side evidence
        Auditor->>Backend: POST /decisions (Human Approval / Override)
        Backend->>DB: Insert HumanDecision record
    end
```

---

## 8. PayPal Sandbox Checkout & Verified Ingestion Architecture (Phase 5)

Phase 5 implements a functional, production-grade checkout and payment-event ingestion integration strictly bound to the **PayPal Sandbox environment**. In compliance with core architectural rules, money movement requires mandatory human auditor approval, payment orders are strictly bound to stored database invoices, and webhook events are deduplicated at the database tier.

```mermaid
flowchart TD
    subgraph Client ["Frontend Client Tier (/payments)"]
        UI_Gate["Auditor Unlock Card (X-Auditor-Key)"]
        UI_Buttons["PayPal JS SDK Buttons (Dynamic Currency)"]
        UI_Ledger["Audit & Payment Transparency Ledger"]
    end

    subgraph SecurityGate ["Auditor Authorization Gate (/invoices/{id}/approve)"]
        KeyCheck{"X-Auditor-Key valid & len >= 16?"}
        BalanceCheck{"remaining_balance > 0?"}
        PersistDecision["Persist HumanDecision (action: approved, target: invoice)"]
        UI_Gate --> KeyCheck
        KeyCheck -->|No| Err401["401 Unauthorized"]
        KeyCheck -->|Yes| BalanceCheck
        BalanceCheck -->|Zero| Err400["400 Bad Request: Paid in Full"]
        BalanceCheck -->|Positive| PersistDecision
    end

    subgraph OrderFlow ["Order Initiation (/payments/invoices/{id}/pay)"]
        LockInvoice["SELECT ... FOR UPDATE (Invoice)"]
        CheckApproval{"Invoice is approved?"}
        CheckExisting{"Active Pending Order in DB?<br/>(uq_payments_pending_invoice_order)"}
        ReuseOrder["Return Existing Pending Order (Idempotent)"]
        CallPayPalOrder["Call PayPal Orders v2 API<br/>(PayPal-Request-Id: PM-ORDER-{id})"]
        InsertPendingPayment["Insert Payment (status: 'pending', provider: 'paypal')"]
        
        PersistDecision -.-> LockInvoice
        LockInvoice --> CheckApproval
        CheckApproval -->|No| Err400_Unapproved["400 Bad Request: Unapproved"]
        CheckApproval -->|Yes| CheckExisting
        CheckExisting -->|Yes| ReuseOrder
        CheckExisting -->|No| CallPayPalOrder
        CallPayPalOrder --> InsertPendingPayment
        InsertPendingPayment --> ReturnOrder["Return 200 OK (order_id, approve_url)"]
        ReuseOrder --> ReturnOrder
        ReturnOrder --> UI_Buttons
    end

    subgraph CaptureFlow ["Bound Order Capture (/payments/orders/{order_id}/capture)"]
        BuyerApproval["Buyer Logs into Sandbox & Approves"]
        UI_Buttons --> BuyerApproval
        BuyerApproval --> CallCapture["POST /api/v1/payments/orders/{order_id}/capture"]
        LockPayment["SELECT ... FOR UPDATE (Payment bound to Order ID)"]
        RecheckApproval["Re-verify Invoice Approval & Remaining Balance"]
        CallPayPalCapture["Call PayPal Capture API<br/>(PayPal-Request-Id: PM-CAPTURE-{id})"]
        VerifyConsistency{"Status COMPLETED & Currency/Amount Match?"}
        UpdatePayment["Update Payment (status: 'completed', capture_id, fee, net)"]
        TriggerRecon["Trigger Phase 4 Reconciliation Engine"]

        CallCapture --> LockPayment
        LockPayment --> RecheckApproval
        RecheckApproval --> CallPayPalCapture
        CallPayPalCapture --> VerifyConsistency
        VerifyConsistency -->|Mismatch| Err400_Mismatch["400 Bad Request: Financial Mismatch"]
        VerifyConsistency -->|Match| UpdatePayment
        UpdatePayment --> TriggerRecon
        TriggerRecon --> ReturnCaptured["200 OK (Captured Payment)"]
        ReturnCaptured --> UI_Ledger
    end

    subgraph WebhookFlow ["Verified Webhook Ingestion (/api/v1/webhooks/paypal)"]
        WebhookArrival["PayPal Dispatches Webhook Event"]
        VerifyCrypto{"Verify Signature via PayPal API<br/>(Headers, Cert URL, Webhook ID)"}
        DedupeSavepoint{"Savepoint Insert provider_event_id<br/>(uq_provider_webhook_events_id)"}
        CaptureEvent{"Event Type?"}
        HandleCapture["Update Payment status to COMPLETED"]
        HandleRefund["Insert Discrete Refund Payment<br/>(provider_refund_id, parent_payment_id)"]
        TriggerReversalRecon["Trigger Reconciliation Engine (is_reversal=True)"]
        CommitAck["Commit Transaction & Return 200 OK"]

        WebhookArrival --> VerifyCrypto
        VerifyCrypto -->|Invalid| Reject400["400 Bad Request: Invalid Signature"]
        VerifyCrypto -->|Valid| DedupeSavepoint
        DedupeSavepoint -->|Duplicate| Ack200Dupe["Rollback Savepoint & Return 200 OK"]
        DedupeSavepoint -->|New Event| CaptureEvent
        CaptureEvent -->|PAYMENT.CAPTURE.COMPLETED| HandleCapture
        CaptureEvent -->|PAYMENT.CAPTURE.REFUNDED| HandleRefund
        HandleCapture --> CommitAck
        HandleRefund --> TriggerReversalRecon
        TriggerReversalRecon --> CommitAck
    end
```

### 8.1 Core Architectural & Security Rules

1. **Strict Sandbox Containment**:
   - `PAYPAL_BASE_URL` is validated using Python's `urlparse`. Scheme must be `https`, and hostname is strictly restricted to `api-m.sandbox.paypal.com` or `api.sandbox.paypal.com`. Subpaths, query strings, fragments, userinfo, and custom ports are rejected at startup.
   - `PAYPAL_ENVIRONMENT` must strictly equal `"sandbox"`. Live production environments and URLs are rejected by Pydantic validation.
   - Client secrets are never returned in HTTP responses or exposed to the frontend.

2. **Auditor Authorization Gate**:
   - `AUDITOR_API_KEY` is loaded from the environment and must be at least 16 characters long.
   - `POST /api/v1/invoices/{invoice_id}/approve` checks the `X-Auditor-Key` header via constant-time comparison (`secrets.compare_digest`), inserting an immutable `HumanDecision` record.
   - Invoices cannot be paid unless `is_approved == True` and `remaining_balance > 0`.

3. **Pending Order Idempotency**:
   - Database partial unique index `uq_payments_pending_invoice_order` on `payments(invoice_id)` where `status in ('pending', 'PENDING') AND provider = 'paypal'`.
   - Repeated calls to `/pay` return the existing pending order without creating redundant PayPal orders.
   - All outgoing PayPal order creation calls pass `PayPal-Request-Id: PM-ORDER-{invoice_id}`.

4. **Bound Capture Verification**:
   - Capture requests lock the associated `Payment` row using `SELECT ... FOR UPDATE`.
   - Re-verifies that the payment is linked to an approved invoice and the captured gross amount and currency match the stored order before marking as `completed`.
   - Captures are made idempotent using `PayPal-Request-Id: PM-CAPTURE-{order_id}`.

5. **Discrete Refund Modeling**:
   - Refunds from `PAYMENT.CAPTURE.REFUNDED` are stored as distinct `Payment` records populated with `provider_refund_id` and linked to the original capture via `parent_payment_id`.
   - Captures are never overwritten. A compensating reversal is passed to the Phase 4 reconciliation engine, proposing a reversal allocation for human auditor review.

6. **Database Webhook Deduplication & Atomic Commitment**:
   - Webhook events are checked against the unique constraint `provider_event_id` using nested database savepoints (`db.begin_nested()`).
   - Duplicate deliveries are acknowledged immediately with `200 OK` without side effects.
   - Responses are returned only after the event record, payment update, and reconciliation trigger are successfully committed.

---

### 8.2 Sequence Flows

#### Sequence 1: Auditor Approval & Sandbox Checkout Flow

```mermaid
sequenceDiagram
    autonumber
    actor Auditor as Human Auditor
    actor Buyer as International Buyer
    participant UI as Next.js Payments UI (/payments)
    participant API as FastAPI Backend (/api/v1)
    participant DB as PostgreSQL (Sole Authority)
    participant PayPal as PayPal Sandbox API

    Auditor->>UI: Inputs Auditor Key & clicks "Approve Invoice"
    UI->>API: POST /api/v1/invoices/{id}/approve (X-Auditor-Key)
    API->>API: Validate key length >= 16 & match AUDITOR_API_KEY
    API->>DB: Verify Invoice & insert HumanDecision(action: approved)
    DB-->>API: Persisted decision
    API-->>UI: 200 OK (status: approved)
    
    Note over UI,PayPal: PayPal SDK Buttons unlock dynamically
    Buyer->>UI: Clicks PayPal Checkout Button
    UI->>API: POST /api/v1/payments/invoices/{id}/pay
    API->>DB: Lock Invoice & check approval & active pending order
    alt Existing Pending Order Exists
        DB-->>API: Existing active Payment row
        API-->>UI: 200 OK (existing order_id, approve_url)
    else New Order Required
        API->>PayPal: POST /v2/checkout/orders (PayPal-Request-Id)
        PayPal-->>API: 201 Created (order_id, approve_url)
        API->>DB: Insert Payment (status: pending, invoice_id)
        API-->>UI: 200 OK (order_id, approve_url)
    end

    Buyer->>PayPal: Logs into Sandbox & Approves Transaction
    PayPal-->>UI: onApprove callback (orderID)
    UI->>API: POST /api/v1/payments/orders/{order_id}/capture
    API->>DB: Lock Payment & re-check Invoice approval & balance
    API->>PayPal: POST /v2/checkout/orders/{order_id}/capture (PayPal-Request-Id)
    PayPal-->>API: 201 Created (capture_id, status: COMPLETED, gross, fee, net)
    API->>API: Verify returned amount & currency match stored order
    API->>DB: Update Payment (status: completed, capture_id, fee, net)
    API->>API: Trigger Phase 4 Reconciliation Engine (auto-allocation)
    DB-->>API: Committed transaction
    API-->>UI: 200 OK (Captured Payment Details)
    UI-->>Auditor: Displays payment in Audit Ledger with SANDBOX badge
```

#### Sequence 2: Webhook Ingestion & Refund Reversal Flow

```mermaid
sequenceDiagram
    autonumber
    participant PayPal as PayPal Sandbox Webhook Dispatcher
    participant API as FastAPI Backend (/api/v1/webhooks/paypal)
    participant DB as PostgreSQL (Sole Authority)
    participant Recon as Phase 4 Reconciliation Engine

    PayPal->>API: POST /api/v1/webhooks/paypal (Headers + Event JSON)
    API->>PayPal: POST /v1/notifications/verify-webhook-signature
    PayPal-->>API: 200 OK (verification_status: SUCCESS)
    
    API->>DB: Begin Savepoint & insert ProviderWebhookEvent(provider_event_id)
    alt Duplicate Event ID
        DB-->>API: IntegrityError (duplicate provider_event_id)
        API->>DB: Rollback Savepoint
        API-->>PayPal: 200 OK (duplicate acknowledged idempotently)
    else New Event ID
        DB-->>API: Persisted ProviderWebhookEvent row
        alt Event is PAYMENT.CAPTURE.COMPLETED
            API->>DB: Update Payment status to completed
        else Event is PAYMENT.CAPTURE.REFUNDED
            API->>DB: Insert child Payment (status: refunded, provider_refund_id, parent_payment_id)
            API->>Recon: Trigger reconciliation proposal (is_reversal=True)
            Recon->>DB: Insert proposed compensating Allocation
        end
        API->>DB: Commit Outer Transaction
        API-->>PayPal: 200 OK (event processed and committed)
    end
```

---

## 9. Deterministic Text Extraction & OCR Fallback Architecture (Phase 7)

Phase 7 implements deterministic text, geometry, table, and spreadsheet extraction with selective OCR fallback. The pipeline guarantees provenance tracking without LLM hallucination, preserves terminal review states, and enforces strict operational bounds before parsing.

```mermaid
flowchart TD
    Doc["Uploaded Document in Private Storage (PDF / XLSX / CSV / Image)"]
    Doc --> CheckFormat{"Format Type"}

    CheckFormat -->|PDF| PDFPipe["PyMuPDF Native Text & Geometry
    + pdfplumber Tables"]
    PDFPipe --> CheckUsable{"has_usable_text?
    (chars >= 30 & alnum >= 10)"}
    CheckUsable -->|Yes| NativeText["Source: 'text'
    Confidence: None"]
    CheckUsable -->|No| RenderRaster["Rasterize Page at 150 DPI
    (Pixel budget <= 16M px)"]
    RenderRaster --> OCRAdapt["Tesseract OCR Adapter
    Source: 'ocr'
    Confidence: [0.0, 1.0]"]

    CheckFormat -->|XLSX| ZipPreCheck["ZIP Header Inspection
    (Uncompressed size <= 30 MB)"]
    ZipPreCheck --> OpenPyXL["openpyxl Parser
    - Preserve formulas
    - Bounded rows/cols/cells"]

    CheckFormat -->|CSV| CSVStd["Standard library csv.reader
    - Field size limit 64 KB
    - Record size limit 256 KB"]

    CheckFormat -->|Image| ImgCheck["Image Header Bounds
    (dim <= 5000, pixels <= 25M)"]
    ImgCheck --> OCRAdapt

    NativeText --> Output["ParsedDocument Response"]
    OCRAdapt --> Output
    OpenPyXL --> Output
    CSVStd --> Output

    Output --> TerminalGate{"Is Document Terminal?
    (approved / rejected)"}
    TerminalGate -->|Yes| KeepTerminal["Preserve status
    Update page_count only"]
    TerminalGate -->|No| UpdateParsed["Set status = 'parsed'
    Update page_count"]
```

### Key Technical Guarantees

1. **Selective OCR Fallback**:
   - Digital PDF pages with usable native text (`>= 30` non-whitespace characters and `>= 10` alphanumeric characters) use PyMuPDF directly without rasterization or OCR.
   - Only scanned image files or PDF pages lacking usable embedded text are rasterized at 150 DPI and processed through the injectable Tesseract OCR adapter.
   - For mixed documents, OCR is executed strictly on the pages that require it, yielding `parse_method = "mixed"`.

2. **Provenance & Normalized Geometry**:
   - Every text block captures 1-based `page_number`, 0-based `block_index`, source method (`text` or `ocr`), and normalized bounding box coordinates `[x0, y0, x1, y1]` scaled strictly between `0.0` and `1.0`.
   - OCR confidence is normalized to `[0.0, 1.0]`. Tesseract `-1` layout/unknown markers are mapped to `None`. Native PDF text confidence is strictly `None`.

3. **Multi-layer Defense Limits**:
   - **XLSX Zip-Bomb Prevention**: Pre-decompression central directory inspection verifies total uncompressed member bytes before `openpyxl` loads the workbook into memory.
   - **CSV Limits**: Bounded record size tracking across multiline quoted records (<= 256 KB) and per-field limit (<= 64 KB).
   - **Image & Render Budgets**: Dimensions verified via PIL header before decoding pixels; PDF OCR rasterization checks expected pixel count before rendering.
   - **Response Payload Budget**: Total output JSON serialized size must not exceed 10 MB.

4. **Terminal Review State Protection (Rule 3)**:
   - Invoices or documents previously transitioned to `approved` or `rejected` are permanently protected against regression: parsing success or failure will never mutate their status to `parsed` or `needs_review`.


## 10. LLM Structured Extraction & Provenance Tracking Architecture (Phase 8)

Phase 8 provides validated, provenance-tracked structured extraction for commercial invoices, retail receipts, and generic forms/key-value entities, consuming deterministic `ParsedDocument` output from Phase 7.

```mermaid
flowchart TD
    Req["POST /api/v1/documents/{id}/extract
    (document_kind: invoice | receipt | form)"] --> LockGuard["1. In-process asyncio.Lock(doc_id)
    (Prevents Event Loop Blocking)"]
    LockGuard --> DBLock["2. SELECT ... FOR UPDATE
    (PostgreSQL Cross-Worker Row Lock)"]
    DBLock --> TermCheck{"3. Terminal Document?
    (approved | rejected)"}
    TermCheck -->|Yes| HTTP400["400 Bad Request
    No Mutation"]
    TermCheck -->|No| ReviewCheck{"4. needs_review with
    prior LLM fields?"}
    ReviewCheck -->|Yes| HTTP409["409 Conflict
    Preserve Prior Fields"]
    ReviewCheck -->|No| ExtractedCheck{"5. Already extracted?"}
    ExtractedCheck -->|Yes| Idempotent["Return Existing Records
    200 OK"]
    ExtractedCheck -->|No| ParseBytes["6. parse_document_bytes()
    In-memory, No DB Commit, Lock Held"]
    ParseBytes --> SourceIdx["7. Build SourceIndex
    [source_id] -> raw_text, page, row, bbox"]
    SourceIdx --> PromptRender["8. Load Prompt Template
    (invoice_v1.md / receipt_v1.md / form_v1.md)
    Document text in delimiters as UNTRUSTED DATA"]
    PromptRender --> LLMCall["9. Provider extract_structured()
    (Gemini REST API / Mock)"]
    LLMCall --> Validate{"10. Pydantic v2
    Schema Validation"}
    Validate -->|Fails Once| SanitizedRetry["11. Sanitized Retry Prompt
    (Path + Error Type only; No PII/Input Values)"]
    SanitizedRetry --> ValidateRetry{"12. Validate Retry"}
    ValidateRetry -->|Fails Again| MarkNeedsReview["Mark needs_review
    400 Bad Request, Rollback"]
    Validate -->|Passes| ProvenanceRecon["13. Server Provenance Reconstruction
    Lookup cited source_ids in SourceIndex"]
    ValidateRetry -->|Passes| ProvenanceRecon
    ProvenanceRecon --> Arithmetic{"14. Arithmetic & Confidence Gate
    (confidence >= 0.85 & total = subtotal + tax + charges - discounts)"}
    Arithmetic -->|Mismatch / Low Conf| SaveFieldsOnly["Save ExtractedFields (PENDING)
    Save EvidenceReferences
    doc.status = needs_review
    created_invoice_id = None"]
    Arithmetic -->|Passed| CreateInvoice["Save ExtractedFields (PENDING)
    Save EvidenceReferences
    Create Invoice & InvoiceLineItems
    doc.status = extracted
    created_invoice_id = UUID"]
    SaveFieldsOnly --> CommitAtomic["15. db.commit() Atomic
    Release Row Lock & Async Lock"]
    CreateInvoice --> CommitAtomic
```

### Key Technical Guarantees

1. **Dual-Layer Concurrency Model**:
   - **In-process `asyncio.Lock`**: Serializes concurrent requests for the exact same document ID within a worker before initiating synchronous blocking database queries, preventing event loop thread starvation.
   - **PostgreSQL `SELECT ... FOR UPDATE`**: Acquires exclusive row locks across independent workers and database sessions, preventing race conditions, duplicate fields, or conflicting status updates.
   - **Lock-preserving Parsing**: Uses `parse_document_bytes()` during extraction without emitting intermediate database commits, preserving the row lock from request entry to final atomic commit.

2. **Server-Authoritative Provenance (Rule 2)**:
   - The LLM is supplied with bracketed source identifiers (e.g. `sheet:Sheet1:row:1:cell:0` or `page:1:block:2`) and is required to cite them in `source_ids`.
   - The server reconstructs `raw_value`, `page_number`, `row_number`, and `bounding_box` directly from the server-side `SourceIndex`.
   - Model-supplied coordinates or raw values are never trusted.
   - For every extracted field, an `EvidenceReference` row is persisted, strictly linking the source document and extracted field.

3. **Strict Validation & Sanitized Retry**:
   - Output is validated against strict Pydantic v2 models (`InvoiceExtraction`, `ReceiptExtraction`, `FormExtraction`) using Python 3.11 generic containers (`ExtractedFieldData[T]`).
   - Nullability rules are strictly enforced: `is_present=False` $\iff$ `value is None`, `source_ids=[]`, and non-empty `null_reason`.
   - On schema validation failure, the pipeline retries once with a sanitized prompt containing only field paths and validation error types; rejected input values and potential PII are omitted.
   - Double validation failure marks the document `needs_review` and returns HTTP 400 without creating invoice or extraction field records.

4. **Financial Accuracy & Arithmetic Verification (Rule 1)**:
   - All amounts and unit prices are parsed and manipulated using Python `Decimal` / `NUMERIC(18, 4)`. Binary floats are strictly prohibited.
   - Decimal arithmetic check verifies $\text{expected\_total} = \text{subtotal} + \text{tax} + \text{charges} - \text{discounts}$.
   - If `subtotal` is missing from the document, a derived subtotal is computed from line items for the arithmetic check only; it is never persisted as an `ExtractedField`.
   - Any arithmetic mismatch or confidence below `0.85` sets document status to `needs_review` and halts `Invoice` creation while preserving `ExtractedField` rows for human review.

5. **No Autonomous Approvals & Terminal Protection (Rule 3)**:
   - All `ExtractedField` records are saved with `ReviewState.PENDING`.
   - No `HumanDecision`, payment, allocation, or match is autonomously created or approved.
   - Terminal documents in `approved` or `rejected` status reject extraction requests with HTTP 400.
   - Re-extracting a `needs_review` document that already contains LLM fields returns HTTP 409 Conflict to protect prior auditor/extraction history.



