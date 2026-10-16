# Build — Independent review

Read this at Phase 6 of `SKILL.md`. A reviewer in a fresh context reads what this run committed, fixes what is wrong, and commits the fixes on the same branch. Nothing is pushed or posted: there is no pull request, no label and no status to set. Skip this phase only when the person asked for no review, or when the run committed nothing.

## Round 1

1. **Spawn one `synergy:Reviewer` agent, in the foreground, in this checkout.** Do not run it in the background and do not give it its own worktree: it must commit on your branch, and git refuses to check out a branch that another worktree holds. Change nothing in the tree while it runs.
2. **Give it this in the prompt:**
   - That it is in **local mode**, which its agent file defines: it fixes and commits on this branch, and never pushes, calls `gh` or posts anything.
   - The range `{start_sha}..HEAD` with its `git log --oneline` output, and the task or story text from Phase 1 with its acceptance criteria.
   - That it fixes every Blocking finding and Quick fix in its default severity rubric, and files nothing. A defect outside the range, or a question only a person can answer, comes back to you as a finding.
   - The files that were already dirty at Start clean, if any, which it must leave alone.
   - The quality gate from Phase 4, which must pass before it commits.
   - What to return: the verdict (`approved`, `changes-requested` or `needs-discussion`); each finding with its `file:line`, its bucket and whether it was fixed; the SHA of each commit it made; the gate result; and whether its fixes did any of the things in **When to re-review**.
3. If the harness does not offer plugin agents, use a general-purpose subagent and tell it to read `agents/reviewer.md` and work in local mode. If no subagent can be spawned at all, review the range yourself by `skills/pr-review/references/local-review.md`, and say in the report that the review was not independent.
4. If a reviewer, in either round, left changes uncommitted because the gate stayed red, work through Phase 4 on them once. If the gate still fails, discard only the reviewer's changes (`git restore` on its files) and report its findings as open.

## When to re-review

Spawn a second review only when the fixes changed or added logic, added a file, an interface or a dependency, changed behaviour a user or a caller would notice, fixed a security defect, or touched code outside the files the first review read. Quick fixes alone do not earn a second review, because the quality gate has already checked them.

## Round 2, then stop

Spawn one more agent the same way, pointed at the fix commits only. Ask whether the Blocking findings are resolved and whether the fixes broke anything. Do not start a third round. If Round 2 still returns `changes-requested`, keep the fixes it committed and report what is still open.

## What goes into the report

Phase 7 reports the review in two or three lines: the verdict, what was fixed and committed, and each open finding with its `file:line` and why it is open. Ask a `needs-discussion` finding as a plain question to the person. If the quality gate failed after the reviewer's fixes, say so first.
