# Atomic claim procedure

Single, canonical way to claim a work item for exclusive work and to
release it. The item is usually an **issue** (story work); the same
procedure claims a **pull request** for review. Referenced by every
command that takes or relinquishes ownership: `pick-story`, `start-story`,
`block-story`, `finish-story`, the `execute` skill's Phase 1 / Phase 2,
and the `code-review` skill's PR claim. **Do not inline a different claim
mechanism anywhere** — call this procedure so all call sites behave
identically.

`{target}` is `issue-{number}` (claiming an issue) or `pr-{number}`
(claiming a PR for review). The claim ref is always `refs/claims/{target}`.
Everything is identical for both; only the **human-visible marker** in
Acquire step 4 differs (assignment for issues, the `reviewing` label for
PRs). `{org}`/`{repo}` come from `ClaudeProject.md` `## Identity`.

## Invariants (the four rules this design rests on)

1. **The claim ref is the lock.** Creating the ref is an atomic
   compare-and-swap (first push wins, a different later object is rejected);
   it is the only thing that excludes two agents sharing one GitHub identity
   — assignment and labels cannot.
2. **The lock is ephemeral; ownership is durable.** Work stays out of the
   pick pool via the **human-visible marker** (issue: `@me` +
   `status-in-progress`/`status-parked`; PR: the open PR + its review-state
   label), not the ref — the picker only selects *unassigned* issues.
3. **Hold an issue claim across PR creation.** Release only *after*
   `gh pr create` succeeds (closes the create-time duplicate race in
   `execute` Phase 7 / `finish-story`; the `sibling-pr-lookup.md` guard then
   sees the live PR).
4. **No auto-expiry — always Release on every exit.** A skipped Release
   leaks the ref until a human reaps it.

Full reasoning and the manual orphan-reap one-liner live in
`templates/claim-procedure-rationale.md` (not read at runtime).

---

## Acquire

Run the moment a work item is selected, **before** assigning, branching,
applying any label, or touching the board. If you do not win the claim,
you perform **no** side effects.

**Step 1 — Re-entry check (already ours?).** A prior step in this same
flow records its winning object in `.claude/claim-{target}.sha`;
re-acquiring must be a no-op, not a self-collision.

**First claim of the session — skip this step (no network probe).** When
`.claude/claim-{target}.sha` does **not** exist, there is no prior claim to
reconcile, so skip Step 1 entirely — do not run `git ls-remote` — and go
straight to Step 2. This is the common case (the first time you claim this
target), and it costs **zero** round trips. Only when the marker file
*exists* is the re-entry probe worth a network call:

```
test -f .claude/claim-{target}.sha \
  && [ "$(cat .claude/claim-{target}.sha)" = "$(git ls-remote origin refs/claims/{target} | sed 's/[[:space:]].*//')" ] \
  && echo HELD
```

Prints `HELD` → you already own it; skip to step 4 (the marker is
idempotent). Otherwise continue.

**Step 2 — Atomic acquire.** Push a **unique** claim object to the ref.
Uniqueness is mandatory — pushing an object identical to one already on
the ref is a silent no-op success that would let a loser believe it won.
The tree is irrelevant; reuse `HEAD^{tree}` and make the message unique
(`git commit-tree` needs a configured git identity, same as commits):

```
CLAIM_SHA=$(git commit-tree HEAD^{tree} \
  -m "claim {target} $(date -u +%Y-%m-%dT%H:%M:%SZ) pid$$-$RANDOM")
git push origin "$CLAIM_SHA":refs/claims/{target}
echo "claim-exit=$?"
```

**Step 3 — Interpret.**

- **`claim-exit=0`** → **won.** Record it so re-entry is idempotent, then
  continue to step 4:
  ```
  mkdir -p .claude
  echo "$CLAIM_SHA" > .claude/claim-{target}.sha
  ```
- **non-zero** → **another agent holds it.** Exit cleanly with **no side
  effects** (no assign, label, branch, board, or comment). In a pick/review
  loop, move to the next candidate; standalone, report "#{number} is
  already claimed by another agent — skipping." and stop.

**Step 4 — Human-visible marker** (durable ownership; resolve label names
by purpose key from the in-context `ClaudeProject.md` label map — fall back
to `templates/default-labels.md` only for a purpose key the map omits):

- **Issue** — assign **and** move to `status-in-progress`, removing
  whatever lifecycle label it had so exactly one state is present:
  ```
  gh issue edit {number} --repo {org}/{repo} --add-assignee @me \
    --remove-label "{previous_lifecycle_label}" --add-label "{status_in_progress_label}"
  ```
- **PR** — apply `reviewing`, removing the prior review-state label:
  ```
  gh pr edit {number} --repo {org}/{repo} \
    --remove-label "{needs_review_label}" --add-label "{reviewing_label}"
  ```

No read-back is needed for *exclusivity* (the atomic push already proved
it). No read-back is needed for the **label** either: `gh ... edit
--add-label X` fails loudly (non-zero exit, "could not add label") when `X`
does not exist — it never silently drops the label — so the edit's own exit
status is the presence signal. Apply the contract:

- **Exit 0** → the label is set; done, no read-back.
- **Non-zero citing an unknown/missing label** → the label was never
  created at setup. Create it with the guarded create-if-missing pattern in
  `default-labels.md` (no `--force`), then retry the edit once. This is the
  only branch that reads, and only when a label had to be created — verify
  after create, not after every edit.

---

## Release

Run when you relinquish the item: PR open (`finish-story`), story blocked
back to the backlog (`block-story`), or a PR review reaching its verdict or
failing (`code-review`).

```
git push origin :refs/claims/{target}
rm -f .claude/claim-{target}.sha
```

Idempotent — deleting an already-gone ref fails harmlessly; ignore the
error. Release frees only the **lock**; it does not clear the
human-visible marker (callers that also return the item to the pool do
their own `--remove-assignee` / state-label removal).

**Release on every exit path** — success, block, error, timeout, or
budget/rate abort, per invariant 4. A crash or hard kill can still skip
this and orphan a ref; freeing that is manual (see the rationale file).

---

## Lost-claim path

Whenever Acquire returns non-zero, the only correct action is to stop
touching the item. You made no changes, so there is nothing to undo. Never
fall back to `--add-assignee` or the `reviewing` label as a "soft" claim —
that reintroduces the race this procedure exists to remove.
