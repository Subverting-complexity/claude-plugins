---
description: 'Block a GitHub story: set its Stage to Blocked and unassign it. Only when a story is explicitly being blocked.'
---

# Block Story

Mark the current story as blocked and record the reason.

**Output standard.** Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `../skills/_shared/wording-standard.md` for how it reads, `../skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `../skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

Requires: a story in progress with a known blocker.

## What "blocked" means

An issue is **blocked** when it cannot make progress because of something outside its own control: another unfinished issue, an external decision, missing access or credentials, or an upstream fix. Blocked is **not** "I gave up" and **not** "this needs more spec" — that second case is the `Needs refinement` stage, a different state.

A blocked issue has its `Stage` field set to **Blocked**, and that field is the whole of the state. The pool is the open, unassigned issues whose `Stage` is blank or `Backlog`, so a `Blocked` issue is out of it; there is no second record to apply, and nothing that can disagree with the field about whether an issue is blocked.

**How it becomes unblocked:**

- **Automatically** — when the blocker is another issue recorded as a native blocked-by edge, `wf unblock` reads the `Blocked` issues, finds every one of that issue's edges closed, sets its `Stage` to `Backlog`, and comments. That write is the release. A `Blocked` issue with no edge at all was set by a person and is never changed by the plugin, which is deliberate: most blocked issues are waiting on the world rather than on an issue.
- **Manually** — for non-issue blockers (a decision, access granted), a person sets `Stage` back to `Backlog` or clears it. That is the entire act: a blank or `Backlog` stage is what available means.

## Preflight

Before doing anything else:

```!
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" preflight-cached
```

`cached: true` — skip straight to Step 1. Otherwise invoke `/synergy:preflight` and proceed once it returns.

## Steps

### 1. Write the blocker comment

Write it to `.claude/block-body.md` with the Write tool (`templates/body-file-write.md`: a body always goes in a file). Say what the blocker is, what was attempted, what failed or is missing, and a suggested resolution if known. The blocker narrative stays in the comment; do not restate it in the issue body. If you edit the body for any other reason, the result has to satisfy `../skills/writing-github-issues/SKILL.md`.

### 2. Block it

One call, whichever kind of blocker it is:

```bash
# Another issue (repeat --blocked-by for every issue this one waits on)
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" block --issue {number} --body-file .claude/block-body.md --blocked-by {N}

# Something outside the tracker: a decision, access, an upstream fix
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" block --issue {number} --body-file .claude/block-body.md

# The work itself needs a person or a browser, so no code agent can do it
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" block --issue {number} --body-file .claude/block-body.md --non-code human
```

It posts the comment, then records the blocker where the tooling reads it:

- **`--blocked-by`** writes native blocked-by edges, the only thing that lets `wf unblock` release the issue when they close. They are the **complete set**: an edge the issue already carries that the list omits is removed, so name every issue this one waits on.
- **`--non-code human|browser`** sets `Ownership` to `Human` or `Browser agent`, adds the matching `[Manual] ` or `[Browser] ` title prefix, and sets the stage to `Non-code` rather than `Blocked`. An edge would hand the work back to a code agent when it closed; `Ownership` keeps it out of the pool for good.

Then it checks for an open pull request that already closes the issue, and only if there is none releases the claim, unassigns `@me` and sets the stage.

Read the result by `status`:

- **`ok`** (exit 0), one line — blocked, unassigned and released.
- **`has-pr`** (exit 11) — an open PR closes this story, so it was left assigned and in its stage: returning it to the pool would let another agent open a second PR for the same work. The comment was still posted. Tell the user the blocker belongs on that PR (push a fix, request changes, or close it), naming the PR by number and title, and stop.
- **`partial`** (exit 24) — `reason` names each step that did not land, such as an edge write refused or a stage write that failed. A failed stage write matters: the issue is still available and the next `pick` will offer it. Report it plainly.
- **`error`** (exit 20) — the issue or the open-PR check could not be read, so nothing was returned to the pool. Report it.

### 3. Reconcile the working tree to clean

There is no cross-session resume, so uncommitted work left in the worktree is stranded, and a dirty tree is never reaped (`docs/worktree-config.md`). Commit real partial work to the story branch and push it (`git push -u origin HEAD`); the pushed branch is what a future session builds on. Then discard the rest and re-check with `wf tree-clean --discard {path}` (or `--all`) until it prints `ok`, as **End clean** in `templates/worktree-hygiene.md` describes. Never `git stash`: the stash is shared across every worktree on the clone.

### 4. Report

Display what was blocked — naming the story by number **and** title together (e.g. `#42 Add login button`, never the number alone) — why, and which stage it now has. Suggest running `/synergy:execute` to continue with the next story.
