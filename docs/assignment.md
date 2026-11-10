# The assignment (Project 4)

TravAI is the group project (P4) for *Coding with AI Agents* (CSCI 498E/598E, Colorado School of Mines, Fall 2026). It's 30% of the final grade. Team: Fernando, Jake, Kyle.

> **This is a summary, not the source.** Synced **2026-11-09**. When sources disagree, this order wins:
> 1. **Canvas** (system of record for deadlines, grades and assignment pages)
> 2. **Student repo** (private, enrolled students only): `Mines-Coding-with-AI-Agents/student`, especially `projects/p4-full-stack-agent/`, `SCHEDULE.md` and `ANNOUNCEMENTS.md`
> 3. **Course site** (public): <https://github.com/Mines-Coding-with-AI-Agents/course>
>
> A session-start hook warns when the watched course files change after this sync (see "Keeping this current" below). The student repo is private, so this file paraphrases it instead of copying it.

## What P4 requires

| Requirement | Where it lives in this repo | Status |
|-------------|-----------------------------|--------|
| A real product for a real user, with an agent at its core (with a justification for needing an agent) | `frontend/`, `backend/` | In progress |
| **One claim backed by a small evaluation that runs in GitHub Actions**, e.g. "beats the obvious simpler approach" | [../EVAL.md](../EVAL.md), [../evals/](../evals/) | Claim not chosen |
| **Multi-agent justification:** because we use 2 agents, the eval must also show the second agent earns its place **against a single agent** | [../EVAL.md](../EVAL.md) | Not started |
| **Cost:** cost of one task, and projected cost at **10,000 requests/day** | [../EVAL.md](../EVAL.md) | Not started |
| **Threat model:** which legs of the lethal trifecta we have and what we did about each | [threat-model.md](threat-model.md) | Draft |
| **Public repo** with `README.md`, `DECISIONS.md` (judgment calls and why), `EVAL.md` (the claim and the numbers), and a **recorded demo** | repo root | Stubs |
| **Live presentation** Thu Dec 3 or Tue Dec 8, graded with a rubric in the room | — | — |
| **AI-assisted review of the repo**, checked by the instructor | the whole repo | — |

The rubric for the presentation and the repo **hasn't been released yet**. When it comes out, sync this file.

## Rules that shape how we work

- **Each member owns one named part from the first week to the presentation**, and presents and answers questions on it. **The commit history shows who owned what**, so each person commits their own part (agent-assisted is fine; agents committing in a teammate's area is not).
- **The user's judgment is the ground truth.** The member who knows the domain leads the user conversations and the examples the eval checks. Our user is Kyle (proposal), and Kyle owns the examples.
- **The five proposal examples are the first eval cases** ([../evals/cases/](../evals/cases/)). #5 is the hard case.
- **Public repo privacy:** describe users by role unless they agree to be named, and keep private example details out.
- **Concrete and honest beats ambitious.** Naming a risk or a failure honestly never costs points.

> ⚠️ **Open question for the instructor:** the student-repo P4 README asks for a user *outside this class*. The Canvas proposal page says *in or outside your group*. Our user is a team member. Canvas wins per the course's own rule, but confirm this with the instructor.

## Dates

| Date | What |
|------|------|
| Fri Nov 6 | Proposal due ✅ |
| Tue Nov 24 (lecture 25) | **Optional dry run** of the presentation |
| Thu Nov 26 | Thanksgiving, no class |
| Tue Dec 1 (lecture 26) | Security & Guardrails, input for the threat model |
| **Thu Dec 3 / Tue Dec 8** | **Presentations, live. P4 due Dec 8** |

## Lectures that feed into the project

| Lecture | Date | Relevant to |
|---------|------|-------------|
| 18 Agent Architectures | Oct 29 | Workflow vs. agent, measured. Our "why an agent" argument |
| 19 Multi-Agent Systems | Nov 3 | One agent vs. a lead + worker, measured. Our "why two agents" eval |
| 20–21 Build From Scratch, Agent SDK | Nov 5, Nov 10 | Building the research and planner agents, bounding their spend |
| 22 Reading Benchmarks Critically | Nov 12 | Choosing a claim that measures what we think it does |
| 23 Evals Are Experiments | Nov 17 | Eval harness, pass@k, error bars, variance |
| 24 LLM as Judge | Nov 19 | Grading plans automatically, and checking the grader |
| 26 Security and Guardrails | Dec 1 | Threat model: lethal trifecta, indirect prompt injection |

Earlier ones that apply: **4** (no single run proves anything), **10** (tool design and reliability), **11** (a schema guarantees shape, not truth), **P2** (an eval that runs in GitHub Actions).

## Keeping this current

- `.claude/hooks/course-check.sh` runs when a Claude Code session starts. It compares the watched course files listed in `.claude/course-snapshot.tsv` with GitHub, and lists current P4 announcements. It says nothing when nothing changed, and it skips silently if `gh` isn't logged in or you're offline.
- When it reports a change, run `/course-sync` to re-read the sources, update this file and the snapshot, and open a PR.
- Canvas isn't covered. When something new about P4 is posted on Canvas, paste it in and run `/course-sync`. *Canvas content last added: 2026-11-09 (proposal and team pages).*
