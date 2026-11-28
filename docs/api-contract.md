# API contract (frontend ↔ backend)

> **Status: DRAFT, implemented by the backend** (all endpoints below). Jake and Fernando still need to agree on it. Until then, treat the shapes as a starting point, not a promise.
>
> **Rule:** when an endpoint or shape changes, update this file in the same PR as the code, and tag the other side for review. Both `frontend/` and `backend/` code follow this file.

Base URL: `NEXT_PUBLIC_API_BASE_URL` (local default `http://localhost:8000`). JSON everywhere. Errors use FastAPI's shape, `{ "detail": "message" }` or the 422 validation list, and the UI shows `detail` to the user. Field names use `snake_case`. Money is a decimal number in `currency` (ISO 4217). Timestamps are ISO 8601 UTC.

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
`transport_mode`: `"fly" | "drive"`. `end_destination` is only for multi-stop trips (appendix example 3). `start_date` may be `null` for flexible dates (the eval cases leave it unset; the backend already accepts this).

→ `201 { "trip_id": "…", "warnings": Warning[] }`. If `warnings` contains a `safety` warning (a US State Dept Level 3 or 4 advisory for a country named in the destination), research **waits**: the UI shows the warning, and the user confirms with `POST /trips/{id}/proceed`. Otherwise research starts right away in the background.

### `POST /trips/{trip_id}/proceed`

The user saw the safety warning and wants to go ahead. Starts research. → `204`. Safe to call more than once; `404` for an unknown trip.

### `GET /trips/{trip_id}/progress`

→ `{ "status": "researching" | "planning" | "done" | "failed", "steps": [{ "message": "Found 4 flights, checking hotel prices", "at": "…" }] }`

Poll this endpoint (no SSE). While a trip waits for `proceed`, it reports `"researching"` with no steps. A `"failed"` trip's last step says why (e.g. no origin given, or no flights found).

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
`min_estimated_cost` is the cheapest flight + hotels + required transport + food and local transport, rounded **up** to the next 50.

→ `409 { "detail": "…" }` while the trip isn't done yet, or when it failed (`detail` is the reason).

Notes on what the backend sends:
- `Plan.total` = flight + hotel + every scheduled item + the plan's `"other"` cost line. The `"other"` line is the research agent's estimate for food and local transport: it has no option or single source, so it isn't an `Option`, and a plan's warnings say it's an estimate. This is the same arithmetic as the frontend's running total.
- Required transport (airport transfers both ways, the drive there and back, trains between stops, a return flight for one-way trips) is put into the days as scheduled items, so the total covers it.
- `Option.details` is informational. Keys the backend fills in: `role` (`round_trip`, `airport_transfer`, `drive`, `day_trip`, `lodging`, …), `research_id`, `price_type`, `price_basis`, `price_layer`, `estimate_method`, `confidence`, `synthetic` (test data, never real prices), `area`, `hours`, and per kind `segments`, `stops`, `nights`, `rooms`, `rating`.
- Warnings: `safety` (advisory), `estimate` (estimated prices, synthetic test data, an assumed start date), `stale_data` (prices recorded more than 48 hours ago), `over_budget` (only when the user's locked items alone go over).

### `POST /plans/{plan_id}/redraft`

```json
{ "days": [Day], "removed_option_ids": ["…"] }
```
Items the user added, moved or kept come with `locked: true`.

→ `{ "plan": Plan, "dropped_items": [{ "option_id": "…", "reason": "Over budget by $120" }] }`

Locked items stay on their day; removed items never come back; `dropped_items` lists unlocked items the user kept that had to go. The planner model runs in this request, so it can take tens of seconds. `422` if a day is past the end of the trip or an option isn't from this trip.

### `PUT /plans/{plan_id}`: save

Body: `Plan` (the client-side edited version). → `200 Plan` with `saved: true`.

The backend uses only `title`, `summary` and `days`, and saves the days exactly as sent. `total`, `cost_breakdown` and `warnings` are recomputed from stored prices, so a client can't save a wrong total. `422` for unknown options.

### `GET /plans/{plan_id}`

→ `Plan`, used to come back to a saved plan later.

## Open questions

- Auth/users: do we need accounts to save plans, or is a shareable plan URL enough for the class demo?
- Where currency conversion happens (backend, presumably).
- How old a cached option can get before it's re-researched, per kind (flights go stale faster than museums). Today: an identical research request reuses a run from the last 24 hours (`RESEARCH_REUSE_HOURS`); the research agent refetches its own cached calls older than 24 hours (`RESEARCH_CACHE_TTL_HOURS`).
