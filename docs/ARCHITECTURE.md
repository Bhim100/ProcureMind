# ProcureMind: Technical Architecture Reference

ProcureMind is an autonomous financial reconciliation engine designed for international trade, three-way document matching, automated discrepancy resolution, and governed sandbox disbursements.

This document serves as the persistent technical architecture reference for all data models, security boundaries, and operational pipelines.

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
    
    Settlement ||--o{ Payment : "batches"
    BankTransaction ||--o{ Settlement : "settles"
    
    Payment ||--o{ ProviderWebhookEvent : "triggers"
    
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
        string provider
        uuid settlement_id FK
        string provider_order_id
        string provider_capture_id UK
        string invoice_reference
        string currency
        numeric gross_amount
        numeric fee_amount
        numeric net_amount
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

    Note over Backend,DB: Phase 3 & 4: Parsing & LLM Extraction (Upcoming)
    Backend->>Backend: Deterministic text parsing / OCR / LLM validation
    Backend->>DB: Insert ExtractedFields & Domain Records (Invoice, Items)

    Note over Backend,DB: Phase 7: Deterministic Reconciliation
    Backend->>DB: Match Invoice against ShippingBill & PayPal Payment
    alt Perfect 3-Way Match
        Backend->>DB: Create Allocation with approved review_status
    else Discrepancy Found (Amount or Fee variance)
        Backend->>DB: Create Discrepancy with severity error & EvidenceReferences
        Backend->>NextJS: Flag in Review Workspace
        Auditor->>NextJS: Inspects side-by-side evidence
        Auditor->>Backend: POST /decisions (Human Approval / Override)
        Backend->>DB: Insert HumanDecision record
    end
```

