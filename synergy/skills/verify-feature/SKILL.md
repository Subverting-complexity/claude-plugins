---
name: verify-feature
description: 'Report on a branch or PR before merging: a summary, a verdict, and each concern as a question. Changes nothing; any host. Trigger on "verify this feature" or "is this branch ready".'
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
  - Bash(git rev-parse *)
  - Bash(graphify *)
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

Follow `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. The comments under Concerns and Nitpicks are the exception: they are written to the author, and Step 4 decides how they read.

## Step 1 — Scope

**The change.** Set `head`, the ref under review, and `base_branch`, the branch it merges into:

- **A pull request number.** Run `gh pr view <n> --json title,body,baseRefName,headRefName,files` and `gh pr diff <n>`. Set `base_branch` to its `baseRefName`, and fetch its head so its files can be read: `git fetch --quiet origin pull/<n>/head`, then `head=$(git rev-parse FETCH_HEAD)`. On a repository not hosted on GitHub, review the branch the pull request comes from as a named branch, using `git` alone, never that platform's tools.
- **A named branch.** Set `target_branch` to its name.
- **No target.** Review the current branch. If `git status --porcelain` shows uncommitted changes, say once that the review does not include them.

Then compare against the remote base, so a stale local branch does not change the diff:

```sh
if [ -z "$base_branch" ]; then
  base_branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)
  base_branch=${base_branch#origin/}
  base_branch=${base_branch:-main}
fi
if git remote get-url origin >/dev/null 2>&1; then
  git fetch --quiet origin "$base_branch"; base="origin/$base_branch"
else
  base="$base_branch"
fi
if [ -z "$head" ]; then
  head=HEAD
  if [ -n "$target_branch" ]; then
    head="$target_branch"
    if git remote get-url origin >/dev/null 2>&1 && git fetch --quiet origin "$target_branch" 2>/dev/null; then
      head="origin/$target_branch"
    fi
  fi
fi
git log "$base".."$head" --oneline
git diff "$base"..."$head" --name-status
```

Use `$head` for every later read. When it is not the checked-out `HEAD`, read files with `git show "$head":<path>`, never from the working tree.

**What it is for.** If a story or issue is linked (`Closes`, `Fixes` or `Resolves #N` in the pull request body, or named by the person), read it with `gh issue view` and take its deliverable, acceptance criteria and boundaries as the baseline. Judge the criteria first, by `skills/_shared/judging-acceptance-criteria.md`, and verify against the full set. A criterion that would be a guess becomes a question for the author, such as "What should happen when the upload fails? The story does not say." Otherwise infer the purpose from the commits and files and say it first: "This branch appears to add X. Verifying against that; correct me if not."

## Step 2 — Read the change in its system

Follow section 1 of `skills/_shared/review-checklist.md`. Read beyond the diff: the whole function or class around each change, the code that feeds it and uses it, the other parts of the system that handle the same data, and the project documentation the change touches. Most problems sit where the diff meets code it does not show.

## Step 3 — Look for concerns

Work through section 2 of `skills/_shared/review-checklist.md`. Give most weight to what decides whether the code holds up over time: is it robust when a dependency fails, modular, free of duplication, and does it follow the patterns of the surrounding code? You cannot run the formatter, so report only deviations you can see. A deviation from a rule the repository states or enforces is a concern. A lone departure from the neighbours, or a whitespace-only one, is a nitpick.

Report only what would change the outcome if the author acted on it. Leave out matters of taste. A small, objective blemish not worth a comment goes under Nitpicks.

Then check every concern and nitpick again by section 3 of the checklist, before you write any of them. The person may post these comments as they stand, so a wrong one costs the author's time and the person's credibility.

## Step 4 — Write each concern as a comment

Each concern and each nitpick is a comment the person may post, as it stands, on the author's change. Write it the way one teammate asks another, never as an order. The author wrote the code and knows the codebase, so do not explain their own files, classes or settings to them.

1. **Open with a question or a request.** Ask how something is meant to work when the intent is unclear ("How will the SMS key get into Production?"). Ask for the change when the fix is clear ("Can we catch `TwilioException` here?"). Start a nitpick with "Nit:" and say it in one line ("Nit: `SmsDispatch` should go in its own file."). Name the exact parameter, method, field or setting in backticks.
2. **Add the reason only when the author cannot see it from the line.** One or two short sentences: what goes wrong for a person or a system if the code stays ("so the batch stops part way through, and a resend texts people twice"). If the code cannot confirm it, say so ("Looks like...", "if anything downstream reacts to ...").

Be as detailed as the point needs and no more. Most comments are one or two lines. Casual phrasing is fine: "Looks like this seeder only runs in dev." The plain-English style rules for replies (`skills/user-facing-communication/SKILL.md`) do not apply to these comments.

Prefer:

> How will the SMS Twilio key get into Production? Looks like this seeder only runs in dev.

Over:

> Remove the seeder, or tell me what it is for now. The app runs seeders only on a developer's machine. In Staging and Production, texting uses only the key that you add by hand.

Leave out everything the author can find without help:

- How the code came to be this way, and which earlier change introduced what.
- The list of files and lines the fix edits. The heading gives the one location that matters.
- How large the fix is: no line counts, no effort, no time.
- Pasted code, and a severity or category label.

Keep the uncertainty that is there. Stop once the question or the request is clear.

If there are concerns to present, read `skills/tone/SKILL.md` and apply it to them, so they read in the user's own voice.

## Step 5 — Report

Four sections in this order, each under its name in bold. Skip Concerns or Nitpicks when it has nothing in it rather than writing "none found".

**Summary.** One short paragraph on what the feature does, in terms a person outside the work understands. If the purpose was inferred, say so here.

**Verdict.** One line: ready to merge, or not ready yet, with the number of changes and of questions for the author. Then one sentence on the acceptance criteria: either all the others are met, or which are not. A criterion that is not met or only partly met is a concern, so do not list the criteria.

**Concerns.** What should change before the merge. Those that are wrong or break a consumer come first. Each one is the location on its own line, then the comment from Step 4 directly under it:

```
`infra/storage.bicep:91`
Can we turn on soft delete for containers? Right now a deleted `photos` container cannot be restored, so every photo would be lost.
```

**Nitpicks.** Small, objective blemishes, in the same format as a concern.

Write nothing after the nitpicks. Say each thing once: no list of what the change touches, no checklist of criteria, no closing list of next steps.

If nothing needs resolving, give the summary, say it is ready in one sentence and stop.
