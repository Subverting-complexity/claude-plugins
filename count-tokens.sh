#!/usr/bin/env bash
# Estimates the instruction-token footprint of a skill or command's hot path.
#
# Includes the given file plus any templates/ and references/ files it cites,
# and those files' own citations (two levels deep). Skips *-rationale.md files
# by default — they are marked "not read at runtime" throughout the codebase.
#
# A citation naming another skill's references directory
# (skills/<skill>/references/<file>.md) resolves against that skill. A citation
# of a canonical _shared-skills/ source is skipped: those files carry
# {{PLUGIN_NAME}} placeholders and are never loaded at runtime.
#
# Usage:
#   bash count-tokens.sh github-workflow/skills/execute/SKILL.md
#   bash count-tokens.sh github-workflow/commands/block-story.md --budget 15000
#   bash count-tokens.sh github-workflow/skills/execute/SKILL.md --include-rationale
#   bash count-tokens.sh <file> --exclude <path> --budget 33000
#
# --exclude drops one cited file from the total (repeatable). Use it to measure
# a subset of the hot path — e.g. the pick/plan/build window of a workflow whose
# later phases pull in a large reference they only load once the earlier work is
# done. Excluding a file does not exclude what that file cites.
#
# Exit codes:
#   0  success (and under budget when --budget given)
#   1  over budget

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
# 3.5 chars/token is conservative for markdown instruction prose.
# Integer arithmetic: multiply chars by 10, divide by 35.
CHARS_PER_TOKEN_X10=35

budget=0
include_rationale=false
input_file=""
declare -a excludes=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --budget)        budget="$2"; shift 2 ;;
        --budget=*)      budget="${1#*=}"; shift ;;
        --exclude)       excludes+=("$2"); shift 2 ;;
        --exclude=*)     excludes+=("${1#*=}"); shift ;;
        --include-rationale) include_rationale=true; shift ;;
        *)               input_file="$1"; shift ;;
    esac
done

if [ -z "$input_file" ]; then
    echo "Usage: $0 <skill-or-command-file> [--budget N] [--exclude PATH] [--include-rationale]" >&2
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

declare -A seen=()
total_chars=0
declare -a report_lines=()

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

add_file() {
    local f="$1"
    local is_transitive="${2:-false}"
    [ "${seen[$f]+x}" ] && return
    seen[$f]=1

    if is_excluded "$f"; then
        report_lines+=("  (excluded) ${f#"$REPO_ROOT"/}")
        return
    fi

    if ! $include_rationale && is_rationale "$f"; then
        report_lines+=("  (skipped, rationale) ${f#"$REPO_ROOT"/}")
        return
    fi

    if [ ! -f "$f" ]; then
        report_lines+=("  (missing) ${f#"$REPO_ROOT"/}")
        return
    fi

    local chars
    chars=$(wc -c < "$f")
    local tokens=$(( chars * 10 / CHARS_PER_TOKEN_X10 ))
    local label="${is_transitive:+  (via dep)}"
    report_lines+=("  $(printf "%6d" "$chars") chars  ~$(printf "%5d" "$tokens") tokens  ${f#"$REPO_ROOT"/}")
    total_chars=$(( total_chars + chars ))
}

# Scan a file for templates/ and references/ citations.
# Outputs one resolved absolute path per line.
#
# A citation that names another skill's references directory
# (skills/<skill>/references/<file>.md — how a shared reference such as
# code-review's auto-merge.md is cited from outside its own skill) is resolved
# against that skill, not the citing one. Without this the path would fall
# through to the plugin-level references/ directory and report "(missing)",
# hiding a real dependency from the budget.
#
# The optional `_shared-` prefix in the pattern is what keeps a
# _shared-skills/<skill>/references/<file>.md citation from being mistaken for a
# deployed skills/ path: grep matches from the earlier position, and the loop
# then skips it as a canonical source that is never loaded at runtime.
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
    grep -oE '((_shared-)?skills/[a-zA-Z0-9_-]+/)?(templates|references)/[a-zA-Z0-9_-]+\.md' "$f" 2>/dev/null \
        | sort -u \
        | while IFS= read -r ref; do
            local name="${ref##*/}"
            local skill
            case "$ref" in
                _shared-skills/*)
                    continue ;;
                skills/*/references/*)
                    skill="${ref#skills/}"
                    skill="${skill%%/*}"
                    echo "$REPO_ROOT/$plugin_dir/skills/$skill/references/$name"
                    continue ;;
                skills/*/templates/*)
                    # Templates live at the plugin root, never under a skill.
                    echo "$template_base/$name"
                    continue ;;
            esac
            local dir="${ref%%/*}"
            if [ "$dir" = "templates" ]; then
                echo "$template_base/$name"
            else
                # Use the input file's own references/ if it has one; fall back
                # to the plugin-level references/ for templates that cross-cite.
                if [ -f "$citer_ref_base/$name" ]; then
                    echo "$citer_ref_base/$name"
                elif [ -f "$ref_base/$name" ]; then
                    echo "$ref_base/$name"
                else
                    echo "$REPO_ROOT/$plugin_dir/references/$name"
                fi
            fi
        done
}

# Level 0: the main file itself.
add_file "$input_abs"

# Level 1: direct citations.
mapfile -t level1 < <(scan_deps "$input_abs" | sort -u)
for dep in "${level1[@]:-}"; do
    [ -z "$dep" ] && continue
    add_file "$dep"
done

# Level 2: citations from level-1 files (deduplication via seen[]).
for dep in "${level1[@]:-}"; do
    [ -z "$dep" ] && continue
    [ -f "$dep" ] || continue
    mapfile -t level2 < <(scan_deps "$dep" | sort -u)
    for nested in "${level2[@]:-}"; do
        [ -z "$nested" ] && continue
        add_file "$nested"
    done
done

total_tokens=$(( total_chars * 10 / CHARS_PER_TOKEN_X10 ))

echo "=== Token footprint: ${input_file} ==="
for line in "${report_lines[@]}"; do
    echo "$line"
done
echo ""
printf "  Total: %7d chars  ~%6d tokens\n" "$total_chars" "$total_tokens"

if [ "$budget" -gt 0 ] 2>/dev/null; then
    if [ "$total_tokens" -gt "$budget" ]; then
        echo ""
        echo "FAIL: footprint ~${total_tokens} tokens exceeds budget ${budget} tokens"
        exit 1
    else
        echo "OK: footprint ~${total_tokens} tokens is within budget ${budget} tokens"
    fi
fi
