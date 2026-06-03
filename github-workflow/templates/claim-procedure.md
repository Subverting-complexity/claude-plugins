# Atomic claim procedure

Single, canonical way to claim a work item for exclusive work and to
release it again. The item is usually an **issue** (story work) but the
same procedure claims a **pull request** for review. Referenced by every
command that takes or relinquishes ownership: `pick-story`,
`start-story`, `block-story`, `finish-story`, the `execute` skill's
Phase 1 / Phase 2, and the `code-review` skill's PR claim. **Do not
inline a different claim mechanism anywhere** — call this
procedure so all call sites behave identically.

## Target and ref name

`{target}` is `issue-{number}` when claiming an issue, or `pr-{number}`
when claiming a pull request for review. The claim ref is always
`refs/claims/{target}`. Everything below is identical for both; only the
**human-visible marker** in Acquire step 4 differs (assignment for
issues, the `reviewing` state label for PRs).

## Why assignment is not a lock

The old lock used idempotent set-insertion (`gh issue edit --add-assignee
@me`, optionally a `reviewing` label) plus a short wait and a read-back of
"am I the only assignee?". This **cannot** exclude two agents that share
one GitHub identity — the normal case when one developer runs several
agents at once. `@me` resolves to the same login for both, so "only
assignee" is true for both, and a shared boolean label reads present for
both. GitHub offers no atomic compare-and-swap on assignees or labels, so
the pattern is unfixable as designed.

Git refs **do** offer a server-side compare-and-swap. Creating a ref that
does not yet exist is atomic: the first push wins, a second push of a
*different* object to the now-existing ref is rejected as a
non-fast-forward. We use a per-issue ref under `refs/claims/` as the lock.

## The lock is ephemeral; ownership is durable

The claim ref protects **only the brief window between selecting a work
item and recording ownership** — the instant where two agents could both
think an unassigned issue is theirs. It is **not** the long-term record of
who owns the work. Durable ownership lives in the **human-visible
markers**:

- **Issue:** the assignment (`@me`) **plus** the `status-in-progress` /
  `status-parked` lifecycle label.
- **PR:** the open PR itself **plus** its review-state label
  (`reviewing` / `updating` / …).

Because `pick-story` / `execute` only ever select *unassigned* issues, an
assigned + labelled issue stays out of the pick pool **indefinitely** —
for days if a human parks it. This is the intended way to pause work and
resume later without a second agent producing a duplicate branch or PR:
the assignment + lifecycle label, not the claim ref, are what keep it
yours. Never treat the claim ref as the thing that prevents duplicate
pickup; the assignment + label do that. The ref only stops the
simultaneous-select race.

This is also why there is **no automatic expiry or background reaper**: a
session that legitimately runs for hours still holds a live claim, and
auto-deleting a ref by age could let a second agent claim an item that is
still being worked. An orphan left by a crashed or killed session is freed
**by hand**, deliberately, after confirming no live session holds it — see
**Reaping orphaned claims** below.

Inputs:

- `{number}` — the issue or PR being claimed or released.
- `{target}` — `issue-{number}` or `pr-{number}` (see above).
- `{org}` / `{repo}` from `ClaudeProject.md` `## Identity` (only needed
  for the human-visible marker in Acquire step 4).

---

## Acquire

Run this the moment a work item is selected, **before** assigning it,
branching, applying any state label, or touching the board. Acquiring is
the gate: if you do not win the claim, you perform **no** side effects.

### Step 1 — Re-entry check (already ours?)

If a previous step in this same flow already won the claim, it recorded
the winning object in `.claude/claim-{target}.sha`. Re-acquiring must be
a no-op, not a self-collision.

```
test -f .claude/claim-{target}.sha \
  && [ "$(cat .claude/claim-{target}.sha)" = "$(git ls-remote origin refs/claims/{target} | awk '{print $1}')" ] \
  && echo HELD
```

If this prints `HELD`, you already own the claim — skip to step 4 (the
marker is idempotent) and proceed. Otherwise continue to step 2.

### Step 2 — Atomic acquire

Build a **unique** claim object and push it to the claim ref. Uniqueness
is mandatory: pushing an object identical to one already on the ref is a
silent no-op success, which would let a loser believe it won. The tree
content is irrelevant — only the commit's uniqueness matters — so reuse
`HEAD^{tree}` and make the message unique:

```
CLAIM_SHA=$(git commit-tree HEAD^{tree} \
  -m "claim {target} $(date -u +%Y-%m-%dT%H:%M:%SZ) pid$$-$RANDOM")
git push origin "$CLAIM_SHA":refs/claims/{target}
echo "claim-exit=$?"
```

