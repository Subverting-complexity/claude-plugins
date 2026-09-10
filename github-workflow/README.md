# github-workflow

A Claude Code plugin that provides an end-to-end GitHub development workflow. Install it on any project and say "start the next story" — the plugin handles picking, planning, building, testing, opening a PR, and having that PR reviewed by separate agents in a fresh context, then applies what the review asks for. It merges too, on projects that switch merging on (see [Auto-merge](#auto-merge)); by default a run ends at an approved PR.

## Install

```bash
claude plugin marketplace add Subverting-complexity/claude-plugins
claude plugin install github-workflow@subverting-complexity
```

Run both from a normal shell, not inside a Claude Code session, then restart the session so skills, commands, agents and hooks load. Adding the marketplace is a per-machine step you do once, ever.

## Usage

| Command                                 | What it does                             |
| --------------------------------------- | ---------------------------------------- |
| `/github-workflow:execute`              | Pick next story, execute end-to-end through independent review (and merge, where enabled) |
| `/github-workflow:execute 47`           | Execute story #47 directly               |
| `/github-workflow:execute --mode maintenance` | Pick and fix the next bug/security/debt issue |
| `/github-workflow:execute --mode audit` | Audit codebase, create issues (no code)  |
| `/github-workflow:execute --no-merge`   | Skip the merge for one run on a project that has merging enabled |
| `/github-workflow:bulk-execute`         | Choose 2-5 related stories and build them as one branch, one PR, one review |
| `/github-workflow:bulk-execute 41 43 47` | Build exactly these stories together     |
| `/github-workflow:code-review`          | Review (or rework + re-review) the next PR |
| `/github-workflow:block-story`          | Mark current story as blocked            |
| `/github-workflow:report-issue`         | Create a bug/arch/debt issue             |
| `/github-workflow:setup`                | Interactive project onboarding wizard    |
| `/github-workflow:guide`                | How to get started / what can I do?      |

The **builder** agent is set as the default via `settings.json`. When the plugin is active, Claude operates as the builder unless you switch agents.

## What's in the box

```
github-workflow/
├── .claude-plugin/
│   └── plugin.json            # Plugin manifest
├── skills/                    # See "Skills" below
├── commands/                  # block-story, guide, report-issue, setup
├── agents/                    # builder, reviewer, doc-writer
├── references/
│   └── story-template.md      # Shared story issue template
├── templates/                 # Canonical procedures + project-config templates
├── hooks/                     # Quality-gate commit hook
├── settings.json              # Default agent = builder
└── README.md                  # This file
```

## Getting started

### First-time setup

Run `/github-workflow:setup` to onboard your project. The wizard:

1. Auto-detects your org, repo, default branch, and package manager.
2. Discovers your project board and fetches field IDs automatically.
3. Checks for milestones to determine sprint vs flat backlog mode.
4. Asks for your label scheme, branch convention, and quality gate.
5. Generates `ClaudeProject.md` (project settings) and `CLAUDE.md` (project rules) at your repo root.
6. Optionally sets up Claude Code companion tools (Graphify, RTK, ccusage, ecc-agentshield, Fallow) and writes `.claude/ecosystem.md` so `execute` and `code-review` use them automatically. This step is the shared `ecosystem-setup` skill — run it again any time with `/github-workflow:setup ecosystem`.

If you already have these files, the setup wizard detects them and offers to fill in missing sections rather than overwrite.

### Prerequisites

Tools the plugin expects on the host machine:

| Tool | Needed for | Notes |
| ---- | ---------- | ----- |
| `gh` (GitHub CLI) | every issue, PR, label, and board operation | Must be authenticated: `gh auth login`. This is a **hard dependency by design** — the plugin has no REST-API fallback. |
| `git` | branching, claims, worktrees | Any recent version. |
| Python ≥ 3.8 | the `wf` CLI (`scripts/wf.py`) | **Required** for `execute`, `bulk-execute` and issue creation. Selection, claiming, board moves, handoff and issue classification are all `wf` commands with no markdown fallback — without Python those commands fail naming the missing prerequisite. `code-review` still has its own PR-selection fallback. |

The plugin also reads two files from the host project:

**`ClaudeProject.md`** (required) — The single source of truth for all project-specific values. Every command and the skill read this file. Full format specification: [`docs/claudeproject-spec.md`](../docs/claudeproject-spec.md).

Required sections: Identity, Package Manager, Quality Gate, Branch Convention, Label Map, Story Template, Issue Types & Fields, Project Board.

Optional sections: Reference Docs.

**`CLAUDE.md`** (required) — Project rules, build principles, and session hygiene.

**`docs/review.config.md`** (optional) — Review label definitions, non-compliance gates, and tech-stack review rules. Required by the `code-review` skill. Generated automatically on first code-review run, or during setup.

### Known limitations

The `wf` story-picker resolves a single repo root via `git rev-parse --show-toplevel` and reads one `ClaudeProject.md` from it. Monorepos that want per-subproject boards, labels, or quality gates are not supported: configure one `ClaudeProject.md` at the repository root that covers the whole repo. Per-subproject configuration is unsupported.

## Backlog modes

The plugin supports two backlog styles, auto-detected from milestones:

### Sprint mode

- Milestones with due dates represent sprints.
- The plugin finds the earliest milestone with open issues — that's the current sprint. No hardcoded sprint order needed.
- Issues are picked by the `Priority` field, then `Effort`, then issue number — the same order as a flat backlog, applied within the current milestone.
- Product version filtering is optional.

### Flat backlog

- No milestones (or milestones without due dates).
- Issues are picked by priority, then effort, then issue number.
- The board's **Backlog** column is the pool: an unassigned issue sitting in it is available.

Both modes use the same commands and skill — the pick logic adapts.

## Label map

**Labels decide nothing.** State is the board column, and priority, effort and ownership are org-level issue fields — so there is one issue label left, the `claude-authored` provenance marker, plus the review-state labels a pull request carries. The map exists so a repository can call that marker whatever it already calls it:

```markdown
| Purpose          | Label              |
| ---------------- | ------------------ |
| claude-authored  | `claude:authored`  |
```

A map row naming a label the workflow retired (`status-*`, `priority-*`, `needs-refinement`, `claude-ready`) is reported by `wf config-audit` as `label-deprecated`. Delete the row; the labels themselves can stay on old issues.

## Project board

A project board is required. Which column a card sits in is the issue's state, and the Backlog column is the pick pool, so there is no useful behaviour left for a project that has no board — preflight fails the run rather than degrading quietly. The columns and what each means are below.

Where the plugin does allow a best-effort step, the rule is that **"best-effort" never means "skip a configured feature."** It applies to one case: **inherently idempotent cleanup** — deleting a claim ref that may already be gone, or removing a label that may not be present. The "failure" is a no-op, not a swallowed error.

When a feature **is** configured, its steps fail loudly: a board, label, or milestone operation that errors is reported to the user, never swallowed. The workflow continues past the failed step, but the failure is surfaced.

The setup wizard auto-fetches:

- Project number and node ID
- Field IDs for Status, Start Date, End Date
- Option IDs for each status column (see the canonical set below)

### The board column *is* the state

An issue's state is which column its card sits in, and nowhere else. There is no label to keep in step, so there is nothing for the board to drift from. The nine columns — Backlog, In Progress, In Review, Blocked, Non-code, Needs refinement, Parked, Needs attention, Done — and what each one means are in one place, `templates/default-labels.md` → Board Columns. Columns resolve by purpose key (`col-backlog`, `col-in-progress`, `col-in-review`, …) exactly as labels do, so a project that renamed a lane only edits `ClaudeProject.md`.

| The issue is | Column |
| ------------ | ------ |
| available to pick | Backlog |
| claimed by an agent | In Progress |
| waiting on a pull request | In Review |
| pointing at an open blocked-by edge | Blocked |
| owned by a person or a browser agent | Non-code |
| specced too thinly to start | Needs refinement |
| deliberately set aside | Parked |
| stopped part-way and needing a person | Needs attention |
| closed | Done |

**A board is required, and so is its Backlog column.** That column *is* the pick pool: `pick` and `candidates` read it and nothing else, so an issue with no card on the board cannot be selected — which is why every issue the plugin creates or updates is placed. The setup wizard creates any missing column (via `updateProjectV2Field`); preflight fails the run when the board or its Backlog column is absent, and warns for every other missing lane.

Approval is structural too. A person approves work by moving its card into Backlog and withholds approval by leaving it in Needs refinement or Parked — there is no `claude-ready` label and no gate setting to turn on.

## Auto-merge

Both entry points can merge a pull request, and **one setting decides whether either of them does**: `Auto-Merge on Approval` in `docs/review.config.md`. It is `disabled` unless you turn it on, including when the file does not exist at all.

| Setting | `/github-workflow:execute` ends at | `/github-workflow:code-review` ends at |
| ------- | ---------------------------------- | -------------------------------------- |
| `disabled` (default) | An approved PR, reviewed and waiting for you | An approved PR |
| `enabled` | A merged PR, with its issues closed and the board moved to Done | A merged PR |

Keeping it to one switch is deliberate. The alternative — merging by default from `execute` and only on request from `code-review` — means the answer to "is this repository going to merge something without me" depends on which command happened to reach the PR, which is not a property anyone can hold in their head. Turn it on in `/github-workflow:setup`, which also runs the hardening step that makes "merge only after CI passes" actually enforceable.

Two ways to suppress a merge on a project that has it on: pass `--no-merge` for a single `execute` run, or leave the PR at a non-approved verdict. And several conditions stop a merge on their own — a red quality gate, a possible duplicate PR, a review that could not run independently, a moved head SHA, absent or red CI. Each of those leaves the PR open with a comment saying why.

## Agents

| Agent         | Role                          | Constraint             |
| ------------- | ----------------------------- | ---------------------- |
| **Builder**   | Implements stories end-to-end | Full tool access       |
| **Reviewer**  | Validates PRs against issues  | Fixes and merges in full mode; read-only when `execute` spawns it for an independent review |
| **DocWriter** | Updates documentation         | Restricted to `docs/`  |

Each agent follows least privilege — only the tools it needs. The builder is the default agent when the plugin is active.

Unlike the skills, the agents are **plugin-specific and not shared or synced** from `_shared-skills/`: each agent's tool allowlist is least-privilege-scoped to this GitHub workflow (specific `gh` and `git` operations, board mutations), so the definitions would not transfer to a plugin with a different surface.

## Skills

The plugin bundles the following skills. The orchestrators (`execute`, `bulk-execute`, `code-review`) drive the workflow; the rest are invoked by them or directly.

| Skill                 | What it does                                       |
| --------------------- | ------------------------------------------------- |
| `execute`             | Orchestrator: pick → build → PR → review → merge   |
| `bulk-execute`        | The same loop for 2-5 related stories at once     |
| `code-architect`      | Architecture design and audit (SOLID + Clean)     |
| `structured-coding`   | Structured coding methodology                     |
| `code-review`         | Deep PR review, labels, optional auto-merge       |
| `preflight`           | Checks project-config health before a run; `wf preflight --fix` repairs what it safely can |
| `feature-discovery`   | Breaks features into stories + stress-tests plans |
| `verify-feature`      | Verifies a change against its story in context    |
| `security-audit`      | Security-focused codebase audit                   |
| `debugging`           | Systematic root-cause debugging methodology       |
| `repo-scaffolding`    | Repository structure and scaffolding              |
| `user-story`          | Authors user stories                              |
| `writing-github-issues` | Standard for every issue title and body         |
| `user-facing-communication` | Standard for every reply the user reads    |
| `acceptance-criteria` | Authors acceptance criteria                       |
| `pr-body`             | Authors PR bodies to the fixed shape              |
| `doc-writer`          | Writes and updates documentation                  |
| `ecosystem-setup`     | Sets up companion tools, writes `ecosystem.md`    |
| `support-request`     | Support-request and incident write-ups            |
| `tone`                | Polishes correspondence in the user's voice       |

## Adapting for a new project

1. Install the plugin (see [Install](#install)).
2. Run `/github-workflow:setup` to generate config files.
3. Say "start the next story" or run `/github-workflow:execute`.

That's it. The plugin reads your config and adapts.

## Routine integration

Once installed, your scheduled task prompts become one-liners:

| Routine            | Prompt                                       |
| ------------------ | -------------------------------------------- |
| Work on next story | `Run /github-workflow:execute`               |
| Work through a related group | `Run /github-workflow:bulk-execute`  |
| Fix bugs           | `Run /github-workflow:execute --mode maintenance` |
| Audit codebase     | `Run /github-workflow:execute --mode audit`  |
| Review a PR, or apply review feedback | `Run /github-workflow:code-review` |
