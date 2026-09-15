# Skill names and the built-ins they avoid

Every skill, command and agent in `synergy` is checked here against the Claude Code built-in commands and bundled skills, and the Anthropic skills installed alongside the plugin. Nothing reads this file at runtime. Check a new name against it before adding one, and add a row when you do.

A person usually types the short name, or asks in plain words, so the namespace prefix does not protect a name. When a plugin name matches or nearly matches another one, the person can get the other one without noticing. That happened with `code-review`: a review run came back as the built-in `/code-review` output instead of the plugin's review.

The built-in list changes between Claude Code releases. The comparison below was made on 15 September 2026, and is a record of that check rather than a complete list.

## What counts as a clash

- **Exact.** The part after the colon is the name of a built-in command, a bundled skill or an Anthropic skill. Always renamed.
- **Near.** The names share their distinctive word, or one is the other with a word added, and the two do the same kind of job. Renamed.
- **Distinct.** The names differ, or they share only a generic word and the jobs differ. Kept, with the reason.

## Renamed

| Old name | New name | Clashed with | Renamed in |
| -------- | -------- | ------------ | ---------- |
| `code-review` | `pr-review` | built-in `/code-review` (exact) | 14.0.0 (Issue #291 — Rename the automated code-review skill so it stops clashing with the built-in) |
| `grill` | `interview` | Anthropic skill `grill-me` (near: same word, same job) | 15.0.0 (Issue #288 — Rename the remaining plugin skills that clash with Claude Code or Anthropic skills) |
| `tone` | `correspondence` | Anthropic skill `adrienne-tone` (near: same word, same job) | 15.0.0 (Issue #288) |
| `setup` | `onboard` | Anthropic skill `setup-claude` (near: same word, both set things up for Claude) | 15.0.0 (Issue #288) |

Names considered and rejected while choosing:

- `voice` for `tone`: it reads as dictation or voice input rather than writing, and was not checked against every Claude Code release.
- `configure` for `setup`: too close to the built-in `/config`.
- `project-setup` for `setup`: keeps the word that clashed.

The `setup` command's step files were renamed with it: `references/onboarding.md`, `onboard-wf.md`, `onboard-reap.md` and `onboard-issues.md`. The `wf.sh setup` subcommand is a different thing, a script argument nobody types as a slash command, and keeps its name.

## Checked and kept

| Name | Nearest other name | Why it stays |
| ---- | ------------------ | ------------ |
| `bulk-execute` | built-in `/batch` | Different name. `/batch` makes one large change across many files in parallel worktrees; `bulk-execute` builds two to five GitHub stories on one branch behind one pull request. Its description no longer says "batch", so a request to batch something does not match both. |
| `verify-feature` | built-in `/verify` | Different name, decided in Issue #287 — Restore verify-feature as a report a person reads. It runs by name only. |
| `pr-review` | built-in `/review` | Different name, and the plugin's review posts labels and can merge. Chosen in 14.0.0 knowing `/review` exists. |
| `ecosystem-setup` | Anthropic skill `setup-claude` | Shares only the generic word "setup". It installs companion tools such as Graphify and RTK, not plugins or connectors, and runs by name only or through `/synergy:onboard ecosystem`. |
| `code-architect` | `code-architect` agent in Anthropic's `feature-dev` plugin | Not a built-in, and not installed alongside this plugin. Revisit if `feature-dev` is installed next to `synergy`. |
| `build`, `execute`, `guide`, `report-issue`, `preflight`, `block-story`, `feature-discovery`, `user-story`, `acceptance-criteria`, `writing-github-issues`, `pr-body`, `support-request`, `user-facing-communication`, `interview`, `correspondence`, `onboard` | none found | No built-in command, bundled skill or installed Anthropic skill uses or nearly uses these names. |
| `Builder`, `Reviewer` (agents) | none found | No built-in agent type uses these names. |

## What was compared

- **Claude Code built-in commands:** `/batch`, `/config`, `/doctor`, `/hooks`, `/init`, `/permissions`, `/review` and `/verify`, among others.
- **Bundled and installed skills:** `artifact-capabilities`, `artifact-design`, `artifact-diagramming`, `claude-api`, `code-review`, `dataviz`, `design`, `fewer-permission-prompts`, `graphify`, `init`, `keybindings-help`, `logo-variations`, `loop`, `run`, `schedule`, `security-review`, `simplify`, `update-config`, `workflow-authoring`.
- **Anthropic skills:** `adrienne-tone`, `consolidate-memory`, `docx`, `explain-usage`, `grill-me`, `import-memory`, `morning`, `pdf`, `pptx`, `schedule`, `setup-claude`, `skill-creator`, `xlsx`.

## Where a retired name may still appear

- `CHANGELOG.md`, which records the history.
- This file.
- `wf preflight`'s `instructions-retired` check in `synergy/scripts/wf_core_preflight.py` and its test, which look for the retired names in a consuming project's `CLAUDE.md` and `ClaudeProject.md` so a project still using one is told.
- Generated Graphify output (`graphify-out/`, `docs/GRAPH_REPORT.md`), which is rebuilt rather than edited.