(`git commit-tree` needs a configured git identity — the same one commits
already require.)

### Step 3 — Interpret the result

- **`claim-exit=0`** → **you won the claim.** Record it so re-entry is
  idempotent, then continue to step 4:
  ```
  mkdir -p .claude
  echo "$CLAIM_SHA" > .claude/claim-{target}.sha
  ```
- **non-zero** → **another agent holds the claim.** Exit cleanly with
  **no side effects**: do not assign, do not apply a state label, do not
  create a branch, do not update the board, do not comment. In a pick or
  review loop, move on to the next candidate. Standalone, report
  "#{number} is already claimed by another agent — skipping." and stop.

### Step 4 — Human-visible marker

Now that the claim is yours, mark it where humans can see it. The marker
is target-specific:

- **Issue:** assign it **and** move it to the `status-in-progress`
  lifecycle label (resolved by purpose key via `default-labels.md`),
  removing whatever lifecycle label it had (`status-ready`,
  `status-parked`, `status-blocked`, …) so exactly one state is present.
  The assignment + this label are the **durable ownership record** that
  keeps the issue out of the pick pool even after the claim ref expires.
  ```
  gh issue edit {number} --repo {org}/{repo} --add-assignee @me \
    --remove-label "{previous_lifecycle_label}" --add-label "{status_in_progress_label}"
  ```
- **PR:** apply the `reviewing` state label (resolved by purpose key),
  removing the prior review-state label (e.g. `needs-review`) so exactly
  one state is present.
  ```
  gh pr edit {number} --repo {org}/{repo} \
    --remove-label "{needs_review_label}" --add-label "{reviewing_label}"
  ```

The claim ref is the **lock**; the assignment/label is the **durable
display + ownership signal** other skills filter on. No read-back of the
marker is required for exclusivity — the atomic push already proved that.
Verify the label took effect per `default-labels.md` (read-back, guarded
create-if-missing) so the issue is never left without a state label.

---

## Release

Run this when you relinquish the item: the PR is open (`finish-story`),
the story is blocked back to the backlog (`block-story`), or a PR
review has reached its verdict or failed (`code-review`). Releasing frees
the ref so the item can be claimed again and keeps `refs/claims/` bounded
to in-flight work.

```
git push origin :refs/claims/{target}
rm -f .claude/claim-{target}.sha
```

Idempotent: deleting a ref that is already gone fails harmlessly —
ignore the error. Releasing does **not** clear the human-visible marker;
callers that also want to return the item to the pool do their own
`--remove-assignee` / state-label removal as before.

**Always release on every exit.** A command that wins a claim must release
it on *all* exit paths — success, block, error, timeout, or budget/rate
abort — not just the happy path. There is no automatic reaper, so a skipped
Release leaks the ref until a human reaps it by hand (**Reaping orphaned
claims** below). Releasing on every exit is what keeps that manual recovery
rare.

---

## Lost-claim path

Whenever Acquire reports a non-zero exit (claim lost), the only correct
action is to stop touching the item. You have made no changes, so there
is nothing to undo. Never fall back to `--add-assignee` or the
`reviewing` label as a "soft" claim — that reintroduces the race this
procedure exists to remove.

---

## Reaping orphaned claims

A claim ref is normally released the instant a session no longer needs it
(PR opened, story blocked, review verdict recorded, or any **Exit
cleanup**). But a ref is server-side state with no owner-side timeout:
unlike the old assignment lock, it does **not** self-heal. If a session
is hard-killed, the machine reboots, or the process dies before its
release runs, the ref survives with no live owner. Every future Acquire
for that target then returns non-zero and the item silently drops out of
the pool — un-pickable (issues) or un-reviewable (PRs) until a human
frees it. This is the deliberate trade for atomicity: there is no
background reaper, so removing an orphan is a manual, intentional act.

This is rare (only an ungraceful exit causes it) but has no automatic
remedy, so the recovery is by hand. List in-flight claims and confirm one
is truly orphaned — its issue has no open session and no open PR, or its
PR review is plainly abandoned — before freeing it:

```
# List every active claim ref and the object each points at.
git ls-remote origin 'refs/claims/*'

# Cross-check: is the issue still being worked, or the PR still in review?
gh issue view {number} --repo {org}/{repo} --json assignees,state
gh pr list --repo {org}/{repo} --state open

# Once certain no live session holds it, delete the orphaned ref.
git push origin :refs/claims/issue-{number}   # or :refs/claims/pr-{number}
```

Deleting a ref that a live agent still holds would let a second agent
claim the same item — so only reap a ref you have confirmed is abandoned.
A freed item returns to the pool and the next Acquire wins it normally.
