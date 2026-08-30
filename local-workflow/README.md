# local-workflow

A Claude Code plugin for project-agnostic local development. No GitHub
integration or platform dependencies required — install it on any
project and get structured coding, architecture design, code review,
user story writing, and more.

## Install

```bash
# From local path
claude --plugin-dir ./plugins/local-workflow

# Or install from marketplace once published
/plugin install local-workflow
```

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

## What's in the box

```
local-workflow/
├── .claude-plugin/
│   └── plugin.json            # Plugin manifest
├── skills/
│   ├── build/
│   │   └── SKILL.md           # Orchestrator: plan → build → verify → commit
│   ├── code-architect/
│   │   ├── SKILL.md           # Architecture planning (SOLID + Clean)
│   │   └── references/        # Book summaries and patterns
│   ├── structured-coding/
│   │   └── SKILL.md           # 5-step coding methodology
│   ├── code-review/
│   │   └── SKILL.md           # Deep code review and analysis
│   ├── feature-discovery/
│   │   └── SKILL.md           # Break features into stories + stress-test plans
│   ├── repo-scaffolding/
│   │   └── SKILL.md           # Repository structure and setup
│   ├── user-story/
│   │   └── SKILL.md           # User story writing
│   ├── acceptance-criteria/
│   │   └── SKILL.md           # Acceptance criteria generation
│   ├── pr-description/
│   │   └── SKILL.md           # PR body formatting
│   ├── tone/
│   │   └── SKILL.md           # Correspondence polishing
│   ├── user-facing-communication/
│   │   ├── SKILL.md           # Reply standard (outcome + state first)
│   │   └── references/        # Worked examples
│   ├── support-request/
│   │   └── SKILL.md           # Support documentation
│   ├── verify-feature/
│   │   └── SKILL.md           # Feature verification
│   ├── mobile-audit/
│   │   └── SKILL.md           # React Native / Expo audit
│   └── ecosystem-setup/
│       └── SKILL.md           # Set up companion tools, write ecosystem.md
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

### Documentation & communication

| Skill                  | What it does                                       |
| ---------------------- | -------------------------------------------------- |
| `user-story`           | Write structured user stories from rough notes     |
| `acceptance-criteria`  | Generate testable acceptance criteria              |
| `pr-description`       | Format PR bodies from diffs and context            |
| `tone`                 | Polish correspondence while preserving your voice  |
| `support-request`      | Document support tickets and investigations        |
| `user-facing-communication` | Shapes every reply you get: outcome and state first, then anything outstanding or assumed. Applies to every session through the plugin's `SessionStart` hook, not only when a command is running |

### Platform-specific

| Skill          | What it does                            |
| -------------- | --------------------------------------- |
| `mobile-audit` | React Native / Expo codebase audit      |

### Tooling & setup

| Skill             | What it does                                                  |
| ----------------- | ------------------------------------------------------------ |
| `ecosystem-setup` | Detect, install, and configure Claude Code companion tools (Graphify, RTK, ccusage, ecc-agentshield, Fallow) and write the `.claude/ecosystem.md` cheat-sheet that `build` and `code-review` read to use those tools automatically |

## Differences from github-workflow

This plugin is the counterpart to `github-workflow`. The key differences:

| Aspect            | local-workflow                     | github-workflow                        |
| ----------------- | ---------------------------------- | -------------------------------------- |
| GitHub required?  | No                                 | Yes                                    |
| Agents            | None (uses default)                | Builder, Reviewer, DocWriter           |
| Commands          | None (skill-driven)                | 8 commands (pick, start, finish, etc.) |
| Board integration | None                               | Project board updates                  |
| Unique skills     | tone, user-story, acceptance-criteria, pr-description, support-request, verify-feature, mobile-audit | code-review (GitHub-specific), setup |

Both plugins share a set of core skills (the full list is in
`_shared-skills/MANIFEST.md`) — among them `code-architect`,
`structured-coding`, `feature-discovery`, `repo-scaffolding`,
and `ecosystem-setup`. In `github-workflow`, `ecosystem-setup` also backs
the `setup` wizard's ecosystem step; here it is invoked on its own.

Because local-workflow has no setup wizard or preflight check, `build`
serves as the onboarding entry point for companion tools: the first time
you build in a project that has not opted into *or* out of the tools, it
surfaces a single optional, non-blocking tip pointing at
`/local-workflow:ecosystem-setup`. Run that once to enable the tools (it
writes `.claude/ecosystem.md`), or decline (it writes
`.claude/ecosystem-declined`) — either way the tip goes quiet for good.
