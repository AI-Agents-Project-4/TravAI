# TravAI research agent

The research agent takes a trip request and returns the research the planner agent needs: flights, hotels, activities,
ground transport, travel advisories, a budget feasibility verdict, and an explicit list of things it could not find.
Every price comes with a source link and a retrieval time. The agent never fills a hole with an invented number. It
either marks a value as an `estimate` with the method used, or reports a `gap`.

The output shape is defined in `schema/research_output.schema.json`, and every run is validated against it.

## Quick start

```bash
# pip install -r requirements.txt     (Python 3.9+; everything else is standard library)
# cp .env.example .env and fill in IGNAV_API_KEY, SERP_API_KEY, GEOAPIFY_API_KEY. Claude Code (`claude`) must be installed and logged in.
python3 scripts/run_agent.py tokyo-5d-5000             # one case from tests/test_cases.json -> tests/outputs/<id>.json
python3 scripts/run_agent.py tokyo-5d-5000 --offline   # replay from cache: no network, no API quota
python3 tests/run_cases.py [ids...] [--offline]        # all cases + automated checks -> tests/outputs/report.md
python3 -m pytest tests -q                             # unit tests (no network)
```

From Python:

```python
from research.agent import run
output = run({
    "origin": "DEN", "destinations": ["Tokyo, Japan"], "start_date": "2027-03-10", "duration_days": 5,
    "travelers": 1, "budget": 5000, "currency": "USD", "transport_modes": ["flight"],
    # optional: "start_point", "end_point" for multi-city trips
})
```

### Request fields

| Field | Meaning |
|---|---|
| `origin` | IATA code (`DEN`) or a city/address (`Denver, CO`). A city enables road routes from the origin. |
| `destinations` | One or more places, in any form (`"Tokyo"`, `"Japan"`, `"Paris"`). Ambiguous names are resolved and the assumption is recorded in `notes`. |
| `start_date`, `duration_days` | Trip starts on this date and lasts N days. Lodging is booked for N nights (N > 1), a deliberately high choice. A 1-day trip has no lodging. |
| `travelers`, `budget`, `currency` | Budget is in `currency`; all output prices are normalized to it. |
| `transport_modes` | Any of `flight`, `drive`, `train`. Controls which flights and ground legs are searched. |
| `start_point`, `end_point` | Optional ordering for multi-city trips. |

## How it works

The agent is a deterministic pipeline. `claude -p` (Claude Code in headless mode) is used only for judgment steps, so
no Anthropic API key is needed, and the flow is easy to test and cap.

```
request
  │
  ├─ validate ──────────────── past date, zero budget, no destination -> status "error" (no searches run)
  │
  ├─ resolve  [claude -p] ──── destinations -> city, country, airports (with commercial service), local currency,
  │                            cost tier, State Dept country name, Wikivoyage title. Geocode each stop (Geoapify).
  │
  ├─ in parallel
  │    ├─ flights ───────────── Ignav search -> pick a price/time spread -> booking links
  │    ├─ lodging ───────────── SerpApi Google Hotels, one search per stop
  │    ├─ advisories ────────── State Dept RSS feed
  │    └─ activities (per stop)
  │         Geoapify places + Wikivoyage listings -> enrich [claude -p] -> price layers 1-4
  │
  ├─ ground transport ──────── routes (Geoapify), airport transfers, intercity legs and flights
  │
  ├─ feasibility ───────────── cheapest realistic total vs budget -> verdict
  │
  └─ validate against schema -> output
```

### Flights (Ignav)
- One round-trip search, or two one-way searches when the start and end cities differ. Intercity flights between stops
  are one-way searches.
- Ignav returns dozens of itineraries per search. The agent keeps up to 6 that give the planner a real trade-off: the
  cheapest two, the fastest, the fewest stops, the cheapest with at most one stop each way, and a mid-priced option.
- Search results carry no booking URL, so each kept flight costs a second request (`booking-links`, about 12 s each,
  run in parallel). If the airline's own link matches the search price within 2%, the flight is marked `verified`.
- **Ignav prices are for the whole party, not per person**, so flight prices use `basis: total_all_travelers`.

### Lodging (SerpApi Google Hotels)
- One search per stop, split evenly across nights. Up to 12 priced properties per stop, with the nightly rate, the stay
  total, rating, coordinates and a link.
- Searches use up to 2 adults, so prices are per room. For more than 2 travelers the feasibility estimate assumes
  `ceil(travelers / 2)` rooms.

