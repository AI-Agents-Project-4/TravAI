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
- Research agent: every fetch goes through one guard (https only, host allowlist, public IPs only, redirects re-checked), and every option is validated before it is saved (Kyle)
- Research agent: two separate allowlists, one for hosts the agent may fetch and one for hosts a `source_url` may link to; both start empty (Kyle)
- Research agent: the demo uses snapshot data derived from real API responses instead of live flight/hotel prices; `fetched_at` is the collection time and options are tagged `data_origin: snapshot` (Kyle)
- Research agent: only Geoapify is called live; Ignav and SerpAPI are used offline to gather test data (Kyle)
- Research agent: per-trip limits on tool calls, pages, tokens and time (Kyle)
- Research agent: demos and live runs use sandbox data (recorded flights and hotels, cached everything else) and can run live only Geoapify and `claude -p` with tools off; every other host and all web search is cache-only, and only `--gather` (`TRAVAI_ALLOW_NETWORK=1`) opens the rest, to collect new data (Kyle)
- Research agent: synthetic test data is never a silent fallback; it is used only when `TRAVAI_SANDBOX_DATA=synthetic` is set (Kyle)
- Research agent: sandbox is the default for everyone, and live use is an explicit `--gather` (Kyle)
