---
description: 'Orientation and help. Trigger: "help", "how do I use this", "get started", "what can you do".'
---

# Guide

Help the user understand the plugin and figure out where to start.

**Plain-English output.** Anything you show the user should be plain and high-level for a reader who is not involved in this codebase: explain what a thing is rather than only naming it, keep it concise, and avoid the patterns in `../skills/_shared/banned-patterns.md`. Full standard: `../skills/_shared/wording-standard.md`.

Trigger: when the user asks "how do I use this", "how do I get started",
"what can you do", "help", or similar orientation questions.

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

> This plugin runs your entire GitHub development workflow — from picking
> a story off your backlog to opening a PR. But first we need to set up
> your project.
>
> Run `/github-workflow:setup` and I'll walk you through it. I'll
> auto-detect your repo, package manager, and board, then ask you a few
> questions about your labels and branch convention. Takes about 2 minutes.

**Config files exist but incomplete:**

> Your project is partially configured. I found `ClaudeProject.md` but
> it's missing some sections.
>
> Run `/github-workflow:setup` and I'll fill in the gaps without
> overwriting what you already have.

**Fully configured:**

> You're all set. Here's what I can do:
>
> **Daily workflow:**
>
> - "Start the next story" → I'll pick the highest priority issue from
>   your backlog, plan it, build it, test it, open a PR, have that PR
>   reviewed by separate agents in a fresh context, and apply what the
>   review asks for. Hands-free, start to finish.
> - **Merging is off until you ask for it.** By default a run ends at an
>   approved pull request and waits for you. Turn on `Auto-Merge on
>   Approval` in `docs/review.config.md` — via `/github-workflow:setup` —
>   and the same run merges it for you once the review approves. That one
>   setting also governs `/github-workflow:code-review`, so there is only
>   ever one answer to "will this merge on its own".
> - `/github-workflow:execute --no-merge` → Skip the merge for a single
>   run on a project that has it switched on.
> - `/github-workflow:execute 42` → Work on a specific issue.
> - `/github-workflow:execute --mode feature` → Pick only feature stories.
> - `/github-workflow:execute --mode maintenance` → Pick and fix the
>   next bug, security issue, architecture problem, or tech debt item.
>   (Shorthand: `--mode bug` also works.)
> - `/github-workflow:bulk-execute` → Build two to five **related**
>   stories as one change: one branch, one pull request, one review. It
>   reads the ready backlog, groups the stories that genuinely belong
>   together, and builds that group. Worth it when the stories touch the
>   same code, or when one is waiting on another; not worth it when they
>   are unrelated, because the pull request then gets hard to review.
> - `/github-workflow:bulk-execute 41 43 47` → Build exactly those
>   stories together, when you already know they belong in one change.
>
> **Review and audit:**
>
> - `/github-workflow:code-review` → Review the next open PR end-to-end
>   (finds it, claims it, reviews in full codebase context, auto-fixes
>   concrete issues, posts structured comment, applies state labels).
>   Also picks up PRs with changes requested and addresses the feedback
>   before re-reviewing.
> - `/github-workflow:execute --mode audit` → Audit the codebase and
>   create issues for anything found.
>
> **Issue management:**
>
> - `/github-workflow:report-issue` → File a bug, security, arch, or
>   debt issue.
> - `/github-workflow:block-story` → Mark the current story as blocked.
> - `/github-workflow:writing-github-issues` → Rewrite an existing issue
>   so it is short and easy to scan. Every command above already writes
>   issues to this standard, so you only need it by hand for issues that
>   came from somewhere else.
>
> **Faster, better-grounded runs (optional):**
>
> - `/github-workflow:setup ecosystem` → Turn on companion tools so the
>   workflow uses them automatically: a codebase knowledge graph
>   (Graphify) for graph-grounded planning and review, plus token, cost,
>   and config-security helpers. Fully skippable — decline and nothing
>   changes.
>
> Most people just say "start the next story" and let me handle it.

**No git repo or gh not authenticated:**

Flag the specific issue and explain how to fix it:

- No git repo → suggest `git init` and adding a remote
- gh not authenticated → suggest `gh auth login`

### 2. Offer next step

Always end with a concrete suggestion based on the state detected.
Don't just list options — recommend the one most likely to be useful
right now.
