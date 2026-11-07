# ProcureMind

ProcureMind is an autonomous financial reconciliation engine designed for invoice, purchase order, and delivery note three-way matching, discrepancy resolution, and governed sandbox disbursements.

## Repository Monorepo Structure

```
PAYPAL/
├── backend/                  # FastAPI Application (Python, SQLAlchemy 2.0, Alembic)
│   ├── app/
│   │   ├── api/              # API routes (v1 health, readiness, and future endpoints)
│   │   ├── core/             # Configuration, CORS, database engine & session
│   │   ├── storage/          # Document object storage abstraction & implementations
│   │   └── main.py           # FastAPI ASGI entrypoint & middleware setup
│   ├── migrations/           # Alembic database migrations
│   ├── tests/                # Automated pytest suite
│   ├── alembic.ini           # Alembic database migration config
│   ├── pyproject.toml        # uv / Python project metadata & dependencies
│   ├── .env.example          # Backend environment placeholders
│   └── README.md             # Backend development guide
├── frontend/                 # Next.js App Router (TypeScript, Tailwind, TanStack Query)
│   ├── app/                  # App Router pages, layout, TanStack Query providers
│   ├── lib/                  # Utilities (cn helper)
│   ├── components.json       # shadcn/ui configuration
│   ├── package.json          # Node dependencies (pnpm)
│   ├── tailwind.config.ts    # Tailwind CSS styling config
│   ├── tsconfig.json         # TypeScript configuration
│   ├── .env.example          # Frontend environment placeholders
│   └── README.md             # Frontend development guide
├── .gitignore                # Global git ignore covering secrets, node_modules, .venv, data
└── README.md                 # System architecture and Phase 0 foundation documentation
```

---

## System Architecture & Technical Diagrams

> Complete diagrams, entity-relationship models, and sequence flows are cataloged in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### 1. High-Level Architecture

```mermaid
flowchart TD
    subgraph ClientTier ["Client Tier (Browser)"]
        UI["Next.js App Router (TypeScript, Tailwind, shadcn/ui)"]
        QueryClient["TanStack Query (Client Cache)"]
        UI --> QueryClient
    end

    subgraph APITier ["FastAPI Backend Engine (/api/v1)"]
        Router["FastAPI Application Router"]
        CORSMiddleware["Strict CORS Middleware"]
        AuthStorageService["ObjectStorageInterface (Local / S3)"]
        DownloadTokenService["Download Token Service (HMAC-SHA256)"]
        
        CORSMiddleware --> Router
        Router --> AuthStorageService
        Router --> DownloadTokenService
    end

    subgraph AuthoritativePersistence ["Authoritative Single Source of Truth"]
        Postgres[("PostgreSQL 16 (Neon Cloud / Local Docker)
        - Sole authority for all balances & ledger state
        - NUMERIC(18, 2) fixed precision (No floats)
        - Timezone-aware UTC timestamps
        - 14 Normalized relational tables")]
    end

    subgraph SecureStorage ["Private Document Storage"]
        LocalStorage["Local Private Directory (./local_storage/private)
        - Strictly path-contained
        - Server-generated UUID storage keys
        - Inaccessible via public web server"]
    end

    subgraph SecondaryStores ["Optional & Secondary Services (Non-Blocking)"]
        FalkorDB[("FalkorDB (Knowledge Graph)")]
        Chroma[("Chroma (Vector Embeddings)")]
        PayPalSandbox["PayPal REST API (Sandbox Only)"]
    end

    QueryClient -->|HTTPS REST| CORSMiddleware
    Router -->|SQLAlchemy 2.0 / Alembic| Postgres
    AuthStorageService --> LocalStorage
    Router -.-> FalkorDB
    Router -.-> Chroma
    Router -.-> PayPalSandbox
```

### 2. Financial Proceeds & Allocation Pipeline

