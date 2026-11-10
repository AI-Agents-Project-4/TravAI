#!/usr/bin/env bash
# PreToolUse hook (Bash): enforce the team rule "never push to main".
#
# We are all org admins, so GitHub's branch protection does not stop an admin
# push to main. This hook stops Claude Code from doing it. It blocks:
#   - git push ... main / HEAD:main / +main / refs/heads/main / --delete main
#   - git push with no branch named while the current branch is main
#   - git push --all / --mirror (they include main)
#   - gh pr merge --admin (bypasses the CI requirement)
# Everything else is allowed. If the input can't be parsed, the command is allowed
# (the hook must never get in the way of normal work).
#
# Exit 2 + stderr = block the command and tell Claude why.
set -uo pipefail

input=$(cat)
read_field() { perl -MJSON::PP -0777 -e 'my $d = eval { decode_json(shift) } or exit 0; my $v = $d; $v = ref $v eq "HASH" ? $v->{$_} : undef for @ARGV; print $v // ""' "$input" "$@"; }
command=$(read_field tool_input command)
cwd=$(read_field cwd)
[ -n "$command" ] || exit 0
[ -n "$cwd" ] || cwd="${CLAUDE_PROJECT_DIR:-$PWD}"

block() {
  echo "Blocked by the TravAI team rule: never push to main directly ($1)." >&2
  echo "Create a branch (<firstname>/<short-desc>), push that, and open a PR. Merge only when CI passes. See CLAUDE.md > Workflow." >&2
  exit 2
}

# Split compound commands (&&, ||, ;, |, newlines) and check each part.
while IFS= read -r segment; do
  read -ra words <<< "$segment"
  [ ${#words[@]} -gt 0 ] || continue

  # gh pr merge --admin
  if [ "${words[0]}" = "gh" ] && [[ " ${words[*]} " == *" pr merge "* ]] && [[ " ${words[*]} " == *" --admin "* ]]; then
    block "gh pr merge --admin skips the required CI check"
  fi

  [ "${words[0]}" = "git" ] || continue

  # Walk past git's global options (-C <dir>, -c <k=v>, --no-pager, ...) to the subcommand.
  dir="$cwd"; i=1
  while [ $i -lt ${#words[@]} ]; do
    case "${words[$i]}" in
      -C) dir="${words[$((i + 1))]:-$dir}"; [[ "$dir" != /* ]] && dir="$cwd/$dir"; i=$((i + 2)) ;;
      -c|--git-dir|--work-tree|--namespace) i=$((i + 2)) ;;
      -*) i=$((i + 1)) ;;
      *) break ;;
    esac
  done
  [ "${words[$i]:-}" = "push" ] || continue

  # Collect the push's positional args: <remote> [<refspec>...]
  positional=()
  i=$((i + 1))
  while [ $i -lt ${#words[@]} ]; do
    w="${words[$i]}"
    case "$w" in
      --all|--mirror) block "git push $w includes main" ;;
      -o|--push-option|--repo|--receive-pack|--exec) i=$((i + 2)); continue ;;
      -*) ;;
      *) positional+=("$w") ;;
    esac
    i=$((i + 1))
  done

  current=$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

  if [ ${#positional[@]} -le 1 ]; then
    # No branch named: git pushes the current branch.
    [ "$current" = "main" ] && block "you are on main and git push would push it"
    continue
  fi

  for refspec in "${positional[@]:1}"; do
    ref="${refspec#+}"            # +main = force push
    dest="${ref##*:}"             # src:dest -> dest (no colon -> whole ref)
    dest="${dest#refs/heads/}"
    src="${ref%%:*}"
    [ "$dest" = "main" ] && block "git push targets main"
    [[ "$ref" != *:* && "$src" == "HEAD" && "$current" == "main" ]] && block "HEAD is main"
  done
done < <(printf '%s\n' "$command" | sed -e 's/&&/\n/g' -e 's/||/\n/g' -e 's/[;|]/\n/g')

exit 0
