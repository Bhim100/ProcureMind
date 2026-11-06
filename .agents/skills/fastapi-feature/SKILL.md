---
name: fastapi-feature
description: Adds a new backend feature to the FastAPI app end to end (SQLAlchemy model, Alembic migration, Pydantic schemas, service, route, tests). Use when asked to add or change an API endpoint, table, or backend resource.
---

# FastAPI Feature Skill

Follow these steps in order. Do not skip the verification step.

## 1. Understand and plan
- Read one existing, similar feature in `backend/app/` and match its structure.
- State the plan in a few lines: tables touched, endpoints added, schemas needed. Ask before proceeding if the change is destructive (drops/renames columns or tables).

## 2. Model (SQLAlchemy 2.0)
- Add the model in `app/models/` using `Mapped[...]` and `mapped_column()`.
- Money columns: `Numeric(18, 2)` plus a currency code column. Timestamps: timezone-aware UTC.
- Add indexes for columns used in filters or joins.

## 3. Migration (Alembic)
- Generate with `alembic revision --autogenerate -m "<message>"`.
- Open the generated file and review it by hand: confirm no unintended drops, correct nullability, sensible defaults for existing rows.
- Run `alembic upgrade head` locally and confirm `alembic downgrade -1` works.

## 4. Schemas (Pydantic v2)
- Create separate `Create`, `Update`, and `Read` schemas in `app/schemas/`.
- `Read` schemas use `model_config = ConfigDict(from_attributes=True)`.
- Validate at the boundary (lengths, enums, positive amounts).

## 5. Service and route
- Put logic in `app/services/`. Keep route handlers in `app/api/` thin.
- Declare `response_model` and explicit status codes on every route.
- Raise `HTTPException` with clear messages for not-found and validation conflicts.

## 6. Tests
- Add tests in `backend/tests/` covering at least one success path, one not-found or validation error, and any permission check.
- Use the existing test DB fixtures. Do not hit real external services (mock PayPal and the LLM).

## 7. Verify before finishing
Run: `ruff check . && ruff format --check . && mypy app && pytest -q` from `backend/`.
Report what you ran and the results. If anything fails, fix it rather than reporting partial success.

## 8. If the feature touches FalkorDB
Add or update the graph writer in `app/graph/` so nodes carry the Postgres record ID, and make the graph write idempotent.

