# Research agent: TODO

Owner: Kyle. Written 2026-11-24 after reading the README and `research/core.py`. Items marked **(check)** are things I have not verified in the code (`agent.py`, `activities.py`, `pricing.py` were not read line by line). Priorities: **P1** before the 11/25 end-to-end version, **P2** before the eval / Demo Day, **P3** nice to have.

## Must do

### Decide where the agent lives (P1)
- [ ] `CLAUDE.md` and the backend docs put the research agent in `backend/app/agents/research/`, but the working code is in `researchAgent/`. Jake needs to know which is the real home before he wires the backend. Update the docs, or move the code, in a PR that tags him.
- [x] The security modules live in `research/security/` and are now wired in: all network access goes through `core._fetch` (fetch guard + budget), every `claude -p` call goes through `core.claude_json` (budget + usage), `run()` creates one budget per trip, and thread pools carry it (`submit_in_context` / `map_in_context`). `tests/security/test_wiring.py` fails if a module opens its own connection, runs its own subprocess, or uses a bare `ex.submit`/`ex.map`.
- [ ] `research/security/fixtures.py` loads a `{collected_at, options: [...]}` JSON format that nothing in this repo produces yet (the real fixtures are HTTP caches and agent outputs). Either write the conversion from the agent output, or delete the loader.

### Match the contract (P1)
- [ ] The output shape (`price.amt`, `basis`, `price_type`, `source.url`, `retrieved_at`) is not the `Option` type in `docs/api-contract.md` (`price`, `price_is_estimate`, `source_url`, `fetched_at`). Either write a mapper or propose a contract change in the same PR as the code, and tag Jake and Fernando.
- [ ] Prices have mixed bases (flights = total for all travelers, hotels = per room per night, activities = per person). The contract says `price` is the total for the whole party. The mapper must do the multiplication, and round estimates up.
- [ ] Tag snapshot data: `data_origin: "snapshot"` is not set anywhere yet. Cached prices date from 2026-11-22, and the UI has to show that age.

