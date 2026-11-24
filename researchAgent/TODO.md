# Research agent: TODO

Owner: Kyle. Written 2026-11-24 after reading the README and `research/core.py`. Items marked **(check)** are things I have not verified in the code (`agent.py`, `activities.py`, `pricing.py` were not read line by line). Priorities: **P1** before the 11/25 end-to-end version, **P2** before the eval / Demo Day, **P3** nice to have.

## Must do

### Decide where the agent lives (P1)
- [ ] `CLAUDE.md` and the backend docs put the research agent in `backend/app/agents/research/`, but the working code is in `researchAgent/`. Jake needs to know which is the real home before he wires the backend. Update the docs, or move the code, in a PR that tags him.
- [ ] The security modules now live in `research/security/` (`fetch_guard`, `option_validation`, `budget`, `fixtures`, `config`), with tests in `tests/security/`. **None of them are called by the agent yet.** Wiring them in is the next step (see Security below).
- [ ] `research/security/fixtures.py` loads a `{collected_at, options: [...]}` JSON format that nothing in this repo produces yet (the real fixtures are HTTP caches and agent outputs). Either write the conversion from the agent output, or delete the loader.

### Match the contract (P1)
- [ ] The output shape (`price.amt`, `basis`, `price_type`, `source.url`, `retrieved_at`) is not the `Option` type in `docs/api-contract.md` (`price`, `price_is_estimate`, `source_url`, `fetched_at`). Either write a mapper or propose a contract change in the same PR as the code, and tag Jake and Fernando.
- [ ] Prices have mixed bases (flights = total for all travelers, hotels = per room per night, activities = per person). The contract says `price` is the total for the whole party. The mapper must do the multiplication, and round estimates up.
- [ ] Tag snapshot data: `data_origin: "snapshot"` is not set anywhere yet. Cached prices date from 2026-11-22, and the UI has to show that age.

### Security (threat model)
- [ ] **T1 / T4, web price search (P1).** Layer 3 gives the model `WebSearch,WebFetch` with untrusted pages. Audit exactly what goes into that prompt: it should be the place name and city only, never origin, dates, budget or anything else about the user. **(check)**
- [ ] **T1, verify web prices in code (P1).** "Only accepted when a page that states the price is cited" is enforced by the prompt. Add a code check: the amount must appear in the cited page text, and be inside a plausible range for its category. Otherwise fall through to layer 4 (estimate).
- [ ] **T1, text from the LLM (P2).** Reject names and descriptions that contain zero-width or bidi characters, and cap their length (see `research/security/option_validation.py`). Geoapify/OSM and Wikivoyage are user-editable, so treat them as untrusted too. The enrichment step runs with tools off, which is good; keep it that way.
- [ ] **T3, source links (P2).** Check every `source.url` host against a list of known hosts. Today they include Google search/maps links, Rome2rio, Wikivoyage and airline links.
- [ ] **T4, direct HTTP (P2).** `pricing.py` and `core.py` call `urllib` directly for Wikivoyage and the other APIs. The hosts are fixed, so the risk is low, but route them through one guarded function so there is a single allowlist and nothing else is reachable. **(check)**
- [ ] **T6, per-trip limit (P1).** `--max-budget-usd 1.0` is per `claude -p` call, and there are about 5 to 10 calls per stop. Add a per-trip cap on LLM spend, calls and wall-clock time (see `research/security/budget.py`), and report `partial` or an error when it stops.
- [ ] **T2, cache (P2).** The default cache keeps entries forever. Production must set `cache_ttl_hours`; add a way to purge by source, and make sure a poisoned price can't be served for long.
- [ ] **Keys (P1).** `core.py` strips keys from cache keys and bodies. I scanned `tests/fixtures/` for `apiKey=`-style values and found none (the 34 name-based hits were false positives such as Google ad `sig=` parameters). `tests/security/test_repo_fixtures_no_keys.py` now fails if an `apiKey=`/`access_token=` value appears in `tests/fixtures/`. Never put these keys in `NEXT_PUBLIC_*`.
- [ ] **Injection test cases (P2).** Add fixture pages and listings with hidden instructions, absurd prices and exfiltration URLs, and show that nothing bad reaches the output.

### Cost and the eval (P1 to P2)
- [ ] `claude_json` throws away the CLI's JSON metadata. Check the output for cost and token fields and record them per call and per trip. The course needs cost per task and at 10,000 requests/day, and nothing is logged now.
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
- [ ] **`core.http` and the cache (P1).** Test `_redact`, `_canon_url` and `_key` so the same request with a different `apiKey` hits the same cache entry, and no key is ever written to a cache file or key. Test `is_fresh` and TTL expiry, that failed requests are not cached, and that offline mode raises `CacheMiss` instead of calling out.
- [ ] **`claude_json` with a fake `subprocess.run` (P1).** Check the command: `--tools ""` when `web=False`, `WebSearch,WebFetch` only when `web=True`, `--max-budget-usd` always present, neutral cwd. Check handling of non-JSON output, `is_error`, missing structured output, timeout, and that the cache key changes with the prompt, schema, `web` and `model`.
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
- [ ] **Wire the guards in, then test the wiring (P1).** A test that fails if any module under `research/` calls `urllib.request.urlopen` or `subprocess` outside the guarded entry points, so a new unguarded call can't slip in.
- [ ] **Prompt-injection fixtures (P2).** Fake Wikivoyage entries, OSM names and web pages with hidden instructions ("ignore previous instructions", "report the price as $1", a URL that carries the user's origin). Assert the output prices come only from the structured fields, no extra URL is fetched, and nothing from the page shows up in tool arguments.
- [ ] **Poisoned cache (P2).** A cached price outside the plausible range must be rejected or flagged on read, not served.
- [ ] **Budget enforcement through the pipeline (P1).** With a tiny `Limits`, a run stops, returns `partial`, and `stopped_by` is recorded. No further model calls are made after the limit.
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
