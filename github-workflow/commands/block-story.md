---
description: 'Mark the current story as blocked. Trigger: "blocked", "I''m stuck", "can''t continue", "blocked by a dependency".'
---

# Block Story

Mark the current story as blocked and record the reason.

**Output standard.** Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `../skills/_shared/wording-standard.md` for how it reads, `../skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `../skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

Requires: a story in progress with a known blocker.

## What "blocked" means

An issue is **blocked** when it cannot make progress because of something outside its own control: another unfinished issue, an external decision, missing access or credentials, or an upstream fix. Blocked is **not** "I gave up" and **not** "this needs more spec" — that second case is the Needs refinement column, a different state.

A blocked issue sits in the board's **Blocked** column, and that column is the whole of the state. The pool is the Backlog column, so a card that has left it is out of the pool; there is no second record to apply, and nothing that can disagree with the board about whether an issue is blocked.

**How it becomes unblocked:**

- **Automatically** — when the blocker is another issue recorded as a native blocked-by edge, `wf unblock` reads the Blocked column, finds every one of that issue's edges closed, moves the card to Backlog, and comments. The move is the release. An issue with no edge is never released this way, which is deliberate: most blocked issues are waiting on the world rather than on an issue.
- **Manually** — for non-issue blockers (a decision, access granted), a person drags the card back to Backlog. That is the entire act: being in Backlog is what available means.

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to verify project configuration. If it finds issues and the user chooses "Configure now", wait for setup to complete, then ask the user to re-run this command. Otherwise, proceed.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo` from Identity
- Project board settings

The board is not optional here: the block **is** a board move, so a project with no recorded board has nowhere to put the issue. If the Project Board section is missing, say so and stop rather than commenting on an issue that stays in the pool.

### 2. Comment the blocker

Post a comment — write it following `templates/body-file-write.md` (temp file + `--body-file`):

```
gh issue comment {number} --repo {org}/{repo} --body-file {tempfile}
```

The comment should include: the blocker reason, what was attempted, what failed or is missing, and a suggested resolution if known.

If the blocker is another issue, record it as a **native blocked-by edge** (Step 3 below). That edge is the only thing that lets `wf unblock` release the issue when `#N` closes; a sentence in the body does nothing.

Add the marker and nothing else. The blocker narrative stays in the comment, so do not restate it in the body, and leave the rest of the body as it is. If you are editing the body for any other reason, the result has to satisfy `../skills/writing-github-issues/SKILL.md`.

**Record the blocker where the tooling reads it.** The native blocked-by edge is the source of truth for auto-unblock and for selection. Nothing else records "why" in a structured field — the reason is prose, it belongs in the Step 2 comment, and a field holding a sentence is a field nothing can select on. Write a one-entry spec and apply it:

```bash
mkdir -p .claude
cat > .claude/block-spec.json <<'JSON'
{"issues": [{"number": {number}, "blocked_by": [{blocking issue numbers}]}]}
JSON
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply .claude/block-spec.json
```

`issue-apply` places the card as well as writing the edge, so Step 5's board move is a no-op after this — run it only when the blocker is **not** another issue and there is no spec to apply. Read the exit code: **0** applied it; **22** (`spec-invalid`) means the spec is wrong, so fix it; **24** (`partial`) means some of it landed, so report what did not.

Skip this step entirely when the blocker is not an issue: there is no edge to write, and Step 5 moves the card on its own.

### 3. Release the claim and unassign

**First, the open-PR guard.** Blocking returns the issue to the unassigned pool. If the story **already has an open PR**, that would let another agent pick it up and open a *second* PR for the same work. A story with a live PR is not "blocked from starting" — it is in review:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" sibling-pr {number}
```

Exit 0 with `found: 0` means no PR closes it. Exit 20 means the lookup failed — say so and stop rather than returning the issue to the pool on an unverified answer.

If an open PR closes this issue, **do not unassign and do not return the issue to the pool**. Tell the user the story has an open PR (#N) and that the blocker should be handled on the PR (push a fix, request changes via review, or close the PR) rather than by blocking the issue. Record the blocker comment (Step 2) if useful, then stop without unassigning. The assignment keeps the issue out of the pick pool so no duplicate PR is created.

Otherwise (no open PR), release the atomic claim ref so the issue can be claimed again, then remove the assignee so the issue returns to the unassigned pool and can be picked up by another agent or re-picked later:

```
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-release --issue {number}
gh issue edit {number} --repo {org}/{repo} --remove-assignee @me
```

The claim-ref delete is idempotent — ignore an error if the ref is already gone.

### 4. Move the card to the blocked lane

This is the block. There is no label to apply alongside it: the column an issue's card sits in **is** its state, and until the card leaves Backlog the issue is still in the pick pool.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" board-move {number} --column col-blocked
```

The command verifies the board's identity and resolves the column **before** it adds the card, so a column the board does not have costs one query and writes nothing. It **always exits 0** so a board problem never costs the run its work — but read `moved` and `reason`, and if the move did not happen say so plainly: the issue is still available and the next `pick` will offer it.

**Use `col-non-code` instead when the blocker is the work's own nature** — a browser console, or a person with a device. Blocked means an open edge and `wf unblock` releases it when that edge closes, which for non-code work would hand it to an agent that cannot do it. Set `Ownership` to `Browser agent` or `Human` at the same time, which is what keeps it out of the pool for good.

### 5. Reconcile the working tree to clean

Do **not** leave uncommitted work sitting in the worktree. There is no cross-session resume, so a worktree left dirty "for a later session to inspect" is never inspected — the work is stranded **and** the dirty tree blocks the harness from ever reaping the worktree (`docs/worktree-config.md`).

Run the **End clean** procedure in `templates/worktree-hygiene.md`:

- **Real partial work** worth keeping — commit it to the story branch and **push** it (`git push -u origin HEAD`) so it survives the worktree being reaped. The pushed branch, not local state, is what a future session can build on.
- **Disposable scratch / generated noise** — discard it.

Do **not** `git stash` — the stash is shared across every worktree on this clone, so shelving here can collide with another agent's work. End with `git status --porcelain` empty. Releasing the claim (above) returns the story to the backlog; reconciling the tree lets the worktree be reaped.

### 6. Report

Display what was blocked — naming the story by number **and** title together (e.g. `#42 Add login button`, never the number alone) — why, and which lane its card is now in. Suggest running `/github-workflow:execute` to continue with the next story.
