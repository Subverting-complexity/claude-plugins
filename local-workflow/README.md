# local-workflow

A Claude Code plugin for project-agnostic local development. No GitHub
integration or platform dependencies required — install it on any
project and get structured coding, architecture design, code review,
user story writing, and more.

## Install

```bash
claude plugin marketplace add Subverting-complexity/claude-plugins
claude plugin install local-workflow@subverting-complexity
```

Run both from a normal shell, not inside a Claude Code session, then
restart the session so the skills and hooks load. Adding the marketplace
is a per-machine step you do once, ever.

## Prerequisites

`git` is the only tool required. There are no GitHub, platform, or
Python dependencies.

## Usage

| Command                                   | What it does                                  |
| ----------------------------------------- | --------------------------------------------- |
| `/local-workflow:build`                   | Plan and implement a task end-to-end, locally |
| `/local-workflow:code-architect`          | Architecture design, audit, or documentation  |
| `/local-workflow:structured-coding`       | 5-step structured coding methodology          |
| `/local-workflow:code-review`             | Deep code review and analysis                 |
| `/local-workflow:feature-discovery`       | Break features into stories + stress-test plans |
| `/local-workflow:repo-scaffolding`        | Scaffold a new repository                     |
| `/local-workflow:user-story`             | Write or format a single user story           |
| `/local-workflow:acceptance-criteria`     | Generate testable acceptance criteria         |
| `/local-workflow:pr-description`         | Format a PR body from changes                 |
| `/local-workflow:tone`                   | Polish correspondence in your voice           |
| `/local-workflow:user-facing-communication` | Rewrite a reply that is too long or unclear about what is finished |
| `/local-workflow:support-request`        | Document a support ticket or investigation    |
| `/local-workflow:verify-feature`         | Verify feature completeness and safety        |
| `/local-workflow:mobile-audit`           | React Native / Expo specific audit            |
| `/local-workflow:ecosystem-setup`        | Set up companion tools + write `.claude/ecosystem.md` |
| `/local-workflow:debugging`              | Reproduce, isolate, fix, and verify a bug     |
| `/local-workflow:security-audit`         | Security-focused codebase audit               |
| `/local-workflow:doc-writer`             | Write or update documentation                 |
| `/local-workflow:preflight`              | Check local git and project-config health     |

## What's in the box

```
local-workflow/
├── .claude-plugin/
│   └── plugin.json            # Plugin manifest
├── skills/                    # See "Skill categories" below
├── references/
│   └── story-template.md      # Shared story issue template
├── settings.json
└── README.md                  # This file
```

## Skill categories

### Planning & architecture

| Skill                | What it does                                       |
| -------------------- | -------------------------------------------------- |
| `code-architect`     | Design new codebases, audit existing, document architecture |
| `feature-discovery`  | Explore and decompose features, or stress-test plans |
| `repo-scaffolding`   | Scaffold a new repository from requirements        |

### Implementation

| Skill                | What it does                                      |
| -------------------- | ------------------------------------------------- |
| `build`              | End-to-end local task implementation              |
| `structured-coding`  | 5-step methodology: understand → plan → code      |
| `code-review`        | Deep review with correctness and style analysis   |
| `verify-feature`     | Verify containment, completeness, and blast radius |
| `debugging`          | Reproduce → hypothesise → isolate → fix → verify   |
| `security-audit`     | Dependency, secrets, OWASP Top 10, input validation |

### Documentation & communication

| Skill                  | What it does                                       |
| ---------------------- | -------------------------------------------------- |
| `user-story`           | Write structured user stories from rough notes     |
| `acceptance-criteria`  | Generate testable acceptance criteria              |
| `pr-description`       | Format PR bodies from diffs and context            |
| `tone`                 | Polish correspondence while preserving your voice  |
| `support-request`      | Document support tickets and investigations        |
| `doc-writer`           | READMEs, API docs, architecture and migration guides |
| `user-facing-communication` | Shapes every reply you get: outcome and state first, then anything outstanding or assumed. Applies to every session through the plugin's `SessionStart` hook, not only when a command is running |

### Platform-specific

| Skill          | What it does                            |
| -------------- | --------------------------------------- |
| `mobile-audit` | React Native / Expo codebase audit      |

### Tooling & setup

| Skill             | What it does                                                  |
| ----------------- | ------------------------------------------------------------ |
| `preflight`       | Check local git state and project config before a run |
| `ecosystem-setup` | Detect, install, and configure Claude Code companion tools (Graphify, RTK, ccusage, ecc-agentshield, Fallow) and write the `.claude/ecosystem.md` cheat-sheet that `build` and `code-review` read to use those tools automatically |

## Differences from github-workflow

This plugin is the counterpart to `github-workflow`. The key differences:

| Aspect            | local-workflow                     | github-workflow                        |
| ----------------- | ---------------------------------- | -------------------------------------- |
| GitHub required?  | No                                 | Yes                                    |
| Agents            | None (uses default)                | Builder, Reviewer, DocWriter           |
| Commands          | None (skill-driven)                | 4 (`setup`, `guide`, `report-issue`, `block-story`) |
| Board integration | None                               | Project board updates                  |
| Not in the other  | `build`, `mobile-audit`            | `execute`, `bulk-execute`, `writing-github-issues` |

`code-review` and `preflight` exist in both under the same name but are
different skills, not synced copies: this plugin reviews a diff and checks
local config, github-workflow manages a PR's whole lifecycle and validates
board, label and auth setup.

Everything else — fifteen skills, listed in `_shared-skills/MANIFEST.md` —
is shared and identical in both. In `github-workflow`, `ecosystem-setup`
also backs the `setup` wizard's ecosystem step; here it is invoked on its
own.

Because local-workflow has no setup wizard or preflight check, `build`
serves as the onboarding entry point for companion tools: the first time
you build in a project that has not opted into *or* out of the tools, it
surfaces a single optional, non-blocking tip pointing at
`/local-workflow:ecosystem-setup`. Run that once to enable the tools (it
writes `.claude/ecosystem.md`), or decline (it writes
`.claude/ecosystem-declined`) — either way the tip goes quiet for good.
