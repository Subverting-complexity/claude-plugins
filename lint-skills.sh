#!/usr/bin/env bash
# Skill frontmatter linter
# Validates: required fields, unreplaced placeholders, trigger phrase
# collisions, template coverage of canonical shared skills

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_ROOT"
status=0

# Collect all SKILL.md files
# Use relative paths so the exclusion pattern isn't defeated when REPO_ROOT itself
# is inside a git worktree (e.g. .claude/worktrees/<name>/).
mapfile -t skill_files < <(find . -name 'SKILL.md' -not -path './.claude/worktrees/*')

echo "=== Skill Frontmatter Linter ==="
echo "Found ${#skill_files[@]} skill files"
echo ""

# Track trigger phrases for collision detection
declare -A trigger_map

for file in "${skill_files[@]}"; do
    rel="${file#./}"
    has_frontmatter=false
    has_name=false
    has_description=false
    name_value=""

    # Check for YAML frontmatter
    if head -n5 "$file" | grep -q '^---$'; then
        has_frontmatter=true

        # Extract frontmatter block (avoid sed|head pipe to prevent SIGPIPE with pipefail)
        frontmatter=$(awk '/^---$/{n++; next} n==1{print} n>=2{exit}' "$file")

        # Check required fields
        if echo "$frontmatter" | grep -qE '^name:'; then
            has_name=true
            name_value=$(echo "$frontmatter" | grep -E '^name:' | sed 's/^name:[[:space:]]*//' | tr -d '"' | xargs)
        fi
        if echo "$frontmatter" | grep -qE '^description:'; then
            has_description=true
        fi
    fi

    # Skip _shared-skills canonical copies — they use {{PLUGIN_NAME}} intentionally
    if [[ "$rel" == _shared-skills/* ]]; then
        # Only check frontmatter presence for canonical files
        if [ "$has_frontmatter" = false ]; then
            echo "WARN: $rel — no YAML frontmatter"
        fi
        continue
    fi

    # Check for unreplaced template variables in plugin copies
    if grep -qF '{{PLUGIN_NAME}}' "$file"; then
        echo "FAIL: $rel — contains unreplaced {{PLUGIN_NAME}} placeholder"
        status=1
    fi
    if grep -qF '{{PLUGIN_VERSION}}' "$file"; then
        echo "FAIL: $rel — contains unreplaced {{PLUGIN_VERSION}} placeholder"
        status=1
    fi
    if grep -qF '{{EXECUTE_SKILL}}' "$file"; then
        echo "FAIL: $rel — contains unreplaced {{EXECUTE_SKILL}} placeholder"
        status=1
    fi

    # Report missing frontmatter fields
    if [ "$has_frontmatter" = false ]; then
        echo "WARN: $rel — no YAML frontmatter"
        continue
    fi
    if [ "$has_name" = false ]; then
        echo "WARN: $rel — missing 'name' in frontmatter"
    fi
    if [ "$has_description" = false ]; then
        echo "WARN: $rel — missing 'description' in frontmatter"
    fi

    # Validate depends-on references exist as skill directories in the same plugin
    if [ "$has_frontmatter" = true ]; then
        depends_on=$(echo "$frontmatter" | awk '/^depends-on:/{found=1; next} found && /^  - /{gsub(/^  - /,""); print} found && !/^  - /&&!/^$/{found=0}')
        if [ -n "$depends_on" ]; then
            plugin_dir=$(echo "$rel" | cut -d'/' -f1)
            while IFS= read -r dep; do
                dep=$(echo "$dep" | xargs)
                [ -z "$dep" ] && continue
                skill_path="$REPO_ROOT/$plugin_dir/skills/$dep/SKILL.md"
                command_path="$REPO_ROOT/$plugin_dir/commands/$dep.md"
                if [ ! -f "$skill_path" ] && [ ! -f "$command_path" ]; then
                    echo "FAIL: $rel — depends-on '$dep' not found in $plugin_dir/skills/ or $plugin_dir/commands/"
                    status=1
                fi
            done <<< "$depends_on"
        fi
    fi

    # Track trigger phrases for collision detection (from description field)
    if [ -n "$name_value" ]; then
        if [ -n "${trigger_map[$name_value]+x}" ]; then
            existing="${trigger_map[$name_value]}"
            # Same skill in different plugins is fine — only flag if paths diverge
            existing_skill=$(echo "$existing" | sed 's|.*/skills/||' | sed 's|/SKILL.md||')
            current_skill=$(echo "$rel" | sed 's|.*/skills/||' | sed 's|/SKILL.md||')
            if [ "$existing_skill" != "$current_skill" ]; then
                echo "WARN: Skill name '$name_value' used by both $existing and $rel"
            fi
        fi
        trigger_map[$name_value]="$rel"
    fi
done

# Template coverage: canonical files under _shared-skills/ are deployed to
# every plugin, so a hardcoded /github-workflow: or /local-workflow: slash
# command leaks the wrong plugin's command into the other plugin's copy.
# Only MANIFEST.md is exempt — it documents the plugins and is never synced.
mapfile -t shared_md < <(find ./_shared-skills -type f -name '*.md' ! -name 'MANIFEST.md' 2>/dev/null)
for file in "${shared_md[@]}"; do
    rel="${file#./}"
    if grep -qE '/(github|local)-workflow:' "$file"; then
        echo "FAIL: $rel — hardcoded plugin slash-command reference; use /{{PLUGIN_NAME}}: instead"
        grep -nE '/(github|local)-workflow:' "$file" | head -5 | sed 's/^/      /'
        status=1
    fi
done

# Issue-writing wiring: github-workflow's writing-github-issues skill is the
# standard for every GitHub issue title and body the plugin produces. That only
# holds if the paths that author or edit an issue body actually point at it, so
# each one is asserted here. Add a file to this list whenever a new path starts
# writing issue bodies; do not delete an entry to make the gate pass.
ISSUE_STANDARD="github-workflow/skills/writing-github-issues/SKILL.md"
declare -a issue_authoring_files=(
    "github-workflow/commands/report-issue.md"        # every autonomous filing funnels here
    "github-workflow/commands/block-story.md"         # edits the body to add the Dependencies marker
    "github-workflow/skills/feature-discovery/SKILL.md"
    "github-workflow/skills/repo-scaffolding/SKILL.md"
    "github-workflow/skills/user-story/SKILL.md"
    "github-workflow/references/story-template.md"
    "github-workflow/templates/CLAUDE.md"             # the rules written into a target project
    "github-workflow/skills/_shared/wording-standard.md"  # states the precedence
)

if [ ! -f "$ISSUE_STANDARD" ]; then
    echo "FAIL: $ISSUE_STANDARD is missing — the issue-writing standard every issue path cites"
    status=1
else
    for f in "${issue_authoring_files[@]}"; do
        if [ ! -f "$f" ]; then
            echo "FAIL: $f is listed as an issue-authoring path but does not exist"
            status=1
        elif ! grep -qF 'writing-github-issues' "$f"; then
            echo "FAIL: $f writes or edits GitHub issue bodies but does not cite writing-github-issues"
            status=1
        fi
    done
fi

# Body-writing wiring: _shared/body-standard.md is the single standard behind
# every body written into a tracker or forge — an issue, a pull request
# description, a comment. Entry points sit on it and hold only what differs:
# pr-body in github-workflow and pr-description in local-workflow for pull
# requests, writing-github-issues for issues. That split only holds if every
# entry point, the wording standard that defers to it, and the write-mechanics
# template all point at it. Add a file whenever a new path starts composing a
# body; do not delete an entry to make the gate pass.
declare -a body_standard_copies=(
    "github-workflow/skills/_shared/body-standard.md"
    "local-workflow/skills/_shared/body-standard.md"
)
declare -a body_authoring_files=(
    "github-workflow/skills/pr-body/SKILL.md"
    "local-workflow/skills/pr-description/SKILL.md"
    "github-workflow/skills/writing-github-issues/SKILL.md"
    "github-workflow/templates/body-file-write.md"     # the write mechanics
    "github-workflow/skills/_shared/wording-standard.md"  # states the precedence
    "local-workflow/skills/_shared/wording-standard.md"
)

for f in "${body_standard_copies[@]}"; do
    if [ ! -f "$f" ]; then
        echo "FAIL: $f is missing — the body standard every issue and PR body follows"
        status=1
    fi
done
for f in "${body_authoring_files[@]}"; do
    if [ ! -f "$f" ]; then
        echo "FAIL: $f is listed as a body-authoring path but does not exist"
        status=1
    elif ! grep -qF 'body-standard.md' "$f"; then
        echo "FAIL: $f composes issue or PR bodies but does not cite body-standard.md"
        status=1
    fi
done

# A repository can publish an issue template that GitHub pre-fills in the web
# UI but that --body-file silently bypasses. The paths that CREATE an issue
# have to resolve it, or every issue the plugin files ignores the project's own
# template. The standard and the creating commands must all cite the procedure.
TEMPLATE_PROC="github-workflow/templates/issue-template-resolution.md"
declare -a issue_creating_files=(
    "$ISSUE_STANDARD"
    "github-workflow/commands/report-issue.md"
    "github-workflow/skills/feature-discovery/SKILL.md"
)

if [ ! -f "$TEMPLATE_PROC" ]; then
    echo "FAIL: $TEMPLATE_PROC is missing — the issue-template resolution procedure"
    status=1
else
    for f in "${issue_creating_files[@]}"; do
        if ! grep -qF 'issue-template-resolution.md' "$f"; then
            echo "FAIL: $f creates GitHub issues but does not cite issue-template-resolution.md"
            status=1
        fi
    done
fi

# Reply-writing wiring: user-facing-communication is the standard for every
# reply either plugin writes to a person. It reaches a session three ways —
# each plugin's SessionStart hook, the shared wording standard every skill
# cites, and a direct citation in each file that writes to the user. Only the
# third can rot silently, so each of those files is asserted here. Add a file
# whenever a new path starts writing to the user; do not delete an entry to
# make the gate pass.
declare -a reply_writing_files=(
    # Both plugins carry the deployed copy of the standard itself.
    "github-workflow/skills/user-facing-communication/SKILL.md"
    "local-workflow/skills/user-facing-communication/SKILL.md"
    # The shared standard that every other skill inherits it through.
    "github-workflow/skills/_shared/wording-standard.md"
    "local-workflow/skills/_shared/wording-standard.md"
    # github-workflow: orchestrators, commands, and the agents that report back.
    "github-workflow/skills/execute/SKILL.md"
    "github-workflow/skills/execute/references/finish.md"
    "github-workflow/skills/bulk-execute/SKILL.md"
    "github-workflow/skills/bulk-execute/references/bulk-finish.md"
    "github-workflow/skills/code-review/SKILL.md"
    "github-workflow/skills/preflight/SKILL.md"
    "github-workflow/skills/writing-github-issues/SKILL.md"  # states the precedence
    "github-workflow/commands/block-story.md"
    "github-workflow/commands/guide.md"
    "github-workflow/commands/report-issue.md"
    "github-workflow/commands/setup.md"
    "github-workflow/agents/builder.md"
    "github-workflow/agents/reviewer.md"
    "github-workflow/agents/doc-writer.md"
    "github-workflow/templates/CLAUDE.md"                    # the rules written into a target project
    # local-workflow: the same surfaces, minus the GitHub-specific ones.
    "local-workflow/skills/build/SKILL.md"
    "local-workflow/skills/code-review/SKILL.md"
    "local-workflow/skills/mobile-audit/SKILL.md"
    "local-workflow/skills/preflight/SKILL.md"
)

for f in "${reply_writing_files[@]}"; do
    if [ ! -f "$f" ]; then
        echo "FAIL: $f is listed as a reply-writing path but does not exist"
        status=1
    elif ! grep -qF 'user-facing-communication' "$f"; then
        echo "FAIL: $f writes replies the user reads but does not cite user-facing-communication"
        status=1
    fi
done

# Every shared skill writes something a person reads, so each canonical source
# cites the standard. Checking the canonical files (rather than the deployed
# copies) means a new shared skill is caught the moment it is added, before it
# is ever synced.
for f in _shared-skills/*/SKILL.md; do
    [ -f "$f" ] || continue
    if ! grep -qF 'user-facing-communication' "$f"; then
        echo "FAIL: $f is a shared skill but does not cite user-facing-communication"
        status=1
    fi
done

# The SessionStart hook is what makes the standard apply outside a workflow
# command. Without it, a plain question in a fresh session gets none of this.
for plugin in github-workflow local-workflow; do
    hooks_file="$plugin/hooks/hooks.json"
    if [ ! -f "$hooks_file" ]; then
        echo "FAIL: $hooks_file is missing — it carries the SessionStart response standard"
        status=1
    elif ! grep -q 'SessionStart' "$hooks_file"; then
        echo "FAIL: $hooks_file has no SessionStart hook — the response standard would only apply inside a command"
        status=1
    elif ! grep -q 'user-facing-communication' "$hooks_file"; then
        echo "FAIL: $hooks_file has a SessionStart hook that does not carry the response standard"
        status=1
    fi
done

echo ""
if [ $status -eq 0 ]; then
    echo "All checks passed."
else
    echo "Linting failed — see FAIL lines above."
fi
exit $status
