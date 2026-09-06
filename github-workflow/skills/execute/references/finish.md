# Execute — Phase 7 (Finish)

Read this at Phase 7 of the `execute` workflow (quality gate passed, work committed); kept out of `SKILL.md` to keep the pick/plan/build window light.

## Phase 7 — Finish

1. **Push and duplicate-PR detection in parallel** (one tool-call batch — no ordering dependency):

   - Push the branch:
     ```
     git push -u origin HEAD
     ```
   - Check for a sibling open PR that already closes this issue on a different branch:
     ```bash
     bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" sibling-pr {number} --exclude-branch {branch}
     ```
     Exit 0 with `found: 0` is the expected answer; exit 20 means the
     lookup failed, so say so rather than reporting no duplicate.

   Wait for both before proceeding: the push must finish before Step 2's PR create; the sibling result optionally prepends a flag line to the PR body.

   Holding the issue claim through PR creation already serializes builders, so a sibling should never be found — this is the backstop for a sub-second race. `--exclude-branch` already drops your own PR, so anything returned is someone else's. If one is found, still create your PR in Step 2, but prepend:

   ```
   > ⚠ Possible duplicate of #{sibling_number} — both close #{number}. Pending reconciliation by code review, which keeps the better-implemented PR and closes the other.
   ```

   Report the duplicate to the user. Do not pick the winner or close the other PR here — that is code review's job.

   The lookup can go stale before PR creation: immediately before composing the body in Step 2, re-verify a found sibling with `gh pr view {sibling_number} --repo {org}/{repo} --json state --jq '.state'`; if it is no longer `OPEN`, drop the flag line and proceed normally.

2. Create a real PR (never a draft). Write the body to a file with the Write tool and pass `--body-file` — never `--body "..."`. The rule and the read-back check are in `templates/body-file-write.md`:

   ```
   gh pr create --repo {org}/{repo} --base {default-branch} --title "{title}" --body-file {tempfile}
   ```

   The body has the fixed shape in `skills/pr-body/SKILL.md`. Do not invent a different one per story:

   ```markdown
   ## Summary

   ## Changes

   ## Test plan
   ```

   - Title under 70 chars.
   - `## Summary` is two to four plain sentences on what was built and why, written so a reviewer who has not seen the issue can follow it.
   - `## Changes` is one bullet per change, each on its own single line, grouped under `###` sub-headings only when the story touched more than three areas.
   - `## Test plan` says how it was verified and which acceptance criteria that covers.
   - **Always** close the associated issue: each linked issue on its own line as `Closes #42`, at the very end of the body, under no heading. A story PR must never omit this.
   - Add no other top-level section, except `## Manual step` when finishing the story needs a person, and `## Quality gate failed` when the **gate-failed flag** is set (`test -f .claude/gate-failed.flag`, written in Phase 5), which goes above `## Summary` with the last error output.
   - Write every paragraph on one line. `templates/body-file-write.md` has the no-wrapping rule.

2b. Validate the PR body — read it back and apply the corruption test and retry in `templates/body-file-write.md` (**Validate** + **Retry**). For a PR body the test also requires a `Closes #N` line for every linked issue; if any is missing, add it via `gh pr edit --body-file` before proceeding.

3. **Hand the story to review** — labels, board and claim in one call:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" handoff --pr {pr_number} --issue {number}
   ```

   Repeat `--issue N` for every issue the PR closes. Add `--gate-failed` when `.claude/gate-failed.flag` exists, which enters review as changes-requested rather than needs-review — the PR is real work, but it is not ready to approve and the label has to say so.

   The command labels the PR `claude-authored` plus the review-state entry label, moves each issue from `status-in-progress` to `status-in-review`, moves its board item to In Review, releases the issue's claim ref, and deletes the session scratch files (`.claude/plan.md`, `preflight-passed.txt`, `label-cache.json`).

   It **always exits 0**, because none of these is a reason to stop once the PR exists. Read the payload instead: `pr_labelled`, and per issue `relabelled` and `board_moved` with a `board` reason. Report anything false — a board that did not move is worth a line, not a halt.

   Releasing the claim here is deliberate. The open PR plus the assignment are the ownership markers from this point on, so holding the ref longer only risks leaking it. The issue stays assigned to @me through review.

4. Note what now exists, in a line or two: the PR by number **and** title together (e.g. `#123 Add login button`, never the number alone) plus its URL, the linked issues (each by number **and** title), and the labels applied. A **progress note, not the run's final report** — do not summarise the work as though it were done, and do not end your turn on it.

   `skills/user-facing-communication/SKILL.md` governs how this reads, and the part that matters most here is being exact about state. The pull request is **open and not yet reviewed**. Say that. A note that reads like a finished run invites the user to treat it as one, which is the failure the next section describes.

5. **Go to Phase 8 now**: read `references/review-and-merge.md` and follow it, in the same turn as step 4. Without asking the user, without waiting for CI, and without checking whether merging is switched on — that setting is read in Phase 10 and decides nothing here.

## Why step 5 is the one that gets skipped

Steps 3 and 4 read like the end of a run: claim released, scratch files deleted, board on In Review, PR labelled `review-needs-review`. All four are housekeeping done early, and that label marks a PR **this run is about to review**, not one queued for someone else. The failure has happened — a run posts its Phase 7 summary, says the PR is waiting on code review and on CI, and offers to review and merge it if the user says the word. Nothing here asks for that. An open, unreviewed PR is an unfinished story: the run ends at Phase 10 or at an exit Phases 8 to 10 name, nowhere else.

**Do not review your own diff on the way there.** An earlier version did, and it was removed: this session wrote the code, so it shares every assumption the code was built on and cannot judge it, and anything it files duplicates what the Phase 8 agents file minutes later. Note the limit. The diff goes to a reviewer **you** spawn and its findings come back to **you**. Your judgement of the code is set aside, never your ownership of the run.