```mermaid
flowchart LR
    subgraph Stage1 ["Stage 1: Payer Transaction"]
        PaymentNode["Payment (Gross/Fee/Net)"]
        Webhook["ProviderWebhookEvent (Unique Event ID)"]
        Webhook -.-> PaymentNode
    end

    subgraph Stage2 ["Stage 2: Provider Settlement"]
        SettlementNode["Settlement (Batch Payout)"]
        PaymentNode -->|Batched into| SettlementNode
    end

    subgraph Stage3 ["Stage 3: Bank Verification"]
        BankNode["BankTransaction (Credit Line / UTR)"]
        SettlementNode -->|Deposited into| BankNode
    end

    subgraph AllocationGate ["Stage 4: Governed Allocation"]
        AllocationNode["Allocation
        (ck_allocation_single_source)"]
        InvoiceNode["Invoice (Total / Balance)"]
        
        PaymentNode -->|Option A: Direct Capture Link| AllocationNode
        SettlementNode -.->|Option B: Batch Link| AllocationNode
        BankNode -.->|Option C: Direct Bank Link| AllocationNode
        AllocationNode -->|Applies to| InvoiceNode
    end
```

### 3. Document Ingestion & Safe Storage Pipeline

```mermaid
flowchart TD
    ClientUpload["Client Upload (POST /api/v1/documents)"] --> SizeCheck{"Size <= 15MB?"}
    SizeCheck -->|No| Err413["413 Payload Too Large"]
    SizeCheck -->|Yes| EmptyCheck{"File > 0 Bytes?"}
    EmptyCheck -->|No| Err400_Empty["400 Bad Request: Empty File"]
    EmptyCheck -->|Yes| ExtCheck{"Allowed Extension?<br/>(pdf, xlsx, csv, png, jpg)"}
    ExtCheck -->|No| Err400_Ext["400 Bad Request: Unsupported Type"]
    ExtCheck -->|Yes| TypeInspection{"Format Type"}

    TypeInspection -->|CSV| CSVValidation["Bounded UTF-8 Validation<br/>(Reject null bytes \\x00)"]
    TypeInspection -->|PDF / Image / Excel| MagicBytes["Binary Magic Bytes Check<br/>(%PDF-, PK\\x03\\x04, PNG, JPG)"]

    CSVValidation -->|Invalid| Err400_Content["400 Bad Request: Malformed"]
    MagicBytes -->|Mismatch| Err400_Content
    CSVValidation -->|Valid| HashGen["Compute SHA-256 Digest"]
    MagicBytes -->|Valid| HashGen

    HashGen --> DupeQuery{"SHA-256 in DB?"}
    DupeQuery -->|Yes| ReturnExisting["200 OK: Existing Document ID<br/>(is_duplicate = true; 0 disk bloat)"]
    
    DupeQuery -->|No| GenKey["Server Storage Key<br/>documents/YYYY/MM/DD/{uuid4}.ext"]
    GenKey --> ContainmentCheck{"Path Containment<br/>is_relative_to(base_dir)"}
    ContainmentCheck -->|Traversal Attempt| Err400_Traversal["400 Bad Request"]
    ContainmentCheck -->|Safe| WriteDisk["Write to Private Storage"]
    WriteDisk --> InsertDoc["Insert Document (status: 'uploaded')"]
    InsertDoc --> ReturnCreated["201 Created"]
```

---

## Architectural Decisions & System Boundaries

1. **PostgreSQL as Sole Authority**:
   - PostgreSQL (hosted on **Neon** for cloud environments) is the single source of truth for all transactional state, balances, ledger entries, matching decisions, and document metadata.
   - Secondary stores (FalkorDB, Chroma) and AI/LLM models must **never** be treated as authoritative for balances or match verdicts.

2. **Database Persistence & Migrations**:
   - Persistence is managed exclusively via **SQLAlchemy 2.0** declarative models (`Mapped[...]`, `mapped_column`) and versioned **Alembic** migrations.
   - All migrations must be reversible (`upgrade` and `downgrade`).

