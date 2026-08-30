# github-workflow

A Claude Code plugin that provides an end-to-end GitHub development
workflow. Install it on any project and say "start the next story" — the
plugin handles picking, planning, building, testing, opening a PR, and
having that PR reviewed by separate agents in a fresh context, then applies
what the review asks for. It merges too, on projects that switch merging on
(see [Auto-merge](#auto-merge)); by default a run ends at an approved PR.

## Install

```bash
# From local path
claude --plugin-dir ./plugins/github-workflow

# Or install from marketplace once published
/plugin install github-workflow
```

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

The **builder** agent is set as the default via `settings.json`. When
the plugin is active, Claude operates as the builder unless you switch
agents.

## What's in the box

```
github-workflow/
├── .claude-plugin/
│   └── plugin.json            # Plugin manifest
├── skills/                    # Skills catalogue — see "Skills" below
│   ├── execute/               # Orchestrator: pick → build → PR → review → merge
│   ├── bulk-execute/          # Same loop for 2-5 related stories on one branch
│   ├── code-architect/        # Architecture design and audit (SOLID + Clean)
│   ├── structured-coding/     # Structured coding methodology
│   ├── code-review/           # Deep PR review, labels, optional auto-merge
│   ├── preflight/             # Project-config health check
│   ├── feature-discovery/     # Break features into stories + stress-test plans
│   ├── verify-feature/        # Verify a change against its story
│   ├── security-audit/        # Security-focused codebase audit
│   ├── debugging/             # Systematic root-cause debugging
│   ├── repo-scaffolding/      # Repository structure and setup
│   ├── user-story/            # Author user stories
│   ├── writing-github-issues/ # Issue-body standard (short, scannable)
│   ├── acceptance-criteria/   # Author acceptance criteria
│   ├── pr-description/        # Author PR descriptions
│   ├── doc-writer/            # Write and update documentation
│   ├── ecosystem-setup/       # Set up companion tools, write ecosystem.md
│   └── _shared/               # Wording + banned-patterns standards
├── commands/                  # 8 slash commands — see "Usage" above
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
5. Generates `ClaudeProject.md` (project settings) and `CLAUDE.md`
   (project rules) at your repo root.
6. Optionally sets up Claude Code companion tools (Graphify, RTK,
   ccusage, ecc-agentshield, Fallow) and writes `.claude/ecosystem.md`
   so `execute` and `code-review` use them automatically. This step is
   the shared `ecosystem-setup` skill — run it again any time with
   `/github-workflow:setup ecosystem`.

If you already have these files, the setup wizard detects them and
offers to fill in missing sections rather than overwrite.

### Prerequisites

Tools the plugin expects on the host machine:

| Tool | Needed for | Notes |
| ---- | ---------- | ----- |
| `gh` (GitHub CLI) | every issue, PR, label, and board operation | Must be authenticated: `gh auth login`. This is a **hard dependency by design** — the plugin has no REST-API fallback. |
| `git` | branching, claims, worktrees | Any recent version. |
| Python ≥ 3.8 | the `wf` story-picker (`scripts/wf.py`) | Recommended, not strictly required — every picker path has an inline fallback, but the fallbacks are slower (many sequential `gh` round-trips). |

The plugin also reads two files from the host project:

**`ClaudeProject.md`** (required) — The single source of truth for all
project-specific values. Every command and the skill read this file.
Full format specification: [`docs/claudeproject-spec.md`](../docs/claudeproject-spec.md).

Required sections: Identity, Package Manager, Quality Gate, Branch
Convention, Label Map, Story Template, Issue Prefixes.

Optional sections: Project Board, Reference Docs.

**`CLAUDE.md`** (required) — Project rules, build principles, and
session hygiene.

**`docs/review.config.md`** (optional) — Review label definitions,
non-compliance gates, and tech-stack review rules. Required by the
`code-review` skill. Generated automatically on first code-review run,
or during setup.

### Known limitations

The `wf` story-picker resolves a single repo root via
`git rev-parse --show-toplevel` and reads one `ClaudeProject.md` from it.
Monorepos that want per-subproject boards, labels, or quality gates are
not supported: configure one `ClaudeProject.md` at the repository root
that covers the whole repo. Per-subproject configuration is unsupported.

## Backlog modes

The plugin supports two backlog styles, auto-detected from milestones:

### Sprint mode

- Milestones with due dates represent sprints.
- The plugin finds the earliest milestone with open issues — that's
  the current sprint. No hardcoded sprint order needed.
- Issues are picked by priority label, then issue number.
- Product version filtering is optional.

### Flat backlog

- No milestones (or milestones without due dates).
- Issues are picked by priority label, then issue number.
- A `status-ready` label gates what's eligible for pickup (configurable).

Both modes use the same commands and skill — the pick logic adapts.

## Label map

Instead of hardcoding label names, the plugin maps **purposes** to
your repository's actual labels via `ClaudeProject.md`:

```markdown
| Purpose          | Label              |
| ---------------- | ------------------ |
| priority-high    | `P1`               |
| type-bug         | `bug`              |
| status-ready     | `status:ready`     |
| claude-authored  | `claude:authored`  |
```

This lets the same plugin work across repos with different label schemes.

## Project board

A project without a board works fine — when no board is configured, the
plugin skips board updates (status transitions, date stamps) silently.

This is the rule everywhere in the plugin: **"best-effort" never means
"skip a configured feature."** It applies only to two cases:

1. **Feature not configured** — e.g. no board in `ClaudeProject.md`. The
   step is skipped silently.
2. **Inherently idempotent cleanup** — e.g. deleting a claim ref that may
   already be gone, or removing a label that may not be present. The
   "failure" is a no-op, not a swallowed error.

When a feature **is** configured, its steps fail loudly: a board, label,
or milestone operation that errors is reported to the user, never
swallowed. The workflow continues past the failed step, but the failure
is surfaced.

When configured, the setup wizard auto-fetches:

- Project number and node ID
- Field IDs for Status, Start Date, End Date
- Option IDs for each status column (see the canonical set below)

### Board columns mirror the lifecycle

The board is the **board-side mirror** of the issue lifecycle labels.
Every command that moves an issue to a new lifecycle *label* also moves
its board item to the paired *column*, so the board never drifts from the
labels. The canonical six-column set — the three **active workflow
columns** (In Progress, In Review, Blocked) plus Backlog, Ready, and Done
— and the full label ⇄ column pairing live in one place,
`templates/default-labels.md` → Board Columns. Columns resolve by purpose
key (`col-in-progress`, `col-in-review`, `col-blocked`, …) exactly like
labels, so "apply == filter" holds for the board too.

| Lifecycle label | Board column |
| --------------- | ------------ |
| `status-in-progress` (and `status-needs-attention`) | In Progress |
| `status-in-review` | In Review |
| `status-blocked` (and `status-parked`) | Blocked |
| `status-ready` | Ready |

When a board is configured, the three active columns must exist: the
setup wizard creates any that are missing (via `updateProjectV2Field`),
and preflight raises a `board-columns-incomplete` error if one is absent.
A project with no board configured skips all of this silently.

## Auto-merge

Both entry points can merge a pull request, and **one setting decides
whether either of them does**: `Auto-Merge on Approval` in
`docs/review.config.md`. It is `disabled` unless you turn it on, including
when the file does not exist at all.

| Setting | `/github-workflow:execute` ends at | `/github-workflow:code-review` ends at |
| ------- | ---------------------------------- | -------------------------------------- |
| `disabled` (default) | An approved PR, reviewed and waiting for you | An approved PR |
| `enabled` | A merged PR, with its issues closed and the board moved to Done | A merged PR |

Keeping it to one switch is deliberate. The alternative — merging by default
from `execute` and only on request from `code-review` — means the answer to
"is this repository going to merge something without me" depends on which
command happened to reach the PR, which is not a property anyone can hold in
their head. Turn it on in `/github-workflow:setup`, which also runs the
hardening step that makes "merge only after CI passes" actually enforceable.

Two ways to suppress a merge on a project that has it on: pass `--no-merge`
for a single `execute` run, or leave the PR at a non-approved verdict. And
several conditions stop a merge on their own — a red quality gate, a
possible duplicate PR, a review that could not run independently, a moved
head SHA, absent or red CI. Each of those leaves the PR open with a comment
saying why.

## Agents

| Agent         | Role                          | Constraint             |
| ------------- | ----------------------------- | ---------------------- |
| **Builder**   | Implements stories end-to-end | Full tool access       |
| **Reviewer**  | Validates PRs against issues  | Fixes and merges in full mode; read-only when `execute` spawns it for an independent review |
| **DocWriter** | Updates documentation         | Restricted to `docs/`  |

Each agent follows least privilege — only the tools it needs.
The builder is the default agent when the plugin is active.

Unlike the skills, the agents are **plugin-specific and not shared or
synced** from `_shared-skills/`: each agent's tool allowlist is
least-privilege-scoped to this GitHub workflow (specific `gh` and `git`
operations, board mutations), so the definitions would not transfer to a
plugin with a different surface.

## Skills

The plugin bundles the following skills. The orchestrators (`execute`,
`bulk-execute`, `code-review`) drive the workflow; the rest are invoked by
them or directly.

| Skill                 | What it does                                       |
| --------------------- | ------------------------------------------------- |
| `execute`             | Orchestrator: pick → build → PR → review → merge   |
| `bulk-execute`        | The same loop for 2-5 related stories at once     |
| `code-architect`      | Architecture design and audit (SOLID + Clean)     |
| `structured-coding`   | Structured coding methodology                     |
| `code-review`         | Deep PR review, labels, optional auto-merge       |
| `preflight`           | Checks project-config health before a run         |
| `feature-discovery`   | Breaks features into stories + stress-tests plans |
| `verify-feature`      | Verifies a change against its story in context    |
| `security-audit`      | Security-focused codebase audit                   |
| `debugging`           | Systematic root-cause debugging methodology       |
| `repo-scaffolding`    | Repository structure and scaffolding              |
| `user-story`          | Authors user stories                              |
| `writing-github-issues` | Standard for every issue title and body         |
| `acceptance-criteria` | Authors acceptance criteria                       |
| `pr-description`      | Authors PR descriptions                           |
| `doc-writer`          | Writes and updates documentation                  |

## Adapting for a new project

1. Load the plugin: `claude --plugin-dir /path/to/github-workflow`
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
| Review a PR        | `Run /github-workflow:code-review`           |
| Fix review feedback| `Run /github-workflow:code-review`           |
