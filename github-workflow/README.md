# github-workflow

A Claude Code plugin that provides an end-to-end GitHub development
workflow. Install it on any project and say "start the next story" —
the plugin handles picking, planning, building, testing, and opening a PR.

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
| `/github-workflow:execute`              | Pick next story, execute end-to-end      |
| `/github-workflow:execute 47`           | Execute story #47 directly               |
| `/github-workflow:execute --mode bug`   | Pick and fix the next bug/security issue |
| `/github-workflow:execute --mode audit` | Audit codebase, create issues (no code)  |
| `/github-workflow:pick-story`           | Select the next story from the backlog   |
| `/github-workflow:start-story`          | Assign, branch, board update             |
| `/github-workflow:finish-story`         | Push, PR, board update                   |
| `/github-workflow:block-story`          | Mark current story as blocked            |
| `/github-workflow:report-issue`         | Create a bug/arch/debt issue             |
| `/github-workflow:update-pr`            | Address review feedback and re-flag PR   |
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
├── skills/
│   ├── execute/
│   │   └── SKILL.md           # Orchestrator: full pick-to-PR workflow
│   ├── code-architect/
│   │   ├── SKILL.md           # Architecture planning (SOLID + Clean)
│   │   ├── references/        # Book summaries and patterns
│   │   ├── README.md
│   │   └── test-cases.md
│   ├── structured-coding/
│   │   └── SKILL.md           # 5-step coding methodology
│   ├── code-review/
│   │   ├── SKILL.md           # Deep code review and analysis
│   │   └── references/
│   ├── grill-me/
│   │   └── SKILL.md           # Stress-test plans with tough questions
│   ├── feature-discovery/
│   │   └── SKILL.md           # Break features into stories
│   └── repo-scaffolding/
│       └── SKILL.md           # Repository structure and setup
├── commands/
│   ├── pick-story.md          # Select next issue from backlog
│   ├── start-story.md         # Assign, set In Progress, branch
│   ├── finish-story.md        # Push, PR, set In Review
│   ├── block-story.md         # Handle blockers
│   ├── report-issue.md        # Create bug/arch/debt issues
│   ├── update-pr.md           # Address review feedback on a PR
│   ├── setup.md               # Interactive project onboarding
│   └── guide.md               # How to get started / orientation
├── agents/
│   ├── builder.md             # Full-access implementation agent
│   ├── reviewer.md            # Read-only PR review agent
│   └── doc-writer.md          # Docs-only documentation agent
├── references/
│   └── story-template.md      # Shared story issue template
├── templates/
│   ├── ClaudeProject.md       # Template for project configuration
│   └── CLAUDE.md              # Template for project rules
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

If you already have these files, the setup wizard detects them and
offers to fill in missing sections rather than overwrite.

### Prerequisites

The plugin reads two files from the host project:

**`ClaudeProject.md`** (required) — The single source of truth for all
project-specific values. Every command and the skill read this file.

Required sections: Identity, Package Manager, Quality Gate, Branch
Convention, Label Map, Story Template, Issue Prefixes.

Optional sections: Project Board, Reference Docs.

**`CLAUDE.md`** (required) — Project rules, build principles, and
session hygiene.

**`docs/review.config.md`** (optional) — Review label definitions,
non-compliance gates, and tech-stack review rules. Required by the
`code-review` skill. Generated automatically on first code-review run,
or during setup.

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
- Option IDs for each status value (Backlog, In Progress, In Review, Done, On Hold)

## Agents

| Agent         | Role                          | Constraint             |
| ------------- | ----------------------------- | ---------------------- |
| **Builder**   | Implements stories end-to-end | Full tool access       |
| **Reviewer**  | Validates PRs against issues  | Read-only, cannot edit |
| **DocWriter** | Updates documentation         | Restricted to `docs/`  |

Each agent follows least privilege — only the tools it needs.
The builder is the default agent when the plugin is active.

## Bundled skills

These skills are bundled with the plugin and used during execution:

| Skill                                | Phase            | What it does                               |
| ------------------------------------ | ---------------- | ------------------------------------------ |
| `/github-workflow:code-architect`    | Planning         | Architecture design using SOLID + Clean    |
| `/github-workflow:structured-coding` | Implementation   | Structured coding methodology              |
| `/github-workflow:code-review`       | Review / Audit   | Deep code review and analysis              |
| `/github-workflow:grill-me`          | Plan validation  | Stress-tests plans with tough questions    |
| `/github-workflow:feature-discovery` | Backlog creation | Breaks features into implementable stories |
| `/github-workflow:repo-scaffolding`  | Project setup    | Repository structure and scaffolding       |

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
| Fix bugs           | `Run /github-workflow:execute --mode bug`    |
| Audit codebase     | `Run /github-workflow:execute --mode audit`  |
| Review a PR        | `Run /github-workflow:code-review`           |
| Fix review feedback| `Run /github-workflow:update-pr`             |
