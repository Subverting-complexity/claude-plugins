# Project Rules

<!-- This file is yours — add whatever guidance you need for your project. -->
<!-- The sections below are suggestions from the github-workflow plugin.   -->
<!-- Edit, reorder, or remove anything that doesn't fit your workflow.     -->
<!--
The workflow itself only checks two things about this file (both
WARNING-level, never blocking): that it exists, and that it references
ClaudeProject.md so sessions discover the project settings. Everything
else is yours. Recommended sections, in rough priority order: General
Rules, Autonomous Execution, Story Execution (with Build Principles),
Bug/Security/Maintenance Workflow, Session Hygiene, and a Supplementary
Files table pointing at ClaudeProject.md and any project reference docs.
-->

## General Rules

Code implementation only. Do not provision accounts, configure
third-party services, set up DNS, or perform manual infrastructure
steps. Flag those as requiring human action.

The **GitHub issue** is the source of truth for every story. Read the
issue body first. Only consult reference docs for cross-cutting
concerns not covered in the issue.

## How Claude Reports Back

Every reply is written to the `user-facing-communication` standard the
plugin ships, and it applies whether or not a workflow command is
running. Assume the reader did not follow the session:

- Open with what was done and the current state. Be exact about which
  state it is. Implemented, committed, pushed, opened as a pull request,
  reviewed, merged and deployed are different things, and a run can stop
  at any of them.
- Put anything outstanding, blocked, or waiting on a person near the
  top, with the reason in plain English.
- Show any meaningful assumption or anything that could not be verified.
- Name every issue and pull request by number **and** title. A bare
  number is not enough.
- Leave out the investigation history, the file list, the test names and
  anything else whose only job is to show the work was thorough.

Ask for `user-facing-communication` directly when a reply is too long,
too technical, or unclear about what is actually finished.

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

## Bug, Security, and Maintenance Workflow

When a bug, security issue, architecture violation, or tech debt is found during
development:

- **Trivial and same scope**: Fix in the current PR.
- **Everything else**: Run `/github-workflow:report-issue` to create
  a GitHub issue. Never silently skip problems.
- **Blocks current story**: Fix it first on its own branch.

Every issue and pull request body this project writes follows one
standard, `_shared/body-standard.md`, through the entry point for the
thing being written: `writing-github-issues` for an issue,
`pr-body` for a pull request. Both mean the same body: open with
the actual problem or the actual change, use the standard section names
and only the sections that carry information, leave out the investigation
that found it, keep any uncertainty the source had, and write each
paragraph on **one unwrapped line**.

An issue that a person has to finish, because it needs a permission or an
approval no agent can give, is marked three ways together: `[Manual]` at
the front of the title, the `status-blocked` label, and a `## Manual step`
section saying what has to be done and why.

`/github-workflow:report-issue` and `/github-workflow:execute` apply all
of this for you. Ask for `writing-github-issues` or `pr-body`
directly when you want an existing issue or pull request rewritten.

## Session Hygiene

- Start a **new session** for each story.
- Target **~100k tokens per session**. One story, one session. Commit
  and push progress early so work survives session boundaries.
- If a story is too large for one session, implement the most important
  slice, open a PR for it, and create follow-up issues for the rest.
- When compacting, preserve: modified files list, current test status,
  story number, branch name, and any blockers found.

## Supplementary Files

These files provide context for specific workflows. You don't need to
read all of them every session — consult them when the topic is
relevant to what you're working on.

| File | When to consult |
| ---- | --------------- |
| `ClaudeProject.md` | Project identity, labels, quality gate, branch convention, board config. Read at the start of any workflow command. |
| `docs/review.config.md` | (Optional — created by setup step 7.) Review label definitions, non-compliance gates, tech-stack review rules. Read when performing or preparing for code review. |

Add your own reference docs to this table as needed — architecture
decisions, coding standards, API specs, etc. — so future sessions
know where to look.
