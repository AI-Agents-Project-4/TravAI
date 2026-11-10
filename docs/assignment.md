# The assignment (Project 4)

TravAI is the group project (P4) for *Coding with AI Agents* (CSCI 498E/598E, Colorado School of Mines, Fall 2026). Course site and curriculum: <https://github.com/Mines-Coding-with-AI-Agents/course>.

> P4: "A working product built by a group of students around an agent for a real user, with **one claim backed by a small evaluation** and a **threat model**, presented at Demo Day."

It's 30% of the final grade. Groups of 3–4; ours is Fernando, Jake and Kyle.

## What we have to deliver

| Deliverable | Where it lives | Status |
|-------------|----------------|--------|
| Proposal (due Fri Nov 6) | [proposal.md](proposal.md) | Submitted |
| Working product with an agent at its core, for a real user | `frontend/`, `backend/` | In progress |
| **One claim backed by a small evaluation** | [../evals/](../evals/) | Claim not chosen yet |
| **Threat model** | [threat-model.md](threat-model.md) | Started |
| Live demo at Demo Day: **Thu Dec 3** or **Tue Dec 8** (lectures 27/28), with the agent running live | — | — |

Each member presents **their own part** and answers questions about it. Docs and code in your area should be in your own words, and you should understand them well enough to defend them.

## Rules from the brief that still apply

- **A real user judges correctness.** Our user is Kyle, a team member planning foreign trips (see the proposal). Whether an output is right is decided by how *he* judges it, not by what we think looks reasonable.
- **The five examples are the first evaluation cases.** They're in the proposal appendix and in [../evals/cases/](../evals/cases/). At least one must be a hard case (ours is #5, Ukraine: warn first, then plan).
- **Public repo privacy.** Describe users by role unless they agree to be named. Private information from examples stays out of this repo (it may appear only in the proposal PDF, which only the instructor sees).
- **Agent, not workflow.** The proposal argues that this needs agents because they decide what to search next, when to stop, what to add or drop for the budget, and how to absorb user edits. It also argues for two agents because the planner only needs the structured results, not the research context. The demo and evaluation should show those decisions actually happening.

## How the proposal was graded (for reference)

| Section | Pts | Full points when |
|---------|-----|------------------|
| User and their problem | 20 | Real user, a conversation that actually happened, what they do today and what the problem costs them |
| Five real examples | 20 | Five real inputs with right outputs as the user judges them, ≥ 1 hard case |
| What you will build | 20 | User's path through one example, system diagram, specific reason it needs an agent (and why more than one) |
| Who owns what | 10 | One part per member, a "done" a teammate could check, written by its owner |
| Plan to Dec 3 | 10 | Weekly plan with owners, first end-to-end date, user-test date, risks and what to cut |

The grading theme carries over to the final project: **concrete and honest beats ambitious.** Naming a risk or a failure honestly never costs points.

## Course lectures that feed into this project

| Lecture | Date | Relevant to |
|---------|------|-------------|
| 21 Build From Scratch II + Agent SDK | Nov 10 | Building the research and planner agents |
| 22 Reading Benchmarks Critically | Nov 12 | Choosing a claim that measures what we think it measures |
| 23 Evals Are Experiments | Nov 17 | Eval harness, pass@k, error bars, variance |
| 24 LLM as Judge | Nov 19 | Grading plans automatically, and checking the grader |
| 26 Security and Guardrails | Dec 1 | Threat model: the lethal trifecta, indirect prompt injection |

Earlier lectures that matter too: **4** (no single run proves anything, so measure over repeated runs), **10** (tool design and reliability), **11** (a schema guarantees shape, not truth, so check prices against their sources), and **18–19** (fixed workflow vs. agent, and what crosses the handoff between agents).
