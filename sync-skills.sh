#!/usr/bin/env bash
# Cross-platform (bash) equivalent of sync-skills.ps1
# Usage:
#   ./sync-skills.sh              Sync all shared skills to all plugins
#   ./sync-skills.sh --verify     Check for drift without writing (CI use)
#   ./sync-skills.sh --plugin X   Sync only plugin X

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SHARED_DIR="$REPO_ROOT/_shared-skills"
SYNC_COMMENT='<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->'
ALL_PLUGINS=("github-workflow" "local-workflow")

VERIFY=false
PLUGIN_FILTER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --verify) VERIFY=true; shift ;;
        --plugin) PLUGIN_FILTER="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ -n "$PLUGIN_FILTER" ]; then
    found=false
    for p in "${ALL_PLUGINS[@]}"; do
        if [ "$p" = "$PLUGIN_FILTER" ]; then found=true; break; fi
    done
    if [ "$found" = false ]; then
        echo "Unknown plugin: $PLUGIN_FILTER. Known: ${ALL_PLUGINS[*]}"
        exit 1
    fi
    PLUGINS=("$PLUGIN_FILTER")
else
    PLUGINS=("${ALL_PLUGINS[@]}")
fi

drift_found=false
sync_count=0
delete_count=0

# Resolve Python once: try python3, then Windows Launcher (py -3), then python.
# Uses the version-check guard so Windows' non-functional python3 Store shim is skipped.
PYTHON=()
if command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
    PYTHON=(python3)
elif command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then
    PYTHON=(py -3)
elif command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
    PYTHON=(python)
fi

get_plugin_version() {
    local plugin_name="$1"
    local pj="$REPO_ROOT/$plugin_name/.claude-plugin/plugin.json"
    if [ -f "$pj" ] && [ ${#PYTHON[@]} -gt 0 ]; then
        "${PYTHON[@]}" -c "import json,sys; print(json.load(sys.stdin).get('version','0.0.0'))" < "$pj"
    else
        echo "0.0.0"
    fi
}

# Each plugin's end-to-end orchestrator is named differently, because the two
# do different jobs and a shared name made them indistinguishable when both
# plugins were installed. A shared skill that wants to cite "this plugin's
# orchestrator" writes /{{PLUGIN_NAME}}:{{EXECUTE_SKILL}} and gets the right
# one. Add a case here when a new plugin joins; the fallback is the github
# name, which is what a new GitHub-shaped plugin would want.
get_execute_skill() {
    case "$1" in
        local-workflow) echo "build" ;;
        *)              echo "execute" ;;
    esac
}

