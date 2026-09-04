# Atomic claim — rationale & orphan recovery

Background and recovery notes for `wf`'s claim commands (`claim`,
`claim-release`, `claim-reap`). This
file is **maintainer documentation, not part of the runtime path** — the
procedure file carries the terse invariants it needs to execute. Read
this only when you need the *why*, or when reaping a stuck claim.

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

Because `execute` only ever selects *unassigned* issues, an
assigned + labelled issue stays out of the pick pool **indefinitely** —
for days if a human parks it. This is the intended way to pause work and
resume later without a second agent producing a duplicate branch or PR:
the assignment + lifecycle label, not the claim ref, are what keep it
yours. Never treat the claim ref as the thing that prevents duplicate
pickup; the assignment + label do that. The ref only stops the
simultaneous-select race.

## Load-bearing invariant: hold the issue claim across PR creation

For an **issue** claim there is one ordering rule the whole
duplicate-prevention design rests on: **the claim must stay held until
*after* the PR is created, and be released only once the PR exists.** This
is what closes the create-time race. While session A holds
`refs/claims/issue-N`, session B cannot acquire it; B can only proceed once
A releases — and A releases only after its PR is live, at which point B's
pre-start guard (`wf sibling-pr`) sees that PR and stops.
Reorder this — release before `gh pr create` — and two sessions could both
create a PR for the same issue. So `execute` Phase 7
creates the PR first and releases the claim afterward, never the reverse.

GitHub offers no atomic "create a PR only if none already closes this
issue" operation (a compare-and-swap cannot span issue state *and* PR
existence), so this invariant plus the pre-start guard make duplicates
practically impossible but not provably so. A sub-second
replication-lag window at the release/create boundary remains
theoretically open; the `code-review` skill's duplicate reconciliation
(Step 2b) is the convergence backstop that makes the system *self-healing*
rather than merely *unlikely* to duplicate.

This is also why there is **no automatic expiry or background reaper**: a
session that legitimately runs for hours still holds a live claim, and
auto-deleting a ref by age could let a second agent claim an item that is
still being worked. An orphan left by a crashed or killed session is freed
**by hand**, deliberately, after confirming no live session holds it — see
**Reaping orphaned claims** below.

## Reaping orphaned claims

A claim ref is normally released the instant a session no longer needs it
(PR opened, story blocked, review verdict recorded, or any **Exit
cleanup**). But a ref is server-side state with no owner-side timeout:
unlike the old assignment lock, it does **not** self-heal. If a session
is hard-killed, the machine reboots, or the process dies before its
release runs, the ref survives with no live owner. Every future Acquire
for that target then returns non-zero and the item silently drops out of
the pool — un-pickable (issues) or un-reviewable (PRs) until the ref is
freed.

**Automated reaper.** Run `/github-workflow:setup reap` to scan all
active claim refs, cross-check each against the corresponding issue or
PR's current state, and free any that no longer back live work. The
reaper applies a staleness threshold (default 4 hours) before touching
any ref, so a normally running session is never interrupted. It flags
claims that are old but still show an in-progress marker as "suspect" —
reporting the manual one-liner below — rather than auto-reaping them.

Run it ad-hoc when a story is stuck, or schedule it as a periodic
maintenance routine via `/schedule`.

**Manual recovery.** If the reaper flags a ref as suspect and you have
confirmed no session is actively using it, free it by hand:

```
# List every active claim ref and the object each points at.
git ls-remote origin 'refs/claims/*'

# Inspect a specific claim to see its age and which session created it.
git fetch origin refs/claims/issue-{number} && git log -1 FETCH_HEAD

# Cross-check: is the issue still being worked, or the PR still in review?
gh issue view {number} --repo {org}/{repo} --json assignees,state,labels
gh pr list --repo {org}/{repo} --state open

# Once certain no live session holds it, delete the orphaned ref.
git push origin :refs/claims/issue-{number}   # or :refs/claims/pr-{number}
```

Deleting a ref that a live agent still holds would let a second agent
claim the same item — so only reap a ref you have confirmed is abandoned.
A freed item returns to the pool and the next Acquire wins it normally.
