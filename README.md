# RRM Backend

FastAPI backend for the Research Resource Manager.

## Run with Docker

```bash
docker compose up --build
```

API: http://localhost:8000 · Swagger UI: http://localhost:8000/docs

## Run locally

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
docker compose up -d db
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload
```

## Tests

```bash
.venv/bin/pytest                      # in-memory SQLite
docker compose exec db psql -U rrm -c 'CREATE DATABASE rrm_test'
TEST_DATABASE_URL=postgresql+psycopg://rrm:rrm@localhost:5432/rrm_test .venv/bin/pytest   # PostgreSQL
```

## Database migrations

The schema is managed with Alembic (`migrations/`). After changing `app/models.py`:

```bash
.venv/bin/alembic revision --autogenerate -m "describe the change"
.venv/bin/alembic upgrade head
```
