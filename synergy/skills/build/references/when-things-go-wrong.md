# Build — When things go wrong

Read this only if a phase is blocked or fails, or the run hits one of the cases below. **Start clean** and **Exit cleanup** are in `SKILL.md`.

**Blocked**: If any phase cannot proceed (missing dependency, unclear requirement, broken environment), tell the user what's blocking you and what information you need to continue. Then run the **Exit cleanup**: commit any real partial work worth keeping (do **not** `git stash` it — the stash is shared across worktrees, and there is no cross-session resume to pick it back up) or discard disposable noise, so the tree ends clean and the worktree can be reaped.

**Abandoning an approach**: If the current approach is wrong and pushing on would make the codebase worse, stop rather than force it. Restore the working tree to the Start clean baseline — discard only *your* session's changes (`git restore` / `git clean -fd` on files you touched), never the user's pre-existing edits. Then report what was attempted and why it was abandoned, so the next attempt starts from that knowledge instead of repeating it.

**Partial progress**: If only part of the work passes the quality gate, commit the passing part as its own atomic commit and leave the failing part out — discard it or note it, but never commit code that fails the gate. In the final report, list exactly what was committed and what remains, with enough detail that a fresh session can finish the job.

**Bug found**: If you discover an unrelated bug during development, note it in the final report. Do not fix it inline unless it is trivial and within the same scope.

**Task too large**: If the plan reveals the task exceeds one session's budget, implement the highest-priority slice, commit it, and report what remains. Do not attempt to complete everything in one session. Run the **Exit cleanup** after committing the slice so the tree ends clean — uncommitted remainder left in the worktree is stranded, not resumed.
