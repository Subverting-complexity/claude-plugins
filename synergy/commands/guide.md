---
description: 'Orientation for the synergy plugin: its commands and where to start. Trigger on asking how to use synergy.'
---

# Guide

Help the user understand the plugin and figure out where to start.

**Output standard.** Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `../skills/_shared/wording-standard.md` for how it reads, `../skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `../skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

Trigger: when the user asks how to use synergy, how to get started with it, what it can do, or a similar orientation question about this plugin. A general "help" about something else is not this command.

## Project state (auto-detected)

```!
echo "--- Project files ---"
[ -f ClaudeProject.md ] && echo "ClaudeProject.md: found" || echo "ClaudeProject.md: missing"
[ -f CLAUDE.md ] && echo "CLAUDE.md: found" || echo "CLAUDE.md: missing"
echo ""
echo "--- Git remote ---"
git remote -v 2>/dev/null | head -2 || echo "No git remote configured"
echo ""
echo "--- GitHub CLI ---"
gh auth status 2>&1 | head -3
```

## Steps

### 1. Respond based on detected state

**No config files found:**

> This plugin runs your entire GitHub development workflow — from picking a story off your backlog to opening a PR. But first we need to set up your project.
>
> Run `/synergy:setup` and I'll walk you through it. I'll auto-detect your repo, package manager, and org issue fields, then ask you a few questions about your branch convention and quality gate. Takes about 2 minutes.

**Config files exist but incomplete:**

> Your project is partially configured. I found `ClaudeProject.md` but it's missing some sections.
>
> Run `/synergy:setup` and I'll fill in the gaps without overwriting what you already have.

**Fully configured:**

> You're all set. Here's what I can do:
>
> **Daily workflow:**
>
> - "Start the next story" → I'll pick the highest priority issue from your backlog, plan it, build it, test it, open a PR, have that PR reviewed by separate agents in a fresh context, and apply what the review asks for. Hands-free, start to finish.
> - **Merging is off until you ask for it.** By default a run ends at an approved pull request and waits for you. Turn on `Auto-Merge on Approval` in `docs/review.config.md` — via `/synergy:setup` — and the same run merges it for you once the review approves. That one setting also governs `/synergy:pr-review`, so there is only ever one answer to "will this merge on its own".
> - `/synergy:execute --no-merge` → Skip the merge for a single run on a project that has it switched on.
> - `/synergy:execute 42` → Work on a specific issue.
> - `/synergy:execute --mode feature` → Pick only feature stories.
> - `/synergy:execute --mode maintenance` → Pick and fix the next bug, security issue, architecture problem, or tech debt item. (Shorthand: `--mode bug` also works.)
> - `/synergy:bulk-execute` → Build the stories that fill an **effort budget** (Low 1, Medium 2, High 6, up to 7), linked or not and within one step of `Priority`, as at most two pull requests: feature and maintenance work never share one, and the first is merged before the second is built. Blockers are built first and independent stories can be built in parallel.
> - `/synergy:bulk-execute 41 43 47` → Build exactly those stories together, plus any open issue they wait on that can be built in the same run.
>
> **Local work (no issue, no pull request):**
>
> - "Build this" or `/synergy:build` → Plan, build, run the quality gate and commit on your machine. Nothing is posted anywhere.
> - "Is this ready?" or `/synergy:pr-review` on uncommitted work, a branch or a commit → Review a local change in the chat.
> - `/synergy:verify-feature` → Write the report a person reads before merging, in the chat only.
>
> **Review and audit:**
>
> - `/synergy:pr-review` → Review the next open PR end-to-end (finds it, claims it, reviews in full codebase context, auto-fixes concrete issues, posts structured comment, applies state labels). Also picks up PRs with changes requested and addresses the feedback before re-reviewing.
> - `/synergy:execute --mode audit` → Audit the codebase and create issues for anything found.
>
> **Issue management:**
>
> - `/synergy:report-issue` → File a bug, security, arch, or debt issue.
> - `/synergy:block-story` → Mark the current story as blocked.
> - `/synergy:writing-github-issues` → Rewrite an existing issue so it is short and easy to scan. Every command above already writes issues to this standard, so you only need it by hand for issues that came from somewhere else.
>
> **How replies are written:**
>
> - `/synergy:user-facing-communication` → The standard for everything the plugin says back to you: what was done and the current state first, then anything outstanding, blocked or assumed. It is on in every session automatically, so you only need to ask for it by name when you want an answer rewritten shorter or clearer.
>
> **Faster, better-grounded runs (optional):**
>
> - `/synergy:setup ecosystem` → Turn on companion tools so the workflow uses them automatically: a codebase knowledge graph (Graphify) for graph-grounded planning and review, plus token, cost, and config-security helpers. Fully skippable — decline and nothing changes.
>
> Most people just say "start the next story" and let me handle it.

**No git repo or gh not authenticated:**

Flag the specific issue and explain how to fix it:

- No git repo → suggest `git init` and adding a remote
- gh not authenticated → suggest `gh auth login`

### 2. Offer next step

Always end with a concrete suggestion based on the state detected. Don't just list options — recommend the one most likely to be useful right now.
