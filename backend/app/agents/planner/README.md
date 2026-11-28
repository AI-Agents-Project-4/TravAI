# Planner agent (owner: Jake)

Turns the research agent's options into **three itineraries** that fit the budget, says honestly when the trip **isn't feasible**, and **redrafts** a plan around the user's edits.

## How it works

The model and the code split the job:

| The model decides | The code decides (`rules.py`) |
|---|---|
| Three themes, a title and summary for each | Whether the trip is feasible at all |
| Which flight and hotel each plan uses | Every total and the cost breakdown |
| Which activities go on which day | Required transport (airport transfers both ways, the drive there and back, trains between stops) |
| On redraft: what fills the time the user freed up | Opening hours, the stop you're at each day, day length, day trips |
| | Fitting the budget, and what gets dropped |

So a plan can never claim a total its options don't add up to (product rule 1), and "not feasible" never depends on the model (rule 3).

### A new trip (`Planner.draft`)

1. **Enough data?** No flights, no place to stay, or no driving route means there's no honest plan: `PlanningFailed`, and the trip shows why.
2. **Feasible?** Cheapest flight + cheapest hotel at each stop + required transport + food and local transport. Over the budget: `feasible: false` with that minimum, rounded up to the next 50.
3. **Propose.** The model gets a compact catalog with short ids (`f1`, `h2`, `a17`), the days with their weekday and stop, and the money left for activities. It answers with ids only, as JSON checked against a schema.
4. **Assemble.** Unknown ids are ignored. Items move to a day when they're open and at the right stop, or get dropped. Days are timed from 09:00 with 30 minutes between items, at most 10 hours. If the plan is over budget, unlocked activities go, most expensive first, then a cheaper flight or hotel.
5. **Fallback.** If the model fails, three themed plans are built from simple rules. The result says so (`used_fallback`), and the eval must count it as a failure.

### A redraft (`Planner.redraft`)

Locked items stay exactly where the user put them. Removed items never come back. The model fills the rest, and the same rules check it, but the budget fit drops only unlocked items and never swaps the flight or hotel. Anything the user kept that had to go comes back in `dropped_items` with a reason. If the user's locked items alone go over budget, the plan gets an `over_budget` warning instead of losing them (rule 5).

## Files

| File | What |
|---|---|
| `types.py` | Plain data: `Item` (an option), `TripFacts`, `ResearchFacts`, `PlanDraft`, results |
| `rules.py` | `Catalog` (options indexed by kind and stop) and `Assembler` (checks, times, totals, budget, warnings) |
| `prompts.py` | System prompts, output schemas, the compact catalog and aliases |
| `llm.py` | `ClaudeCLI` (`claude -p`, the team's Claude plan) and `AnthropicAPI` (SDK, for GitHub Actions), with token and cost logging |
| `planner.py` | `Planner`: draft, redraft, the rule-based fallback, single-agent mode |

No database and no web framework in here: `app/pipeline.py` and `app/routes/plans.py` turn rows into `Item`s and drafts back into rows, and `app/cli.py` runs it on in-memory options for the eval.

## Safety

Catalog text comes from websites and is treated as data (rule 6). Every system prompt says so, the mapper strips invisible characters and caps lengths, and the model can only answer with ids from the catalog. Anything else is ignored.

## Tests

`backend/tests/test_planner.py` runs it on a small handmade catalog. `test_trip_flow.py` runs it on real research output (Kyle's offline cache) through the API, with a fake model (`tests/fakes.py`).
