# Bulk Execute — Phase 7 (Finish)

Read this at Phase 7 of the `bulk-execute` workflow: every story in the current group is built, gated and committed. It is `execute`'s Phase 7 done once for a group — one push, one pull request, one review — with the per-issue work repeated for each story.

Throughout, **"the set" means the current group's stories actually built**: the entries in `.claude/bulk-set.json` with this `group` whose `built` is `true`. Stories dropped along the way are already back in the backlog, and the other group's stories take no part in anything below.

## 1. Write the body

Write it to `.claude/pr-body.md` with the Write tool, never as a shell argument. A bulk pull request asks more of a reviewer than a single-story one, so it adds one section to the fixed shape in `skills/pr-body/SKILL.md` and keeps everything else the same. Use these headings, with these names, in this order, on every bulk pull request:

```markdown
## Summary

## Stories

## Changes

## Test plan
```

1. **`## Summary`** — two or three sentences on what the stories do, and on their shared thread when they have one; unlinked stories that fit one budget are said to be so. This is the paragraph that makes the diff readable, and it is the one most worth writing carefully.
2. **`## Stories`** — a table, each row giving the issue **number and title** together, plus one line on what it asked for. Never a bare list of numbers: a reader should not have to open three issues to find out what the pull request does.
3. **`## Changes`** — a `###` sub-section per story, in build order, saying what was implemented and which acceptance criteria it answers.
4. **`## Test plan`** — how to verify the change, with the per-story steps kept distinguishable so a tester can check each story separately.
5. **`Closes #N` lines** — at the very end of the body, one per built story, each on its own line and under no heading. **No story that was not built gets one**: a `Closes` line for a dropped or unfinished story closes it on merge with no code behind it, which is the worst outcome this workflow can produce. Read `.claude/bulk-set.json` rather than trusting memory here.
6. **`## Quality gate failed`** — only when `.claude/gate-failed.flag` exists (written in Phase 5). It is the one section that goes **above** `## Summary`. Give the last error output, and say which stories were built and which were released back to the backlog because of it.

Add no other top-level section, and write every paragraph on one line.

## 2. Push and open one real pull request (never a draft)

**Title.** Under 70 characters, naming what the set does as a whole rather than any one story: "Resolve labels by purpose key throughout the picker", not "Fix #41 and #43 and #47".

Repeat `--issue N` once per **built** story (`built` is `true` in `.claude/bulk-set.json`), and for no other:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pr-create --title "{title}" --body-file .claude/pr-body.md   --issue {number} --issue {number} ...
```

It pushes the branch, checks every built story for another open pull request that already closes it immediately before creating, puts a duplicate warning line at the top of the body for each one found, adds any missing `Closes #N` line, reads the body back and rewrites it once if it came back corrupt.

- **`ok`**, one line — `pr` and `url` are the new pull request. When `duplicates` is present, report each by story and PR, number and title. Do not pick a winner or close the other PR here; code review reconciles them. A duplicate against **any** story stops the Phase 10 merge for the whole pull request, because a bulk PR cannot be split.
- **`partial`** (exit 24) — the pull request exists but its body still fails the check (`problems`). Warn the user that it may need editing by hand, and carry on.
- **`error`** (exit 20) — the push or the create failed. No pull request exists; fix the cause and re-run.

## 3. Hand every story to review

One call, whatever the size of the set — repeat `--issue N` once per **built** story (the ones whose `built` is `true` in `.claude/bulk-set.json`):

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" handoff --pr {pr_number} \
  --issue {number} --issue {number} ...
```

Add `--gate-failed` when `.claude/gate-failed.flag` exists, which enters review as changes-requested rather than needs-review.

It takes the pull request's review claim first, so the set is never held by no lock between the build and the review, then labels the pull request with the review-state entry label once, then for **each** issue sets its `Stage` to `In Review` and releases its claim ref — so the per-story release that used to be its own step is done here. Finally it deletes `.claude/plan.md` and `label-cache.json`.

It **always exits 0**: once the pull request exists, none of this is a reason to stop. When everything landed it prints one line. Otherwise the full payload names what did not — `pr_labelled`, and per issue `stage_set`, a `stage_message` and `claim_released`. A failure on one issue does not affect the others; report what failed by issue number **and** title and carry on. The review matters more than a label.

Keep `.claude/bulk-set.json`: Phases 8 to 10 still read it for the story list, and **Exit cleanup** deletes it at the end of the run. Every issue stays assigned to @me through review.

## 4. Note what now exists

A line or two, as a **progress note rather than the run's final report**: the pull request by number **and** title plus its URL, every story it closes by number **and** title, any story that was dropped and why, and the labels applied. Do not summarise the work as though it were done, and do not end your turn here.

`skills/user-facing-communication/SKILL.md` governs how this reads. Be exact about state: the pull request is **open and not yet reviewed**. A dropped story is outstanding work, so say what it was and what would let it be picked up, rather than listing it as a detail among the labels.

## 5. Go to Phase 8 now

Read `skills/execute/references/review-and-merge.md` and follow it, in the same turn as step 4, with the substitutions listed in `SKILL.md`. Without asking the user, without waiting for CI, and without checking whether merging is switched on — that setting is read in Phase 10 and decides nothing here.

An open, unreviewed pull request is an unfinished run, and that is more true here than anywhere: this one holds several stories, so leaving it unreviewed strands all of them at once.
