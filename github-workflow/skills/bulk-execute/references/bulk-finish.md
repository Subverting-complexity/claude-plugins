# Bulk Execute — Phase 7 (Finish)

Read this at Phase 7 of the `bulk-execute` workflow: every story in the set
is built, gated and committed. It is `execute`'s Phase 7 done once for a
set — one push, one pull request, one review — with the per-issue work
repeated for each story.

Throughout, **"the set" means the stories actually built**: the entries in
`.claude/bulk-set.json` whose `built` is `true`. Stories dropped along the
way are already back in the backlog and take no part in anything below.

## 1. Push, and check each story for a sibling pull request

Run these together in one tool-call batch — there is no ordering dependency
between them, and the checks are one per story:

- Push the branch:
  ```
  git push -u origin HEAD
  ```
- For **each** built story, check for an open pull request that already
  closes it on a different branch:
  ```bash
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" sibling-pr {number} --exclude-branch {branch}
  ```
  Exit 0 with `found: 0` is the expected answer; exit 20 means the lookup
  failed, so say so rather than reporting no duplicate.

Wait for all of them before continuing: the push must finish before step 2
creates the PR, and any sibling found changes the PR body.

Holding every story's claim through PR creation already serializes builders,
so a sibling should never be found. `--exclude-branch` already drops your
own PR, so anything returned is someone else's. Still create the pull
request, but prepend one line per affected story:

```
> ⚠ Possible duplicate of #{sibling_number} — both close #{story_number}. Pending reconciliation by code review, which keeps the better-implemented PR and closes the other.
```

Report each duplicate to the user. Do not pick a winner or close the other
PR here — that is code review's job. A duplicate against **any** story in
the set stops the Phase 10 merge for the whole pull request, because a
bulk PR cannot be split.

The lookup can go stale before the PR is created. Immediately before
composing the body, re-verify each found sibling with
`gh pr view {sibling_number} --repo {org}/{repo} --json state --jq '.state'`;
drop the flag line for any that is no longer `OPEN`.

## 2. Create one real pull request (never a draft)

Write the body to a file with the Write tool and pass `--body-file` —
never `--body "..."`. The rule and the read-back check are in
`templates/body-file-write.md`. Then:

```
gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body-file {tempfile}
```

**Title.** Under 70 characters, naming what the set has in common rather
than any one story: "Resolve labels by purpose key throughout the picker",
not "Fix #41 and #43 and #47". A reader scanning the pull request list
should be able to tell what changed without opening it.

**Body.** A bulk pull request asks more of a reviewer than a single-story
one, so it adds one section to the fixed shape in
`skills/pr-description/SKILL.md` and keeps everything else the same. Use
these headings, with these names, in this order, on every bulk pull
request:

```markdown
## Summary

## Stories

## Changes

## Test plan
```

1. **`## Summary`** — two or three sentences on the shared thread: what the
   stories have in common and why they are one change rather than three.
   This is the paragraph that makes the diff readable, and it is the one
   most worth writing carefully.
2. **`## Stories`** — a table, each row giving the issue **number and
   title** together, plus one line on what it asked for. Never a bare list
   of numbers: a reader should not have to open three issues to find out
   what the pull request does.
3. **`## Changes`** — a `###` sub-section per story, in build order, saying
   what was implemented and which acceptance criteria it answers.
4. **`## Test plan`** — how to verify the change, with the per-story steps
   kept distinguishable so a tester can check each story separately.
5. **`Closes #N` lines** — at the very end of the body, one per built
   story, each on its own line and under no heading. This is what settles
   the issues on merge, so it must be exact:
   - Every built story gets one. A missing line leaves that issue open
     after the merge, assigned and labelled `status-in-review`, with
     nothing left to pick it up.
   - **No story that was not built gets one.** A `Closes` line for a
     dropped or unfinished story closes it on merge with no code behind it,
     which is the worst outcome this workflow can produce. Read
     `.claude/bulk-set.json` rather than trusting memory here.
6. **`## Quality gate failed`** — only when `.claude/gate-failed.flag`
   exists (`test -f .claude/gate-failed.flag`, written in Phase 5). It is
   the one section that goes **above** `## Summary`. Give the last error
   output, and say which stories were built and which were released back to
   the backlog because of it.

Add no other top-level section, and write every paragraph on one line —
`templates/body-file-write.md` has the no-wrapping rule.

## 2b. Validate the body

Read the body back and apply the corruption test and retry in
`templates/body-file-write.md` (**Validate** + **Retry**). For a bulk pull
request the test has one extra requirement: **the set of `Closes #N` lines
must match the built stories exactly** — no missing line, and no extra one.
If it does not, fix it with `gh pr edit --body-file` before going on. Count
them; do not eyeball them.

## 3. Hand every story to review

One call, whatever the size of the set — repeat `--issue N` once per **built**
story (the ones whose `built` is `true` in `.claude/bulk-set.json`):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" handoff --pr {pr_number} \
  --issue {number} --issue {number} ...
```

Add `--gate-failed` when `.claude/gate-failed.flag` exists, which enters
review as changes-requested rather than needs-review.

It labels the pull request `claude-authored` plus the review-state entry
label once, then for **each** issue moves it from `status-in-progress` to
`status-in-review`, moves its board item to In Review, and releases its claim
ref — so the per-story release that used to be its own step is done here.
Finally it deletes `.claude/plan.md`, `preflight-passed.txt` and
`label-cache.json`.

It **always exits 0**: once the pull request exists, none of this is a reason
to stop. Read the payload instead — `pr_labelled`, and per issue
`relabelled`, `board_moved` and a `board` reason. A failure on one issue does
not affect the others; report what failed by issue number **and** title and
carry on. The review matters more than a label.

Keep `.claude/bulk-set.json`: Phases 8 to 10 still read it for the story
list, and **Exit cleanup** deletes it at the end of the run. Every issue
stays assigned to @me through review.

## 4. Note what now exists

A line or two, as a **progress note rather than the run's final report**:
the pull request by number **and** title plus its URL, every story it closes
by number **and** title, any story that was dropped and why, and the labels
applied. Do not summarise the work as though it were done, and do not end
your turn here.

`skills/user-facing-communication/SKILL.md` governs how this reads. Be
exact about state: the pull request is **open and not yet reviewed**. A
dropped story is outstanding work, so say what it was and what would let
it be picked up, rather than listing it as a detail among the labels.

## 5. Go to Phase 8 now

Read `skills/execute/references/review-and-merge.md` and follow it, in the
same turn as step 4, with the substitutions listed in `SKILL.md`. Without
asking the user, without waiting for CI, and without checking whether
merging is switched on — that setting is read in Phase 10 and decides
nothing here.

An open, unreviewed pull request is an unfinished run, and that is more
true here than anywhere: this one holds several stories, so leaving it
unreviewed strands all of them at once.
