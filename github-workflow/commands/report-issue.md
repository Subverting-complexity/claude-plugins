---
description: 'Create a bug, security, architecture, or tech debt issue. Trigger: "report a bug", "report tech debt", "security issue", "create an issue".'
---

# Report Issue

Create a bug, security, architecture, or tech debt issue discovered during development.

**Issue wording.** The title and body you create here follow
`../skills/writing-github-issues/SKILL.md`. Read it before writing the
body. It is the standard for every issue this plugin files, and it is
short: open with the actual problem, use `## Summary` plus only the
sections that carry information, cut the investigation history, and keep
any uncertainty the source had.

**Output standard.** Everything a person reads — plans, questions, findings, summaries, and
anything posted or committed — follows `../skills/_shared/wording-standard.md`
for how it reads, `../skills/user-facing-communication/SKILL.md` for what it
contains and in what order (outcome and current state first, then anything
outstanding, blocked or assumed, every work item named as well as numbered,
no investigation history), and `../skills/_shared/banned-patterns.md` for what
must never appear. Every reply, not only the last one. Inside the issue
body the issue standard above governs structure and length; banned
patterns still apply there in full.

## Preflight

Before doing anything else, invoke `/github-workflow:preflight` to
verify project configuration. If it finds issues and the user chooses
"Configure now", wait for setup to complete, then ask the user to
re-run this command. Otherwise, proceed.

## Steps

### 1. Read configuration

Read `ClaudeProject.md` and extract:

- `org`, `repo` from Identity
- Label map (for priority and lifecycle labels)

If `ClaudeProject.md` is missing or has no label map, use the default
label names from `templates/default-labels.md`. When using defaults in
an interactive session, warn the user: "Label map not configured —
using default labels. Run `/github-workflow:setup` to configure labels
for this project."

### 2. Classify the issue

Determine the type:

- **Bug** — Something is broken or behaves incorrectly
- **Security** — Vulnerability, insecure pattern, or missing protection
- **Architecture** — Layer violation, coupling, design problem
- **Tech Debt** — Working but needs improvement

### 3. Assess severity and select labels

First decide what happens to the issue:

- **Blocks current story** → Create and fix first on its own branch
- **Same scope and trivial** → Fix inline in current PR
- **Everything else** → Create issue for later

Then map the severity to a **priority label** from the label map in
`ClaudeProject.md`:

- **Critical** — security hole, data loss, or a crash on a core path →
  `priority-critical` label
- **High** — broken feature, blocks other work, or a clear regression →
  `priority-high` label
- **Medium** — incorrect behaviour with a workaround, or notable debt →
  `priority-medium` label
- **Low** — cosmetic, minor cleanup, or nice-to-have → `priority-low`
  label

Do **not** select a type label. What kind of work this is comes from the
native issue type in Step 5, and `type-*` labels are no longer part of the
label map on any project.

Also include:

- **Lifecycle state** — exactly one, so the new issue is never
  unlabelled: `status-ready` when the report is actionable as written
  (it includes where and a suggested fix — the usual case),
  `needs-refinement` when the report is too vague to implement without a
  refinement session, or `status-blocked` when the issue cannot be closed
  until a person does something no agent can do (grant a permission, add a
  secret, approve a submission). In that last case the title also takes the
  `[Manual]` prefix and the body gets a `## Manual step` section — the three
  go together, and the rule is in
  `../skills/writing-github-issues/SKILL.md` under **Issues that need a
  person**.
- **Provenance** — `claude-authored`, since this issue is Claude-created.

Build the label list from whichever of these the project actually
defines in its label map. Skip any purpose that has no label configured
— never pass a placeholder or an empty label name to `gh`. Resolve every
name by purpose key through `templates/default-labels.md`.

### 4. Detect current milestone

If in sprint mode, find the current milestone so the new issue lands
in the right sprint:

```
gh api repos/{org}/{repo}/milestones --jq 'map(select(.due_on != null)) | sort_by(.due_on) | .[] | select(.open_issues > 0) | .title' | head -1
```

Milestones without a due date are filtered out before sorting —
`sort_by(.due_on)` misorders nulls. If open milestones exist but **all**
lack due dates, sprint mode is not detected: say so explicitly ("open
milestones found, but none has a due date — creating without a
milestone") rather than silently skipping. If this returns nothing (that
case, flat backlog mode, or no open milestones), the issue is created
without a milestone — do **not** pass an empty `--milestone` flag, as
`gh` rejects it.

### 4c. Resolve the repository's issue template

Follow `templates/issue-template-resolution.md` to find out whether the
target repository publishes an issue template, either its own or one
inherited from the organisation's `.github` repository. It is one cached
GraphQL call.

If a template applies, the body you write in Step 5 uses **its** headings
and order. If none does, which is the common case, use the standard's own
sections. Either way this is best-effort: a lookup failure falls back to
the standard sections and never blocks the issue.

If a template carries frontmatter labels, add them to the label list
assembled in Step 3, minus any `type-*` label — the native type says that.
Ignore any assignees it names, for the same reason Step 5 leaves the
assignee blank.

### 5. Create the issue

One write, through `wf issue-apply`. It is the only path that creates an
issue: it applies the title rules, the native issue type, the org's field
values, the labels and the milestone together, so an issue filed here is
shaped exactly like one filed by `feature-discovery` or `execute`.

Write the issue body to the standard in
`../skills/writing-github-issues/SKILL.md` — which is also where the title
rules live — to `.claude/report-body.md` with the Write tool, and the
spec beside it (`templates/body-file-write.md` — a body always goes in a
file, never into a shell argument or a JSON string):

