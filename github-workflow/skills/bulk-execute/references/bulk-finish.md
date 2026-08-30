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
  closes it on a different branch, using the authoritative lookup in
  `templates/sibling-pr-lookup.md`.

Wait for all of them before continuing: the push must finish before step 2
creates the PR, and any sibling found changes the PR body.

Holding every story's claim through PR creation already serializes builders,
so a sibling should never be found. If one is, ignore any result whose
`headRefName` equals this branch (your own PR). Still create the pull
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

Write the body following `templates/body-file-write.md` (temp file plus
`--body-file`), then:

```
gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body-file {tempfile}
```

**Title.** Under 70 characters, naming what the set has in common rather
than any one story: "Resolve labels by purpose key throughout the picker",
not "Fix #41 and #43 and #47". A reader scanning the pull request list
should be able to tell what changed without opening it.

**Body.** A bulk pull request asks more of a reviewer than a single-story
one, so the body has to do more work. In this order:

1. **What this change is** — two or three sentences on the shared thread:
   what the stories have in common and why they are one change rather than
   three. This is the paragraph that makes the diff readable, and it is the
   one most worth writing carefully.
2. **The stories** — a table, each row giving the issue **number and
   title** together, plus one line on what it asked for. Never a bare list
   of numbers: a reader should not have to open three issues to find out
   what the pull request does.
3. **`Closes #N` lines** — one per built story, each on its own line. This
   is what settles the issues on merge, so it must be exact:
   - Every built story gets one. A missing line leaves that issue open
     after the merge, assigned and labelled `status-in-review`, with
     nothing left to pick it up.
   - **No story that was not built gets one.** A `Closes` line for a
     dropped or unfinished story closes it on merge with no code behind it,
     which is the worst outcome this workflow can produce. Read
     `.claude/bulk-set.json` rather than trusting memory here.
4. **What changed, per story** — a short section each, in build order,
   saying what was implemented and which acceptance criteria it answers.
5. **Test plan** — how to verify the change, with the per-story steps kept
   distinguishable so a tester can check each story separately.
6. **Quality Gate Failed** — only when `.claude/gate-failed.flag` exists
   (`test -f .claude/gate-failed.flag`, written in Phase 5). Prepend the
   section with the last error output, and say which stories were built and
   which were released back to the backlog because of it.

## 2b. Validate the body

Read the body back and apply the corruption test and retry in
`templates/body-file-write.md` (**Validate** + **Retry**). For a bulk pull
request the test has one extra requirement: **the set of `Closes #N` lines
must match the built stories exactly** — no missing line, and no extra one.
If it does not, fix it with `gh pr edit --body-file` before going on. Count
them; do not eyeball them.

## 3. Label the PR and move each issue

`execute`'s Phase 7 does this in one combined GraphQL mutation. The same
call works here, extended with one pair of label aliases and one board alias
per issue — `removeIssueLabel1` / `addIssueLabel1` / `moveBoard1`,
`removeIssueLabel2` / … — since GraphQL requires an alias per repeated
field. Read `skills/execute/references/finish.md` step 3 for the mutation,
its prerequisites (PR node ID, label node IDs, issue node IDs, board item
and column IDs), and the `-f 'name[]'=<id>` array-building rule, then repeat
the issue half of it per story.

What each story needs is what a single-story run needs:

- On the **pull request** (once): add `claude-authored` and the review-state
  entry label — `review-needs-review`, or `review-changes-requested` when
  `.claude/gate-failed.flag` exists.
- On **each built issue**: remove `status-in-progress`, add
  `status-in-review`.
- On **each built issue's board item**: move to the column paired with
  `status-in-review`, which is `col-in-review`.

Resolve the board and each issue's item ID per `templates/board-resolution.md`.
Label node IDs come from one `gh label list --repo {org}/{repo} --json
name,id --limit 1000` shared across every story — fetch it once, not per
issue. Create any missing label with the guarded create-if-missing pattern
in `templates/default-labels.md` (no `--force`).

**Fallback.** If the combined mutation fails — a stale cached label ID, or
simply too many aliases for comfort — fall back to per-issue calls, which
are slower but independently verifiable:

1. `gh pr edit {pr_number} --repo {org}/{repo} --add-label claude-authored
   --add-label {review-state-label}` (once).
2. For each built story: `gh issue edit {number} --repo {org}/{repo}
   --remove-label status-in-progress --add-label status-in-review`.
3. For each built story: the board move,
   `templates/board-resolution.md` Step 5 targeting `col-in-review`. Skip
   silently when no board is configured.

A failure on one issue does not abandon the others. Apply what you can,
report what failed by issue number and title, and carry on — the pull
request exists and the review matters more than a label.

## 4. Release every claim

The pull request plus the assignments are now the ownership markers, so the
claim refs are no longer needed. Release **one per story in the set**, not
just the lead — read `.claude/bulk-set.json` if the set is no longer in
context:

```
git push origin :refs/claims/issue-{number}     # once per story in the set
rm -f .claude/claim-issue-{number}.sha
```

Then delete the scratch files that have done their job:

```
rm -f .claude/plan.md .claude/preflight-passed.txt .claude/label-cache.json
```

Each claim-ref delete is idempotent — ignore an error if it is already gone.
Keep `.claude/bulk-set.json`: Phases 8 to 10 still read it for the story
list, and **Exit cleanup** deletes it at the end of the run. Every issue
stays assigned to @me through review.

## 5. Note what now exists

A line or two, as a **progress note rather than the run's final report**:
the pull request by number **and** title plus its URL, every story it closes
by number **and** title, any story that was dropped and why, and the labels
applied. Do not summarise the work as though it were done, and do not end
your turn here.

`skills/user-facing-communication/SKILL.md` governs how this reads. Be
exact about state: the pull request is **open and not yet reviewed**. A
dropped story is outstanding work, so say what it was and what would let
it be picked up, rather than listing it as a detail among the labels.

## 6. Go to Phase 8 now

Read `skills/execute/references/review-and-merge.md` and follow it, in the
same turn as step 5, with the substitutions listed in `SKILL.md`. Without
asking the user, without waiting for CI, and without checking whether
merging is switched on — that setting is read in Phase 10 and decides
nothing here.

An open, unreviewed pull request is an unfinished run, and that is more
true here than anywhere: this one holds several stories, so leaving it
unreviewed strands all of them at once.
