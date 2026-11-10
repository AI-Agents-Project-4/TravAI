# Decisions

> **Required by the course:** the judgment calls we made and why. Each entry is written **by the person who made the call**, in their own words. They'll be asked about these on presentation day. Coding agents can remind you to log a decision, but don't let them write the reasoning for you.

Format (newest first):

```
## YYYY-MM-DD — <decision> (<first name>)
**Context:** what forced the choice
**Options:** what else we considered
**Decision and why:**
**Revisit if:**
```

## To write up

Decisions already made that still need an entry:

- Repo layout: one repo with `frontend/` + `backend/` (Fernando)
- pnpm for the frontend; Vitest for frontend tests (Fernando)
- Next.js 16 + FastAPI + Postgres cache, from the proposal (team)
- Two agents (research → planner) rather than one, from the proposal (team). The eval must back this up, see [EVAL.md](EVAL.md)
- Protected `main`: PRs + passing CI, no required approvals (Fernando)
