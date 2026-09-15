#!/usr/bin/env bash
# Reports the plugin's instruction load in three tiers.
#
#   Tier 1, every chat: every skill, command and agent description, plus the
#     SessionStart hook. Every session pays it, whether or not the plugin is
#     used. A skill or command that sets `disable-model-invocation` is left out,
#     because Claude Code keeps its description out of context.
#   Tier 2, every run: a skill's own file, plus every templates/ or references/
#     file it cites without stating a condition, followed two levels deep.
#   Tier 3, on a trigger: a cited file whose citing sentence states a condition
#     (if, unless, when, whenever, only), and everything that file cites.
#
# A file cited without a condition anywhere on the path is tier 2. Write "once"
# rather than "when" for a step every run reaches, or the file it reads is
# counted as tier 3. Skips *-rationale.md files by default: they are marked
# "not read at runtime" throughout the codebase.
#
# A citation naming another skill's references directory
# (skills/<skill>/references/<file>.md) resolves against that skill.
#
# Usage:
#   bash count-tokens.sh github-workflow/skills/execute/SKILL.md --budget 15000
#   bash count-tokens.sh --every-chat --budget 900
#   bash count-tokens.sh <file> --exclude <path> --include-rationale
#   bash count-tokens.sh --self-test
#
# --budget gates tier 2 for a file, or tier 1 with --every-chat. Tier 3 is
# reported and never gated. --exclude drops one cited file (repeatable);
# excluding a file does not exclude what that file cites.
#
# Exit codes:
#   0  success (and under budget when --budget given, or self-test passed)
#   1  over budget, bad usage, or self-test failed

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
PLUGIN_DIR="github-workflow"

# description_chars comes from the per-file description gate, so the two
# scripts can never measure a description differently.
# shellcheck source=check-budgets.sh
source "$SCRIPT_DIR/check-budgets.sh"

# 3.5 chars/token is conservative for markdown instruction prose.
# Integer arithmetic: multiply chars by 10, divide by 35.
CHARS_PER_TOKEN_X10=35

budget=0
include_rationale=false
every_chat=false
self_test_mode=false
input_file=""
declare -a excludes=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --budget)        budget="$2"; shift 2 ;;
        --budget=*)      budget="${1#*=}"; shift ;;
        --exclude)       excludes+=("$2"); shift 2 ;;
        --exclude=*)     excludes+=("${1#*=}"); shift ;;
        --include-rationale) include_rationale=true; shift ;;
        --every-chat)    every_chat=true; shift ;;
        --self-test)     self_test_mode=true; shift ;;
        *)               input_file="$1"; shift ;;
    esac
done

tokens() {
    echo $(( $1 * 10 / CHARS_PER_TOKEN_X10 ))
}

# --- Tier 1: every chat -----------------------------------------------------

# Succeeds when a file's frontmatter turns off model invocation. Claude Code
# accepts true, yes, on and 1 in any letter case.
model_invocation_disabled() {
    awk '
        /^---[[:space:]]*$/ { fm++; if (fm >= 2) exit; next }
        fm == 1 && tolower($0) ~ /^disable-model-invocation:[[:space:]]*["\047]?(true|yes|on|1)["\047]?[[:space:]]*$/ { found = 1 }
        END { exit found ? 0 : 1 }
    ' "$1"
}

