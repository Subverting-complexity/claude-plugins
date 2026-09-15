---
name: pr-review
description: 'Review a pull request (the next one needing review, or a number) or a local change (uncommitted work, a branch, a commit, "is this ready?"). Fixes concrete issues; for a PR posts the review and labels. --read-only evaluates only.'
arguments:
  - name: mode
    description: 'Review mode: full (default) — evaluate and fix; read-only — evaluate only, no edits or pushes'
  - name: pr
    description: 'Optional PR number. When given, that PR is reviewed and the picker is skipped — used by the execute skill Phase 8 and by any caller that already knows which PR it wants reviewed.'
  - name: bypass-ci
    description: 'When set, the CI gate in auto-merge (Step 11) is treated as satisfied even if remote checks are red or absent. Explicit, never default — use only when CI cannot run for reasons outside the PR (e.g. GitHub Actions billing).'
allowed-tools:
  - Read
  - Edit
  - Write
  - Glob
  - Grep
  - Bash(gh *)
  - Bash(git *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(find *)
  - Bash(grep *)
  - Bash(rg *)
  - Bash(npm *)
  - Bash(npx *)
  - Bash(pnpm *)
  - Bash(yarn *)
  - Bash(dotnet *)
  - Bash(python *)
  - Bash(pip *)
  - Bash(cargo *)
  - Bash(go *)
  - Bash(make *)
---

# PR Review

**Pull request or local change.** Review a pull request when a PR number is given, when asked to review PRs, from `execute` or `bulk-execute`, or from a scheduled routine: that is the workflow in `references/pr-workflow.md`. For anything else (uncommitted work, a branch with no PR, a commit, named files, "verify this feature", "is this ready?") follow `references/local-review.md` instead and do not read the pull request workflow; add `references/react-native.md` when the change is React Native or Expo code.

Pull requests are reviewed only on GitHub. On a repository hosted anywhere else (Azure DevOps, GitLab, Bitbucket), a request to review a pull request becomes a local review of its branch, and nothing is posted to that platform.

When the target is a pull request, read `references/pr-workflow.md` and follow it from the top. Either way, what you report back is shaped by `skills/user-facing-communication/SKILL.md`.
