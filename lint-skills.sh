#!/usr/bin/env bash
# Skill frontmatter linter
# Validates: required fields, unreplaced placeholders, trigger phrase collisions

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
status=0

# Collect all SKILL.md files
mapfile -t skill_files < <(find "$REPO_ROOT" -name 'SKILL.md' -not -path '*/.claude/worktrees/*')

echo "=== Skill Frontmatter Linter ==="
echo "Found ${#skill_files[@]} skill files"
echo ""

# Track trigger phrases for collision detection
declare -A trigger_map

for file in "${skill_files[@]}"; do
    rel="${file#"$REPO_ROOT"/}"
    has_frontmatter=false
    has_name=false
    has_description=false
    name_value=""

    # Check for YAML frontmatter
    if head -n5 "$file" | grep -q '^---$'; then
        has_frontmatter=true

        # Extract frontmatter block
        frontmatter=$(sed -n '/^---$/,/^---$/p' "$file" | head -50)

        # Check required fields
        if echo "$frontmatter" | grep -qE '^name:'; then
            has_name=true
            name_value=$(echo "$frontmatter" | grep -oP '^name:\s*\K.*' | tr -d '"' | xargs)
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

echo ""
if [ $status -eq 0 ]; then
    echo "All checks passed."
else
    echo "Linting failed — see FAIL lines above."
fi
exit $status
