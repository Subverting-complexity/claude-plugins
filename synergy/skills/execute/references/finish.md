# Execute — Phase 7 (Finish)

Read this at Phase 7 of the `execute` workflow (quality gate passed, work committed); kept out of `SKILL.md` to keep the pick/plan/build window light.

## Phase 7 — Finish

1. **Write the body** to `.claude/pr-body.md` with the Write tool, never as a shell argument. It has the fixed shape in `skills/pr-body/SKILL.md`, never one invented per story:

   ```markdown
   ## Summary

   ## Changes

   ## Test plan
   ```

   - `## Summary` is two to four plain sentences on what was built and why, for a reviewer who has not seen the issue. `## Changes` is one bullet per change, under `###` sub-headings only past three areas. `## Test plan` says how it was verified and which acceptance criteria that covers.
   - **Always** close the associated issue: each linked issue on its own line as `Closes #42`, at the very end of the body, under no heading.
   - Add no other top-level section, except `## Manual step` when finishing the story needs a person, and `## Quality gate failed` when `.claude/gate-failed.flag` exists (written in Phase 5), which goes above `## Summary` with the last error output.
   - Write every paragraph on one line.

2. **Push and open a real PR (never a draft)** in one call. Title under 70 characters:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" pr-create --title "{title}" --body-file .claude/pr-body.md --issue {number}
   ```

   It pushes the branch, checks for another open PR that already closes the issue immediately before creating, opens the PR with a duplicate warning line at the top when it finds one, adds any missing `Closes #N` line, reads the body back and rewrites it once if it came back corrupt.

   - **`ok`**, one line — `pr` and `url` are the new PR. When `duplicates` is present, another open PR closes the same issue: report it by number and title. Do not pick the winner or close the other PR here; code review reconciles them, and Phase 10 does not merge.
   - **`partial`** (exit 24) — the PR exists but its body still fails the check (`problems`). Warn the user that the body may need editing by hand, and carry on.
   - **`error`** (exit 20) — the push or the create failed, and `reason` says which. No PR exists; fix the cause and re-run. A re-run on a branch whose PR already exists checks that PR rather than opening a second.

3. **Hand the story to review** — labels, stage and claim in one call:

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" handoff --pr {pr_number} --issue {number}
   ```

   Repeat `--issue N` for every issue the PR closes. Add `--gate-failed` when `.claude/gate-failed.flag` exists, which enters review as changes-requested rather than needs-review — the PR is real work, but it is not ready to approve and the label has to say so.

   The command takes the PR's review claim (`refs/claims/pr-{pr_number}`), labels the PR with the review-state entry label, sets each issue's `Stage` to `In Review`, releases the issue's claim ref, and deletes `.claude/plan.md`. The review claim comes first, so the work is never held by no lock: a scheduled `/synergy:pr-review` run that fires before Phase 8 finds the PR claimed and moves on. A `pr_claimed` of `lost` in a full payload means another agent already holds the review, which Phase 8 step 1 handles.

   It **always exits 0**, because none of these is a reason to stop once the PR exists. When everything landed it prints one line and there is nothing more to read. Otherwise the full payload names what did not: `pr_claimed`, `pr_labelled`, and per issue `stage_set` with a `stage_message` and `claim_released`. Report anything false loudly ("Stage update failed: {reason}. Continuing.") — it is worth a line, not a halt, but it does mean the issue's state still says `In Progress`.

   Releasing the claim here is deliberate. The open PR plus the assignment are the ownership markers from this point on, so holding the ref longer only risks leaking it. The issue stays assigned to @me through review.

4. Note what now exists, in a line or two: the PR by number **and** title together (e.g. `#123 Add login button`, never the number alone) plus its URL, the linked issues (each by number **and** title), and the labels applied. A **progress note, not the run's final report** — do not summarise the work as though it were done, and do not end your turn on it.

   `skills/user-facing-communication/SKILL.md` governs how this reads, and the part that matters most here is being exact about state. The pull request is **open and not yet reviewed**. Say that. A note that reads like a finished run invites the user to treat it as one, which is the failure the next section describes.

5. **Go to Phase 8 now**: read `references/review-and-merge.md` and follow it, in the same turn as step 4. Without asking the user, without waiting for CI, and without checking whether merging is switched on — that setting is read in Phase 10 and decides nothing here.

Steps 3 and 4 read like the end of a run, and runs have stopped there, offering to review and merge if asked. The `needs-review` label marks a PR **this run is about to review**. The run ends at Phase 10 or at an exit Phases 8 to 10 name, nowhere else, and it never reviews its own diff on the way.
