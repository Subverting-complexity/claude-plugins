# Claude Plugins Monorepo

This repo contains multiple Claude Code plugins that share skills.

> **Dogfooding note:** This repo is itself configured as a
> `github-workflow` target. Project settings (org/repo, labels, quality
> gate, board) live in [`ClaudeProject.md`](ClaudeProject.md); workflow
> commands (`/github-workflow:pick-story`, `:execute`, `:code-review`,
> etc.) read it. The open backlog of plugin-hardening work is tracked on
> the [claude-plugins board](https://github.com/orgs/Subverting-complexity/projects/8).

## CRITICAL RULES

1. **NEVER edit a synced skill copy directly.** If the file starts
   with `<!-- SYNCED from _shared-skills/ -->`, it is generated.
   Edit the canonical source in `_shared-skills/` instead. See the
   shared skills list in `_shared-skills/MANIFEST.md`. Before editing
   ANY skill file, check whether it exists in `_shared-skills/` — if
   it does, that is the only file you may edit.

2. **Always run `./sync-skills.ps1` (or `./sync-skills.sh`) after
   editing a shared skill.** This deploys the change to all plugins.
   Commit the canonical file AND the synced copies together in the
   same commit.

3. **Always bump plugin versions before merging.** If you changed any
   file in a plugin (directly or via sync), bump that plugin's version
   in `{plugin}/.claude-plugin/plugin.json`:
   - **Patch** (x.y.Z): bug fixes, typo corrections, minor wording
   - **Minor** (x.Y.0): new skills, commands, behavioral changes
   - **Major** (X.0.0): breaking changes, removed skills

4. **Always commit and open a PR when work is complete.** This is the
   default and it **overrides** the generic "only commit/push when asked"
   caution — finishing a unit of work here *means* committing it on a
   feature branch and opening a pull request against `main`, without
   waiting to be told. Only skip this if the user explicitly says not to
   (e.g. "don't commit", "just show me the diff"). Never leave completed
   changes uncommitted in the working tree. Before committing: branch off
   `main` if on it, run the quality gate, sync shared skills (rule 2), and
   bump versions (rule 3). End commit messages and PR bodies with the
   standard co-author / generation trailers.

## Shared Skills

These skills exist in `_shared-skills/` and are deployed to multiple
plugins. The full list is in `_shared-skills/MANIFEST.md`:

- `code-architect`
- `feature-discovery`
- `grill-me`
- `repo-scaffolding`
- `structured-coding`
- `_shared/` (banned-patterns)
- `references/` (story-template)

### How to edit

1. Edit the file in `_shared-skills/{skill}/SKILL.md`
2. Use `{{PLUGIN_NAME}}` for plugin-specific references
   (e.g., `/{{PLUGIN_NAME}}:execute`) and `{{PLUGIN_VERSION}}`
   for version references
3. Run `./sync-skills.ps1` (or `./sync-skills.sh`) to deploy
4. Run `./sync-skills.ps1 -Verify` to confirm zero drift
5. Commit canonical + synced copies together
6. Bump affected plugin versions

### Checking for drift

```powershell
./sync-skills.ps1 -Verify    # PowerShell
./sync-skills.sh --verify     # Bash (macOS/Linux)
```

Returns exit code 1 if any plugin copy has drifted from the canonical
source.

## Plugins

| Plugin | Description |
|--------|-------------|
| `github-workflow` | GitHub-based development workflows (stories, PRs, reviews) |
| `local-workflow` | Project-agnostic local development (coding, architecture, discovery) |

## Running parallel agents

These workflows spawn parallel/background agents, each of which the harness
places in its own git worktree. When running agents in parallel — especially
on Windows, where per-worktree `node_modules` duplication causes file-lock
cleanup failures — follow the recommended harness configuration and manual
reap routine in [`docs/worktree-config.md`](docs/worktree-config.md).

## Tooling

| Tool | What it does |
|------|-------------|
| `sync-skills.ps1` / `sync-skills.sh` | Sync shared skills to plugins, clean up orphans |
| `lint-skills.sh` | Validate skill frontmatter and detect unreplaced placeholders |
| `hooks/pre-commit` | Git hook that blocks commits editing synced copies directly |
| `.github/workflows/ci.yml` | CI: drift check, skill lint, plugin.json validation |

### Installing the pre-commit hook

```bash
cp hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

## Updating installed plugins

After merging changes to main, the local Claude Code marketplace cache
is stale. You must refresh it before updating:

```powershell
claude plugins marketplace update subverting-complexity
claude plugins update github-workflow@subverting-complexity
claude plugins update local-workflow@subverting-complexity
```

Without the marketplace refresh, `plugins update` reports "already at
latest" against the cached version — not the actual latest on main.
