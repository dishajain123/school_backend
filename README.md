# School Backend (FastAPI)

Production-oriented backend for the School Management System.

## Tech Stack
- Python 3.9+
- FastAPI
- SQLAlchemy (async) + asyncpg
- Alembic (migrations)
- JWT auth
- MinIO/object storage integration
- Pytest

## Project Structure
- `app/api/v1/endpoints/` REST endpoints by module
- `app/services/` business logic
- `app/repositories/` DB/data access layer
- `app/schemas/` request/response schemas
- `app/models/` SQLAlchemy models
- `app/core/` config, security, shared infra
- `app/middleware/` cors, request-id, rate-limit, logging
- `migrations/` Alembic migration scripts
- `scripts/` bootstrap/seed utilities
- `tests/` test suite

## Local Setup
1. Create and activate a virtualenv:
```bash
python3 -m venv .venv
source .venv/bin/activate
```
2. Install dependencies:
```bash
pip install -r requirements.txt -r requirements-dev.txt
```
3. Configure env:
```bash
cp .env.example .env
```
4. Update at least:
- `DATABASE_URL`
- `SECRET_KEY`
- `MINIO_*` (or set `MINIO_ENABLED=false` for local DB-only testing)

## Run Database Migrations
```bash
alembic upgrade head
```

## Run Server
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Health check:
```bash
curl http://127.0.0.1:8000/health
```

## Run Tests
```bash
pytest -q
```

## Useful Seed Scripts
- `scripts/seed_roles_permissions.py`
- `scripts/seed_masters.py`
- `scripts/seed_demo_data.py`
- `scripts/create_staff_admin.py`

Run example:
```bash
python -m scripts.seed_masters
```

## Environment Notes
- `ENVIRONMENT` supports: `production | staging | development | local`
- `DEBUG=true` is only allowed in `local/development`
- `EXPOSE_OTP_HINT_IN_FORGOT_PASSWORD` should remain `false` outside local testing
- `DEFAULT_SCHOOL_ID` should be set for strict single-school fallback behavior

## Deployment Notes (Baseline)
- Use managed Postgres and set `DATABASE_URL` via secret manager
- Set strong `SECRET_KEY` (32+ chars)
- Configure strict `ALLOWED_ORIGINS` (no wildcard)
- Run migrations before app start
- Keep `local_storage/` out of source control (runtime-only data)
- Configure object storage credentials/permissions with least privilege

## Pre-Share Checklist
- No secrets in git (`.env` ignored)
- No runtime files in git (`local_storage/` ignored)
- Tests pass (`pytest -q`)
- Migrations are up to date (`alembic upgrade head`)
