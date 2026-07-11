# Resolving merge conflicts on a branch

A reusable procedure for resolving merge conflicts between a checked-out
**working branch** and an **incoming branch** (typically the branch being
merged in — e.g. a PR's base). Load it at the point of need; for example,
`references/auto-merge.md` step 2 loads it when a PR reports
`mergeable: CONFLICTING`. Nothing here is auto-merge-specific — the
caller supplies:

- `<working-branch>` — the branch currently checked out, whose intent
  must be preserved.
- `<incoming-branch>` — the branch whose changes must be brought in.

## Procedure

1. Bring the incoming branch in:
   ```bash
   git fetch origin <incoming-branch>
   git merge origin/<incoming-branch>
   ```
2. For each conflicted file, read **both** sides in full context (not
   just the conflict hunk) and resolve so the working branch's intent
   **and** the incoming change are both preserved.
3. Re-run the project quality gate locally to prove the resolution
   compiles and the tests pass.
4. Commit the resolution and push:
   ```bash
   git add -A && git commit -m "Resolve merge conflicts with <incoming-branch>"
   git push
   ```
5. Return the new `HEAD` SHA to the calling procedure — anything tracking
   a recorded SHA (e.g. a review footer) must be updated to it.

## Escalation — only when the resolution genuinely needs human judgment

When the two sides made incompatible product or design decisions and no
objectively correct merge exists: run `git merge --abort` and return to
the calling procedure **unresolved**, reporting which files conflicted
and why no correct resolution exists. Do not guess at the merge — the
caller decides what happens next (e.g. filing the conflict to the board).
