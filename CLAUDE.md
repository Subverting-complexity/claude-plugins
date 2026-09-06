# Claude Plugins Monorepo

This repo contains multiple Claude Code plugins that share skills.

> **Dogfooding note:** This repo is itself configured as a `github-workflow` target. Project settings (org/repo, labels, quality gate, board) live in [`ClaudeProject.md`](ClaudeProject.md); workflow commands (`/github-workflow:execute`, `:code-review`, etc.) read it. The open backlog of plugin-hardening work is tracked on the [claude-plugins board](https://github.com/orgs/Subverting-complexity/projects/8).

## CRITICAL RULES

1. **NEVER edit a synced skill copy directly.** If the file contains a line starting with `<!-- SYNCED from _shared-skills/ -->`, it is generated. (In a `SKILL.md` the banner sits just below the YAML frontmatter — which must stay on line 1 — so it is not always the first line.) Edit the canonical source in `_shared-skills/` instead. See the shared skills list in `_shared-skills/MANIFEST.md`. Before editing ANY skill file, check whether it exists in `_shared-skills/` — if it does, that is the only file you may edit.

2. **Always run `./sync-skills.ps1` (or `./sync-skills.sh`) after editing a shared skill.** This deploys the change to all plugins. Commit the canonical file AND the synced copies together in the same commit.

3. **Always bump plugin versions before merging.** If you changed any file in a plugin (directly or via sync), bump that plugin's version in `{plugin}/.claude-plugin/plugin.json`:
   - **Patch** (x.y.Z): bug fixes, typo corrections, minor wording
   - **Minor** (x.Y.0): new skills, commands, behavioral changes
   - **Major** (X.0.0): breaking changes, removed skills

4. **Always commit and open a PR when work is complete.** This is the default and it **overrides** the generic "only commit/push when asked" caution — finishing a unit of work here *means* committing it on a feature branch and opening a pull request against `main`, without waiting to be told. Only skip this if the user explicitly says not to (e.g. "don't commit", "just show me the diff"). Never leave completed changes uncommitted in the working tree. Before committing: branch off `main` if on it, run the quality gate, sync shared skills (rule 2), and bump versions (rule 3). End commit messages and PR bodies with the standard co-author / generation trailers.

## Shared Skills

Fourteen skills live in `_shared-skills/` and are deployed to both plugins, alongside `_shared/` (wording standard, banned patterns and body standard) and `references/` (story template). The list, and what is deliberately *not* shared, are in `_shared-skills/MANIFEST.md`.

`_shared/body-standard.md` is the single standard for every body written into a tracker or forge: an issue, a pull request description, a comment. It holds the wording, the bullet and title rules, the style and the no-hard-wrapping rule. Its entry points carry only the part that differs, which is which sections a body has: `writing-github-issues` for a GitHub issue, `pr-body` in github-workflow and `pr-description` in local-workflow for a pull request.

The two pull request skills are deliberately **not** shared, and they have separate slash commands (`/github-workflow:pr-body`, `/local-workflow:pr-description`) so neither format can be reached by mistake. github-workflow's is fixed (`## Summary` → `## Changes` → `## Test plan`, then `Closes #N`) because `execute`, `bulk-execute` and `code-review` read and extend those bodies. local-workflow's keeps the component-section format. Do not re-merge them into `_shared-skills/`.

`lint-skills.sh` asserts that every entry point, the wording standard and `templates/body-file-write.md` still cite the body standard, so they cannot drift apart again.

`user-facing-communication` is the standard for every reply either plugin writes to a person: what was done and the current state first, then anything outstanding, blocked or assumed. It reaches a session three ways, so it holds whether or not a workflow command is running: each plugin's `SessionStart` hook injects it, `_shared/wording-standard.md` cites it (and every skill cites that), and every skill, command and agent that writes to the user names it directly. `lint-skills.sh` asserts that last part, so the wiring cannot be dropped one file at a time.

### How to edit

1. Edit the file in `_shared-skills/{skill}/SKILL.md`
2. Use `{{PLUGIN_NAME}}` for plugin-specific references (e.g., `/{{PLUGIN_NAME}}:execute`) and `{{PLUGIN_VERSION}}` for version references
3. Run `./sync-skills.ps1` (or `./sync-skills.sh`) to deploy
4. Run `./sync-skills.ps1 -Verify` to confirm zero drift
5. Commit canonical + synced copies together
6. Bump affected plugin versions

### Never hard-wrap an instruction file

Every markdown file in this repo is written one paragraph per line, however long the line runs. Do not reflow prose to 72, 80 or any other column, and do not rewrap a paragraph you edit. The only line breaks a file has are the ones markdown needs: between blocks, between list items, and inside fenced code.

This is not cosmetic. These files are the examples the model learns the house style from, and while they were wrapped it wrapped the issue and pull request bodies it wrote — which trackers then reflowed, putting the breaks where they suited nobody. `_shared/body-standard.md` states the rule for bodies; this section states it for the files that teach it.

### Checking for drift

```powershell
./sync-skills.ps1 -Verify    # PowerShell
./sync-skills.sh --verify     # Bash (macOS/Linux)
```

Returns exit code 1 if any plugin copy has drifted from the canonical source.

## Plugins

| Plugin | Description |
|--------|-------------|
| `github-workflow` | GitHub-based development workflows (stories, PRs, reviews) |
| `local-workflow` | Project-agnostic local development (coding, architecture, discovery) |

## Running parallel agents

These workflows spawn parallel/background agents, each of which the harness places in its own git worktree. When running agents in parallel — especially on Windows, where per-worktree `node_modules` duplication causes file-lock cleanup failures — follow the recommended harness configuration and manual reap routine in [`docs/worktree-config.md`](docs/worktree-config.md).

## Tooling

| Tool | What it does |
|------|-------------|
| `bootstrap.ps1` / `bootstrap.sh` | One-time per-clone setup: pin LF line endings, renormalize, install the pre-commit hook, check Python is available |
| `sync-skills.ps1` / `sync-skills.sh` | Sync shared skills to plugins, clean up orphans |
| `lint-skills.sh` | Validate skill frontmatter and detect unreplaced placeholders |
| `run-tests.sh` | Run the offline decision-logic tests; auto-detects `python3`, `py -3` (Windows Launcher), or `python` |
| `run-tests.ps1` | Windows PowerShell equivalent of `run-tests.sh`; prints a `winget` install hint if no Python is found |
| `count-tokens.sh` | Estimate instruction-token footprint of a skill's hot path (file + cited templates/references, two levels deep); `--exclude PATH` narrows it to a subset, e.g. one workflow's build window |
| `check-budgets.sh` | Enforce per-file description-char and body-line budgets on deployed skills and commands (ratchet gate) |
| `count-roundtrips.sh` | Count `gh`/`git` network calls described in instruction files (informational, no gate) |
| `hooks/pre-commit` | Git hook that blocks commits editing synced copies directly and blocks CRLF line endings |
| `.github/workflows/ci.yml` | CI: drift check, skill lint, decision-logic tests, version-bump check, token-footprint budgets, plugin.json validation |
| `.claude/ecosystem.md` | Cheat-sheet for installed Claude Code companion tools (graphify, RTK, ccusage, ecc-agentshield) and when the workflow uses each. Consult it before searching the codebase blind or running an audit/review. Generated by the shared `ecosystem-setup` skill — regenerate via `/github-workflow:setup ecosystem` or `/local-workflow:ecosystem-setup`. |

### Bootstrapping your clone

Run this once after cloning (idempotent). It pins line endings to LF — matching `.gitattributes`, so files like `CLAUDE.md` don't churn to CRLF on Windows and leave worktrees stuck "dirty" — and installs the pre-commit hook:

```bash
./bootstrap.sh      # macOS / Linux / Git Bash
./bootstrap.ps1     # Windows PowerShell
```

This replaces the manual hook install (`cp hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit`), which still works if you only want the hook.

## Updating installed plugins

After merging changes to main, the local Claude Code marketplace cache is stale. You must refresh it before updating:

```powershell
claude plugin marketplace update subverting-complexity
claude plugin update github-workflow@subverting-complexity
claude plugin update local-workflow@subverting-complexity
```

Without the marketplace refresh, `plugin update` reports "already at latest" against the cached version — not the actual latest on main.

> The command is `claude plugin` (singular). Run it from a normal shell, not inside a Claude Code session — the CLI blocks nested sessions; if needed, prefix with `env -u CLAUDECODE`. Verify a manifest before shipping with `claude plugin validate ./<plugin>` — it catches schema errors (e.g. unrecognized keys) that plain JSON validation misses. `claude plugin validate .` does the same for the marketplace manifest.

## The marketplace manifest

`.claude-plugin/marketplace.json` is the listing every consumer resolves against, so a mistake in it breaks installs for every repo in [`docs/consumers.md`](docs/consumers.md) at once, and the failure mode is silence rather than an error. Two rules keep it honest.

**A plugin's version lives in its own `plugin.json` and nowhere else.** An entry in the marketplace manifest must not carry a `version`. A second copy goes stale the first time someone bumps `plugin.json` without it, and from then on `claude plugin update` compares against a number nobody maintains.

**Every plugin directory is listed, and every entry points at the plugin that claims that name.** An entry whose `source` holds a `plugin.json` with a different `name` resolves to nothing; a plugin directory with no entry cannot be installed at all.

CI checks both, plus the accepted top-level and per-entry keys, in the *Validate plugin manifests* job. Claude Code silently ignores a key it does not recognise, which is why the gate rejects one rather than warning.

## Declaring a plugin in a consuming project

A project can commit its plugin dependency to `.claude/settings.json`, so that sessions opened in that repository enable the plugin without anyone installing it by hand:

```bash
claude plugin install github-workflow@subverting-complexity --scope project
```

Be aware of how that install splits itself across two files, because the split is easy to misread. The command writes `enabledPlugins` into the **project** settings, which is the part that gets committed, but it records the marketplace under `extraKnownMarketplaces` in the **user** settings, which stays on the machine that ran it.

The consequence is that a committed `enabledPlugins` entry names a marketplace the repository never declares. Adding `extraKnownMarketplaces` to the project settings alongside it looks like the fix, and it is harmless, but it does **not** work: a config that has never registered the marketplace does not fetch it on the strength of a project-level declaration. Verified against v2.1.220, in a repository whose committed settings declared both keys:

| User config | Project settings | Result |
| ----------- | ---------------- | ------ |
| Marketplace never added | Both keys | `No plugins installed` — nothing fetched |
| Marketplace added | `enabledPlugins` only | Resolves, `Scope: project` |
| Marketplace added | Both keys | Resolves, `Scope: project` |

So the marketplace registration is a per-machine step that cannot be committed. Each developer runs this once, ever, and it covers every repository they subsequently clone:

```bash
claude plugin marketplace add Subverting-complexity/claude-plugins
```

After that one command, a repository's committed `enabledPlugins` is enough on its own — no `plugin install` per project. That is the real benefit of committing the declaration, and it is worth saying plainly in a consuming project's own README, because the failure mode when the marketplace is missing is silence rather than an error.

## Supplementary Files

These files provide context for specific workflows. You don't need to read all of them every session — consult them when the topic is relevant to what you're working on.

| File | When to consult |
| ---- | --------------- |
| `ClaudeProject.md` | Project identity, labels, quality gate, branch convention, board config. Read at the start of any workflow command. |
| `docs/consumers.md` | Which repos depend on these plugins. Read before cutting a major or otherwise breaking release, to judge the blast radius. |
| `docs/review.config.md` | Review-state labels, the non-compliance gates a PR must clear, tech-stack review rules, and the auto-merge settings. Read when reviewing a PR or when asking why a run did or did not merge. Auto-merge is enabled here, so a finished `execute` run merges its own PR once the review approves. |
| `.claude/ecosystem.md` | Installed Claude Code companion tool cheat-sheet (Graphify, RTK, ccusage, ecc-agentshield). Read before searching the codebase or running an audit/review: prefer `graphify query` over blind file search; run `ecc-agentshield scan` when touching config files; use `npx ccusage` to check token spend. |