frontmatter_name() {
    awk '
        /^---[[:space:]]*$/ { fm++; if (fm >= 2) exit; next }
        fm == 1 && /^name:/ { sub(/^name:[[:space:]]*/, ""); gsub(/["\047]/, ""); print; exit }
    ' "$1"
}

# Characters of text every SessionStart hook puts into context. hooks.json
# keeps one "command" per line; a command of the form echo '...' puts its
# quoted text into context, so the echo and quotes are not counted.
session_start_chars() {
    local hooks="$1"
    [ -f "$hooks" ] || { echo 0; return; }
    awk '
        # The SessionStart block ends at the next event key at its own indent
        # or shallower; the nested "hooks": [ inside it does not end it.
        /"SessionStart"[[:space:]]*:/ { inside = 1; match($0, /^[[:space:]]*/); indent = RLENGTH; next }
        inside && /^[[:space:]]*"[A-Za-z]+"[[:space:]]*:[[:space:]]*\[/ {
            match($0, /^[[:space:]]*/)
            if (RLENGTH <= indent) inside = 0
        }
        inside && /"command"[[:space:]]*:/ {
            cmd = $0
            sub(/^[^:]*:[[:space:]]*"/, "", cmd)
            sub(/"[[:space:]]*,?[[:space:]]*$/, "", cmd)
            if (cmd ~ /^echo \047/) { sub(/^echo \047/, "", cmd); sub(/\047$/, "", cmd) }
            total += length(cmd)
        }
        END { print total + 0 }
    ' "$hooks"
}

# Sets every_chat_total (chars) and fills every_chat_lines with a breakdown.
declare -a every_chat_lines=()
every_chat_total=0
measure_every_chat() {
    local plugin_root="$REPO_ROOT/$PLUGIN_DIR"
    local plugin_name f name chars
    plugin_name="$(basename "$PLUGIN_DIR")"
    every_chat_lines=()
    every_chat_total=0
    for f in "$plugin_root"/skills/*/SKILL.md "$plugin_root"/commands/*.md "$plugin_root"/agents/*.md; do
        [ -f "$f" ] || continue
        if model_invocation_disabled "$f"; then
            every_chat_lines+=("  (hidden, disable-model-invocation) ${f#"$REPO_ROOT"/}")
            continue
        fi
        name="$(frontmatter_name "$f")"
        [ -z "$name" ] && name="$(basename "$f" .md)"
        # The listing names each entry as plugin:name, then its description.
        chars=$(( ${#plugin_name} + 1 + ${#name} + $(description_chars "$f") ))
        every_chat_lines+=("  $(printf "%6d" "$chars") chars  ~$(printf "%5d" "$(tokens "$chars")") tokens  ${f#"$REPO_ROOT"/}")
        every_chat_total=$(( every_chat_total + chars ))
    done
    chars=$(session_start_chars "$plugin_root/hooks/hooks.json")
    every_chat_lines+=("  $(printf "%6d" "$chars") chars  ~$(printf "%5d" "$(tokens "$chars")") tokens  SessionStart hook output")
    every_chat_total=$(( every_chat_total + chars ))
}

# --- Tiers 2 and 3: one skill or command ------------------------------------

is_rationale() {
    [[ "$1" == *-rationale.md ]]
}

is_excluded() {
    local rel="${1#"$REPO_ROOT"/}"
    local pattern
    for pattern in ${excludes[@]+"${excludes[@]}"}; do
        [ "$rel" = "${pattern#"$REPO_ROOT"/}" ] && return 0
    done
    return 1
}

# Succeeds when every citation of REF in FILE states a condition. A citation
# states one when a condition word (if, unless, when, whenever, only, except)
# appears in the sentence making it, or in the first sentence of its paragraph.
# A list item or table row is judged whole. One unconditional citation makes
# the file an every-run read.
cites_on_condition() {
    awk -v ref="$2" '
        function states_condition(s) {
            s = tolower(s)
            return s ~ /(^|[^a-z])(if|unless|when|whenever|only|except)([^a-z]|$)/
        }
        index($0, ref) {
            if ($0 ~ /^[ \t]*([-*+]|[0-9]+\.|\|)[ \t]/) {
                seen = 1
                if (!states_condition($0)) unconditional = 1
                next
            }
            n = split($0, sentences, /[.!?]+[ \t]+/)
            for (i = 1; i <= n; i++) {
                if (!index(sentences[i], ref)) continue
                seen = 1
                if (!states_condition(sentences[i]) && !states_condition(sentences[1])) unconditional = 1
            }
        }
        END { exit (seen && !unconditional) ? 0 : 1 }
    ' "$1"
}

# Scan a file for templates/ and references/ citations. Prints one line per
# citation: the citation as written, a tab, and the resolved absolute path.
#
# A citation that names another skill's references directory
# (skills/<skill>/references/<file>.md — how a shared reference such as
# code-review's auto-merge.md is cited from outside its own skill) is resolved
# against that skill, not the citing one. Without this the path would fall
# through to the plugin-level references/ directory and report "(missing)",
# hiding a real dependency from the count.
scan_deps() {
    local f="$1"
    [ -f "$f" ] || return 0
    # A plain `references/x.md` citation is relative to whichever file makes it,
    # which is not always the file this run started from: a level-1 reference
    # belonging to another skill cites its own siblings that way.
    local citer_ref_base="$ref_base"
    case "$f" in
        */references/*) citer_ref_base="${f%/*}" ;;
        */skills/*)     citer_ref_base="${f%/*}/references" ;;
    esac
    grep -oE '(skills/[a-zA-Z0-9_-]+/)?(templates|references)/[a-zA-Z0-9_-]+\.md' "$f" 2>/dev/null \
        | sort -u \
        | while IFS= read -r ref; do
            local name="${ref##*/}"
            local skill path
            case "$ref" in
                skills/*/references/*)
                    skill="${ref#skills/}"
                    skill="${skill%%/*}"
                    path="$REPO_ROOT/$plugin_dir/skills/$skill/references/$name" ;;
                skills/*/templates/*|templates/*)
                    # Templates live at the plugin root, never under a skill.
                    path="$template_base/$name" ;;
                *)
                    # Use the citing file's own references/ if it has one; fall
                    # back to the plugin-level references/ for templates that
                    # cross-cite.
                    if [ -f "$citer_ref_base/$name" ]; then
                        path="$citer_ref_base/$name"
                    elif [ -f "$ref_base/$name" ]; then
                        path="$ref_base/$name"
                    else
                        path="$REPO_ROOT/$plugin_dir/references/$name"
                    fi ;;
            esac
            printf '%s\t%s\n' "$ref" "$path"
        done
}

declare -A tier=()
declare -a order=()

tier_changed=0

# Record FILE at TIER, keeping the lower tier when it is reached twice.
place() {
    local f="$1" t="$2"
    if [ -z "${tier[$f]+x}" ]; then
        tier[$f]="$t"
        order+=("$f")
        tier_changed=1
    elif [ "$t" -lt "${tier[$f]}" ]; then
        tier[$f]="$t"
        tier_changed=1
    fi
}

# Fills tier[] and order[] for one file and what it cites, two levels deep.
classify() {
    local input_abs="$1"
    local rel ref dep t
    rel="${input_abs#"$REPO_ROOT"/}"
    plugin_dir=$(echo "$rel" | cut -d'/' -f1)
    template_base="$REPO_ROOT/$plugin_dir/templates"
    # For skills, references/ resolves relative to the skill's own directory.
    # For commands or top-level files, it resolves relative to the plugin directory.
    if [[ "$rel" == *"/skills/"* ]]; then
        ref_base="$(dirname "$input_abs")/references"
    else
        ref_base="$REPO_ROOT/$plugin_dir/references"
    fi

    tier=()
    order=()
    place "$input_abs" 2

    local -a level1=()
    while IFS=$'\t' read -r ref dep; do
        [ -z "$dep" ] && continue
        t=2
        cites_on_condition "$input_abs" "$ref" && t=3
        place "$dep" "$t"
        level1+=("$dep")
    done < <(scan_deps "$input_abs")

    # A level-2 citation can lower a level-1 file's tier after its own
    # citations were placed, so repeat the pass until no tier changes.
    local parent parent_tier
    tier_changed=1
    while [ "$tier_changed" -eq 1 ]; do
        tier_changed=0
        for parent in ${level1[@]+"${level1[@]}"}; do
            [ -f "$parent" ] || continue
            is_excluded "$parent" && continue
            if ! $include_rationale && is_rationale "$parent"; then continue; fi
            parent_tier="${tier[$parent]}"
            while IFS=$'\t' read -r ref dep; do
                [ -z "$dep" ] && continue
                t="$parent_tier"
                if [ "$t" -eq 2 ] && cites_on_condition "$parent" "$ref"; then t=3; fi
                place "$dep" "$t"
            done < <(scan_deps "$parent")
        done
    done
}

tier2_chars=0
tier3_chars=0
declare -a tier2_lines=()
declare -a tier3_lines=()
declare -a skipped_lines=()

measure_file() {
    local f chars line
    tier2_chars=0
    tier3_chars=0
    tier2_lines=()
    tier3_lines=()
    skipped_lines=()
    for f in "${order[@]}"; do
        if is_excluded "$f"; then
            skipped_lines+=("  (excluded) ${f#"$REPO_ROOT"/}")
            continue
        fi
        if ! $include_rationale && is_rationale "$f"; then
            skipped_lines+=("  (skipped, rationale) ${f#"$REPO_ROOT"/}")
            continue
        fi
        if [ ! -f "$f" ]; then
            skipped_lines+=("  (missing) ${f#"$REPO_ROOT"/}")
            continue
        fi
        chars=$(wc -c < "$f")
        line="  $(printf "%6d" "$chars") chars  ~$(printf "%5d" "$(tokens "$chars")") tokens  ${f#"$REPO_ROOT"/}"
        if [ "${tier[$f]}" -eq 2 ]; then
            tier2_lines+=("$line")
            tier2_chars=$(( tier2_chars + chars ))
        else
            tier3_lines+=("$line")
            tier3_chars=$(( tier3_chars + chars ))
        fi
    done
}

gate() {
    local label="$1" measured="$2"
    [ "$budget" -gt 0 ] 2>/dev/null || return 0
    echo ""
    if [ "$measured" -gt "$budget" ]; then
        echo "FAIL: ${label} ~${measured} tokens exceeds budget ${budget} tokens"
        return 1
    fi
    echo "OK: ${label} ~${measured} tokens is within budget ${budget} tokens"
}

# --- Self-test: prove the tiers are assigned as documented ------------------
self_test() {
    local tmp fail=0
    tmp="$(mktemp -d)"
    trap "rm -rf '$tmp'" EXIT
    local p="$tmp/plug"
    mkdir -p "$p/skills/main/references" "$p/skills/hidden" "$p/templates" "$p/commands" "$p/agents" "$p/hooks"

    cat > "$p/skills/main/SKILL.md" <<'EOF'
---
name: main
description: 'Twenty chars exactly'
---
Start by reading `references/always.md` and follow it.

If the run fails, read `references/rare.md`.

Once the build passes, follow `templates/step.md`. The run ends there.

Always read `references/both.md` last. Read `references/both.md` again only when asked.

Runs only on approval. Load `references/led.md` and follow it.

- `references/listed.md` — the label table. Read only to look up a label.

Never close a PR except per `references/except.md`.

If a person asks, read `references/early.md`.

Finish with `references/zlate.md`.
EOF
    # early.md is placed at tier 3 first; zlate.md, read every run, cites it
    # again, so early.md and what it cites must end at tier 2.
    echo 'Then read `references/early-deep.md`.' > "$p/skills/main/references/early.md"
    echo 'Then read `references/early.md`.' > "$p/skills/main/references/zlate.md"
    echo 'Early deep.' > "$p/skills/main/references/early-deep.md"
    echo 'Led.' > "$p/skills/main/references/led.md"
    echo 'Listed.' > "$p/skills/main/references/listed.md"
    echo 'Except.' > "$p/skills/main/references/except.md"
    echo 'Then read `references/deep.md`.' > "$p/skills/main/references/always.md"
    echo 'Then read `references/rare-deep.md`.' > "$p/skills/main/references/rare.md"
    echo 'Unconditional.' > "$p/skills/main/references/deep.md"
    echo 'Unconditional.' > "$p/skills/main/references/rare-deep.md"
    echo 'Both.' > "$p/skills/main/references/both.md"
    echo 'Step.' > "$p/templates/step.md"
    printf -- "---\nname: hidden\ndescription: 'Should not count'\ndisable-model-invocation: True\n---\nBody.\n" > "$p/skills/hidden/SKILL.md"
    printf -- "---\ndescription: 'Ten chars!'\n---\nBody.\n" > "$p/commands/cmd.md"
    cat > "$p/hooks/hooks.json" <<'EOF'
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo 'five!'"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo 'not counted, not at session start'"
          }
        ]
      }
    ]
  }
}
EOF

    REPO_ROOT="$tmp"
    PLUGIN_DIR="plug"

    classify "$p/skills/main/SKILL.md"
    expect_tier() {
        local got="${tier[$p/$1]:-unset}"
        [ "$got" = "$2" ] || { echo "self-test FAIL: $1 is tier $got, expected $2"; fail=1; }
    }
    expect_tier skills/main/SKILL.md 2
    expect_tier skills/main/references/always.md 2
    expect_tier skills/main/references/deep.md 2
    expect_tier skills/main/references/rare.md 3
    expect_tier skills/main/references/rare-deep.md 3
    expect_tier templates/step.md 2
    expect_tier skills/main/references/both.md 2
    expect_tier skills/main/references/led.md 3
    expect_tier skills/main/references/listed.md 3
    expect_tier skills/main/references/except.md 3
    expect_tier skills/main/references/early.md 2
    expect_tier skills/main/references/early-deep.md 2

    local saved_budget="$budget"
    budget=1
    if gate "self-test load" 2 >/dev/null; then echo "self-test FAIL: gate passed a load over its budget"; fail=1; fi
    if ! gate "self-test load" 1 >/dev/null; then echo "self-test FAIL: gate failed a load within its budget"; fail=1; fi
    budget="$saved_budget"

    # main: "plug:main" (9) + quoted description (22); cmd: "plug:cmd" (8) +
    # quoted description (12); SessionStart: "five!" (5). hidden is left out.
    measure_every_chat
    local expected=$(( 9 + 22 + 8 + 12 + 5 ))
    [ "$every_chat_total" -eq "$expected" ] || { echo "self-test FAIL: every-chat total $every_chat_total chars, expected $expected"; fail=1; }

    if [ "$fail" -eq 0 ]; then
        echo "self-test OK: tiers follow stated conditions, hidden skills and other hooks stay out of the every-chat total"
        return 0
    fi
    return 1
}

# --- Main -------------------------------------------------------------------

if $self_test_mode; then
    self_test
    exit $?
fi

measure_every_chat
every_chat_tokens=$(tokens "$every_chat_total")

if $every_chat; then
    echo "=== Every chat (tier 1): ${PLUGIN_DIR} ==="
    for line in "${every_chat_lines[@]}"; do
        echo "$line"
    done
    echo ""
    printf "  Total: %7d chars  ~%6d tokens\n" "$every_chat_total" "$every_chat_tokens"
    gate "every-chat load" "$every_chat_tokens"
    exit $?
fi

if [ -z "$input_file" ]; then
    echo "Usage: $0 <skill-or-command-file> [--budget N] [--exclude PATH] [--include-rationale]" >&2
    echo "       $0 --every-chat [--budget N]" >&2
    echo "       $0 --self-test" >&2
    exit 1
fi

# Resolve to absolute path, accepting both relative-to-repo and absolute forms.
if [ -f "$REPO_ROOT/$input_file" ]; then
    input_abs="$REPO_ROOT/$input_file"
elif [ -f "$input_file" ]; then
    input_abs="$(cd "$(dirname "$input_file")" && pwd)/$(basename "$input_file")"
else
    echo "Error: file not found: $input_file" >&2
    exit 1
fi

classify "$input_abs"
measure_file

tier2_tokens=$(tokens "$tier2_chars")
tier3_tokens=$(tokens "$tier3_chars")

echo "=== Load: ${input_file} ==="
echo "Every run (tier 2):"
for line in ${tier2_lines[@]+"${tier2_lines[@]}"}; do echo "$line"; done
echo "On a trigger (tier 3):"
for line in ${tier3_lines[@]+"${tier3_lines[@]}"}; do echo "$line"; done
for line in ${skipped_lines[@]+"${skipped_lines[@]}"}; do echo "$line"; done
echo ""
printf "  Every chat   (tier 1): ~%6d tokens  (plugin-wide; --every-chat for the breakdown)\n" "$every_chat_tokens"
printf "  Every run    (tier 2): ~%6d tokens\n" "$tier2_tokens"
printf "  On a trigger (tier 3): ~%6d tokens  (reported, not gated)\n" "$tier3_tokens"
gate "every-run load" "$tier2_tokens"
