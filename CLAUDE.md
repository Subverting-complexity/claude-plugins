# Claude Plugins Monorepo

This repo contains multiple Claude Code plugins that share skills.

## Shared Skills

Skills in `_shared-skills/` are the canonical source. Plugin copies
are generated — **never edit a plugin's copy of a shared skill
directly**. If a file starts with
`<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->`
it is a synced copy.

### Editing shared skills

1. Edit the file in `_shared-skills/{skill}/SKILL.md`
2. Use `{{PLUGIN_NAME}}` for any plugin-specific references
   (e.g., `/{{PLUGIN_NAME}}:execute`)
3. Run `./sync-skills.ps1` to deploy to all plugins
4. Commit the canonical file AND the synced copies together

### Checking for drift

```powershell
./sync-skills.ps1 -Verify
```

Returns exit code 1 if any plugin copy has drifted from the canonical
source. Use in CI to catch accidental direct edits.

See `_shared-skills/MANIFEST.md` for the full list of shared skills
and template variables.

## Version Bumps

When making changes to a plugin, bump its version in
`{plugin}/.claude-plugin/plugin.json` before merging:

- **Patch** (1.5.1): bug fixes, typo corrections, minor wording changes
- **Minor** (1.6.0): new skills, new commands, behavioral changes,
  new features
- **Major** (2.0.0): breaking changes to skill interfaces, removed
  skills, restructured commands

The sync script checks for version bumps: if any synced file changed,
it warns you to bump the affected plugin versions.

## Plugins

| Plugin | Description |
|--------|-------------|
| `github-workflow` | GitHub-based development workflows (stories, PRs, reviews) |
| `local-workflow` | Project-agnostic local development (coding, architecture, discovery) |
