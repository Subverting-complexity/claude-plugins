---
description: 'Create a bug, security, architecture, or tech debt issue. Trigger: "report a bug", "report tech debt", "security issue", "create an issue".'
---

# Report Issue

Create a bug, security, architecture, or tech debt issue discovered during development.

**Issue wording.** The title and body you create here follow `../skills/writing-github-issues/SKILL.md`. Read it before writing the body. It is the standard for every issue this plugin files, and it is short: open with the actual problem, use `## Summary` plus only the sections that carry information, cut the investigation history, and keep any uncertainty the source had.

**Output standard.** Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `../skills/_shared/wording-standard.md` for how it reads, `../skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `../skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one. Inside the issue body the issue standard above governs structure and length; banned patterns still apply there in full.

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to verify project configuration. If it finds issues and the user chooses "Configure now", wait for setup to complete, then ask the user to re-run this command. Otherwise, proceed.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo` from Identity
- The field names under Issue Types & Fields

### 2. Classify the issue

Determine the type:

- **Bug** — Something is broken or behaves incorrectly
- **Security** — Vulnerability, insecure pattern, or missing protection
- **Architecture** — Layer violation, coupling, design problem
- **Tech Debt** — Working but needs improvement

### 3. Assess severity, size and owner

First decide what happens to the issue:

- **Blocks current story** → Create and fix first on its own branch
- **Same scope and trivial** → Fix inline in current PR
- **Everything else** → Create issue for later

Then settle the three field values every issue must carry. They are written in Step 5; decide them here.

- **`Priority`** — **Urgent** for a security hole, data loss or a crash on a core path; **High** for a broken feature, work this blocks, or a clear regression; **Medium** for incorrect behaviour with a workaround, or notable debt; **Low** for cosmetic work, minor cleanup or a nice-to-have. This is the whole of the pool's order, so an issue without it sorts to the back and is never picked.
- **`Effort`** — **Low** for a targeted fix in a few files, **Medium** for moderate scope with some investigation, **High** for broad impact, architectural change or significant unknowns.
- **`Ownership`** — **Code agent** unless the fix needs a browser (**Browser agent**) or a person (**Human**). This is what keeps work a code agent cannot finish out of the pool. When the report covers both kinds of work, file two issues rather than choosing one owner for both halves: `../skills/writing-github-issues/SKILL.md` → **Scope: one issue, one party**.

**No label carries any of this.** There is no priority label, no type label and no state label to choose — `wf issue-apply` writes the fields, sets the native issue type from `kind`, and places the card. The only label to pass is `claude-authored`, the provenance marker.

An issue too vague to implement without a refinement session is not filed into the pool: file it and move its card to `col-refinement`, which is what keeps it out.

### 4. Detect current milestone

If in sprint mode, find the current milestone so the new issue lands in the right sprint:

```
gh api repos/{org}/{repo}/milestones --jq 'map(select(.due_on != null)) | sort_by(.due_on) | .[] | select(.open_issues > 0) | .title' | head -1
```

Milestones without a due date are filtered out before sorting — `sort_by(.due_on)` misorders nulls. If open milestones exist but **all** lack due dates, sprint mode is not detected: say so explicitly ("open milestones found, but none has a due date — creating without a milestone") rather than silently skipping. If this returns nothing (that case, flat backlog mode, or no open milestones), the issue is created without a milestone — do **not** pass an empty `--milestone` flag, as `gh` rejects it.

### 4c. Resolve the repository's issue template

Follow `templates/issue-template-resolution.md` to find out whether the target repository publishes an issue template, either its own or one inherited from the organisation's `.github` repository. It is one cached GraphQL call.

If a template applies, the body you write in Step 5 uses **its** headings and order. If none does, which is the common case, use the standard's own sections. Either way this is best-effort: a lookup failure falls back to the standard sections and never blocks the issue.

If a template carries frontmatter labels, add them to the label list assembled in Step 3, minus any `type-*` label — the native type says that. Ignore any assignees it names, for the same reason Step 5 leaves the assignee blank.

### 5. Create the issue

One write, through `wf issue-apply`. It is the only path that creates an issue: it applies the title rules, the native issue type, the org's field values, the labels and the milestone together, so an issue filed here is shaped exactly like one filed by `feature-discovery` or `execute`.

Write the issue body to the standard in `../skills/writing-github-issues/SKILL.md` — which is also where the title rules live — to `.claude/report-body.md` with the Write tool, and the spec beside it (`templates/body-file-write.md` — a body always goes in a file, never into a shell argument or a JSON string):

```bash
mkdir -p .claude
cat > .claude/report-spec.json <<'JSON'
{"issues": [{"title": "{title}",
             "body_file": ".claude/report-body.md",
             "kind": "{bug|security|architecture|tech debt}",
             "milestone": "{current_milestone}",
             "labels": ["{priority_label}", "claude-authored"],
             "fields": {"field-priority": "{Urgent|High|Medium|Low}",
                        "field-effort": "{Low|Medium|High}",
                        "field-ownership": "{Code agent|Browser agent|Human}",
                        "field-origin": "Development"}}]}
