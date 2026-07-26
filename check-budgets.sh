#!/usr/bin/env bash
# Token-budget gate for skill/command descriptions and skill bodies (Lever D).
#
# A ratchet: the Lever A/B/F context savings cannot silently regrow. CI fails
# the build when any deployed skill or command exceeds its budget.
#
#   - Description budget (skills + commands): a per-file char cap on the YAML
#     frontmatter `description:` value. Calibrated just above the post-Lever-A
#     measured max so it locks in the trim without blocking normal edits.
#   - Body budget (skills): a per-file line cap on the body (everything after
#     the closing frontmatter `---`). Defaults to the Anthropic ≤500-line
#     guideline; large orchestrators get an explicit, calibrated override.
#
# Budgets are calibrated from the post-A/B baselines — see BODY_OVERRIDE and the
# defaults below. Re-measure and re-calibrate (never just raise to silence a
# failure) if a deliberate, reviewed change grows a file.
#
# Checks the DEPLOYED plugin copies only (github-workflow/, local-workflow/);
# the _shared-skills/ canonical templates carry {{PLUGIN_NAME}} placeholders and
# are not loaded into context, so they are excluded.
#
# Usage:
#   bash check-budgets.sh              # enforce budgets; exit 1 if any exceeded
#   bash check-budgets.sh --self-test  # prove the gate rejects an oversized file
#
# Exit codes:
#   0  all files within budget (or self-test passed)
#   1  at least one file over budget (or self-test failed)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"

# 3.5 chars/token is conservative for markdown instruction prose (matches
# count-tokens.sh). Integer arithmetic: chars * 10 / 35.
CHARS_PER_TOKEN_X10=35

# --- Budgets (calibrated from post-Lever-A/B measured baselines) ------------
# Description: current max is 494 chars (verify-feature); 510 sits ~3.2% above
# it. (Block-scalar descriptions like verify-feature's run longer than the
# single-line ones, so the binding max is well above debugging's 434.)
DESC_BUDGET_CHARS=510
# Body: the Anthropic ≤500-line guideline; most skills sit well under it.
BODY_BUDGET_LINES=500

# Per-file body overrides for legitimately large orchestrators. Each value sits
# just above the file's current measured body with a few % headroom, mirroring
# the footprint-check convention — tight enough to catch regression, loose
# enough not to block normal edits. Key = repo-relative path.
declare -A BODY_OVERRIDE=(
    # PR-review orchestrator; body is 715 lines, 740 is ~3.5% headroom.
    ["github-workflow/skills/code-review/SKILL.md"]=740
    # Story orchestrator, the other legitimately large one: it now covers 11
    # phases (pick through merge) rather than stopping at the PR, and the
    # post-PR detail already lives in references/. Body is 513 lines, 530 is
    # ~3.3% headroom, matching the calibration above.
    ["github-workflow/skills/execute/SKILL.md"]=530
)

# --- Helpers ----------------------------------------------------------------

# Print the logical length (in characters) of a frontmatter `description:`
# value, handling both single-line values and YAML block scalars (>, >-, |, |-,
# and their +/- chomping variants). Continuation lines are the indented lines
# that follow until the next top-level frontmatter key. Returns 0 if absent.
description_chars() {
    awk '
        /^---[[:space:]]*$/ { fm++; if (fm >= 2) exit; next }
        fm == 1 && done != 1 {
            if (collecting != 1) {
                if ($0 ~ /^description:/) {
                    val = $0
                    sub(/^description:[[:space:]]*/, "", val)
                    # A bare block-scalar indicator means the value is on the
                    # following indented lines, not this one.
                    if (val ~ /^[>|][+-]?[[:space:]]*$/) val = ""
                    collecting = 1
                }
            } else {
                if ($0 ~ /^[[:space:]]+/) {
                    cont = $0
                    sub(/^[[:space:]]+/, "", cont)
                    val = (val == "") ? cont : val " " cont
                } else {
                    collecting = 0
                    done = 1
                }
            }
        }
        END { print length(val) }
    ' "$1"
}

# Print the number of body lines (everything after the closing frontmatter
# delimiter). Files without frontmatter count as all-body.
body_lines() {
    awk '
        /^---[[:space:]]*$/ { fm++; next }
        fm >= 2 { c++ }
        END { print c + 0 }
    ' "$1"
}

tokens_for() {
    echo $(( $1 * 10 / CHARS_PER_TOKEN_X10 ))
}

# --- Enforcement ------------------------------------------------------------

status=0
checked=0