3. **Domain Authority in FastAPI**:
   - **FastAPI** owns all business operations, compliance validation, document parsing coordination, and external provider integrations (PayPal REST API, LLM API keys).
   - The Next.js frontend is a consumer of the FastAPI API and **never** directly accesses the database or duplicates core business logic.

4. **Strict CORS Policy**:
   - FastAPI enforces explicit origin checking via `CORSMiddleware`.
   - Allowed origins are configured via `CORS_ORIGINS` (defaulting to local development origins `http://localhost:3000` and `http://127.0.0.1:3000`). Wildcards (`"*"`) are disallowed in production.

5. **Document Object Storage Abstraction**:
   - Defined via `ObjectStorageInterface` in `backend/app/storage/interface.py`:
     - **Local Development**: Files are written to a private local filesystem directory (`./local_storage/`), ignored by Git.
     - **Hosted Private Storage**: Private S3-compatible object storage (e.g., AWS S3, Cloudflare R2, MinIO) with pre-signed short-lived URLs. Documents are never public.

6. **Non-Blocking Secondary Integrations (FalkorDB & Chroma)**:
   - **FalkorDB** provides secondary relational visualization and graph traversals. Nodes in FalkorDB are strictly referenced by their PostgreSQL primary key.
   - **Chroma** provides vector embeddings for similarity lookup when required.
   - **Non-blocking guarantee**: Outages, disconnections, or write failures in FalkorDB or Chroma will not abort or fail core PostgreSQL transactions or API requests.

7. **Financial Data Integrity & Provenance**:
   - All monetary amounts are handled strictly using Python `Decimal` or integer minor units—never IEEE 754 floating point numbers.
   - Source provenance (document ID, page number, bounding box/row, raw text, normalized value, extraction method, review state) is preserved for auditability.
   - AI will **never** autonomously approve financial payouts; human review states are mandatory for ambiguous or failing matches.
   - PayPal operations are strictly constrained to Sandbox/simulation environments.

---

## Required Environment Variables

### Backend (`backend/.env.example`)

| Variable | Description | Example / Default |
|---|---|---|
| `ENVIRONMENT` | Runtime mode (`development`, `test`, `production`) | `development` |
| `APP_NAME` | Service identifier | `ProcureMind API` |
| `API_V1_STR` | Prefix for version 1 API routes | `/api/v1` |
| `DEBUG` | Enable debug logs and detailed errors | `true` |
| `CORS_ORIGINS` | Comma-separated list of permitted origins | `http://localhost:3000,http://127.0.0.1:3000` |
| `DATABASE_URL` | PostgreSQL connection string (Neon or local) | `postgresql://postgres:postgres@localhost:5432/procuremind_dev` |
| `STORAGE_BACKEND` | Storage provider (`local` or `s3`) | `local` |
| `LOCAL_STORAGE_DIR` | Local directory for uploaded files | `./local_storage` |
| `S3_BUCKET_NAME` | Private S3 bucket name (for hosted) | `procuremind-private-docs` |
| `S3_REGION` | S3 AWS/cloud region | `us-east-1` |
| `S3_ENDPOINT_URL` | Optional custom S3 endpoint (e.g. MinIO/R2) | `""` |
| `S3_ACCESS_KEY_ID` | Storage access key | `""` |
| `S3_SECRET_ACCESS_KEY` | Storage secret key | `""` |
| `FALKORDB_ENABLED` | Toggle secondary graph integration | `false` |
| `CHROMA_ENABLED` | Toggle secondary vector storage | `false` |

### Frontend (`frontend/.env.example`)

| Variable | Description | Example / Default |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | Base URL for FastAPI backend | `http://localhost:8000` |

---

## Local Development Startup Commands

### 1. Backend Setup & Startup (Python + uv)

