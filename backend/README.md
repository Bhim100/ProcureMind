# ProcureMind Backend

FastAPI application providing the core business operations and API endpoints for ProcureMind.

## Setup & Running with uv

1. Create a virtual environment and install dependencies:
```bash
uv venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

uv pip install -e ".[dev]"
```

2. Configure environment:
```bash
cp .env.example .env
```

3. Run development server:
```bash
uv run uvicorn app.main:app --reload --port 8000
```

4. Run tests:
```bash
uv run pytest
```

