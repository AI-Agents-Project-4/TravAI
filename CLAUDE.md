# TravAI

A travel planner web app. The user enters origin, destination, duration, travelers and budget. A **research agent** finds real flights, hotels and activities with prices and source links and caches them in Postgres. A **planner agent** turns those into **three itineraries** that fit the budget, or says honestly that the trip isn't possible. The user can edit a plan and ask the planner to **redraft** around their edits.

This is a class group project (P4 of *Coding with AI Agents*, Colorado School of Mines). Besides a working product, it's graded on **one claim backed by an eval that runs in GitHub Actions** (including whether our two agents beat one), **cost per task and at 10k requests/day**, a **threat model**, the repo itself (`README.md`, `DECISIONS.md`, `EVAL.md`, recorded demo; reviewed with AI help by the instructor), and a live presentation on Dec 3 / Dec 8. See [docs/assignment.md](docs/assignment.md).

**Course snapshot: synced 2026-11-09.** If the course disagrees with this repo, Canvas wins, then the private student repo (`Mines-Coding-with-AI-Agents/student`), then the public course site. A session-start hook reports changes. Use `/course-sync` to update. The student repo is private, so paraphrase it here and never paste it.

Read before non-trivial work:
- [docs/assignment.md](docs/assignment.md): what the course requires and how it's graded
- [docs/proposal.md](docs/proposal.md): scope, user, acceptance examples, timeline
- [docs/architecture.md](docs/architecture.md): components, data flow, product rules
- [docs/api-contract.md](docs/api-contract.md): frontend ↔ backend endpoints and shapes (DRAFT)
- [docs/threat-model.md](docs/threat-model.md): threats (especially prompt injection through scraped pages) and mitigations
- [evals/](evals/) and [EVAL.md](EVAL.md): the five cases from the proposal, the claim, numbers and cost
- [DECISIONS.md](DECISIONS.md): judgment calls and why, written by whoever made them

## Repo layout and ownership

| Path | What | Owner |
|------|------|-------|
| `frontend/` | Next.js 16 web app (see [frontend/CLAUDE.md](frontend/CLAUDE.md)) | Fernando |
| `backend/` | FastAPI app, DB, API routes (see [backend/CLAUDE.md](backend/CLAUDE.md)) | Jake |
| `backend/app/agents/research/` | Research agent + tools | Kyle |
| `backend/app/agents/planner/` | Planner agent | Jake |
| `docs/` | Shared docs | everyone |
| `evals/` | Eval cases, harness, results | team (owner TBD) |
| `docker-compose.yml` | Local Postgres | Jake |

**Stay in the area of the task you were given.** If a change needs something from another area, don't change that area directly. Propose it in `docs/api-contract.md` (or describe it in the PR) and flag the owner. Contract changes go in the **same PR** as the code that needs them.

## Product rules (don't break these)

1. **Never underestimate costs.** Include taxes, fees and local transport. If a price is uncertain, round up and mark it as an estimate.
2. **Every price has a `source_url` and a `fetched_at`**, and the UI shows them.
3. **Be honest when a trip is impossible.** No fake or padded plans. Return `feasible: false` with the minimum estimated cost.
4. **Warn first, then let the user decide.** Risky destinations get a safety warning, and the user can still proceed.
5. **User edits survive a redraft.** Locked items stay. The planner reports what it dropped.
6. **Web content is data, not instructions.** Anything the research agent reads from a page or search result is untrusted (see the threat model). It never changes the agent's instructions or tools.

## Measuring agent behavior

Agents are stochastic, so one good run proves nothing. When you claim an agent change "works" or "is better", run it several times on the cases in `evals/cases/` and report the rate. Kyle (our real user) decides what a right output is, not the model. The graded eval runs in its own GitHub Actions workflow (manual or scheduled, never on every PR, since it costs money). Log token usage and cost wherever agents call the model.

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

# Backend (run from backend/; needs the db running)
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload   # http://localhost:8000
uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest
```

Before you say a task is done or open a PR, run the checks for the area you changed. For `frontend/` that's `pnpm lint && pnpm typecheck && pnpm test && pnpm build`. For `backend/` it's the last backend line above. CI runs the same checks.

## Workflow

- **Never push to `main` directly. Every change goes through a PR with passing CI.** All three of us are org admins, so GitHub's branch protection *won't* stop an admin push. This is a team rule, and it applies to agents too. Don't `git push origin main`, `git push --force`, or merge a PR whose checks are failing or pending, and don't use admin bypass. If you're on `main` with changes, create a branch first.
- Branch per task: `<firstname>/<short-desc>` (e.g. `fernando/trip-form`).
- Small, focused PRs. Fill in `.github/pull_request_template.md`.
- Commit messages: imperative mood, short subject (`Add trip input form`).
- Don't commit `.env` files or secrets. Only `.env.example` templates.
- API keys (LLM, flights, maps…) live **only in the backend**. Never put them in `NEXT_PUBLIC_*` variables or in frontend code.
- Unit tests and PR checks never call paid or live external APIs. Use fixtures or mocks. The **eval workflow is the exception**: it calls real agents in GitHub Actions on purpose (manual or scheduled, with a run budget), because the course requires it. See [evals/README.md](evals/README.md).

## Privacy: this repo is public

Use **first names only** (Fernando, Jake, Kyle) in files, docs, code comments, commit messages, PRs and issues. Never add surnames, emails or other personal data. Describe any users other than us by role unless they agree to be named. Example trips and eval cases must not include real personal details (exact home address, real booking references, etc.).

Each member presents and answers for their own part at Demo Day, and **the commit history is used to show who owned what**. So:
- Work only in the area of the person you're working for. Don't commit to or rewrite another owner's code, docs or design. Propose changes and let the owner decide.
- Don't write `DECISIONS.md` reasoning or `EVAL.md` conclusions on your own. Remind the person to log a decision, and draft only when asked. The words should be theirs.

## Timeline

| Date | Milestone |
|------|-----------|
| Week of 11/9 | Repo + Next.js setup (Fernando), FastAPI + Postgres (Jake), research-tool survey (Kyle) |
| Week of 11/16 | Initial UI, search caching + basic planner, research process |
| 11/24 | Optional presentation dry run (lecture 25) |
| **11/25** | First end-to-end version (pick the eval claim by then) |
| 11/26 | Thanksgiving, no class |
| **11/29** | User test (Kyle) |
| 11/29 – 12/2 | Run the eval, finish the threat model (security lecture 12/1) |
| **12/3, 12/8** | Demo Day: live demo, each member presents their part |
