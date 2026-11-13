# TravAI backend (owner: Jake)

The FastAPI service the frontend talks to. It stores trips, researched options and plans in Postgres, and will run the research and planner agents. Endpoints and shapes: [../docs/api-contract.md](../docs/api-contract.md).

**Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 (sync, psycopg 3), Alembic migrations, Postgres 17. [uv](https://docs.astral.sh/uv/) manages Python and dependencies.

## Setup

From the repo root:

```bash
cp .env.example .env          # once; DATABASE_URL lives here
docker compose up -d db       # local Postgres on :5432
```

Then from `backend/`:

```bash
uv sync                        # installs Python 3.13 + dependencies into .venv
uv run alembic upgrade head    # create/update the tables
uv run uvicorn app.main:app --reload   # http://localhost:8000, docs at /docs
```

`GET /health` returns `{"status": "ok", "database": "ok"}` when the API can reach Postgres, and 503 when it can't.

## Checks (same as CI)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

Tests need Postgres running. They use a separate `travai_test` database (created automatically, rebuilt from the migrations on every run), so your dev data is never touched. Set `TEST_DATABASE_URL` to use another one. Tests never call paid or live APIs.

## Changing the schema

1. Edit `app/models.py`.
2. `uv run alembic revision --autogenerate -m "add something"` and read the generated file in `migrations/versions/`.
3. `uv run alembic upgrade head`.

`tests/test_schema.py` fails if the models and migrations disagree.

## Layout

```
backend/
  app/
    main.py        # FastAPI app, CORS, routers
    config.py      # settings from env / root .env
    db.py          # engine + per-request session (get_db)
    models.py      # tables: trips, progress_steps, options, plans, model_calls
    schemas.py     # request/response models (Pydantic)
    routes/        # health.py, trips.py
    agents/
      research/    # Kyle: finds flights, hotels, activities → writes options
      planner/     # Jake: reads options → 3 itineraries, feasibility, redraft
  migrations/      # Alembic
  tests/
```

## Tables

| Table | What | Written by |
|-------|------|-----------|
| `trips` | One trip request from the form, its status and feasibility result | API, planner |
| `progress_steps` | Progress messages shown while research runs | research agent |
| `options` | Researched flights, hotels, activities, transport, food. Price (taxes and fees included), `source_url` and `fetched_at` are required. Cached by `destination`. | research agent |
| `plans` | The three itineraries. Days, cost breakdown and warnings are JSONB in the contract's shapes. | planner |
| `model_calls` | Tokens and cost of every LLM call, per agent (`research`, `planner`, or `single` for the single-agent baseline) | both agents |

## Status

Implemented: `GET /health`, `POST /trips` (stores the request; no research starts yet and no safety warnings yet), `GET /trips/{id}/progress`. Everything else in the contract is still to do.
