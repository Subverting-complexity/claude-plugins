---
description: 'Review the next open pull request end-to-end — find it, read the code in context, fix what can be fixed, post a structured review, and apply state labels. One PR per run, auto-selected. Trigger: "review a PR", "review the next PR", "check PRs", "run a review".'
argument-hint: '[--read-only] [--bypass-ci]'
---

# Review

One-shot entry point for reviewing the next open pull request. This is a
thin wrapper: it runs the `code-review` skill, which auto-selects the next
PR needing review (no PR number needed), reviews it in full codebase
context, fixes concrete issues, posts a structured comment, and applies
state labels.

**No extra input is required.** Do not ask the user which PR to review —
the skill picks the next one by priority (`needs-re-review` first, then
lowest number) and locks it. Review exactly one PR, then stop.

## What to do

Invoke the `code-review` skill now, passing through any arguments the user
supplied:

- **`--read-only`** → run the skill in read-only mode (evaluate and label,
  but make no edits, pushes, or merges). This is the mode the Reviewer
  agent uses.
- **`--bypass-ci`** → tell the skill to treat the CI gate in its auto-merge
  step as satisfied even if remote checks are red or absent. Use only when
  CI cannot run for reasons outside the PR (e.g. GitHub Actions billing). It
  never bypasses a merge conflict.
- **No arguments** → run the default full review (evaluate and fix).

The skill handles preflight, configuration, selection, claiming, the review
itself, and labelling. Report its result to the user as-is.
