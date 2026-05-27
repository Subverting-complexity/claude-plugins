# Project Rules

Read `ClaudeProject.md` for project-specific workflow settings
(org, repo, labels, quality gate, branch convention, board).

## General Rules

Code implementation only. Do not provision accounts, configure
third-party services, set up DNS, or perform manual infrastructure
steps. Flag those as requiring human action.

The **GitHub issue** is the source of truth for every story. Read the
issue body first. Only consult reference docs (listed in ClaudeProject.md)
for cross-cutting concerns not covered in the issue.

## Autonomous Execution

Execute the full story workflow end-to-end without pausing for
confirmation. Skills are planning aids — consume their output and
continue to implementation. Never stop to ask "Ready to implement?"

## Story Execution

Work on **one story at a time** in a **fresh session per story**.
Complete it (PR created) or mark it blocked before starting the next.

### Build Principles

- One responsibility per file.
- Domain must not import from infrastructure. Strict layer boundaries.
- Every module unit-testable in isolation. Inject dependencies.
- Search for existing utilities before creating new ones.
- Write tests alongside the code, not after.

### Chaining Stories

When a story depends on another unmerged story:

1. Build the dependency on its own branch from the default branch.
2. Branch the dependent story off the dependency branch.
3. Set the dependent PR's base to the dependency branch.
4. After merge, rebase onto the default branch and update the PR base.

## Bug and Issue Workflow

When a bug, architecture violation, or tech debt is found during
development:

- **Trivial and same scope**: Fix in the current PR.
- **Everything else**: Run `/github-workflow:report-issue` to create
  a GitHub issue. Never silently skip problems.
- **Blocks current story**: Fix it first on its own branch.

## Session Hygiene

- Start a **new session** for each story.
- When compacting, preserve: modified files list, current test status,
  story number, branch name, and any blockers found.
