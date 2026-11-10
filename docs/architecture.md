# Architecture

How the parts of TravAI fit together. For the exact request/response shapes, see [api-contract.md](api-contract.md). For scope and examples, see [proposal.md](proposal.md).

## Components and owners

| Component | Owner | Location | Stack |
|-----------|-------|----------|-------|
| Web app (UI) | Fernando | `frontend/` | Next.js 16 (App Router), React 19, Tailwind v4, TypeScript |
| API + persistence | Jake | `backend/` | Python, FastAPI, uv, Postgres |
| Research agent + tools | Kyle | `backend/app/agents/research/` | Python, LLM + search/travel tools |
| Planner agent | Jake | `backend/app/agents/planner/` | Python, LLM |
| Database | Jake | `docker-compose.yml` (local) | Postgres 17 |

## Request flow

```
 Browser (Next.js)                FastAPI                         Postgres
 ─────────────────                ───────                         ────────
 1. Trip form ── POST /trips ───▶ create trip, start research ──▶ trips
                                    │
 2. Progress  ◀─ GET progress ────  Research agent ──── saves ──▶ options
    screen       (poll or SSE)      (flights, hotels,              (price, currency,
                                     activities, transport)         source_url, fetched_at)
                                    │
 3. Compare 3 ◀─ GET plans ──────  Planner agent ───── reads ───  options
    plans                           builds 3 itineraries ─ saves ▶ plans
                                    or "not feasible"
 4. Edit plan (client-side running total)
 5. Redraft ── POST redraft ────▶ Planner agent: keep user edits,
              ◀─ plan + dropped ─  refit the rest to the budget
 6. Save ───── PUT plan ────────▶                         ──────▶ plans
```

Key points:

- **The research agent writes and the planner reads.** The planner never sees the research agent's conversation. It only gets the structured options in the database. That keeps the planner's context small and makes the cache reusable across trips to the same destination.
- **Cached options can be stale.** Every option has a `fetched_at` timestamp. The backend decides when an option is too old to reuse; the UI shows its age next to the price.
- **Progress updates** (for example "Found 4 flights, checking hotel prices") come from the research agent while it runs. Polling vs. Server-Sent Events: **TBD (Jake)**. The frontend should hide this choice behind one hook.
- **Redraft is authoritative about user edits.** Anything the user added, removed or moved must survive. The planner changes only the rest, and it returns what it dropped to stay under budget.

## Product rules (apply to every component)

1. **Never underestimate costs.** Include taxes, fees and local transport. When unsure, round up and say so. A plan that's too cheap is worse than one that's too expensive.
2. **Every price has a source.** It needs `source_url` and `fetched_at`, and the UI shows both.
3. **Be honest when a trip is impossible.** If no plan fits the budget, say so and give the minimum estimated cost (appendix example 4).
4. **Warn first, then let the user decide.** Risky destinations get a safety warning before planning, and the user can still continue (example 5).
5. **The user's edits come first.** A redraft never undoes something the user chose.

## Acceptance scenarios

These come from the proposal appendix. Each should work end-to-end by the user test on 11/29.

| # | Input | Expected |
|---|-------|----------|
| 1 | Tokyo, 5 days, 1 traveler, $5,000 | 3 distinct itineraries ≤ budget; edit + redraft keeps edits; running total updates |
| 2 | Colorado Springs, 1 day, $500, drive | No flight; driving selectable; day plan ≤ budget |
| 3 | Europe, 2 weeks, $10,000, start (+ optional end) | Chronologically sensible multi-stop route with travel between stops (**cuttable**) |
| 4 | Japan, 1 month, $500 | "Not feasible" with honest minimum cost; no fake plans |
| 5 | Ukraine, 3 days, $1,000 | Safety warning first; user can proceed; then normal 3 itineraries (**warnings are cuttable**) |

## Features we can cut

If time runs short, in this order: dangerous-area warnings, cross-country itineraries, travel customization features.
