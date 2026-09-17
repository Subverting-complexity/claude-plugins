---
name: verify-feature
description: 'Report on a branch or PR before merging: what it touches, concerns, nitpicks, acceptance criteria. Changes nothing; any host. Trigger on "verify this feature" or "is this branch ready".'
arguments:
  - name: target
    description: 'Optional pull request number or branch name. Defaults to the current branch against its base.'
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(git diff *)
  - Bash(git log *)
  - Bash(git status *)
  - Bash(git show *)
  - Bash(git branch *)
  - Bash(git fetch *)
  - Bash(git symbolic-ref *)
  - Bash(git remote *)
  - Bash(gh pr view *)
  - Bash(gh pr diff *)
  - Bash(gh issue view *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(find *)
  - Bash(grep *)
  - Bash(rg *)
---

# Verify Feature

Read one feature, on a branch or in a pull request, and write the review a colleague would leave before it merges. **Change nothing**: no edits, commits, pushes, comments, labels or filed issues. The person reading the report decides what happens next.

**The report stays in this conversation.** Return it here and nowhere else: never post it as a comment, review or vote on a pull request, issue or work item, on GitHub or on any other platform, and never write it to a file unless the person asks. Do not remark on where the repository is hosted.

This is the review a person runs. The automated loop that fixes, labels and merges is `/synergy:pr-review`, and it is not this.

Read `CLAUDE.md` for project rules if it exists.

## Output standard

Everything a person reads follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear.

## Step 1 — Scope

**The change.** A pull request number: `gh pr view <n> --json title,body,baseRefName,headRefName,files` and `gh pr diff <n>`. On a repository hosted anywhere other than GitHub, review the branch that pull request comes from, with `git` alone and never that platform's own tools. Otherwise the named branch, or the current one, against the remote default branch, so a stale local `main` does not widen the diff:

```sh
default_branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)
default_branch=${default_branch#origin/}
default_branch=${default_branch:-main}
if git remote get-url origin >/dev/null 2>&1; then
  git fetch --quiet origin "$default_branch"; base="origin/$default_branch"
else
  base="$default_branch"
fi
git log "$base"..HEAD --oneline
git diff "$base"...HEAD --name-status
```

**What it is for.** When a story or issue is linked (`Closes #N` in the pull request body, or named by the person), read it with `gh issue view` and take its deliverable, acceptance criteria and stated boundaries as the baseline. Otherwise infer the purpose from the commits and files and say it before going on: "This branch appears to add X. Verifying against that; correct me if not."

## Step 2 — Map what it touches

For every changed file, read the whole file, the files it imports and the files that import it. For every changed or removed export, find each call site and read it, including implicit ones: reflection, serialisation, config and stored data. Note which consumers sit inside the feature and which sit outside it. Read the tests for the changed modules.

If `.claude/ecosystem.md` exists, use the tools it lists first (Graphify to trace connections, Fallow for unused exports and duplication). If it does not, work by hand and say nothing about tools.

## Step 3 — Look for concerns

- **Containment.** Changes unrelated to the purpose; shared utilities, base types or global config whose change reaches other features; new global side effects; exports nothing needs; bundled formatting or refactors.
- **Completeness.** Walk each acceptance criterion. Look for TODOs, placeholders, commented-out code and unreachable paths.
- **Correctness.** Trace each path with concrete values. Check zero, one, max, null, empty and negative values, concurrency, and what happens when a dependency fails. Injection, validation at boundaries, and secrets or personal data in code, logs or errors.
- **Duplication.** For each meaningful block of new logic, search for an existing equivalent by what it does (the endpoint, field, rule or error), not by its name, in shared utilities, base types, sibling features and the diff itself. Name the existing symbol, or say it is only a resemblance.
- **Complexity.** Judged against this codebase: deep nesting, a function doing several things or switched by a boolean, indirection with one implementation, generalisation for needs that do not exist.
- **Downstream and regressions.** Read removed lines as a diff. Changed signatures, behaviour or data shapes against every consumer; tests deleted, skipped or loosened; guards, retries or catches dropped from shared paths; changed defaults, flags, timeouts or limits; work added inside loops or hot paths.
- **Tests.** Every new path exercised, errors and boundaries included, with exact assertions. A bug fix has a regression test.

Report only what would change the outcome if the author acted on it. A matter of taste is left out; a small, objective blemish that is not worth a comment goes under Nitpicks.

## Step 4 — Write each concern as a comment

Each concern is a short comment to the person who wrote the code:

1. What the code does, naming the exact method, field or file in backticks, in one plain sentence.
2. What follows from that. If the code cannot confirm it, say it conditionally ("if anything downstream reacts to ...").
3. A real question where the answer depends on intent, or a concrete list of what is missing.

Keep the uncertainty that is there, ask questions rather than issue instructions when intent is unclear, do not paste code back, and stop once the point and the question are clear. Severity goes in the heading, never in the prose.

Only when there are concerns to present, read `skills/tone/SKILL.md` and apply it to them, so they read in the user's own voice.

## Step 5 — Report

In this order, skipping any section with nothing in it rather than writing "none found":

**Feature summary.** One paragraph: what the feature does, and whether it looks ready to merge, ready once named concerns are settled, or not ready. Answer "is this ready?" with yes, no or conditionally first.

**What it touches.** The parts of the system the change reaches, as a short list: each module, command, screen, endpoint or table, and which consumers outside the feature depend on it.

**Concerns.** Blocking first, then Worth resolving, each under a heading that carries the location and the severity:

```
#### `src/sync/SupportRequestSync.cs:42` (Blocking)
```

`Blocking` is wrong or breaks a consumer. `Worth resolving` should probably change before merge.

**Nitpicks.** One line each, kept apart from the concerns: `path:line` and what to change.

**Acceptance criteria.** For each criterion, from the story or from the inferred scope: met, not met or partly met, and what is missing in the last two cases.

**What to do next.** For each Blocking and Worth-resolving concern, in the order that unblocks the others: what to change, what breaks if it stays, and rough effort (trivial, small or medium). Where a concern ended in a question, the next step is the author's answer; repeat the question.

If nothing needs resolving, say so in one sentence and stop.
