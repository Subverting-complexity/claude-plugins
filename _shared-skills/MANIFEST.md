# Shared Skills Manifest

Canonical source for skills shared across multiple plugins. **Never
edit plugin copies directly** — edit here, then run `sync-skills.ps1`.

## Shared skills

| Skill | Deployed to | Notes |
|-------|-------------|-------|
| `code-architect` | github-workflow, local-workflow | Includes `references/` subdirectory with architecture book summaries |
| `feature-discovery` | github-workflow, local-workflow | Uses `references/story-template.md` |
| `grill-me` | github-workflow, local-workflow | `disable-model-invocation: true`, no filesystem output |
| `repo-scaffolding` | github-workflow, local-workflow | Uses `references/story-template.md`, no spec docs |
| `structured-coding` | github-workflow, local-workflow | Autonomous workflow escape hatch |

## Shared resources

| Directory | Deployed to | Notes |
|-----------|-------------|-------|
| `_shared/` | `{plugin}/skills/_shared/` | Banned patterns, shared across all skills |
| `references/` | `{plugin}/references/` | Story template, shared across plugins |

## Template variables

The sync script replaces these placeholders with plugin-specific values:

| Variable | Replacement |
|----------|-------------|
| `{{PLUGIN_NAME}}` | Plugin directory name (e.g., `github-workflow`, `local-workflow`) |
| `{{PLUGIN_VERSION}}` | Plugin version from `plugin.json` (e.g., `1.7.0`) |

## Sync commands

```powershell
# Sync all shared skills to all plugins
./sync-skills.ps1

# Sync to a single plugin
./sync-skills.ps1 -Plugin github-workflow

# Check for drift without writing (CI use)
./sync-skills.ps1 -Verify
```

## Workflow

1. Edit the canonical file in `_shared-skills/`
2. Run `./sync-skills.ps1`
3. Review the synced copies (they get a `<!-- SYNCED -->` comment)
4. Commit everything together (canonical + synced copies)
5. Bump plugin versions if the change is user-facing
