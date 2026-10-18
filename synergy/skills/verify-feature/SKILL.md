---
name: verify-feature
description: 'Report on a branch or PR before merging: a summary, a verdict, and each concern as a suggested fix. Changes nothing; any host. Trigger on "verify this feature" or "is this branch ready".'
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
  - Bash(bash *wf.sh jev *)
---

# Verify Feature

Read one feature, on a branch or in a pull request, and write the review a colleague would leave before it merges. **Change nothing**: no edits, commits, pushes, comments, labels or filed issues. The reader decides what happens next.

**The report stays in this conversation.** Never post it to a pull request, issue or work item on any platform, and never write it to a file unless asked. Do not remark on where the repository is hosted.

The automated loop that fixes, labels and merges is `/synergy:pr-review`, not this.

Read `CLAUDE.md` for project rules if it exists.

## Output standard

Follow `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear.

## Step 1 — Scope

**The change.** For a pull request number, run `gh pr view <n> --json title,body,baseRefName,headRefName,files` and `gh pr diff <n>`. On a repository not hosted on GitHub, review the branch the pull request comes from using `git` alone, never that platform's tools. Otherwise review the named or current branch against the remote default branch, so a stale local `main` does not widen the diff:

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

**What it is for.** If a story or issue is linked (`Closes #N` in the pull request body, or named by the person), read it with `gh issue view` and take its deliverable, acceptance criteria and boundaries as the baseline. Otherwise infer the purpose from the commits and files and say it first: "This branch appears to add X. Verifying against that; correct me if not."

## Step 2 — Map what it touches

- Read each changed file whole, the files it imports and the files that import it.
- For every changed or removed export, find and read each call site, including implicit ones: reflection, serialisation, config and stored data. Note which consumers sit inside the feature and which outside.
- Read the tests for the changed modules.
- Read the formatter and linter config, and one untouched neighbour of each new or heavily changed file, as the baseline for style and structure.

If `.claude/ecosystem.md` exists, use the tools it lists first (Graphify to trace connections, Fallow for unused exports and duplication). If it does not, work by hand and say nothing about tools.

## Step 3 — Look for concerns

- **Containment.** Changes unrelated to the purpose; edits to shared utilities, base types or global config that reach other features; new global side effects; unneeded exports; bundled formatting or refactors.
- **Completeness.** Each acceptance criterion; TODOs, placeholders, commented-out code, unreachable paths.
- **Correctness.** Trace each path with concrete values: zero, one, max, null, empty, negative. Concurrency, and what happens when a dependency fails. Injection, validation at boundaries, secrets or personal data in code, logs or errors.
- **Modularity.** Does each unit have one job and one reason to change? Look for logic in the wrong layer (a controller or screen doing domain work, domain code doing I/O), dependencies pointing the wrong way, new cycles, one module reaching into another's internals, and units that cannot be tested without their neighbours.
- **Extensibility.** Would the next case of the same kind (another type, provider, field or rule) mean editing existing code in several places? Look for type or string switches repeated across files, hard-coded lists and constants, and behaviour fixed in code where the codebase already uses config, a registry or an interface. Report it only where a second case already exists or the codebase already has the pattern. Never ask for an abstraction against a need that has not appeared.
- **Duplication.** For each meaningful block of new logic, search for an existing equivalent by what it does (the endpoint, field, rule or error), not by name, in shared utilities, base types, sibling features and the diff itself. Name the existing symbol, or say it is only a resemblance.
- **Complexity.** Judged against this codebase: deep nesting, a function doing several things or switched by a boolean, indirection with one implementation, generalisation for needs that do not exist.
- **Conventions.** Compare with the formatter and linter config, `CLAUDE.md` and the neighbouring code: naming, file placement, import order, error handling, logging, test layout, comment density. You cannot run the formatter, so report only deviations you can see. A deviation from a rule the repository states or enforces is a concern. A lone departure from the neighbours, or a whitespace-only one, is a nitpick.
- **Downstream and regressions.** Read removed lines as a diff. Changed signatures, behaviour or data shapes against every consumer; tests deleted, skipped or loosened; guards, retries or catches dropped from shared paths; changed defaults, flags, timeouts or limits; work added inside loops or hot paths.
- **Tests.** Every new path exercised, errors and boundaries included, with exact assertions. A bug fix has a regression test.

Report only what would change the outcome if the author acted on it. Leave out matters of taste. A small, objective blemish not worth a comment goes under Nitpicks.

## Step 4 — Write each concern as a comment

Each concern and each nitpick is a short comment to the author, written so that a junior developer on the team understands it without asking. It has two parts and nothing else:

1. **The suggested fix, as one instruction.** "Use the shared `teamGroupObjectId` for storage." Name the exact parameter, method, field or setting in backticks.
2. **The problem, in one to three sentences.** What the code does now, then what goes wrong for a person or a system if it stays. State the consequence in plain terms ("storage then gives access to the wrong group", "every photo is lost"), because that is the part the reader cannot work out from the diff. If the code cannot confirm the consequence, say so conditionally ("if anything downstream reacts to ...").

A nitpick often needs only the instruction and one short reason.

Leave out everything the author can find without help:

- How the code came to be this way, and which earlier change introduced what.
- The list of files and lines the fix edits. The heading gives the one location that matters.
- How large the fix is: no line counts, no effort, no time.
- Pasted code, and a severity or category label.

Suggest the fix when the story, the code or the docs settle what is right. A story that does not mention something has not excluded it, so suggest the fix and do not ask whether the gap was deliberate. Ask a question only when the right fix depends on an intent you cannot find, and then the question takes the place of the instruction.

Keep the uncertainty that is there. Stop once the fix and the problem are clear.

If there are concerns to present, read `skills/tone/SKILL.md` and apply it to them, so they read in the user's own voice.

## Step 5 — Report

Four sections in this order, each under its name in bold. Skip Concerns or Nitpicks when it has nothing in it rather than writing "none found".

**Summary.** One short paragraph on what the feature does, in terms a person outside the work understands. If the purpose was inferred, say so here.

**Verdict.** One line: ready to merge, or not ready yet, with the number of changes and of questions for the author. Then one sentence on the acceptance criteria: either all the others are met, or which are not. A criterion that is not met or only partly met is a concern, so do not list the criteria.

**Concerns.** What should change before the merge. Those that are wrong or break a consumer come first. Each one is the location on its own line, then the comment from Step 4 directly under it:

```
`infra/storage.bicep:91`
Turn on soft delete for containers. Deleted photos can be restored for 7 days, but a deleted `photos` container cannot. If someone deletes it, every photo is lost.
```

**Nitpicks.** Small, objective blemishes, in the same format as a concern.

Write nothing after the nitpicks. Say each thing once: no list of what the change touches, no checklist of criteria, no closing list of next steps.

If nothing needs resolving, give the summary, say it is ready in one sentence and stop.
