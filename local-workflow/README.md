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

## Usage

| Command                                   | What it does                                  |
| ----------------------------------------- | --------------------------------------------- |
| `/local-workflow:execute`                 | Plan and implement a task end-to-end          |
| `/local-workflow:code-architect`          | Architecture design, audit, or documentation  |
| `/local-workflow:structured-coding`       | 5-step structured coding methodology          |
| `/local-workflow:code-review`             | Deep code review and analysis                 |
| `/local-workflow:feature-discovery`       | Break a feature into implementable stories    |
| `/local-workflow:grill-me`               | Stress-test a plan with tough questions       |
| `/local-workflow:repo-scaffolding`        | Scaffold a new repository                     |
| `/local-workflow:user-story`             | Write or format a single user story           |
| `/local-workflow:acceptance-criteria`     | Generate testable acceptance criteria         |
| `/local-workflow:pr-description`         | Format a PR body from changes                 |
| `/local-workflow:tone`                   | Polish correspondence in your voice           |
| `/local-workflow:support-request`        | Document a support ticket or investigation    |
| `/local-workflow:verify-feature`         | Verify feature completeness and safety        |
| `/local-workflow:mobile-audit`           | React Native / Expo specific audit            |

## What's in the box

```
local-workflow/
├── .claude-plugin/
│   └── plugin.json            # Plugin manifest
├── skills/
│   ├── execute/
│   │   └── SKILL.md           # Orchestrator: plan → build → verify
│   ├── code-architect/
│   │   ├── SKILL.md           # Architecture planning (SOLID + Clean)
│   │   └── references/        # Book summaries and patterns
│   ├── structured-coding/
│   │   └── SKILL.md           # 5-step coding methodology
│   ├── code-review/
│   │   └── SKILL.md           # Deep code review and analysis
│   ├── feature-discovery/
│   │   └── SKILL.md           # Break features into stories
│   ├── grill-me/
│   │   └── SKILL.md           # Stress-test plans with tough questions
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
│   ├── support-request/
│   │   └── SKILL.md           # Support documentation
│   ├── verify-feature/
│   │   └── SKILL.md           # Feature verification
│   └── mobile-audit/
│       └── SKILL.md           # React Native / Expo audit
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
| `feature-discovery`  | Explore and decompose features into user stories   |
| `grill-me`           | Relentless stress-testing of plans and assumptions |
| `repo-scaffolding`   | Scaffold a new repository from requirements        |

### Implementation

| Skill                | What it does                                      |
| -------------------- | ------------------------------------------------- |
| `execute`            | End-to-end task implementation                    |
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

### Platform-specific

| Skill          | What it does                            |
| -------------- | --------------------------------------- |
| `mobile-audit` | React Native / Expo codebase audit      |

## Differences from github-workflow

This plugin is the counterpart to `github-workflow`. The key differences:

| Aspect            | local-workflow                     | github-workflow                        |
| ----------------- | ---------------------------------- | -------------------------------------- |
| GitHub required?  | No                                 | Yes                                    |
| Agents            | None (uses default)                | Builder, Reviewer, DocWriter           |
| Commands          | None (skill-driven)                | 8 commands (pick, start, finish, etc.) |
| Board integration | None                               | Project board updates                  |
| Unique skills     | tone, user-story, acceptance-criteria, pr-description, support-request, verify-feature, mobile-audit | code-review (GitHub-specific), setup |

Both plugins share 5 core skills: `code-architect`, `structured-coding`,
`feature-discovery`, `grill-me`, and `repo-scaffolding`.
