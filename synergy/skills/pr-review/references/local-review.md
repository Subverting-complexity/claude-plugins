# Local review

Review a change that has no pull request: uncommitted work, a branch, a commit, or named files. It needs no access to GitHub or any other hosting platform. It fixes concrete problems and reports tersely, in this conversation only: it posts nothing to any platform, and it does not remark on where the repository is hosted.

When the person wants a report to read rather than fixes ("verify this feature", "is this ready?", a review before merging, "don't change anything"), read `skills/verify-feature/SKILL.md` and follow it instead of this file.

Read `CLAUDE.md` for project rules if it exists. When the change is React Native or Expo code, also work through `references/react-native.md` in Steps 3 and 4.

## Step 1 — Scope

| The user says | Review |
|---------------|--------|
| "Review my changes", or no target | All uncommitted changes, staged and unstaged |
| "Review this branch" | The branch against its base |
| File paths | Those files in full |
| A commit or "the last commit" | That commit |
| "Everything since X" | X to `HEAD` |

For a branch, resolve the base from the remote so a stale local `main` does not widen the diff:

```sh
default_branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')
default_branch=${default_branch:-main}
if git remote get-url origin >/dev/null 2>&1; then
  git fetch --quiet origin "$default_branch"; base="origin/$default_branch"
else
  base="$default_branch"
fi
git log "$base"..HEAD --oneline
git diff "$base"...HEAD --name-status
```

**What the change is for.** When a story or issue is given, take its deliverable, acceptance criteria and stated boundaries as the baseline. Judge the criteria first, by `_shared/judging-acceptance-criteria.md`, and review against the full set, given and derived. A criterion that would be a guess comes back as a `needs-discussion` question. Otherwise infer the purpose from the commits and files, and say it before going on: "This branch appears to add X. Reviewing against that; correct me if not."

## Step 2 — Read in context

Follow section 1 of `_shared/review-checklist.md`: the whole function or class around each change, the code that feeds it and uses it, every call site, the other parts of the system that handle the same data, the tests, and the project documentation the change touches. Note which consumers sit inside the change and which sit outside it; that split drives Steps 3 and 4.

## Steps 3 and 4 — Correctness, fit and blast radius

Work through section 2 of `_shared/review-checklist.md`. Give most weight to what decides whether the code holds up over time: is it robust when a dependency fails, modular, free of duplication, and does it follow the patterns of the surrounding code?

Then check every finding again by section 3 of the checklist. Fix or report only the findings that survive it.

## Step 5 — Fix or report

Fix concrete, objective problems directly unless the user asked only for a report: logic and off-by-one errors, missing null checks that would crash, failures that are swallowed or leave work half done, missing tests for new paths, logic that duplicates an existing utility, dead code the change introduced, wrong types. Do not fix matters of taste. Flag anything that needs a design decision.

## Step 6 — Report

Follow `skills/user-facing-communication/SKILL.md` for the shape (verdict and current state first), `_shared/wording-standard.md` for the wording, and `_shared/banned-patterns.md`.

Report only what would change the outcome if acted on. Write each finding as a comment a colleague would leave on the change:

1. What the code does, naming the exact method, field or file, in one plain sentence.
2. What follows from that. If the code cannot confirm it, say it conditionally.
3. A real question where the answer depends on intent, or a concrete list of what is missing.

Keep genuine uncertainty. Do not paste code back. Put severity in the heading, not the prose:

```
#### `src/sync/SupportRequestSync.cs:42` (Blocking)
```

`Blocking` is wrong or breaks a consumer; `Worth resolving` should probably change first; `Note` is the author's call. Say whether each was fixed.

Then, only where they carry information:

- **Acceptance criteria:** met, not met or partly met for each, and what is missing.
- **What to do next:** for each Blocking and Worth-resolving finding, in the order that unblocks the others: what to change, what breaks if it stays, and rough effort (trivial, small, medium).

When asked "is this ready?", answer yes, no or conditionally first. If nothing needs resolving, say so in one sentence and stop.