### Activities
1. **Candidates.** Geoapify places around the city centre (sights, museums, heritage, parks, entertainment,
   restaurants, nightlife, markets), merged with **Wikivoyage see/do listings**, which are curated and rank above raw OSM
   results. For trips of 3+ days, the LLM also proposes 3 day trips (geocoded; round-trip travel time is an LLM
   estimate and labelled as such).
2. **Enrichment** (one batched `claude -p` call per 30 places). English name (using OSM's English name when present,
   otherwise a translation), category, visit duration, a one-line description, and a keep/drop flag. Translated names are
   marked `name_source: "llm_translation"` and get lower confidence; the original name is kept in `name_local`.
3. **Pricing.** Four layers, tried in order. The layer used is recorded in `price.price_layer`.

| Layer | Source | Price type | Notes |
|---|---|---|---|
| 1 `osm_fee` | OSM `fee=no` tag | `published_rate` | Only means "free". `fee=yes` carries no amount. |
| 2 `wikivoyage` | Wikivoyage `price=` text | `published_rate` | Parsed to an amount and currency. If several amounts appear (range, adult/child), the highest is used and the price is flagged ambiguous. A bare number with no currency is refused unless the local currency is known. |
| 3 `web_search` | Claude web search, top 12 unpriced places per stop | `published_rate` | Only accepted when a page that states the price is cited. The model is told never to estimate. |
| 4 `category_estimate` | Category base cost x country cost tier | `estimate` | Set high on purpose. Low confidence. Always has `estimate_method`. |

   Names are matched to Wikivoyage entries at a 0.9 similarity threshold (0.75 if within 200 m), because early versions
   priced the wrong place when thresholds were looser.
4. **Opening hours** are parsed from OSM only for simple forms (`Mo-Fr 09:00-18:00; Sa off`). Anything complex is
   omitted rather than guessed. A close time earlier than the open time means the place closes after midnight.

### Ground transport
- Road route from the origin to the first stop when `drive` is allowed and the origin is a city (Geoapify; fuel is an estimate).
- Airport to city transfer. If the arrival airport is more than 80 km from the city (for example flying to Poland for
  Lviv), it is costed as a bus/train, not a taxi.
- Between stops: drive routes, train estimates (no live rail data, so labelled low confidence), and one-way flights.
- A rental-car estimate when the user can both fly and drive.

### Advisories
US State Dept RSS feed, matched by country name. Levels map to `normal`, `caution`, `reconsider`, `do_not_travel`.
`map_data_reliability` is set to `poor` for Level 4 with conflict language, `uncertain` for Level 3 or 4, else `good`.
A destination with no matching entry is recorded as a gap, never assumed safe.

### Feasibility
`estimated_minimum_total` = cheapest flights + a lodging baseline + food/local transport + driving/rental where relevant.
- Lodging uses the median of the 6 cheapest nightly prices per city, times nights, times rooms.
- Food and local transport use the LLM's per-person daily cost, set high. **Activities are not included.**
- Verdicts: `comfortable` (up to 65% of budget), `tight` (85%), `very_tight` (up to 115%), `likely_impossible` (over 115%).
  The 15% margin exists because the estimate is only good to roughly that much, so a 2% overshoot is not reported as impossible.
- If flights or lodging could not be priced, the verdict is `unknown`, and the reasoning says what was missing.

### Output status
`ok` (enough for the planner), `partial` (a category is missing, see `gaps`), `infeasible` (clearly over budget, but
the cheapest options found are still returned), `error` (invalid request, or nothing usable).

## Output at a glance

See `schema/research_output.schema.json` for the full definition and `tests/outputs/tokyo-5d-5000.json` for a real example.

- Every priced item has a `price` with `amount`, `currency`, `basis` (`per_person`, `per_night`, `total_all_travelers`...),
  `price_type` (`live_quote`, `published_rate`, `estimate`), `retrieved_at` and `price_layer`. Prices in another currency
  also carry `amount_normalized` and `fx_rate`.
- Every item has a `source.url` and a `confidence` (`level`, `verified`, optional `notes`).
- `gaps` lists what was tried and not found. The planner must not assume those things exist.
- `notes` records assumptions (for example "Paris interpreted as Paris, France").

## Data sources and quotas

