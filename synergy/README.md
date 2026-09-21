# synergy

A Claude Code plugin that provides an end-to-end GitHub development workflow. Install it on any project and say "start the next story" — the plugin handles picking, planning, building, testing, opening a PR, and having that PR reviewed by separate agents in a fresh context, then applies what the review asks for. It merges too, on projects that switch merging on (see [Auto-merge](#auto-merge)); by default a run ends at an approved PR.

## Install

```bash
claude plugin marketplace add Subverting-complexity/claude-plugins
claude plugin install synergy@subverting-complexity
```

Run both from a normal shell, not inside a Claude Code session, then restart the session so skills, commands, agents and hooks load. Adding the marketplace is a per-machine step you do once, ever.

## Usage

| Command                                 | What it does                             |
| --------------------------------------- | ---------------------------------------- |
| `/synergy:execute`              | Pick next story, execute end-to-end through independent review (and merge, where enabled) |
| `/synergy:execute 47`           | Execute story #47 directly               |
| `/synergy:execute --mode maintenance` | Pick and fix the next bug/security/debt issue |
| `/synergy:execute --mode audit` | Audit codebase, create issues (no code)  |
| `/synergy:execute --no-merge`   | Skip the merge for one run on a project that has merging enabled |
| `/synergy:bulk-execute`         | Plan the stories that fill an effort budget, blockers first, and build them as at most two PRs, each reviewed and merged |
| `/synergy:bulk-execute 41 43 47` | Build exactly these stories together     |
| `/synergy:pr-review`          | Review (or rework + re-review) the next PR |
| `/synergy:build`                | Plan, build, verify and commit a local task, with no issue or PR |
| `/synergy:block-story`          | Mark current story as blocked            |
| `/synergy:report-issue`         | Create a bug/arch/debt issue             |
| `/synergy:setup`                | Interactive project onboarding wizard    |
| `/synergy:guide`                | How to get started / what can I do?      |

The plugin does not change the agent an ordinary session runs as. The **Builder** and **Reviewer** agents are there to be spawned by the workflows or chosen by name.

## What's in the box

```
synergy/
├── .claude-plugin/
│   └── plugin.json            # Plugin manifest
├── skills/                    # See "Skills" below
├── commands/                  # block-story, guide, report-issue, setup
├── agents/                    # builder, reviewer
├── references/                # Story template and the setup procedures
├── templates/                 # Canonical procedures + project-config templates
├── hooks/                     # Reply standard, repository host, write guard
└── README.md                  # This file
```

## Getting started

### First-time setup

Run `/synergy:setup` to onboard your project. The wizard:

1. Auto-detects your org, repo, default branch, and package manager.
2. Checks that the org defines the `Stage` issue field with its ten options, and records your project board if you have one. It also checks the repository has its area epics, the permanent parts of the product every issue sits under ([`references/area-epics.md`](references/area-epics.md)).
3. Checks for milestones to determine sprint vs flat backlog mode.
4. Asks for your branch convention and quality gate.
5. Generates `ClaudeProject.md` (project settings) and `CLAUDE.md` (project rules) at your repo root.
6. Optionally sets up Claude Code companion tools (Graphify, RTK, ccusage, ecc-agentshield, Fallow) and writes `.claude/ecosystem.md` so `execute` and `pr-review` use them automatically. This step is the shared `ecosystem-setup` skill — run it again any time with `/synergy:setup ecosystem`.

If you already have these files, the setup wizard detects them and offers to fill in missing sections rather than overwrite.

### Prerequisites

Tools the plugin expects on the host machine:

| Tool | Needed for | Notes |
| ---- | ---------- | ----- |
| `gh` (GitHub CLI) | every issue, PR, label, and field operation | Must be authenticated: `gh auth login`. This is a **hard dependency by design** — the plugin has no REST-API fallback. |
| `git` | branching, claims, worktrees | Any recent version. |
| Python ≥ 3.8 | the `wf` CLI (`scripts/wf.py`) | **Required** for `execute`, `bulk-execute` and issue creation. Selection, claiming, stage writes, handoff and issue classification are all `wf` commands with no markdown fallback — without Python those commands fail naming the missing prerequisite. `pr-review` still has its own PR-selection fallback. |

The plugin also reads two files from the host project:

**`ClaudeProject.md`** (required) — The single source of truth for all project-specific values. Every command and the skill read this file. Full format specification: [`docs/claudeproject-spec.md`](../docs/claudeproject-spec.md).

Required sections: Identity, Package Manager, Quality Gate, Branch Convention, Issue Types & Fields.

Recommended sections: Story Template, Session Budget, Refinement.

Optional sections: Project Board, Reference Docs, Bundled Skills.

**`CLAUDE.md`** (required) — Project rules, build principles, and session hygiene.

**`docs/review.config.md`** (optional) — Review label definitions, non-compliance gates, and tech-stack review rules. Required by the `pr-review` skill. Generated automatically on first pr-review run, or during setup.

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
- The pool is the open, unassigned issues whose `Stage` is blank or `Backlog`.

Both modes use the same commands and skill — the pick logic adapts.

## Labels

**Labels decide nothing, and the workflow puts none on an issue.** State is the `Stage` field, and priority, effort and ownership are org-level issue fields. The only labels it applies are the review-state labels a pull request carries, named in `docs/review.config.md` and created by `wf labels-ensure`.

A `## Label Map` left in an older `ClaudeProject.md` is still read. A row naming a label the workflow retired (`status-*`, `priority-*`, `needs-refinement`, `claude-ready`) is reported by `wf config-audit` as `label-deprecated`. Delete the row; the labels themselves can stay on old issues.

## Stage and boards

An issue's state is its org `Stage` field, and nowhere else. There is no label to keep in step and no board column is read. The ten stages (Backlog, In Progress, In Review, Blocked, Non-code, Needs refinement, Parked, Needs attention, Done, Area) and what each one means are in one place, [`docs/issue-fields.md`](../docs/issue-fields.md). They resolve by purpose key (`stage-backlog`, `stage-in-progress`, `stage-in-review`, …).

| The issue is | Stage |
| ------------ | ----- |
| available to pick | Backlog, or blank |
| claimed by an agent | In Progress |
| waiting on a pull request | In Review |
| waiting on an open blocked-by edge, or on something a person recorded | Blocked |
| owned by a person or a browser agent | Non-code |
| specced too thinly to start | Needs refinement |
| deliberately set aside | Parked |
| stopped part-way and needing a person | Needs attention |
| closed | Done |
| a permanent area epic, never picked, closed or moved | Area |

**The `Stage` field is required, with all ten options.** The pick pool is the open, unassigned issues whose `Stage` is blank or `Backlog`, read from the repository's issues, so an issue with no board card is still pickable. Preflight fails the run when the org has no `Stage` field or when it lacks an option. Creating the field is a manual step in the GitHub UI: org settings → *Planning* → *Issue fields*.

**Every issue sits under an area.** An area epic is an `Epic` at `Stage` `Area`: one permanent part of the product, such as Library or Listening, that is never closed. A `Feature` sits under an area, a `User Story` under a feature, and a `Bug` or `Chore` under a feature or directly under an area. Release notes are grouped by area, so each repository keeps its own area epics and every finished issue must resolve to one. [`references/area-epics.md`](references/area-epics.md) covers the hierarchy and how to move an existing project onto it.

**Boards are for people to look at.** Set each board view's "Column by" to `Stage` and the board shows every issue's state. GitHub's built-in "Auto-add to project" workflow and the scheduled `board-sync` job keep cards on boards; agents never move cards. A `## Project Board` section in `ClaudeProject.md` is optional and informational.

Where the plugin does allow a best-effort step, the rule is that **"best-effort" never means "skip a configured feature."** It applies to one case: **inherently idempotent cleanup** — deleting a claim ref that may already be gone, or removing a label that may not be present. The "failure" is a no-op, not a swallowed error.

When a feature **is** configured, its steps fail loudly: a field, label, or milestone operation that errors is reported to the user, never swallowed. The workflow continues past the failed step, but the failure is surfaced.

Approval is structural too. A person approves work by setting its stage to `Backlog` or leaving it blank, and withholds approval by setting `Needs refinement` or `Parked`. There is no `claude-ready` label and no gate setting to turn on.

## Auto-merge

Both entry points can merge a pull request, and **one setting decides whether either of them does**: `Auto-Merge on Approval` in `docs/review.config.md`. It is `disabled` unless you turn it on, including when the file does not exist at all.

| Setting | `/synergy:execute` ends at | `/synergy:pr-review` ends at |
| ------- | ---------------------------------- | -------------------------------------- |
| `disabled` (default) | An approved PR, reviewed and waiting for you | An approved PR |
| `enabled` | A merged PR, with its issues closed and set to Done | A merged PR |

Keeping it to one switch is deliberate. The alternative — merging by default from `execute` and only on request from `pr-review` — means the answer to "is this repository going to merge something without me" depends on which command happened to reach the PR, which is not a property anyone can hold in their head. Turn it on in `/synergy:setup`, which also runs the hardening step that makes "merge only after CI passes" actually enforceable.

Two ways to suppress a merge on a project that has it on: pass `--no-merge` for a single `execute` run, or leave the PR at a non-approved verdict. And several conditions stop a merge on their own — a red quality gate, a possible duplicate PR, a review that could not run independently, a moved head SHA, absent or red CI. Each of those leaves the PR open with a comment saying why.

## Where it writes

The plugin posts only to GitHub. A hook checks every shell and MCP tool call before it runs, and anything that would write to Azure DevOps, GitLab or Bitbucket asks you first. `verify-feature` and a local review return their report in the chat. At the start of each session and each subagent, another hook reads the repository's remote and tells Claude whether it is on GitHub, Azure DevOps, GitLab or Bitbucket, so it does not use `gh` in a repository that is not on GitHub.

To limit GitHub writes to your own organisations, create `~/.claude/synergy/github-allowlist.json` on your machine:

```json
{ "account": "your-github-login", "owners": ["your-org"] }
```

With it in place, a push, pull request, issue, comment, label, merge or other GitHub write is blocked outright when it targets an owner not listed, including your personal account unless you list it, or when `gh` is signed in as a different account. A write the hook cannot judge, such as a push whose destination it cannot work out, is blocked too. Reading and cloning anywhere still work. The list is personal: never commit it to a repository, and each developer keeps their own. Without the file nothing is restricted.

## Agents

| Agent         | Role                          | Constraint             |
| ------------- | ----------------------------- | ---------------------- |
| **Builder**   | Implements stories end-to-end | Scoped allowlist (see `agents/builder.md`) |
| **Reviewer**  | Validates PRs against issues  | Fixes and merges in full mode; read-only when `execute` or `bulk-execute` spawns it for an independent review |

Each agent follows least privilege — only the tools it needs. The builder is the default agent when the plugin is active.

Each agent's tool allowlist is scoped to the GitHub workflow (specific `gh` and `git` operations, issue field writes). A local `build` run uses no agent of its own.

## Skills

The plugin bundles the following skills. The orchestrators (`execute`, `bulk-execute`, `pr-review`, `build`) drive the workflow; the rest are invoked by them or directly.

| Skill                 | What it does                                       |
| --------------------- | ------------------------------------------------- |
| `execute`             | Orchestrator: pick → build → PR → review → merge   |
| `bulk-execute`        | The same loop for the stories that fill an effort budget, as at most two PRs |
| `code-architect`      | Architecture design and audit (SOLID + Clean)     |
| `build`               | Orchestrator for local work: plan → build → verify → commit, no issue or PR |
| `pr-review`           | Deep PR review, labels, optional auto-merge; also reviews a local change, with a React Native checklist |
| `verify-feature`      | A report to read before merging: what a branch or PR touches, concerns, nitpicks, acceptance criteria. Changes nothing |
| `spec-hardening`      | A report on a spec before it is built: what it misses, gets wrong or leaves open, checked against the codebase. Changes nothing |
| `preflight`           | Checks project-config health before a run; `wf preflight --fix` repairs what it safely can |
| `feature-discovery`   | Breaks features into stories; plans a new project's foundations |
| `grill`               | Stress-tests a plan or design by interviewing you |
| `user-story`          | Authors user stories                              |
| `writing-github-issues` | Standard for every issue title and body         |
| `user-facing-communication` | Standard for every reply the user reads    |
| `acceptance-criteria` | Authors acceptance criteria                       |
| `release-notes`       | Writes user and internal release notes, grouped by product area |
| `pr-body`             | Authors PR bodies to the fixed shape, or the component format where there is no `ClaudeProject.md` |
| `ecosystem-setup`     | Sets up companion tools, writes `ecosystem.md`    |
| `support-request`     | Support-request and incident write-ups            |
| `tone`                | Polishes correspondence in the user's voice       |

## Adapting for a new project

1. Install the plugin (see [Install](#install)).
2. Run `/synergy:setup` to generate config files.
3. Say "start the next story" or run `/synergy:execute`.

That's it. The plugin reads your config and adapts.

## Routine integration

Once installed, your scheduled task prompts become one-liners:

| Routine            | Prompt                                       |
| ------------------ | -------------------------------------------- |
| Work on next story | `Run /synergy:execute`               |
| Work through a related group | `Run /synergy:bulk-execute`  |
| Fix bugs           | `Run /synergy:execute --mode maintenance` |
| Audit codebase     | `Run /synergy:execute --mode audit`  |
| Review a PR, or apply review feedback | `Run /synergy:pr-review` |
