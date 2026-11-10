#!/usr/bin/env bash
# SessionStart hook: tell the agent when the course material that docs/assignment.md
# summarizes has changed since it was last synced, and list current P4 announcements.
#
# - Compares each entry in .claude/course-snapshot.tsv with GitHub (via `gh api`).
# - Prints nothing when nothing changed, so a quiet session stays quiet.
# - Read-only, and fails silent: no gh, not logged in, no access to the private
#   student repo, or offline -> exits 0 with no output. Each call has a 5 s deadline.
#
# Testing aid: COURSE_CHECK_TODAY=YYYY-MM-DD pretends it is another day.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SNAPSHOT="$ROOT/.claude/course-snapshot.tsv"
STUDENT_REPO="Mines-Coding-with-AI-Agents/student"
today=$(date +%Y-%m-%d)
[[ "${COURSE_CHECK_TODAY:-}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && today=$COURSE_CHECK_TODAY

command -v gh >/dev/null 2>&1 || exit 0
[ -f "$SNAPSHOT" ] || exit 0

# Run a command with a 5-second deadline (perl's alarm works on macOS and Linux).
with_deadline() { perl -e 'alarm 5; exec @ARGV' "$@"; }

tmp=$(mktemp -d 2>/dev/null) || exit 0
trap 'rm -rf "$tmp"' EXIT

# Look up every watched entry in parallel; each writes its label to a file if it changed.
i=0
while IFS=$'\t' read -r repo dir entry pinned label; do
  [[ -z "$repo" || "$repo" == \#* ]] && continue
  i=$((i + 1))
  (
    tree="main"; [ "$dir" != "." ] && tree="main:$dir"
    current=$(with_deadline gh api "repos/$repo/git/trees/$tree" \
      --jq ".tree[] | select(.path==\"$entry\") | .sha" 2>/dev/null) || exit 0
    path="$entry"; [ "$dir" != "." ] && path="$dir/$entry"
    [ -n "$current" ] && [ "$current" != "$pinned" ] && echo "- $label: \`$repo\` → \`$path\`" > "$tmp/changed.$i"
  ) &
done < "$SNAPSHOT"

# Current announcements (Show until >= today) that mention P4.
(with_deadline gh api -H "Accept: application/vnd.github.raw" \
  "repos/$STUDENT_REPO/contents/ANNOUNCEMENTS.md" 2>/dev/null | awk -v today="$today" '
    function flush() { if (title != "" && substr(title, 1, 10) <= today && until >= today && body ~ /P4/) print "- " title }
    /^## [0-9]{4}-[0-9]{2}-[0-9]{2} / { flush(); title = substr($0, 4); until = ""; body = ""; next }
    /^- Show until: / { until = $4; next }
    { body = body "\n" $0 }
    END { flush() }' > "$tmp/announcements") &
wait

changed=$(cat "$tmp"/changed.* 2>/dev/null)
announcements=$(cat "$tmp/announcements" 2>/dev/null)

[ -z "$changed" ] && [ -z "$announcements" ] && exit 0

echo "=== TravAI course check ==="
if [ -n "$changed" ]; then
  echo "Course material changed since docs/assignment.md was last synced:"
  echo "$changed"
  echo "Tell the user about this at the start of your reply, and suggest running /course-sync."
fi
if [ -n "$announcements" ]; then
  echo "Current course announcements that mention P4 (student repo ANNOUNCEMENTS.md):"
  echo "$announcements"
fi
exit 0