JSON
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply .claude/report-spec.json
```

The body goes in a file and the spec names it (`body_file`) rather than carrying the text, because a body has backticks, `$`, quotes and blank lines in it and hand-building that into a JSON string is where bodies get mangled.

Drop the `milestone` key entirely in flat-backlog mode, or whenever Step 4 found no current milestone. It takes the milestone's title, and a title that names no **open** milestone fails the spec rather than filing the issue outside the sprint.

**The title carries no prefix**, with one exception. No `[BUG]`, `[SECURITY]`, `[ARCH]` or `[DEBT]`, no priority and no size. GitHub renders the issue type and the fields beside the title already. `wf issue-apply` strips such a prefix if one slips in, and reports that it did.

The exception is `[Manual]`, for an issue a person has to do (Step 3). It is kept, because nothing native says an issue needs a human.

**The labels carry no type, no priority and no state.** `kind` supplies the native issue type and the `Classification` value together, and the three required fields carry the rest. `wf issue-apply` drops any retired label in the list. Pass `claude-authored` and nothing else.

**You do not choose the lane.** `issue-apply` decides it from the issue's own state — `Ownership` first, then open dependency edges — and places the card itself. Non-code work goes to Non-code, an issue with an open edge to Blocked, everything else to Backlog.

**Leave the assignee blank.** The spec has no assignee key, and you must not follow up with `gh issue edit --add-assignee`. Creating an issue is never an act of claiming it: new issues must enter the unassigned pool so `execute` (which queries `--assignee ""`) can select them. Assignment happens only at claim time (`execute` Acquire).

**Field values.**

- `kind` is the Step 2 classification in lower case.
- `field-priority`, `field-effort` and `field-ownership` are the three values Step 3 settled. All three are **required**: `issue-apply` refuses a spec that leaves one blank rather than filing work nothing can rank, size or route.
- `field-origin` is **Development**, or **Security Audit** if this report came out of a security audit session. It is optional — leave it out and the created issue gets a comment saying it was filed without one.

**The issue number** comes back in the command's JSON as `applied[0].number`, and is written into the spec file too. Later steps need it.

**Read the exit code.** **0** created it. **21** (`no-capabilities`) means the org defines no issue types or fields — report that the issue could not be classified rather than filing an unclassified one by hand. **22** (`spec-invalid`) means the spec is wrong (an unknown label, a milestone that is not open, a missing required field, or an org that defines no `Priority`, `Effort` or `Ownership` field at all): fix it and re-run. **23** and **24** mean the issue exists but some metadata did not land — report which, by number and title, and carry on. Re-running the same spec after a partial failure completes the remainder rather than filing a duplicate.

**Body shape.** Follow `../skills/writing-github-issues/SKILL.md`.

Where Step 4c found a template, use its headings and order instead of the list below, filling them per `templates/issue-template-resolution.md` (Step 4 or 5). The rules on what to write and what to cut are unchanged.

With no template, a reported problem usually lands as:

- `## Summary` — what is wrong, and what should happen instead when that is not already obvious. Name where it is (file paths, and line numbers when they help someone find it). Say what the impact is only when the problem does not already make it clear.
- `## Cause` — only when you know it and it tells the implementer where the fix belongs. One or two sentences, not the investigation that found it.
- `## Changes` — the suggested fix, when you have one. Leave it out rather than guessing, and keep any uncertainty you have ("this will likely need...").
- `## Acceptance criteria` — 2 to 5 testable statements.

Do not narrate how you found the problem, and do not add a section that would be empty. Most filings are a Summary and acceptance criteria.

**Does not go in the body:** whether it blocks the current story. That is a routing decision for the caller (Step 3) and belongs in what you report back, not in the issue. A genuine ordering constraint between two issues is a native blocked-by edge, not a sentence in the body.

### 6. Validate issue body

`issue-apply` reads the created issue back in the same request and reports any mismatch, so there is nothing to check by hand when it exits 0. Only if it reported a mismatch on the body, apply the corruption test and retry in `templates/body-file-write.md` (**Validate** + **Retry**). The `Closes #N` clause is PR-only and does not apply to an issue body.

### 6b. The board placement is already done

`issue-apply` places every issue it touches on the board itself, in the column its own state names — Blocked when a native edge points at something open, Non-code when the issue is scoped to a person or a browser agent, Backlog otherwise. There is no board step to run by hand, and no column to choose: the state decides it, in one place, for created and updated issues alike.

Read `board_column` and `board_moved` from the command's output and report them. A `board_moved` of `false` carries a `board_message` saying why; it is never fatal, because the board mirrors the issue and is never the source of truth.

### 7. Report

Display the created issue by number **and** title together (e.g. `#42 Fix login crash`, never the number alone) plus its URL, whether it blocks the current story or is deferred, and its board column (if placed).