| Data | Source | Free allowance | Notes |
|---|---|---|---|
| Flights | Ignav | 1,000 requests | 1 per search + 1 per booking link. A typical trip uses about 8 to 15. |
| Hotels | SerpApi | 250 searches/month | 1 per stop. |
| Places, geocoding, routing | Geoapify | 3,000 credits/day | About 10 to 20 calls per stop. No transit routing for Tokyo. |
| Curated attractions and prices | Wikivoyage | free | Cached by page. Requests are batched and back off on 429s. |
| Advisories | travel.state.gov RSS | free | |
| Currency | Frankfurter, then open.er-api.com | free | Frankfurter lacks some currencies (UAH, for example). |
| Judgment steps | `claude -p` | your Claude plan | About 5 to 10 calls per stop (resolve, enrichment batches, web price search, day trips); each takes seconds to a few minutes. |

## Caching and offline replay

Every HTTP and `claude -p` call is cached on disk under `tests/fixtures/` (`http_cache/`, `llm_cache/`, `wikivoyage/`),
so reruns are free and deterministic. API keys are removed from cache keys and stored bodies. Delete a cache file to
force a refresh. `--offline` raises an error instead of touching the network, so use it to confirm a run is fully
reproducible. Cached prices and availability date from **2026-11-22**.

Failed requests are not cached, which matters for one case: a currency Frankfurter lacks falls back to the second
source, and offline mode handles that explicitly.

## Tests

- `tests/test_pricing.py`, `tests/test_agent_units.py`: unit tests for price parsing, name matching, Wikivoyage lookup,
  hours parsing, request validation, flight selection and estimates.
- `tests/test_cases.json`: 13 input cases with expectations: the 5 proposal scenarios (Tokyo, Colorado Springs day trip,
  Europe, Japan for a month on $500, Ukraine) plus group travel, a non-USD budget, an ambiguous name, a remote destination
  and invalid input.
- `tests/run_cases.py`: runs the cases and checks the schema, status, counts, verdict, source links, currency
  normalization and case-specific rules. Statements that need a human are listed as `MANUAL` in
  `tests/outputs/report.md` and never counted as passed.

## Layout

```
schema/research_output.schema.json   output contract for the planner
research/
  agent.py        pipeline: resolve, flights, lodging, advisories, transport, feasibility
  activities.py   places, enrichment, day trips, pricing layers 3-4, opening hours
  pricing.py      pricing layers 1-2, price parsing, Wikivoyage index and matching
  sources.py      Ignav, SerpApi, Geoapify, State Dept, FX clients
  compact.py      planner_view(): slim output for the planner
  core.py         .env, HTTP/LLM disk cache, claude -p wrapper
scripts/          run_agent.py, top20_tokyo.py (pricing-layer demo on 20 Tokyo landmarks)
tests/            unit tests, test_cases.json, run_cases.py, fixtures/ (caches), outputs/
```

## Integrating with the backend (for Jake)

The agent is a plain Python function, so the FastAPI backend can import it directly. There is no separate service.

### What the backend has to know

1. **It is slow and blocking.** A live run takes roughly 1 to 5 minutes (booking-link lookups and web price search
   dominate). Never call it inside a request handler. Start it as a background task and let the UI poll for progress.
   A replay from cache takes about a second.
2. **It needs the right environment on the server.** `.env` with the three API keys, and the Claude Code CLI
   (`claude`) installed and logged in for the user the server runs as. If `claude` is missing, the judgment steps fail.
3. **Set `cache_ttl_hours` in production.** The default keeps cached results forever, which is right for tests but would
   serve stale flight prices. `cache_ttl_hours=24` refetches anything older than a day.
   It is a process-wide setting, so use one value for all runs.
4. **Never trust a price without checking its fields.** Every price has `price_type`. `estimate` means no source was
   found. Show those differently in the UI. `confidence.verified` is true only for flights whose booking link matched
   the search price.
5. **Handle `status`.** `ok` and `partial` mean usable data. `infeasible` still contains the cheapest flights and
   lodging, so the planner can explain the gap. `error` means the request was invalid, or nothing usable was found; the
   reason is in `gaps` and `notes`.
6. **`run()` can raise** (network trouble that survived retries, `claude` missing). Catch it, mark the run failed, and
   surface a generic message. The output also contains a private `_schema_errors` list. It should be empty; strip any
   key starting with `_` before storing or sending to the frontend.

### Calling it

