# Claude Plugins Monorepo

This repo contains one Claude Code plugin, `github-workflow`, which covers GitHub story work and work that stays on your machine. It used to be two plugins (`github-workflow` and `local-workflow`) sharing fifteen skills through a sync step; 13.0.0 merged them, so every skill now has exactly one copy and there is nothing to sync. A new name for the merged plugin is still to be chosen.

> **Dogfooding note:** This repo is itself configured as a `github-workflow` target. Project settings (org/repo, quality gate, issue fields) live in [`ClaudeProject.md`](ClaudeProject.md); workflow commands (`/github-workflow:execute`, `:pr-review`, etc.) read it. The open backlog of plugin-hardening work can be viewed on the [claude-plugins board](https://github.com/orgs/Subverting-complexity/projects/8), grouped by each issue's `Stage`.

## CRITICAL RULES

1. **Keep what loads into every session small.** Every skill, command and agent description, and the `SessionStart` hook, is in context for every session whether or not the plugin is used. `check-budgets.sh` caps a description at 240 characters, and CI caps the total with `count-tokens.sh --every-chat`. Put detail in the skill body or in a `references/` file loaded on demand, never in the description.

   A skill that only a person ever runs by name, and that no skill, command or agent needs Claude to invoke, sets `disable-model-invocation: true` in its frontmatter. Claude Code then leaves its description out of context entirely while `/github-workflow:<name>` still works; the cost is that Claude can no longer invoke it, and asking in plain words no longer triggers it. `tone`, `support-request`, `acceptance-criteria` and `ecosystem-setup` carry it. A workflow that needs one of them reads its `SKILL.md` and follows it, as `setup` does for `ecosystem-setup`.

2. **Always bump the plugin version before merging.** If you changed any file under `github-workflow/`, bump its version in `github-workflow/.claude-plugin/plugin.json`:
   - **Patch** (x.y.Z): bug fixes, typo corrections, minor wording
   - **Minor** (x.Y.0): new skills, commands, behavioral changes
   - **Major** (X.0.0): breaking changes, removed skills

3. **Always commit and open a PR when work is complete.** This is the default and it **overrides** the generic "only commit/push when asked" caution — finishing a unit of work here *means* committing it on a feature branch and opening a pull request against `main`, without waiting to be told. Only skip this if the user explicitly says not to (e.g. "don't commit", "just show me the diff"). Never leave completed changes uncommitted in the working tree. Before committing: branch off `main` if on it, run the quality gate, and bump the version (rule 2). End commit messages and PR bodies with the standard co-author / generation trailers.

## Standards the skills share

`github-workflow/skills/_shared/` holds the wording standard, the banned patterns and the body standard, and `github-workflow/references/` holds the story template. Skills cite them by path.

`_shared/body-standard.md` is the single standard for every body written into a tracker or forge: an issue, a pull request description, a comment. It holds the wording, the bullet and title rules, the style and the no-hard-wrapping rule. Its entry points carry only the part that differs, which is which sections a body has: `writing-github-issues` for a GitHub issue, `pr-body` for a pull request.

`pr-body` has two formats and the repository chooses between them, never the writer. A repository with a `ClaudeProject.md` always gets the fixed shape (`## Summary` → `## Changes` → `## Test plan`, then `Closes #N`), because `execute`, `bulk-execute` and `pr-review` read and extend those bodies. Any other repository, or another platform, gets the component-section format in `pr-body/references/component-format.md`.

`writing-github-issues` and `user-story` stay separate on purpose: one is the standard for a GitHub issue body, the other writes a story for pasting into any project management tool.

`lint-skills.sh` asserts that every entry point, the wording standard and `templates/body-file-write.md` still cite the body standard, so they cannot drift apart again.

`user-facing-communication` is the standard for every reply the plugin writes to a person: what was done and the current state first, then anything outstanding, blocked or assumed. It reaches a session three ways, so it holds whether or not a workflow command is running: the `SessionStart` hook injects it, `_shared/wording-standard.md` cites it (and every skill cites that), and every skill, command and agent that writes to the user names it directly. `lint-skills.sh` asserts that last part, so the wiring cannot be dropped one file at a time.

### Never hard-wrap an instruction file

Every markdown file in this repo is written one paragraph per line, however long the line runs. Do not reflow prose to 72, 80 or any other column, and do not rewrap a paragraph you edit. The only line breaks a file has are the ones markdown needs: between blocks, between list items, and inside fenced code.

This is not cosmetic. These files are the examples the model learns the house style from, and while they were wrapped it wrapped the issue and pull request bodies it wrote — which trackers then reflowed, putting the breaks where they suited nobody. `_shared/body-standard.md` states the rule for bodies; this section states it for the files that teach it.

## Plugin

| Plugin | Description |
|--------|-------------|
| `github-workflow` | GitHub story work end to end (`execute`, `bulk-execute`, `pr-review`), local work that stops at a commit (`build`), and the planning, review and writing skills both use |
## Running parallel agents

These workflows spawn parallel/background agents, each of which the harness places in its own git worktree. When running agents in parallel — especially on Windows, where per-worktree `node_modules` duplication causes file-lock cleanup failures — follow the recommended harness configuration and manual reap routine in [`docs/worktree-config.md`](docs/worktree-config.md).

## Tooling

| Tool | What it does |
|------|-------------|
| `bootstrap.ps1` / `bootstrap.sh` | One-time per-clone setup: pin LF line endings, renormalize, install the pre-commit hook, check Python is available |
| `lint-skills.sh` | Validate skill frontmatter and the wiring between skills and the standards they cite |
| `run-tests.sh` | Run the offline decision-logic tests; auto-detects `python3`, `py -3` (Windows Launcher), or `python` |
| `run-tests.ps1` | Windows PowerShell equivalent of `run-tests.sh`; prints a `winget` install hint if no Python is found |
| `count-tokens.sh` | Report instruction load in three tiers: every chat (`--every-chat`: descriptions and the `SessionStart` hook), every run of a skill (its file plus references it cites without a condition, two levels deep), and on a trigger (references cited on a stated condition). `--budget` gates tier 1 or tier 2; tier 3 is never gated. A citation counts as conditional when its sentence, its paragraph's first sentence, or its list item says if, unless, when, whenever, only or except, so write "once" for a step every run reaches |
| `check-budgets.sh` | Enforce per-file description-char and body-line budgets on skills and commands (ratchet gate) |
| `count-roundtrips.sh` | Count `gh`/`git` network calls described in instruction files (informational, no gate) |
| `hooks/pre-commit` | Git hook that blocks CRLF line endings |
| `.github/workflows/ci.yml` | CI: skill lint, decision-logic tests, version-bump check, token-footprint budgets, plugin.json validation |
| `.claude/ecosystem.md` | Cheat-sheet for installed Claude Code companion tools (graphify, RTK, ccusage, ecc-agentshield) and when the workflow uses each. Consult it before searching the codebase blind or running an audit/review. Generated by the `ecosystem-setup` skill — regenerate via `/github-workflow:setup ecosystem`. |

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
```

Without the marketplace refresh, `plugin update` reports "already at latest" against the cached version — not the actual latest on main.

> The command is `claude plugin` (singular). Run it from a normal shell, not inside a Claude Code session — the CLI blocks nested sessions; if needed, prefix with `env -u CLAUDECODE`. Verify a manifest before shipping with `claude plugin validate ./<plugin>` — it catches schema errors (e.g. unrecognized keys) that plain JSON validation misses. `claude plugin validate .` does the same for the marketplace manifest.

## The marketplace manifest

`.claude-plugin/marketplace.json` is the listing every consumer resolves against, so a mistake in it breaks installs for every repo in [`docs/consumers.md`](docs/consumers.md) at once, and the failure mode is silence rather than an error. Two rules keep it honest.

**A plugin's version lives in its own `plugin.json` and nowhere else.** An entry in the marketplace manifest must not carry a `version`. A second copy goes stale the first time someone bumps `plugin.json` without it, and from then on `claude plugin update` compares against a number nobody maintains.

**Every plugin directory is listed, and every entry points at the plugin that claims that name.** An entry whose `source` holds a `plugin.json` with a different `name` resolves to nothing; a plugin directory with no entry cannot be installed at all.

CI checks both, plus the accepted top-level and per-entry keys, in the *Validate plugin manifests* job. Claude Code silently ignores a key it does not recognise, which is why the gate rejects one rather than warning.

## Installing the plugin for a project

Install the plugin per machine, at user scope, and never commit it into a consuming project. A project's `.claude/settings.json` must not carry `enabledPlugins` or `extraKnownMarketplaces` for this marketplace, and `claude plugin install --scope project` must not be used, because it writes `enabledPlugins` into that file.

A committed entry pins the plugin by name, so a rename or a merge in this marketplace makes it stop resolving in every repository that carries it, and the failure is silence rather than an error. It also does not fetch anything on a machine that has never added the marketplace. Each developer runs these once, and they cover every repository:

```bash
claude plugin marketplace add Subverting-complexity/claude-plugins
claude plugin install github-workflow@subverting-complexity
```

## Supplementary Files

These files provide context for specific workflows. You don't need to read all of them every session — consult them when the topic is relevant to what you're working on.

| File | When to consult |
| ---- | --------------- |
| `ClaudeProject.md` | Project identity, quality gate, branch convention, issue fields. Read at the start of any workflow command. |
| `docs/consumers.md` | Which repos depend on the plugin. Read before cutting a major or otherwise breaking release, to judge the blast radius. |
| `docs/review.config.md` | Review-state labels, the non-compliance gates a PR must clear, tech-stack review rules, and the auto-merge settings. Read when reviewing a PR or when asking why a run did or did not merge. Auto-merge is enabled here, so a finished `execute` run merges its own PR once the review approves. |
| `.claude/ecosystem.md` | Installed Claude Code companion tool cheat-sheet (Graphify, RTK, ccusage, ecc-agentshield). Read before searching the codebase or running an audit/review: prefer `graphify query` over blind file search; run `ecc-agentshield scan` when touching config files; use `npx ccusage` to check token spend. |
