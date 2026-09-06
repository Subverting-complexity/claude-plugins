# Shared Skills Manifest

Canonical source for the 14 skills shared across multiple plugins. **Never edit plugin copies directly** — edit here, then sync. The edit procedure is in [`CLAUDE.md`](../CLAUDE.md#how-to-edit).

## Shared skills

| Skill | Deployed to | Notes |
|-------|-------------|-------|
| `acceptance-criteria` | github-workflow, local-workflow | User-facing test criteria, grouped by change |
| `code-architect` | github-workflow, local-workflow | Includes `references/` subdirectory with architecture book summaries |
| `debugging` | github-workflow, local-workflow | Systematic reproduce → hypothesize → isolate → fix → verify cycle |
| `doc-writer` | github-workflow, local-workflow | README, API docs, architecture guides, migration guides, changelogs |
| `ecosystem-setup` | github-workflow, local-workflow | Detect/install/configure companion tools (Graphify, RTK, ccusage, ecc-agentshield, Fallow) and write `.claude/ecosystem.md`. github-workflow's `setup` Step 8 delegates here |
| `feature-discovery` | github-workflow, local-workflow | Discovery mode (stories) + validation mode (plan stress-test). Uses `references/story-template.md` |
| `repo-scaffolding` | github-workflow, local-workflow | Uses `references/story-template.md`, no spec docs |
| `security-audit` | github-workflow, local-workflow | Dependency scanning, secrets detection, OWASP Top 10, input validation |
| `structured-coding` | github-workflow, local-workflow | Autonomous workflow escape hatch |
| `support-request` | github-workflow, local-workflow | Support request / incident documentation in a fixed two-block format |
| `tone` | github-workflow, local-workflow | User-voice correspondence polishing. Includes `references/` with voice examples and glossary |
| `user-facing-communication` | github-workflow, local-workflow | The shape of every reply a person reads: outcome and state first, then Outstanding / Assumptions / Noteworthy. Cited by every skill, command and agent that writes to the user, and injected into every session by each plugin's `SessionStart` hook. Includes `references/examples.md` |
| `user-story` | github-workflow, local-workflow | Single user story from rough notes or requirements |
| `verify-feature` | github-workflow, local-workflow | Pre-merge containment, completeness, and side-effect analysis |

## Shared resources

| Directory | Deployed to | Notes |
|-----------|-------------|-------|
| `_shared/` | `{plugin}/skills/_shared/` | Banned patterns, the wording standard, and `body-standard.md` — the single standard behind every issue body, pull request description and comment. github-workflow's `pr-body`, local-workflow's `pr-description`, and github-workflow's `writing-github-issues` are its entry points and hold only the part that differs, which is which sections a body has |
| `references/` | `{plugin}/references/` | Story template, shared across plugins |

## Not shared (and why)

These exist in one or both plugins but are deliberately not canonicalized here. Do not "deduplicate" them into `_shared-skills/`.

| Skill | Why not shared |
|-------|----------------|
| `code-review` | github: full PR-lifecycle manager; local: lightweight diff reviewer. Divergence intentional — different products sharing a trigger |
| `execute` (github) / `build` (local) | Different jobs, different names. github's `execute` runs the whole GitHub loop — claim a story, build it, open a PR, have it reviewed independently, merge it. local's `build` stops at a commit. Shared skills cite whichever applies via `{{EXECUTE_SKILL}}` |
| `bulk-execute` (github) | github-only, and deliberately not a flag on `execute`. It needs GitHub issues, claims, a board and one PR closing several issues, none of which local-workflow has. It reuses `execute`'s review, merge and cleanup references rather than copying them |
| `writing-github-issues` (github) | github-only. It is the standard for every GitHub issue title and body the plugin writes, and local-workflow has no issue tracker to write one for. The shared skills that can produce a GitHub issue (`feature-discovery`, `repo-scaffolding`, `user-story`, `references/story-template.md`) name it in prose and degrade to the story template when a plugin does not ship it, rather than citing a path that would dangle in local-workflow. It is the counterpart to the shared `user-facing-communication`: that one shapes what you say **to** the user, this one shapes the issue body, and neither reaches into the other |
| `pr-body` (github) / `pr-description` (local) | Was one shared `pr-description` until the two formats had to diverge, and github's was renamed so each has its own slash command. github's body is fixed (`## Summary` → `## Changes` → `## Test plan`, then `Closes #N`) because `execute`, `bulk-execute` and `code-review` read and extend it, and a shape that varies per pull request cannot be extended reliably. local's keeps the component-section format, written for whoever is about to read the diff, with no automated loop behind it. Both still sit on `_shared/body-standard.md` for wording, bullets, titles and the no-wrapping rule — only the section shape differs, so do not re-merge them |
| `preflight` | github: board/label/auth validator; local: lightweight git/config checks |
| `mobile-audit` | local-only by product decision |
| `agents` | Never shared — least-privilege tool scoping is plugin-specific |

## Template variables

The sync script replaces these placeholders with plugin-specific values:

| Variable | Replacement |
|----------|-------------|
| `{{PLUGIN_NAME}}` | Plugin directory name (e.g., `github-workflow`, `local-workflow`) |
| `{{PLUGIN_VERSION}}` | Plugin version from `plugin.json` (e.g., `1.7.0`) |
| `{{EXECUTE_SKILL}}` | Name of that plugin's end-to-end orchestrator: `execute` in github-workflow, `build` in local-workflow |

A shared skill points at "this plugin's end-to-end command" by writing `/{{PLUGIN_NAME}}:{{EXECUTE_SKILL}}`, which resolves to the right one. Without it the two orchestrators would share a name and the skill picker would choose between identical descriptions arbitrarily. The mapping lives in `get_execute_skill` (`sync-skills.sh`) and `Get-ExecuteSkill` (`sync-skills.ps1`) — add a case to both when a plugin joins.

## Sync commands

```powershell
# Sync all shared skills to all plugins
./sync-skills.ps1

# Sync to a single plugin
./sync-skills.ps1 -Plugin github-workflow

# Check for drift without writing (CI use)
./sync-skills.ps1 -Verify
```
