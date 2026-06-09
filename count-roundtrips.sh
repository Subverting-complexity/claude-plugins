#!/usr/bin/env bash
# Counts gh/git network calls described in a set of instruction files.
#
# Parses each file for lines that invoke gh (GitHub CLI API) or git network
# operations (fetch, push, ls-remote), giving a static proxy for how many
# round trips a workflow makes. Use this to evidence latency claims in PRs
# and to catch regression before they ship.
#
# Usage:
#   bash count-roundtrips.sh github-workflow/commands/pick-story.md
#   bash count-roundtrips.sh --workflow execute
#   bash count-roundtrips.sh --workflow pick --workflow finish
#
# Exit code: always 0 (informational tool, no gate).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Regex patterns that represent a gh or git network round trip in instruction prose.
GH_PATTERN='gh (api|issue|pr|repo|release) '
GIT_NET_PATTERN='git (push|fetch|ls-remote|pull) '

declare -a files=()
declare -a workflows=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --workflow) workflows+=("$2"); shift 2 ;;
        *)          files+=("$1"); shift ;;
    esac
done

# Expand known workflow shortcuts to their hot-path file sets.
for wf in "${workflows[@]:-}"; do
    case "$wf" in
        execute)
            files+=(
                "github-workflow/skills/execute/SKILL.md"
                "github-workflow/skills/execute/references/finish-and-self-review.md"
                "github-workflow/templates/board-resolution.md"
                "github-workflow/templates/claim-procedure.md"
                "github-workflow/templates/story-selection.md"
                "github-workflow/templates/issue-fields-resolution.md"
                "github-workflow/templates/sibling-pr-lookup.md"
                "github-workflow/templates/worktree-hygiene.md"
            )
            ;;
        pick)
            files+=(
                "github-workflow/commands/pick-story.md"
                "github-workflow/templates/story-selection.md"
                "github-workflow/templates/claim-procedure.md"
                "github-workflow/templates/default-labels.md"
            )
            ;;
        finish)
            files+=(
                "github-workflow/commands/finish-story.md"
                "github-workflow/templates/board-resolution.md"
                "github-workflow/templates/claim-procedure.md"
                "github-workflow/templates/sibling-pr-lookup.md"
            )
            ;;
        *)
            echo "Unknown workflow: $wf. Known: execute, pick, finish" >&2
            exit 1
            ;;
    esac
done

if [ ${#files[@]} -eq 0 ]; then
    echo "Usage: $0 <file1> [file2 ...] [--workflow execute|pick|finish]" >&2
    exit 1
fi

echo "=== Round-trip analysis ==="
total_gh=0
total_git=0

for f in "${files[@]}"; do
    abs="$REPO_ROOT/$f"
    if [ ! -f "$abs" ]; then
        printf "  (missing) %s\n" "$f"
        continue
    fi

    gh_count=$(grep -cE "$GH_PATTERN" "$abs" 2>/dev/null || true)
    git_count=$(grep -cE "$GIT_NET_PATTERN" "$abs" 2>/dev/null || true)

    printf "  %-60s  gh: %2d  git: %2d\n" "$f" "$gh_count" "$git_count"
    total_gh=$(( total_gh + gh_count ))
    total_git=$(( total_git + git_count ))
done

echo ""
echo "  Total gh calls:          $total_gh"
echo "  Total git network calls: $total_git"
echo "  Total round trips:       $(( total_gh + total_git ))"
