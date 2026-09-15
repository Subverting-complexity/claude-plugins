---
description: 'Set up or configure a project for this plugin, harden auto-merge, set up companion tools, reap claims or audit issues.'
argument-hint: '[harden|ecosystem|reap|wf|issues]'
---

# Setup

Interactive onboarding wizard for configuring the github-workflow plugin.

**Output standard.** Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `../skills/_shared/wording-standard.md` for how it reads, `../skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `../skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

Each mode reads only its own steps. Read no other step file than the one the mode below names.

## 1. Verify prerequisites

Every mode starts here. Check the required shell tools are available.

**bash** (required, because every auto-run `!`-block in this plugin uses bash syntax): run `bash --version`. If bash is not found, stop and tell the user to install it. On Windows, [Git for Windows](https://git-scm.com) includes Git Bash; alternatively enable WSL.

**GitHub CLI** (required, because every workflow command uses `gh`): run `gh auth status`. If this fails, stop and tell the user to run `gh auth login` first.

## 2. Run the mode

A mode runs against an already-configured project and skips the full onboarding:

- If `$ARGUMENTS` is `harden` (or `auto-merge`): wire up or repair the CI and merge gate. Locate `docs/review.config.md` and `ClaudeProject.md`, then follow `templates/harden-auto-merge.md`.
- If `$ARGUMENTS` is `ecosystem`: install, update or add companion tools. Read `../skills/ecosystem-setup/SKILL.md` and follow it, rather than invoking the skill (it sets `disable-model-invocation`, so only a person can run it by name).
- If `$ARGUMENTS` is `reap`: free orphaned claim refs left behind when a story or PR is stuck and no agent will pick it up. Follow `references/setup-reap.md`.
- If `$ARGUMENTS` is `issues` (or `backlog`): audit and backfill open issues that carry no native type or no field values. Follow `references/setup-issues.md`.
- If `$ARGUMENTS` is `wf` (or `picker`): create, or repair with `--force`, the Python virtualenv the `wf` picker reuses. Follow `references/setup-wf.md`.

With no argument, run the full onboarding. Read `references/setup-onboarding.md` once and follow every step in order.
