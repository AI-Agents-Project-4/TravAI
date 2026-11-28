# TravAI backend (owner: Jake)

The FastAPI service the frontend talks to. It runs the research agent (Kyle's code in `../researchAgent/`) and the planner agent, and stores trips, researched options and plans in Postgres. Endpoints and shapes: [../docs/api-contract.md](../docs/api-contract.md).

**Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0 (sync, psycopg 3), Alembic migrations, Postgres 17. [uv](https://docs.astral.sh/uv/) manages Python and dependencies.

## Setup

From the repo root:

```bash
cp .env.example .env          # once; DATABASE_URL and the planner settings live here
docker compose up -d db       # local Postgres on :5432
```

Then from `backend/`:

```bash
uv sync                        # installs Python 3.13 + dependencies into .venv
uv run alembic upgrade head    # create/update the tables
uv run uvicorn app.main:app --reload   # http://localhost:8000, docs at /docs
```

`GET /health` returns `{"status": "ok", "database": "ok"}` when the API can reach Postgres, and 503 when it can't.

### What a real trip needs

- **The research agent's setup** (its README "Setup"): `researchAgent/.env` with `GEOAPIFY_API_KEY`, the recorded flight/hotel data in `researchAgent/sandbox_data/` (local only; without it flights and hotels come back as gaps), and the `claude` CLI logged in.
- **The planner's model:** `PLANNER_LLM=cli` (default) uses the same `claude` CLI. `PLANNER_LLM=api` uses the Anthropic SDK with `ANTHROPIC_API_KEY`. `PLANNER_LLM=none` skips the model; plans then come from simple rules, and the progress steps say so.
- **To try the whole app with no keys and no model**, replay research from the committed cache with synthetic flights and hotels:

  ```bash
  RESEARCH_OFFLINE=true TRAVAI_SANDBOX_DATA=synthetic PLANNER_LLM=none uv run uvicorn app.main:app
  ```

  Then plan the trips in `researchAgent/tests/test_cases.json` exactly as written (e.g. DEN → "Tokyo, Japan", 2027-03-10, 5 days, 1 traveler, $5,000). Other trips aren't in the cache and will fail offline. Synthetic prices are labeled "TEST DATA" in every plan.

The backend never sets `TRAVAI_ALLOW_NETWORK` and refuses to start if it is set: research always runs in Kyle's sandbox mode.

## How a trip runs

```
POST /trips ── safety check (cached State Dept feed) ── Level 3/4? ── wait for POST /proceed
     │
     └─ background worker (one at a time, app/jobs.py)
          1. research: reuse an identical run from the last 24 h, or run the research agent
             (progress messages go straight to GET /trips/{id}/progress)
          2. map its output to Options (app/integration/options.py): party totals,
             estimates rounded up, links and text checked; saved to Postgres
          3. planner (app/agents/planner/): feasibility in code, then the model proposes
             3 themed plans, then rules check hours, stops, day length, budget and totals
          4. plans saved, trip "done" (or "failed" with the reason as the last step)
```

Redraft and save run in the request: `POST /plans/{id}/redraft` calls the planner model (tens of seconds); `PUT /plans/{id}` only recomputes totals.

## Running one trip for the eval

`app/cli.py` runs research and the planner with no server and no database, and prints the plans (or the infeasible verdict) plus every model call's tokens and cost:

```bash
uv run python -m app.cli ../evals/cases/01-tokyo-5d-5000.json --origin DEN --start-date 2027-03-10
uv run python -m app.cli case.json --mode single --out result.json   # the single-agent baseline
```

The eval cases leave `origin` and `start_date` empty, so pass them (or fill them in the cases). This makes real model calls; mind the cost.

## Checks (same as CI)

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

Tests need Postgres running. They use a separate `travai_test` database (created automatically, rebuilt from the migrations on every run), so your dev data is never touched. Set `TEST_DATABASE_URL` to use another one.

Tests never call paid or live APIs. The research agent runs for real but offline (`RESEARCH_OFFLINE=true`, synthetic flights and hotels), replaying its committed cache; the planner's model is a fake (`tests/fakes.py`).

## Changing the schema

1. Edit `app/models.py`.
2. `uv run alembic revision --autogenerate -m "add something"` and read the generated file in `migrations/versions/`.
3. `uv run alembic upgrade head`.

`tests/test_schema.py` fails if the models and migrations disagree.

## Layout

```
backend/
  app/
    main.py          # FastAPI app, CORS, routers, startup checks
    config.py        # settings from env / root .env
    db.py            # engine, per-request session, sessions for background jobs
    models.py        # tables (below)
    schemas.py       # request/response models (Pydantic)
    jobs.py          # the background worker
    pipeline.py      # a trip's job: research -> options -> planner -> plans
    cli.py           # one trip without the server (eval entry point)
    routes/          # health.py, trips.py, plans.py, views.py
    integration/     # research_agent.py (calls Kyle's code), options.py (output -> Options)
    agents/
      research/      # Kyle: README only; the code is in ../researchAgent/
      planner/       # Jake: the planner agent (see its README)
  migrations/        # Alembic
  tests/
```

## Tables

| Table | What | Written by |
|-------|------|-----------|
| `trips` | One trip request from the form, its status, safety warnings, feasibility result and agent mode | API, pipeline |
| `research_runs` | Each research agent run (request, status, output without private keys). Identical requests reuse a recent run: the search cache | pipeline |
| `progress_steps` | Progress messages shown while research and planning run | research agent, pipeline |
| `options` | Researched flights, hotels, activities, transport, food for a trip. Price (party total, taxes and fees included), `source_url` and `fetched_at` are required | pipeline (from research) |
| `plans` | The three itineraries. Days, cost breakdown and warnings are JSONB in the contract's shapes | planner |
| `model_calls` | Tokens and cost of every model call, per agent (`research`, `planner`, or `single` for the single-agent baseline) | both agents |