```python
from research.agent import run

def do_research(run_id: str, request: dict):
    def progress(stage, message):                  # stages: resolve, search, flights, lodging, activities,
        db.update_progress(run_id, stage, message) # transport, feasibility, done
    try:
        out = run({**request, "request_id": run_id}, progress=progress, cache_ttl_hours=24)
        out = {k: v for k, v in out.items() if not k.startswith("_")}
        db.save_research(run_id, out)              # e.g. a JSONB column; see below
    except Exception as e:
        db.fail(run_id, str(e)[:300])
```

A FastAPI shape for it (state in your Postgres, not in memory):

```python
@app.post("/research")
def start(req: TripRequest, tasks: BackgroundTasks):
    run_id = db.create_run(req)
    tasks.add_task(do_research, run_id, req.model_dump())   # run in a worker/thread, not the event loop
    return {"run_id": run_id}

@app.get("/research/{run_id}")
def status(run_id: str):
    return db.get_run(run_id)    # {status, stage, message, ...} for the progress screen
```

`TripRequest` must produce the fields in the request table above (`origin`, `destinations`, `start_date`,
`duration_days`, `travelers`, `budget`, `currency`, `transport_modes`).

The progress messages match the proposal's progress screen, for example "Found 6 flights", "Found 12 places to stay",
"Found 92 activities".

### What to store and what the planner reads

- **Store the whole output** as one JSON document per run (`request_id`, request, output, `generated_at`). Every item has
  a stable `id`, a price with `retrieved_at`, and a `source.url`. The planner needs prices and links to be saved with
  each option, so no extra bookkeeping is needed. If you want per-option rows, split by `flights`, `lodging`,
  `activities` and `ground_transport` and key on `id`.
- **Do not hand the full output to the planner.** It is large: about 27k tokens for Tokyo and 73k for a three-city trip.
  Use the slim view instead, which keeps what the planner needs (prices, durations, opening hours, coordinates, day-trip
  travel times, `est` flags) and is about 5k to 6.5k tokens:

```python
from research.compact import planner_view
view = planner_view(out, max_activities=60)    # activities sorted: sourced prices and higher confidence first
```

  The view keeps `id`s, so the planner can answer with ids and the backend can look the full item up in the stored output.
  `max_activities` is a cap across all stops. Raise it for multi-city trips.

### How the planner should use the fields

- **Budget:** use `price.amt` (already normalized to the request currency) with its `basis`. Flights are the total for
  all travelers. Hotel nightly prices are per room. Activity prices are `per_person`, so multiply by travelers.
- **Never overstate certainty:** items with `est: true` are category estimates set high. If the plan relies on them, say so.
- **Impossible budgets:** if `feasibility.verdict` is `likely_impossible` (status `infeasible`), tell the user honestly.
  Use `feasibility.breakdown` and the cheapest flights and lodging in the output to explain why, instead of building
  three plans that cannot fit.
- **Safety:** if `advisories` contains `do_not_travel` or `reconsider`, lead with the warning, then let the user proceed.
  `reliability` of `uncertain` or `poor` means map distances and times may be off.
- **Missing data:** anything in `gaps` does not exist as far as the planner knows. Do not invent a replacement.
- **Schedules:** `hours` uses local 24h times, and a close time earlier than the open time means after midnight.
  Activities without `hours` have unknown hours; do not assume they are open all day.

### Handing over test data before the backend is wired up

`tests/outputs/<case-id>.json` holds a real output for each of the 13 test cases (Tokyo, a drive-only day trip, a
three-city Europe trip, an impossible budget, Ukraine, and so on). Replaying costs nothing:

```
python3 scripts/run_agent.py tokyo-5d-5000 --offline
```

## Known limits

- **Prices are not independently verified.** Ignav and SerpApi prices have not been compared with Google Flights or
  Booking.com by hand. Wikivoyage prices can be stale, and web-searched prices are only as good as the page found.
- **No live train or transit data.** Train legs, local transport and taxis are labelled estimates with low confidence.
- **Feasibility excludes activities** and assumes mid-range food, so it is a screening estimate, not a quote.
- **Day-trip travel times** are LLM estimates, and day trips are mostly priced by category estimate.
- **Hotel prices are for up to 2 adults per room.** Larger groups use a room-count assumption.
- **Ukraine-style cases.** The agent routes through the nearest operating airport and warns, but the overland border
  crossing and delays are not modelled, and Geoapify's map data may be out of date.
- **Name matching is conservative.** A real attraction can miss its Wikivoyage price because its name differs
  (for example "Kabuki-za" vs "Kabukiza Theater"). It then falls to the next pricing layer.
- **Running it requires Claude Code** installed and logged in on whatever machine runs the agent, including the backend server.
