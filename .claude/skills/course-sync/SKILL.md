---
name: course-sync
description: Re-sync docs/assignment.md with the course's P4 requirements (Canvas text the user pastes, the private student repo, the public course site), update the snapshot the session-start check compares against, and open a PR. Use when the course-check hook reports a change, when the user pastes new P4 material from Canvas, or when asked to "sync the course" / "check the course for P4 changes".
---

# Sync the course requirements

`docs/assignment.md` summarizes what P4 requires. The session-start hook `.claude/hooks/course-check.sh` compares the watched course files in `.claude/course-snapshot.tsv` against GitHub. This skill brings both up to date.

## Source priority

1. **Canvas**, which only reaches us when the user pastes it. Always wins.
2. **Student repo** `Mines-Coding-with-AI-Agents/student` (**private**).
3. **Course site** `Mines-Coding-with-AI-Agents/course` (public).

## Steps

1. **See what changed.** For each row in `.claude/course-snapshot.tsv`, compare the pinned sha with the current one and read the diff:
   ```bash
   gh api "repos/<repo>/git/trees/main:<directory>" --jq '.tree[] | select(.path=="<entry>")'
   gh api "repos/<repo>/compare/<old-commit>...main" --jq '.files[] | select(.filename | startswith("<directory>/<entry>")) | {filename, patch}'
   ```
   To find `<old-commit>`, look up the commit that last touched the path on or before the snapshot date: `gh api "repos/<repo>/commits?path=<path>&until=<snapshot-date>T23:59:59Z&per_page=1" --jq '.[0].sha'`. If the user has the student repo cloned locally (e.g. `~/Developer/CS/AI/student`), `git -C <clone> fetch` and `git diff` work too. **Never run `git pull` there.** That repo has its own `./bin/update`.
   Also read the current P4 items in the student repo's `ANNOUNCEMENTS.md`, and any Canvas text the user pasted.
2. **Report before you edit.** Tell the user in a few lines what changed and what it means for TravAI: new or changed requirements, dates, or rubric items, and anything that conflicts with what we're building. Flag conflicts between sources and resolve them using the priority above. Say which source you followed.
3. **Update `docs/assignment.md`.** Change the requirements table, dates, open questions and the "Synced" date. Also update the "Canvas content last added" line if Canvas text was pasted. If something affects other files (`EVAL.md`, `evals/README.md`, `docs/threat-model.md`, the timeline in `CLAUDE.md`), update those too, or list them for the owner if they're in someone else's area.
4. **Update `.claude/course-snapshot.tsv`** with the new shas (and add rows for anything new worth watching, e.g. a rubric file).
5. **Check privacy.** The student repo is private and this repo is public. Paraphrase and keep only what we act on. Don't paste whole files or long passages from the student repo. First names only.
6. **Open a PR** on a branch `<firstname>/course-sync-<YYYY-MM-DD>` (`main` is protected). Summarize the changes and any team decisions they force.