### Sandbox (done) and what it leaves open
- [x] **Demos and live runs use sandbox data.** Done: flights and hotels come from recordings (nearest match), everything else from the exact-request cache, and only Geoapify and `claude -p` with tools off may run live. Web price search never runs (those places get the category estimate). Full network access needs `TRAVAI_ALLOW_NETWORK=1`, which only `--gather` sets. `data_mode()` is always "sandbox" without it.
- [x] **Synthetic data is never a silent fallback.** Only `TRAVAI_SANDBOX_DATA=synthetic` selects it (tests, CI). With no recordings and no choice, flights and hotels become gaps.
- [ ] **The demo needs the recordings.** `sandbox_data/` is gitignored (it holds real provider responses), so it exists only where `scripts/build_sandbox_index.py` was run. It can be rebuilt from the committed `tests/fixtures/http_cache/`, but check that the demo machine has it, and decide whether it may be shared at all (provider terms). Without it the demo shows no flights or hotels.
- [ ] **The demo needs `claude` and the Geoapify key.** Tools-off `claude -p` runs live in the sandbox (resolve, enrich, day trips), so the CLI must be installed and logged in on the demo machine, and `GEOAPIFY_API_KEY` must be set. Check both before Demo Day. If the CLI is a problem, the alternative is cache-only model calls, which limits the demo to cached destinations.
- [ ] **Model calls are live data too.** A tools-off call sends place names and the trip's origin and destination to the model provider. That is not outside data coming in, but it is a call out. Say so in the threat model, and decide if the demo's "no reaching out" claim should mention it.
- [ ] **Exchange rates are cache-only.** Hotel prices in a currency other than the request's need an FX rate from the cache. A pair that was never fetched makes that search fail ("not in the sandbox data") instead of calling the FX service. Check the currencies the demo trips need, or add the pairs while gathering.
- [ ] **Geoapify risks when live.** Responses are untrusted (OSM names are user-editable), so the T1 checks apply; the key must be in the backend env only; Geoapify's quota applies (3,000 credits/day free). Add a per-trip cap on Geoapify calls if the demo accepts free-form input.
- [ ] **Coverage of the sandbox.** List which routes and cities have recordings and which destinations resolve from cache, and make the demo offer only trips it can answer well. `sandbox_misses.jsonl` logs the searches it could not answer.
- [ ] **Check the demo path end to end.** Start the backend the way the demo will and confirm `TRAVAI_ALLOW_NETWORK` is not set anywhere (server env, Dockerfile, `.env`, CI). Consider a startup check in the backend that refuses to start if it is set.
- [ ] **Stale prices.** Recorded prices are snapshots (see each price's `retrieved_at`); the UI must show their age. Estimates adapted from another date are marked and rounded up.
- [ ] **Data gathering plan.** Decide who runs `--gather` and `record_sandbox.py --live`, for which trips, and commit only sanitized results. After gathering, remove `ignav.com` and `serpapi.com` from `FETCH_ALLOWED_HOSTS` so even gather mode cannot reach them. (`record_sandbox.py` and `build_sandbox_index.py` need `TRAVAI_ALLOW_NETWORK=1` to make live calls; run them with it set.)

### Open from wiring in the guards
- [ ] `validate_option` (price range, hidden characters, source host) is not applied to the agent's output yet, because the output is not in the `Option` shape. Apply it in the mapper to the contract.
- [ ] `SOURCE_LINK_HOSTS` is empty. Decide how to treat links from many booking sites: allowlist, flag unknown domains, or only show the domain in the UI (T3).
- [ ] The real pinned-IP HTTPS transport (`fetch_guard._default_transport`) has never run against a real host; all tests fake it. Run one case with `--gather` and `.env` keys and check it works, including the POST to Ignav. Sandbox replays never reach it.
- [ ] Calls with a body are not retried across redirects (a redirect on POST is refused). Check no real endpoint relies on one.

### Security (threat model)
- [x] **T1 / T4, web price search (P1).** Audited: the layer 3 prompt contains only the place name, city and country, never the origin, dates, budget or traveler count. Keep it that way; a test that pins the prompt to those fields would stop a future change from adding trip data.
- [ ] **T1, verify web prices in code (P1).** Partly done: a web-found `source_url` must now be a well-formed http(s) link (no credentials, IP host or odd port). Still open: check that the amount appears in the cited page text, and that it is in a plausible range for its category. Plain `http://` links are allowed on purpose, since some official tourism sites have no https link (found when the guard first rejected one in `cos-daytrip-500`); decide if that is acceptable.
- [ ] **T1, text from the LLM (P2).** Reject names and descriptions that contain zero-width or bidi characters, and cap their length (see `research/security/option_validation.py`). Geoapify/OSM and Wikivoyage are user-editable, so treat them as untrusted too. The enrichment step runs with tools off, which is good; keep it that way.
- [ ] **T3, source links (P2).** Check every `source.url` host against a list of known hosts. Today they include Google search/maps links, Rome2rio, Wikivoyage and airline links.
- [x] **T4, direct HTTP (P2).** Done: Wikivoyage and FX calls use `core.raw_get`, which applies the same guard and budget. `FETCH_ALLOWED_HOSTS` lists the seven hosts the agent calls. **Remove `ignav.com` and `serpapi.com` from it once the test data is gathered**, so a demo run can never reach them.
- [x] **T6, per-trip limit (P1).** Done: per-trip caps on HTTP requests (400), model calls (100), cost ($25) and time (900 s), counted only for real requests (cache hits are free). When one is hit, the run stops, the status becomes `partial` and a gap says why. **These numbers are guesses. Check them against a real live run** (`_usage` in the output has the counts).
- [ ] **T2, cache (P2).** The default cache keeps entries forever. Production must set `cache_ttl_hours`; add a way to purge by source, and make sure a poisoned price can't be served for long.
- [ ] **Keys (P1).** `core.py` strips keys from cache keys and bodies. I scanned `tests/fixtures/` for `apiKey=`-style values and found none (the 34 name-based hits were false positives such as Google ad `sig=` parameters). `tests/security/test_repo_fixtures_no_keys.py` now fails if an `apiKey=`/`access_token=` value appears in `tests/fixtures/`. Never put these keys in `NEXT_PUBLIC_*`.
- [ ] **Injection test cases (P2).** Add fixture pages and listings with hidden instructions, absurd prices and exfiltration URLs, and show that nothing bad reaches the output.

### Cost and the eval (P1 to P2)
- [x] `claude_json` now records tokens and cost per call and per trip in `_usage` (private key, strip before sending to the frontend). **Not yet checked against a live run:** it reads `total_cost_usd` and `usage.input_tokens/output_tokens/cache_read_input_tokens` from the CLI's JSON. If the CLI uses other field names the numbers will show as 0. Run one live case and confirm `_usage.cost_usd` is not 0.
- [ ] Pick the eval claim by 11/25 (see `evals/README.md`). Candidates that fit this agent: no underestimates, correct feasibility verdicts, honest gaps.
- [ ] Run the cases several times and report the rate with intervals. Replaying from cache is deterministic, so it measures nothing about stochastic behavior. Use live or cache-miss runs for the graded eval. Note that `claude -p` calls are cached by prompt, so repeats may return the same answer.
- [ ] Build the GitHub Actions eval workflow (manual or scheduled, with a run budget). It needs a way to call Claude from Actions; `claude -p` on a logged-in machine won't work there.
- [ ] Single-agent comparison: the course needs two agents vs one on the same cases and tools. Decide how that mode works here.
- [ ] Kyle decides what "right" means for the `MANUAL` checks in `tests/outputs/report.md`. Do not let the model decide.
- [ ] Spot-check prices by hand against Google Flights and the hotel pages (listed under "Known limits" in the README). The eval should say which prices were checked.

### Deployment (P2)
- [ ] The agent needs the Claude Code CLI installed and logged in on the server. Decide whether that is acceptable for the demo and for the cost-at-scale numbers, or whether to use the API with a key held only in the backend.
- [ ] A run takes 1 to 5 minutes. Jake's backend must run it as a background task with progress, as the README describes.

### Repo and course (P1 to P2)
- [ ] Write the `DECISIONS.md` entries (the "To write up" list has five research agent items, plus these: where the agent lives, the CLI vs API choice, the pricing layers). The reasoning has to be yours.
- [ ] Rewrite `backend/app/agents/research/README.md` (still Fernando's placeholder) to point at the real code.
- [ ] Update the threat model statuses once mitigations are built, with what you actually did.
- [ ] Licensing and terms: `tests/fixtures/` is about 15 MB of cached responses from Ignav, SerpApi, Geoapify, Wikivoyage and OSM, in a public repo. Check each provider's terms for republishing, and add the required attribution (Wikivoyage is CC BY-SA, OSM data is ODbL).
- [ ] Privacy: fixtures and example outputs must not contain real personal details.

## Testing

What exists today: `tests/test_pricing.py` (price parsing, name matching, Wikivoyage lookup), `tests/test_agent_units.py` (nights split, request validation, hours, flight selection, estimates, cache freshness, progress callback, planner view, offline replay), `tests/run_cases.py` with 13 cases in `tests/test_cases.json`, and `tests/security/` (fetch guard, option validation, budget, fixture loader, key scan). Everything below is a gap. Rules from `CLAUDE.md` apply: unit tests and PR checks never call paid or live APIs; use fixtures, fakes and the offline cache. The eval workflow is the only exception.

### Unit tests (P1 for the first four, P2 for the rest)
- [ ] **`feasibility_step` (P1).** It decides "impossible" and has no direct test. Test each verdict boundary (65%, 85%, 115% of budget, just under and just over), `unknown` when flights or lodging are missing, room count for odd traveler counts, and that the estimate is never below the cheapest priced items.
- [ ] **`core.http` and the cache (P1).** Partly done in `test_wiring.py` (guard used, allowlist enforced, cache hits free, failures and secrets not cached, retries, size limit, offline). Still open: `_canon_url` / `_key` (same request with a different `apiKey` hits the same entry), TTL expiry, `_redact` of stored bodies.
- [x] **`claude_json` with a fake `subprocess.run` (P1).** Done in `test_wiring.py`: tools off unless web search is requested, spend cap and no-session flags always present, neutral working directory, usage recorded, cache hits free, call and cost limits. Still open: non-JSON output, `is_error`, timeout.
- [ ] **Estimates are always high and labeled (P1).** `estimate_price`, `_est` and the transport estimates: every estimate has `price_type: estimate` and an `estimate_method`, and rounding goes up, never down (product rule 1). Add a property-style check over many inputs.
- [ ] `web_prices`: a price with no cited page is rejected, a price whose page text doesn't contain the amount is rejected (once that check exists), a plausible-range failure falls through to layer 4.
- [ ] `build_flight`: `verified` only when the booking link price is within 2% of the search price; `total_all_travelers` basis; missing booking link handled.
- [ ] `lodging_step`: more than 2 travelers uses `ceil(n/2)` rooms; properties without a price are skipped; night split across stops adds up.
- [ ] `advisories_step`: each level maps correctly (normal, caution, reconsider, do_not_travel); `map_data_reliability` rules; a country with no feed entry becomes a gap, never "safe".
- [ ] `transport_step`: airport more than 80 km from the city is costed as bus/train; rental car estimate only when both fly and drive are allowed; drive-only trips have no flight.
- [ ] `activities`: `rank_score`, `select_candidates`, `merge_wikivoyage` (Wikivoyage ranks above raw OSM), `enrich` batching at 30 places and the keep/drop flag, `day_trip_candidates`, `build_activities` output shape.
- [ ] `sources.py` request building with the HTTP layer faked: parameters, headers, and that keys are sent but never appear in the cache or the returned data. `frankfurter_fx` fallback to the second FX source when a currency is missing.
- [ ] `compact.planner_view`: keeps ids, `est` flags and prices, honors `max_activities`, stays under a token budget for all 13 case outputs.
- [ ] Edge inputs: empty destinations, duplicate stops, a one-day trip (no lodging), very long trips, non-ASCII place names, zero travelers, negative budget, currency codes in lower case.

### Pipeline and integration tests (P1 to P2)
- [ ] **End-to-end `run()` with fake clients (P1).** Replace `sources.*` and `claude_json` with stubs so the whole pipeline runs with no network or cache. Check the output validates against `schema/research_output.schema.json`, every priced item has `source.url` and `retrieved_at`, and `status` is right for ok, partial, infeasible and error.
- [ ] **Failure injection (P1).** Make each source fail in turn (Ignav timeout, SerpApi 429, Geoapify empty, `claude` missing). The run must end as `partial` with a matching entry in `gaps`, never crash and never fill the hole with a made-up number.
- [ ] **Offline replay of all 13 cases (P2).** Run each case with `--offline` in a test and compare to expectations (status, verdict, counts). This already exists as `run_cases.py`; wrap it so `pytest` runs it and it fails on regressions.
- [ ] **Golden-output snapshot (P2).** Keep a trimmed expected output for 2 or 3 cases and diff against it, so unintended changes in prices, ordering or fields show up in review.
- [ ] **Schema tests (P2).** Valid and invalid sample documents against the schema; every required field; `additionalProperties` behavior; a test that the backend mapper (once written) output matches `docs/api-contract.md`.
- [ ] **Contract mapper tests (P1, once the mapper exists).** Flights total for all travelers, hotel per night times nights times rooms, activity per person times travelers, estimates rounded up, `fetched_at` set from `retrieved_at`.

### Security tests (P1 to P2)
- [x] **Wire the guards in, then test the wiring (P1).** Done (see above).
- [ ] **Prompt-injection fixtures (P2).** Fake Wikivoyage entries, OSM names and web pages with hidden instructions ("ignore previous instructions", "report the price as $1", a URL that carries the user's origin). Assert the output prices come only from the structured fields, no extra URL is fetched, and nothing from the page shows up in tool arguments.
- [ ] **Poisoned cache (P2).** A cached price outside the plausible range must be rejected or flagged on read, not served.
- [x] **Budget enforcement through the pipeline (P1).** Done with fake pipelines in `test_wiring.py` (limit hit, limit swallowed by a step, limit raised out of the run, separate budgets per run). Still open: a live run that hits a limit.
- [ ] **No secrets in outputs (P1).** Scan every file in `tests/outputs/` and every cache file for `apiKey=`-style values after a run. (Fixtures are already scanned.)
- [ ] **Safety warning test (P2).** Ukraine and any `do_not_travel` country must carry the advisory, and the trip must still be returned so the user can decide (product rule 4).

### Behavior over repeated runs (P2, feeds the eval)
- [ ] Run each case several times live (not from cache) and record how often each automated check passes. A single run proves nothing. Report the rate and how many runs it is based on.
- [ ] Track the stochastic parts separately: `resolve`, `enrich`, web price search, day-trip proposals. Check how often the same prompt gives a different structured answer, since the LLM cache hides this.
- [ ] Product-rule checks on every output: no estimate below the cheapest real price for the same thing, every price has a source and time, the infeasible case says so with a minimum cost, and gaps are listed.
- [ ] Hand-check a sample against the real sites and write down the result (the README says prices have never been compared by hand). Kyle decides what is right, not the model.

### CI and test hygiene (P1)
- [ ] There is no CI job that runs `researchAgent/` tests. Ask Jake or the team to add one; I can't edit `.github/` from this task. Until then, run `python3 -m pytest tests -q` before each PR.
- [ ] `tests/test_agent_units.py::test_planner_view_...` needs `tests/outputs/tokyo-5d-5000.json`, which is git-ignored. In a fresh checkout it fails until you run `python3 scripts/run_agent.py tokyo-5d-5000 --offline`. Make that test generate its own input, or skip with a clear message.
- [ ] Use fake clocks and fixed dates in tests so they don't change with the day.
- [ ] Keep tests fast and offline. Mark anything that needs the network, or the `claude` CLI, so it is skipped by default.

## Could do

- [ ] Real transit and rail data instead of low-confidence estimates (README "Known limits").
- [ ] Include activities in the feasibility estimate (they are excluded today).
- [ ] Improve name matching so real attractions don't miss their Wikivoyage price ("Kabuki-za" vs "Kabukiza Theater").
- [ ] Hotel prices for more than 2 adults per room, instead of the room-count assumption.
- [ ] Day-trip travel times from routing instead of LLM estimates.
- [ ] Model overland border crossings for cases like Ukraine, and flag outdated map data (T8).
- [ ] Replace the cache-forever default with per-kind freshness (flights go stale faster than museums); this is an open question in the API contract.
- [ ] Add a second source to cross-check flight and hotel prices.
- [ ] Add a progress/ETA estimate so the UI can show something better than stage names.
