# TravAI research agent

The research agent takes a trip request and returns the research the planner agent needs: flights, hotels, activities,
ground transport, travel advisories, a budget feasibility verdict, and an explicit list of things it could not find.
Every price comes with a source link and a retrieval time. The agent never fills a hole with an invented number. It
either marks a value as an `estimate` with the method used, or reports a `gap`.

The output shape is defined in `schema/research_output.schema.json`, and every run is validated against it.

## Setup

Run everything from the `researchAgent/` directory.

1. **Python 3.9+** and `pip install -r requirements.txt` (`jsonschema`, `pytest`; everything else is standard library).
2. **Claude Code** (`claude`) installed and logged in. The judgment steps run `claude -p`, so no Anthropic API key is needed.
3. `cp .env.example .env` and fill in the keys you need:

| Key | Needed for | Not needed when |
|---|---|---|
| `GEOAPIFY_API_KEY` | places, geocoding, routing | replaying with `--offline` |
| `IGNAV_API_KEY` | flights | `--offline` or `--sandbox` |
| `SERP_API_KEY` | hotels | `--offline` or `--sandbox` |

A missing key raises an error that names the key, and that run fails. Never commit `.env`.

## Running it

There are three data modes. They differ in where flights, hotels and everything else come from.

| Mode | How to select | Flights and hotels | Geoapify, Claude, other sources | Use it for |
|---|---|---|---|---|
| **live** (default) | no flag | Ignav and SerpApi, spends quota | live (cached on disk after the first call) | real research, recording new data |
| **offline replay** | `--offline` | exact-request cache only | exact-request cache only | reproducing a past run with no network; the 13 test cases |
| **sandbox** | `--sandbox`, `data_mode_override="sandbox"` or `TRAVAI_DATA_MODE=sandbox` | recorded data, nearest match if the trip was not recorded (see [Sandbox mode](#sandbox-mode-recorded-flights-and-hotels)) | live | dev, evals and demos without Ignav/SerpApi quota |

```bash
python3 scripts/run_agent.py tokyo-5d-5000               # live. Case ids are in tests/test_cases.json
python3 scripts/run_agent.py tokyo-5d-5000 --offline     # replay from cache: no network, no quota
python3 scripts/run_agent.py tokyo-5d-5000 --sandbox     # recorded flights and hotels, live everything else
python3 tests/run_cases.py [ids...] [--offline]          # all cases + automated checks -> tests/outputs/report.md
python3 -m pytest tests -q                               # unit tests (no network, no keys)
```

`run_agent.py` takes a case id (not a free-form trip; run it with no arguments to list the ids) and writes `tests/outputs/<id>.json`. That folder is generated and
gitignored. For your own trip, call `run()` from Python:

```python
from research.agent import run

output = run({
    "origin": "DEN", "destinations": ["Tokyo, Japan"], "start_date": "2027-03-10", "duration_days": 5,
    "travelers": 1, "budget": 5000, "currency": "USD", "transport_modes": ["flight"],
    # optional: "start_point", "end_point" for multi-city trips
}, data_mode_override="sandbox")      # omit for live
```

`run(req, *, offline=False, now=None, progress=None, cache_ttl_hours=None, data_mode_override=None)`:

| Parameter | Meaning |
|---|---|
| `offline` | Replay only from the exact-request cache; raises instead of touching the network. |
| `data_mode_override` | `"sandbox"` or `"live"`. `None` keeps the current mode (env `TRAVAI_DATA_MODE`, default live). Process-wide. |
| `progress(stage, message)` | Optional callback for a progress screen (stages: resolve, search, flights, lodging, activities, transport, feasibility, done). |
| `cache_ttl_hours` | Refetch cached results older than this. `None` keeps everything (tests, replay). Process-wide. |
| `now` | Override the clock (tests). |

It returns the research output (see [Output at a glance](#output-at-a-glance)). Keys starting with `_` are private;
`_schema_errors` should be empty.

### Request fields

| Field | Meaning |
|---|---|
| `origin` | IATA code (`DEN`) or a city/address (`Denver, CO`). A city enables road routes from the origin. |
| `destinations` | One or more places, in any form (`"Tokyo"`, `"Japan"`, `"Paris"`). Ambiguous names are resolved and the assumption is recorded in `notes`. |
| `start_date`, `duration_days` | Trip starts on this date and lasts N days. Lodging is booked for N nights (N > 1), a deliberately high choice. A 1-day trip has no lodging. |
| `travelers`, `budget`, `currency` | Budget is in `currency`; all output prices are normalized to it. |
| `transport_modes` | Any of `flight`, `drive`, `train`. Controls which flights and ground legs are searched. |
| `start_point`, `end_point` | Optional ordering for multi-city trips. |

A request with a past `start_date`, no destination, fewer than 1 traveler or day, or a budget of zero or less returns
`status: "error"` without running any searches.

## Sandbox mode (recorded flights and hotels)

Ignav and SerpApi quotas are small, so flights and hotels can be answered from recorded real responses instead of live
calls. Geoapify and Claude still run live, so a sandbox run still needs `GEOAPIFY_API_KEY` and `claude`.

How it answers a search (`research/sandbox.py`):

1. **Exact recording** of the same route or city, dates, party size and currency: returned as recorded, marked as a
   snapshot (`confidence.notes` says when it was recorded).
2. **Nearest recording** for the same route or city: returned as an **estimate**. Prices are rounded up, `confidence` is
   `low`, and `price.estimate_method` says what the recording was for. Flights allow a departure within 14 days and a
   trip length within 4 nights. Hotels allow check-in within 120 days. Other currencies are converted and rounded up.
3. **Nothing close:** a `gap` ("no recorded fares close enough"), and the search is appended to `sandbox_misses.jsonl`.

Prices and links are never invented, and `retrieved_at` stays the original recording time. Flight times are not shifted
to fit your dates. An estimate for other dates gets a Google Flights search link, not the recorded booking link, because
that link is for the recorded date. Every sandbox run adds a note saying the prices are recorded snapshots and when they
were captured. With no flights found, `status` is `partial` and the feasibility verdict is `unknown`.

### Recording and refilling data

```bash
python3 scripts/record_sandbox.py                   # DRY RUN (default): prints the planned calls and the most they could cost
python3 scripts/record_sandbox.py --live            # make the calls. Needs IGNAV_API_KEY and SERP_API_KEY
python3 scripts/record_sandbox.py --live --only flights --max-ignav 40 --max-serp 40
python3 scripts/build_sandbox_index.py              # REQUIRED after recording: cache -> sandbox_data/*.jsonl
python3 scripts/record_sandbox.py --from-misses 5   # dry run: only the 5 most-requested searches the sandbox missed
```

- The trip grid is the `TRIPS`, `GAP_FLIGHTS` and `GAP_HOTELS` lists in `scripts/record_sandbox.py`. Edit them to record
  different trips. `--base-only` skips the gap-fill list.
- Calls already in the cache are skipped, so it is safe to stop and re-run. `--max-ignav` and `--max-serp` cap the calls
  made in one run. It stops at once on HTTP 401, 402, 403 or 429, and skips (and reports) a single search or booking link
  that Ignav rejects.
- Each Ignav search is followed by up to 3 booking-link calls, so a flight search costs up to 4 calls. A hotel search
  costs 1. Ignav only searches dates up to about mid-November 2027.
- Recorded requests mirror the agent's exactly, but airports and city names are written by hand. If the agent resolves a
  different airport or spells a city differently, that one request will miss in sandbox mode.
- `sandbox_data/*.jsonl` is rebuilt from `tests/fixtures/http_cache/`. Both are generated data, so check each API
  provider's terms on redistributing responses before committing them to a public repo.

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

See `schema/research_output.schema.json` for the full definition. For a real example, run `python3 scripts/run_agent.py tokyo-5d-5000 --offline` and open `tests/outputs/tokyo-5d-5000.json`.

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
- `tests/test_sandbox.py`: sandbox matching (exact, nearest date, party-size scaling, currency, name normalization, misses)
  and the agent's labeling of estimates, with hand-made data and a guard that fails if sandbox mode touches the network.
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
  sandbox.py      sandbox mode: nearest-match lookup over recorded flights and hotels
  core.py         .env, HTTP/LLM disk cache, data mode, claude -p wrapper
sandbox_data/     compact recorded flights, hotels and booking links (built by scripts/build_sandbox_index.py)
scripts/          run_agent.py, record_sandbox.py, build_sandbox_index.py, top20_tokyo.py (pricing demo on 20 Tokyo landmarks)
tests/            unit tests, test_cases.json, run_cases.py, fixtures/ (caches), outputs/ (generated, gitignored)
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

`tests/outputs/` is generated and not committed. Replaying a test case writes a real output to
`tests/outputs/<case-id>.json` for free (13 cases: Tokyo, a drive-only day trip, a three-city Europe trip, an impossible
budget, Ukraine, and so on):

```
python3 tests/run_cases.py --offline       # all 13, plus tests/outputs/report.md
python3 scripts/run_agent.py tokyo-5d-5000 --offline
```

## Troubleshooting

| You see | Cause and fix |
|---|---|
| `IGNAV_API_KEY missing from .env` (or SERP / GEOAPIFY) | Copy `.env.example` to `.env` and fill it in. `--offline` and `--sandbox` do not need the Ignav and SerpApi keys. |
| `CacheMiss: offline and not cached` | `--offline` only replays exact past requests. Run it live once, or use `--sandbox` for flights and hotels. |
| `sandbox: no recorded fares close enough` (in `gaps`) | No recording for that route near those dates. See [Recording and refilling data](#recording-and-refilling-data). |
| `status: "error"` with "Invalid request" in `notes` | Past date, missing destination, or a zero budget or traveler count. |
| Run fails in the resolve or enrichment step | `claude` is not installed or not logged in for this user. |
| Ignav answers HTTP 424 `unsupported_search` | The dates are outside Ignav's search window (about mid-November 2027 at the time of writing). |

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
- **Sandbox flights match rarely.** Each route was recorded for one date, so on a recorded route with random dates only
  about 6% of searches found a close enough fare. Use dates near a recording, or record the trip first (`--from-misses`).
- **Running it requires Claude Code** installed and logged in on whatever machine runs the agent, including the backend server.