check_description() {
    local file="$1"
    local chars tokens
    chars=$(description_chars "$file")
    [ "$chars" -eq 0 ] && return 0  # missing/empty — lint-skills flags that
    tokens=$(tokens_for "$chars")
    if [ "$chars" -gt "$DESC_BUDGET_CHARS" ]; then
        echo "FAIL  description  $file"
        echo "      ${chars} chars (~${tokens} tok) exceeds budget ${DESC_BUDGET_CHARS} chars by $(( chars - DESC_BUDGET_CHARS )) — trim the frontmatter description"
        status=1
    fi
}

check_body() {
    local file="$1"
    local lines budget
    lines=$(body_lines "$file")
    budget="${BODY_OVERRIDE[$file]:-$BODY_BUDGET_LINES}"
    if [ "$lines" -gt "$budget" ]; then
        echo "FAIL  body         $file"
        echo "      ${lines} body lines exceeds budget ${budget} by $(( lines - budget )) — move detail to templates/ or references/ read on demand"
        status=1
    fi
}

run_gate() {
    local skill_files command_files
    mapfile -t skill_files < <(find github-workflow local-workflow -name 'SKILL.md' 2>/dev/null | sort)
    mapfile -t command_files < <(find github-workflow local-workflow -path '*/commands/*.md' 2>/dev/null | sort)

    for f in "${skill_files[@]:-}"; do
        [ -z "$f" ] && continue
        check_description "$f"
        check_body "$f"
        checked=$(( checked + 1 ))
    done
    for f in "${command_files[@]:-}"; do
        [ -z "$f" ] && continue
        check_description "$f"
        checked=$(( checked + 1 ))
    done
}

# --- Self-test: prove the gate actually bites -------------------------------
# Fabricates an over-budget and an under-budget skill in a temp dir and asserts
# the gate flags the former and passes the latter. This is the automated proof
# of the issue's success criterion ("a deliberately oversized description/body
# is rejected").
self_test() {
    local tmp over_desc
    tmp="$(mktemp -d)"
    # Bake the path into the trap now (not a deferred $tmp reference) so the
    # EXIT handler does not trip `set -u` after this function's locals go away.
    trap "rm -rf '$tmp'" EXIT

    # Over-budget on BOTH description (long) and body (many lines).
    over_desc="$(printf 'x%.0s' $(seq 1 $(( DESC_BUDGET_CHARS + 50 ))))"
    {
        echo "---"
        echo "name: oversized"
        echo "description: ${over_desc}"
        echo "---"
        for _ in $(seq 1 $(( BODY_BUDGET_LINES + 20 ))); do echo "body line"; done
    } > "$tmp/oversized.md"

    # Within budget on both.
    {
        echo "---"
        echo "name: fine"
        echo "description: A short, within-budget description."
        echo "---"
        echo "A small body."
    } > "$tmp/fine.md"

    local over_desc_chars over_body fine_desc_chars fine_body fail=0
    over_desc_chars=$(description_chars "$tmp/oversized.md")
    over_body=$(body_lines "$tmp/oversized.md")
    fine_desc_chars=$(description_chars "$tmp/fine.md")
    fine_body=$(body_lines "$tmp/fine.md")

    [ "$over_desc_chars" -gt "$DESC_BUDGET_CHARS" ] || { echo "self-test FAIL: oversized description ($over_desc_chars) not detected"; fail=1; }
    [ "$over_body" -gt "$BODY_BUDGET_LINES" ]       || { echo "self-test FAIL: oversized body ($over_body) not detected"; fail=1; }
    [ "$fine_desc_chars" -le "$DESC_BUDGET_CHARS" ] || { echo "self-test FAIL: within-budget description ($fine_desc_chars) wrongly flagged"; fail=1; }
    [ "$fine_body" -le "$BODY_BUDGET_LINES" ]       || { echo "self-test FAIL: within-budget body ($fine_body) wrongly flagged"; fail=1; }

    if [ "$fail" -eq 0 ]; then
        echo "self-test OK: gate rejects oversized description and body, passes within-budget files"
        return 0
    fi
    return 1
}

# --- Main -------------------------------------------------------------------

if [ "${1:-}" = "--self-test" ]; then
    self_test
    exit $?
fi

echo "=== Skill/command budget gate ==="
echo "Description budget: ${DESC_BUDGET_CHARS} chars | Body budget: ${BODY_BUDGET_LINES} lines (per-file overrides apply)"
echo ""

run_gate

echo ""
if [ "$status" -eq 0 ]; then
    echo "OK: all ${checked} files within budget."
else
    echo "Budget gate failed — trim the file(s) above or recalibrate the budget with a documented reason."
fi
exit $status
