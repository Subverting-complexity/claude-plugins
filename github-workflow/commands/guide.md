---
description: 'Orientation and help. Trigger: "how do I use this", "what can you do", "help", "get started", "guide me", "what''s available", "walkthrough", "show capabilities", "tutorial".'
---

# Guide

Help the user understand the plugin and figure out where to start.

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
> - "Start the next story" → I'll pick one from your backlog, plan it,
>   build it, test it, and open a PR. All hands-free.
> - `/github-workflow:execute 42` → Work on a specific issue.
> - `/github-workflow:execute --mode bug` → Pick and fix the next bug.
>
> **Review and audit:**
>
> - `/github-workflow:code-review` → Review the next open PR end-to-end
>   (finds it, claims it, reviews in full codebase context, auto-fixes
>   concrete issues, posts structured comment, applies state labels).
> - `/github-workflow:update-pr` → Address review feedback on a PR
>   with changes requested, push fixes, flag for re-review.
> - `/github-workflow:execute --mode audit` → Audit the codebase and
>   create issues for anything found.
>
> **Issue management:**
>
> - `/github-workflow:report-issue` → File a bug, arch, or debt issue.
> - `/github-workflow:block-story` → Mark the current story as blocked.
>
> **Individual steps** (the execute skill runs these automatically, but
> you can also run them one at a time):
>
> - `/github-workflow:pick-story` → Just pick the next story.
> - `/github-workflow:start-story` → Assign, branch, board update.
> - `/github-workflow:finish-story` → Push, PR, board update.
>
> Most people just say "start the next story" and let me handle it.

**No git repo or gh not authenticated:**

Flag the specific issue and explain how to fix it:

- No git repo → suggest `git init` and adding a remote
- gh not authenticated → suggest `gh auth login`

### 3. Offer next step

Always end with a concrete suggestion based on the state detected.
Don't just list options — recommend the one most likely to be useful
right now.