```bash
# Navigate to backend directory
cd backend

# Create virtual environment and install dependencies
uv venv
# Activate on Windows:
.venv\Scripts\activate
# Activate on macOS/Linux:
# source .venv/bin/activate

# Install dependencies in editable mode with dev tools
uv pip install -e ".[dev]"

# Create local environment file
cp .env.example .env

# Run automated tests
uv run pytest -v

# Start FastAPI development server
uv run uvicorn app.main:app --reload --port 8000
```
Backend API docs will be available at: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs).
Liveness probe: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health).
Readiness probe: [http://localhost:8000/api/v1/ready](http://localhost:8000/api/v1/ready).

### 2. Frontend Setup & Startup (Node.js + pnpm)

```bash
# Navigate to frontend directory
cd frontend

# Install dependencies
pnpm install

# Approve build scripts for native modules (sharp)
pnpm approve-builds --all

# Create local environment file
cp .env.example .env.local

# Run production build check
pnpm run build

# Start Next.js development server
pnpm dev
```
Frontend application will be available at: [http://localhost:3000](http://localhost:3000).

---

## Dependency-Aware Phase Plan

- **Phase 0: Architecture & Foundation** *(Current Phase - Completed)*
  - Establish monorepo structure, package managers (`uv`, `pnpm`), gitignore rules, environment examples.
  - Implement FastAPI health/readiness endpoints, strict CORS, and storage abstraction.
  - Implement Next.js App Router minimal shell with TanStack Query diagnostics.
  - Zero business logic, domain models, or credentials committed.

- **Phase 1: Persistence & Storage Foundation**
  - Define PostgreSQL relational schema via SQLAlchemy 2.0 (Vendors, Purchase Orders, Invoices, Delivery Receipts, Line Items, Audit Provenance).
  - Implement initial Alembic migration (`001_initial_schema.py`) with full up/down scripts.
  - Implement file upload intake pipeline adhering to `ObjectStorageInterface`.

- **Phase 2: Document Processing & Extraction Engine**
  - Implement document parsing engine (PyMuPDF for text, pdfplumber for tabular data, openpyxl for spreadsheets, OCR fallback).
  - Structured extraction using Pydantic v2 schemas and versioned prompt files.
  - Provenance capture (page, row, bbox, extraction confidence, review status flag).

- **Phase 3: Reconciliation & Matching Engine**
  - Deterministic 3-way matching rules (PO vs. Invoice vs. Delivery Receipt) using Decimal currency arithmetic.
  - Discrepancy taxonomy and categorization (unit price variance, quantity mismatch, missing line items).
  - Grounded AI exception explanations strictly anchored to extracted document context.

- **Phase 4: FalkorDB Secondary Visualization & Audit Graph**
  - Secondary graph indexing in FalkorDB mirroring PostgreSQL entities by ID.
  - Non-blocking asynchronous event updates; failures in graph writes do not block transaction completion.

- **Phase 5: PayPal Sandbox Payment Integration**
  - PayPal REST API integration (Sandbox environment only) for verified matching payouts.
  - Webhook listener for payment execution status and dispute logging.
  - Explicit compliance disclosures (Sandbox-only disclaimers; no automated regulatory clearance claims).

- **Phase 6: Frontend Reconciliation & Review Workspace**
  - Split-pane review UI showing document viewer and extracted line item comparison.
  - Discrepancy flagging, manual line adjustment, and human-in-the-loop approval workflow.
  - Real-time status updates via TanStack Query.

---

## Known Risks & Mitigation Strategies

1. **Floating-point inaccuracies in financial calculations**:
   - *Mitigation*: Strictly enforce `Decimal` types in Python and `NUMERIC(18, 2)` / integer cents in PostgreSQL.
2. **Database migration drift between local dev and Neon serverless**:
   - *Mitigation*: Enforce `alembic upgrade head` in CI/CD pipeline, `pool_pre_ping=True` in SQLAlchemy engine, and maintain tested downgrade migrations.
3. **Secondary graph/vector store outages degrading core availability**:
   - *Mitigation*: Isolate FalkorDB and Chroma behind resilient error handling; all primary business operations must complete even if graph or vector syncing fails.
4. **Hallucination or autonomous payout execution by LLM**:
   - *Mitigation*: Strict architectural boundary—LLMs only extract structured text and generate explanations; all approval and payment execution decisions require deterministic rule validation and human signoff.

