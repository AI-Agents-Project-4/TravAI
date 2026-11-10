# TravAI

An AI travel planner. Enter where you're going, for how long, and your budget. A research agent finds real, sourced prices for flights, hotels and activities, and a planner agent builds three itineraries that fit your budget. You can then edit one and have it redrafted around your changes.

Group project (P4) for *Coding with AI Agents* at Colorado School of Mines ([course](https://github.com/Mines-Coding-with-AI-Agents/course)).

- [Assignment and deliverables](docs/assignment.md)
- [Proposal](docs/proposal.md)
- [Architecture](docs/architecture.md)
- [API contract (draft)](docs/api-contract.md)
- [Threat model (draft)](docs/threat-model.md)
- [Evaluation: claim, numbers, cost](EVAL.md)
- [Decisions](DECISIONS.md)
- Recorded demo: *coming before Demo Day*

## Team

| Area | Owner |
|------|-------|
| Frontend (`frontend/`) | Fernando |
| Backend + planner agent (`backend/`) | Jake |
| Research agent (`backend/app/agents/research/`) | Kyle |

## Prerequisites

- Node.js 24+ and pnpm (`corepack enable`)
- Docker (for local Postgres)
- Python + [uv](https://docs.astral.sh/uv/) (backend)

## Quickstart

```bash
# Database
cp .env.example .env
docker compose up -d db

# Frontend
cd frontend
cp .env.example .env.local
pnpm install
pnpm dev            # http://localhost:3000
```

Backend setup instructions will be in [backend/README.md](backend/README.md).

## Contributing

`main` is protected. Create a branch (`<firstname>/<short-desc>`), open a PR, and make sure CI passes. See [CLAUDE.md](CLAUDE.md) for the conventions that both people and coding agents follow.
