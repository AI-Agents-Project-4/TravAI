# API contract (frontend ↔ backend)

> **Status: DRAFT.** Jake and Fernando still need to agree on it. Until then, treat the shapes as a starting point, not a promise.
>
> **Rule:** when an endpoint or shape changes, update this file in the same PR as the code, and tag the other side for review. Both `frontend/` and `backend/` code follow this file.

Base URL: `NEXT_PUBLIC_API_BASE_URL` (local default `http://localhost:8000`). JSON everywhere. Field names use `snake_case`. Money is a decimal number in `currency` (ISO 4217). Timestamps are ISO 8601 UTC.

## Shared types

```ts
type Money = { amount: number; currency: string };  // e.g. { amount: 1249.0, currency: "USD" }

type OptionKind = "flight" | "hotel" | "activity" | "transport" | "food";

// One researched thing the planner can use. Written by the research agent.
type Option = {
  id: string;
  kind: OptionKind;
  title: string;                 // "Round trip DEN–HND, ANA", "Senso-ji Temple"
  description?: string;
  price: Money;                  // total for the whole party, taxes and fees included
  price_is_estimate: boolean;    // true if there was no exact quote (then it's rounded up)
  source_url: string;            // required, and shown in the UI
  fetched_at: string;            // when the price was retrieved
  location?: { name: string; lat?: number; lng?: number };
  duration_minutes?: number;
  opening_hours?: string;
  details?: Record<string, unknown>;  // per-kind extras (airline, stops, check-in, ...)
};

type ScheduledItem = {
  option_id: string;
  start_time?: string;           // "09:30" local time
  end_time?: string;
  locked: boolean;               // true = the user placed it, so a redraft must keep it
};

type Day = { day: number; date?: string; items: ScheduledItem[] };

type Warning = {
  kind: "safety" | "stale_data" | "estimate" | "over_budget";
  message: string;
  source_url?: string;
};

type Plan = {
  id: string;
  trip_id: string;
  title: string;                 // "Temples and history"
  summary: string;
  flight_option_id?: string;     // none for drive-only trips
  hotel_option_id?: string;
  days: Day[];
  cost_breakdown: { category: OptionKind | "other"; total: Money }[];
  total: Money;
  budget: Money;
  warnings: Warning[];
  saved: boolean;
};
```

## Endpoints

### `POST /trips`: start planning

```json
{
  "origin": "DEN",
  "destination": "Tokyo, Japan",
  "start_date": "2027-03-10",
  "duration_days": 5,
  "travelers": 1,
  "budget": { "amount": 5000, "currency": "USD" },
  "transport_mode": "fly",
  "end_destination": null
}
```
`transport_mode`: `"fly" | "drive"`. `end_destination` is only for multi-stop trips (appendix example 3).

→ `201 { "trip_id": "…", "warnings": Warning[] }`. If `warnings` contains a `safety` warning, the UI shows it and waits for the user to confirm before it shows progress. *(Open question: should research wait for that confirmation? Proposal: yes, and confirm with `POST /trips/{id}/proceed`.)*

### `GET /trips/{trip_id}/progress`

→ `{ "status": "researching" | "planning" | "done" | "failed", "steps": [{ "message": "Found 4 flights, checking hotel prices", "at": "…" }] }`

Polling vs. SSE (`GET /trips/{id}/events`): **TBD (Jake)**.

### `GET /trips/{trip_id}/plans`

→ when the trip is feasible:
```json
{ "feasible": true, "plans": [Plan, Plan, Plan], "options": [Option] }
```
`options` holds every option the plans refer to, plus extra options the user can add while editing.

→ when it isn't:
```json
{ "feasible": false, "reason": "…", "min_estimated_cost": { "amount": 9800, "currency": "USD" } }
```

### `POST /plans/{plan_id}/redraft`

```json
{ "days": [Day], "removed_option_ids": ["…"] }
```
Items the user added, moved or kept come with `locked: true`.

→ `{ "plan": Plan, "dropped_items": [{ "option_id": "…", "reason": "Over budget by $120" }] }`

### `PUT /plans/{plan_id}`: save

Body: `Plan` (the client-side edited version). → `200 Plan` with `saved: true`.

### `GET /plans/{plan_id}`

→ `Plan`, used to come back to a saved plan later.

## Open questions

- Auth/users: do we need accounts to save plans, or is a shareable plan URL enough for the class demo?
- Where currency conversion happens (backend, presumably).
- How old a cached option can get before it's re-researched, per kind (flights go stale faster than museums).
