# TravAI

A travel planner web app. The user enters origin, destination, duration, travelers and budget. A **research agent** finds real flights, hotels and activities with prices and source links and caches them in Postgres. A **planner agent** turns those into **three itineraries** that fit the budget, or says honestly that the trip isn't possible. The user can edit a plan and ask the planner to **redraft** around their edits.

Read before non-trivial work:
- [docs/proposal.md](docs/proposal.md): scope, user, acceptance examples, timeline
- [docs/architecture.md](docs/architecture.md): components, data flow, product rules
- [docs/api-contract.md](docs/api-contract.md): frontend ↔ backend endpoints and shapes (DRAFT)

## Repo layout and ownership

| Path | What | Owner |
|------|------|-------|
| `frontend/` | Next.js 16 web app (see [frontend/CLAUDE.md](frontend/CLAUDE.md)) | Fernando |
| `backend/` | FastAPI app, DB, API routes (see [backend/CLAUDE.md](backend/CLAUDE.md)) | Jake |
| `backend/app/agents/research/` | Research agent + tools | Kyle |
| `backend/app/agents/planner/` | Planner agent | Jake |
| `docs/` | Shared docs | everyone |
| `docker-compose.yml` | Local Postgres | Jake |

**Stay in the area of the task you were given.** If a change needs something from another area, don't change that area directly. Propose it in `docs/api-contract.md` (or describe it in the PR) and flag the owner. Contract changes go in the **same PR** as the code that needs them.

## Product rules (don't break these)

1. **Never underestimate costs.** Include taxes, fees and local transport. If a price is uncertain, round up and mark it as an estimate.
2. **Every price has a `source_url` and a `fetched_at`**, and the UI shows them.
3. **Be honest when a trip is impossible.** No fake or padded plans. Return `feasible: false` with the minimum estimated cost.
4. **Warn first, then let the user decide.** Risky destinations get a safety warning, and the user can still proceed.
5. **User edits survive a redraft.** Locked items stay. The planner reports what it dropped.

## Commands

```bash
# Frontend (run from frontend/)
pnpm install
pnpm dev          # http://localhost:3000
pnpm lint
pnpm typecheck
pnpm test         # vitest run
pnpm build

# Database (run from repo root; first: cp .env.example .env)
docker compose up -d db
docker compose down

# Backend: Jake adds these once backend/ has a pyproject.toml (uv run ...)
```

Before you say a task is done or open a PR, run the checks for the area you changed. For `frontend/` that's `pnpm lint && pnpm typecheck && pnpm test && pnpm build`. CI runs the same checks.

## Workflow

- `main` is protected: all changes go through a PR, and CI must pass.
- Branch per task: `<firstname>/<short-desc>` (e.g. `fernando/trip-form`).
- Small, focused PRs. Fill in `.github/pull_request_template.md`.
- Commit messages: imperative mood, short subject (`Add trip input form`).
- Don't commit `.env` files or secrets. Only `.env.example` templates.
- API keys (LLM, flights, maps…) live **only in the backend**. Never put them in `NEXT_PUBLIC_*` variables or in frontend code.
- Tests must not call paid or live external APIs. Use fixtures or mocks.

## Privacy: this repo is public

Use **first names only** (Fernando, Jake, Kyle) in files, docs, code comments, commit messages, PRs and issues. Never add surnames, emails or other personal data. Example trips must not include real personal details.

## Timeline

| Date | Milestone |
|------|-----------|
| Week of 11/9 | Repo + Next.js setup (Fernando), FastAPI + Postgres (Jake), research-tool survey (Kyle) |
| Week of 11/16 | Initial UI, search caching + basic planner, research process |
| **11/25** | First end-to-end version |
| **11/29** | User test (Kyle) |
| **12/3, 12/8** | Presentations |
