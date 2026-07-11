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

echo ""
if [ $status -eq 0 ]; then
    echo "All checks passed."
else
    echo "Linting failed — see FAIL lines above."
fi
exit $status
