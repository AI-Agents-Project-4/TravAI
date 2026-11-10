# Backend (FastAPI) — owner: Jake

Project-wide rules and the product rules are in [../CLAUDE.md](../CLAUDE.md). The endpoints this service must serve are in [../docs/api-contract.md](../docs/api-contract.md).

> **Status:** no code yet. Jake owns the initial FastAPI + Postgres setup. Once it exists, update this file with the real commands, layout and DB/migration tooling, and add a `backend` job to `.github/workflows/ci.yml`.

## Intended conventions

- **uv** manages Python and dependencies (`pyproject.toml` + `uv.lock` are committed). Run everything through `uv run …`.
- **pytest** for tests, in `backend/tests/`.
- Settings come from environment variables (root `.env`, e.g. `DATABASE_URL`). Never hard-code secrets.
- All LLM, search and travel API keys live here, never in the frontend.
- Tests and CI must **not** call paid or live APIs (LLM, flights, search). Use recorded fixtures or fakes, so the planner can be tested with dummy research data.

## Agent boundaries

| Path | Owner | Writes | Reads |
|------|-------|--------|-------|
| `app/agents/research/` | Kyle | options (and progress steps) | trip request, cached options |
| `app/agents/planner/` | Jake | plans | trip request, options |

- The planner reads **only structured options from the DB**, never the research agent's transcript.
- Every stored option needs `price` (taxes and fees included, rounded up if estimated), `currency`, `source_url` and `fetched_at`. See the `Option` type in the API contract.
- If no plan can fit the budget, the planner returns `feasible: false` with `min_estimated_cost`. It never stretches a plan to fit.
- On redraft, items with `locked: true` must stay as they are. Return `dropped_items` with a reason for each.