```bash
mkdir -p .claude
cat > .claude/report-spec.json <<'JSON'
{"issues": [{"title": "{title}",
             "body_file": ".claude/report-body.md",
             "kind": "{bug|security|architecture|tech debt}",
             "milestone": "{current_milestone}",
             "labels": ["{priority_label}", "{lifecycle_label}", "claude-authored"],
             "fields": {"field-priority": "{Urgent|High|Medium|Low}",
                        "field-effort": "{Low|Medium|High}",
                        "field-origin": "Development"}}]}
JSON
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply .claude/report-spec.json
```

The body goes in a file and the spec names it (`body_file`) rather than
carrying the text, because a body has backticks, `$`, quotes and blank lines
in it and hand-building that into a JSON string is where bodies get mangled.

Drop the `milestone` key entirely in flat-backlog mode, or whenever Step 4
found no current milestone. It takes the milestone's title, and a title that
names no **open** milestone fails the spec rather than filing the issue
outside the sprint.

**The title carries no prefix**, with one exception. No `[BUG]`,
`[SECURITY]`, `[ARCH]` or `[DEBT]`, no priority and no size. GitHub renders
the issue type and the fields beside the title already. `wf issue-apply`
strips such a prefix if one slips in, and reports that it did.

The exception is `[Manual]`, for an issue a person has to do (Step 3). It is
kept, because nothing native says an issue needs a human.

**The labels carry no type.** `kind` supplies the native issue type and the
`Classification` value together. A `type-*` label in the list is dropped for
the same reason. Pass the priority label, the lifecycle label and
`claude-authored`, omitting any the project does not define — an issue with
no lifecycle label is never picked up by `execute`, and it is the one easiest
to leave out.

**Leave the assignee blank.** The spec has no assignee key, and you must not
follow up with `gh issue edit --add-assignee`. Creating an issue is never an
act of claiming it: new issues must enter the unassigned pool so `execute`
(which queries `--assignee ""`) can select them. Assignment happens only at
claim time (`execute` Acquire).

**Field values.**

- `kind` is the Step 2 classification in lower case.
- `field-priority` is the Step 3 priority as the field names it: Critical
  becomes **Urgent**, the rest keep their names. **Keep** the `priority-*`
  label as well — priority is dual-tracked: the field orders selection and
  drives the portal's views, and the label is the fallback for issues the
  field was never set on.
- `field-effort` is your scope assessment: **Low** for a targeted fix in a
  few files, **Medium** for moderate scope with some investigation, **High**
  for broad impact, architectural change or significant unknowns.
- `field-origin` is **Development**, or **Security Audit** if this report
  came out of a security audit session.

**The issue number** comes back in the command's JSON as
`applied[0].number`, and is written into the spec file too. Later steps need
it.

**Read the exit code.** **0** created it. **21** (`no-capabilities`) means the org defines no
issue types or fields — report that the issue could not be classified rather
than filing an unclassified one by hand. **22** (`spec-invalid`) means the
spec is wrong (an unknown label, a milestone that is not open, a missing
mandatory field): fix it and re-run. **23** and **24** mean the issue exists
but some metadata did not land — report which, by number and title, and carry
on. Re-running the same spec after a partial failure completes the remainder
rather than filing a duplicate.

**Body shape.** Follow `../skills/writing-github-issues/SKILL.md`.

Where Step 4c found a template, use its headings and order instead of the
list below, filling them per `templates/issue-template-resolution.md`
(Step 4 or 5). The rules on what to write and what to cut are unchanged.

With no template, a reported problem usually lands as:

- `## Summary` — what is wrong, and what should happen instead when that
  is not already obvious. Name where it is (file paths, and line numbers
  when they help someone find it). Say what the impact is only when the
  problem does not already make it clear.
- `## Cause` — only when you know it and it tells the implementer where
  the fix belongs. One or two sentences, not the investigation that
  found it.
- `## Changes` — the suggested fix, when you have one. Leave it out
  rather than guessing, and keep any uncertainty you have ("this will
  likely need...").
- `## Acceptance criteria` — 2 to 5 testable statements.

Do not narrate how you found the problem, and do not add a section that
would be empty. Most filings are a Summary and acceptance criteria.

**Does not go in the body:** whether it blocks the current story. That
is a routing decision for the caller (Step 3) and belongs in what you
report back, not in the issue. A genuine ordering constraint between two
issues goes in `## Dependencies` as `Blocked by #N`.

### 6. Validate issue body

`issue-apply` reads the created issue back in the same request and reports
any mismatch, so there is nothing to check by hand when it exits 0. Only if
it reported a mismatch on the body, apply the corruption test and retry in
`templates/body-file-write.md` (**Validate** + **Retry**). The `Closes #N`
clause is PR-only and does not apply to an issue body.

### 6b. Place the issue on the board (best-effort, if configured)

So the new issue mirrors its lifecycle label on the board from the moment
it is created, place it in the column paired with the lifecycle state
chosen in Step 3 (see `templates/default-labels.md` → Board Columns):

- `status-ready` → **Ready** (`col-ready`)
- `needs-refinement` → **Backlog** (`col-backlog`)
- `status-blocked` → **Blocked** (`col-blocked`)

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" board-move {number} --column {col-ready|col-backlog|col-blocked}
```

The command adds the issue to the board (a new issue is never on it yet),
decides for itself whether a board is configured — a silent no-op when it
is not — and verifies the board's identity before writing. It **always
exits 0**, because a board mirrors the labels and is never the source of
truth, so read `moved` and `reason` and report a failure rather than
stopping for one.

### 7. Report

Display the created issue by number **and** title together (e.g.
`#42 Fix login crash`, never the number alone) plus its URL, whether
it blocks the current story or is deferred, and its board column (if
placed).