process_md_content() {
    local content="$1"
    local plugin_name="$2"
    local version execute_skill
    version=$(get_plugin_version "$plugin_name")
    execute_skill=$(get_execute_skill "$plugin_name")

    local result
    result=$(echo "$content" \
        | sed "s/{{PLUGIN_NAME}}/$plugin_name/g" \
        | sed "s/{{PLUGIN_VERSION}}/$version/g" \
        | sed "s/{{EXECUTE_SKILL}}/$execute_skill/g")

    # Already carries the banner -- leave it untouched (idempotent re-sync).
    if echo "$result" | grep -qF "$SYNC_COMMENT"; then
        echo "$result"
        return
    fi

    # The banner is an HTML comment, but a SKILL.md must keep its YAML
    # frontmatter ('---') on line 1 or the skill loader cannot parse it and
    # the skill silently fails to register. So when the file opens with
    # frontmatter, insert the banner on its own line immediately AFTER the
    # closing '---'. Files without frontmatter get the banner prepended.
    if [ "$(echo "$result" | head -n1)" = "---" ]; then
        result=$(echo "$result" | awk -v banner="$SYNC_COMMENT" '
            { print }
            /^---$/ { n++; if (n == 2 && !done) { print banner; done = 1 } }
        ')
    else
        result="$SYNC_COMMENT
$result"
    fi
    echo "$result"
}

# Track expected files per plugin for orphan detection
declare -A expected_files

sync_directory() {
    local source_dir="$1"
    local dest_dir="$2"
    local plugin_name="$3"

    if [ ! -d "$source_dir" ]; then return; fi

    while IFS= read -r -d '' file; do
        local rel="${file#"$source_dir"/}"
        local dest="$dest_dir/$rel"
        local dest_parent
        dest_parent=$(dirname "$dest")

        expected_files["$dest"]=1

        if [[ "$file" == *.md ]]; then
            local source_content
            source_content=$(cat "$file")
            local processed
            processed=$(process_md_content "$source_content" "$plugin_name")

            if [ "$VERIFY" = true ]; then
                if [ -f "$dest" ]; then
                    local existing
                    existing=$(cat "$dest")
                    # Trim trailing whitespace for comparison
                    local p_trimmed e_trimmed
                    p_trimmed=$(echo "$processed" | sed 's/[[:space:]]*$//')
                    e_trimmed=$(echo "$existing" | sed 's/[[:space:]]*$//')
                    if [ "$p_trimmed" != "$e_trimmed" ]; then
                        echo "  DRIFT: $rel"
                        drift_found=true
                    else
                        echo "  OK: $rel"
                    fi
                else
                    echo "  MISSING: $rel"
                    drift_found=true
                fi
            else
                mkdir -p "$dest_parent"
                echo "$processed" > "$dest"
                sync_count=$((sync_count + 1))
                echo "  Synced: $rel"
            fi
        else
            if [ "$VERIFY" = true ]; then
                if [ -f "$dest" ]; then
                    local src_hash dest_hash
                    src_hash=$(sha256sum "$file" | cut -d' ' -f1)
                    dest_hash=$(sha256sum "$dest" | cut -d' ' -f1)
                    if [ "$src_hash" != "$dest_hash" ]; then
                        echo "  DRIFT: $rel"
                        drift_found=true
                    else
                        echo "  OK: $rel"
                    fi
                else
                    echo "  MISSING: $rel"
                    drift_found=true
                fi
            else
                mkdir -p "$dest_parent"
                cp "$file" "$dest"
                sync_count=$((sync_count + 1))
                echo "  Synced: $rel"
            fi
        fi
    done < <(find "$source_dir" -type f -print0)
}

remove_orphaned_files() {
    local dest_dir="$1"
    if [ ! -d "$dest_dir" ]; then return; fi

    while IFS= read -r -d '' file; do
        if [ -z "${expected_files["$file"]+x}" ]; then
            local rel="${file#"$dest_dir"/}"
            if [ "$VERIFY" = true ]; then
                echo "  ORPHAN: $rel (would be deleted)"
                drift_found=true
            else
                rm -f "$file"
                delete_count=$((delete_count + 1))
                echo "  Deleted orphan: $rel"
            fi
        fi
    done < <(find "$dest_dir" -type f -print0)

    # Clean up empty directories
    if [ "$VERIFY" = false ]; then
        find "$dest_dir" -type d -empty -delete 2>/dev/null || true
    fi
}

# Collect shared skill directories (excluding _shared and references)
mapfile -t skill_dirs < <(find "$SHARED_DIR" -maxdepth 1 -mindepth 1 -type d \
    ! -name '_shared' ! -name 'references' | sort)

has_shared=false
[ -d "$SHARED_DIR/_shared" ] && has_shared=true

has_references=false
[ -d "$SHARED_DIR/references" ] && has_references=true

for plugin_name in "${PLUGINS[@]}"; do
    plugin_skills_dir="$REPO_ROOT/$plugin_name/skills"

    if [ ! -d "$plugin_skills_dir" ]; then
        echo "WARN: Plugin skills dir not found: $plugin_skills_dir -- skipping"
        continue
    fi

    echo ""
    echo "=== $plugin_name ==="

    # Reset expected files for this plugin
    expected_files=()

    for skill_dir in "${skill_dirs[@]}"; do
        skill_name=$(basename "$skill_dir")
        dest_skill_dir="$plugin_skills_dir/$skill_name"
        echo "  [$skill_name]"
        sync_directory "$skill_dir" "$dest_skill_dir" "$plugin_name"
    done

    if [ "$has_shared" = true ]; then
        echo "  [_shared]"
        sync_directory "$SHARED_DIR/_shared" "$plugin_skills_dir/_shared" "$plugin_name"
    fi

    if [ "$has_references" = true ]; then
        echo "  [references]"
        sync_directory "$SHARED_DIR/references" "$REPO_ROOT/$plugin_name/references" "$plugin_name"
    fi

    # Clean up orphaned files
    echo "  [cleanup]"
    for skill_dir in "${skill_dirs[@]}"; do
        skill_name=$(basename "$skill_dir")
        remove_orphaned_files "$plugin_skills_dir/$skill_name"
    done
    if [ "$has_shared" = true ]; then
        remove_orphaned_files "$plugin_skills_dir/_shared"
    fi
    if [ "$has_references" = true ]; then
        remove_orphaned_files "$REPO_ROOT/$plugin_name/references"
    fi
done

echo ""
if [ "$VERIFY" = true ]; then
    if [ "$drift_found" = true ]; then
        echo "DRIFT DETECTED -- run sync-skills.sh (or sync-skills.ps1) to fix"
        exit 1
    else
        echo "All synced files are up to date."
        exit 0
    fi
else
    echo "Synced $sync_count file(s), deleted $delete_count orphan(s) across ${#PLUGINS[@]} plugin(s)."
    if [ $sync_count -gt 0 ] || [ $delete_count -gt 0 ]; then
        echo ""
        echo "REMINDER: Bump plugin version(s) if these changes are user-facing."
        for plugin_name in "${PLUGINS[@]}"; do
            version=$(get_plugin_version "$plugin_name")
            echo "  $plugin_name : current version $version"
        done
    fi
fi
