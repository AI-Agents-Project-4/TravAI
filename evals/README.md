# Evaluation

The course requires **one claim backed by a small evaluation that runs in GitHub Actions**. Because we have two agents, it also requires showing the second agent beats **a single agent** on the same cases, and reporting the **cost** (per task and at 10,000 requests/day). See [../docs/assignment.md](../docs/assignment.md). This folder holds the cases, the harness and the raw results. The write-up (claim, numbers, cost) goes in [../EVAL.md](../EVAL.md).

> **Status:** cases seeded from the proposal. The claim, owner and harness aren't decided yet. Decide them as a team before 11/25 so there's time to run the eval before Demo Day.

## The claim (to decide)

Pick **one** claim the user cares about that we can measure honestly. Candidates that come straight from the proposal:

1. **No underestimates.** For feasible trips, each plan's stated total is ≥ the cost re-checked from its `source_url`s in ≥ X% of plans.
2. **Feasibility is right.** The planner returns 3 in-budget plans for feasible cases and `feasible: false` for infeasible ones (example 4), with Kyle's judgment as the ground truth.
3. **Edits survive redraft.** After a redraft, 100% of locked user edits are still there, and the total stays within budget or the dropped items are reported.

The claim should compare against **the obvious simpler approach** (e.g. a single prompt with web search, or a fixed workflow). Separately, **TravAI's two agents must be compared with one agent** that does research and planning together, on the same cases and with the same tools.

Whichever we choose, the measurement should follow lectures 4 and 23. Run each case several times (agents are stochastic), report pass@k or a rate **with error bars**, and say how many runs it's based on. If an LLM grades the outputs (lecture 24), check that grader against Kyle's own judgments on a sample.

## Cases

`cases/*.json`: one file per case, starting with the five from the proposal appendix. Each case has the input (in the shape of `POST /trips` from the [API contract](../docs/api-contract.md)) and **what a right output looks like as Kyle would judge it**. Add more cases from Kyle's real trips as they come up, but keep private details out (this repo is public).

| Case | Kind |
|------|------|
| [01-tokyo-5d-5000](cases/01-tokyo-5d-5000.json) | Normal, flagship walkthrough |
| [02-colorado-springs-1d-500](cases/02-colorado-springs-1d-500.json) | Drive, no flight |
| [03-europe-14d-10000](cases/03-europe-14d-10000.json) | Multi-stop, cuttable |
| [04-japan-30d-500](cases/04-japan-30d-500.json) | Infeasible: must say so honestly |
| [05-ukraine-3d-1000](cases/05-ukraine-3d-1000.json) | **Hard case**: warn first, then plan |

Fields marked `null` (exact origin, dates) must be filled in with Kyle before the eval runs. Run the eval on fixed dates so results can be compared.

## Rules

- **The eval runs in GitHub Actions** (required). It calls real agents, so it costs money. Give it its own workflow, triggered manually (`workflow_dispatch`) and/or on a schedule, **not** on every PR. Keep the API key in a repo secret and set a run budget (cases × runs × max tokens). The regular `frontend` CI check stays free.
- Log tokens and cost for every run, since `EVAL.md` reports the cost per task and at 10,000 requests/day.
- Save the raw output of every run (`results/<date>-<claim>/`), not just the summary, so the numbers can be checked.
- Report failures as honestly as successes.
