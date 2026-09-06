---
name: writing-github-issues
description: >-
  Creates and rewrites GitHub issues so they are short, clear and easy to act on.
  Lead with the actual problem, keep only information needed to implement or
  verify the work, preserve uncertainty, and remove investigation history.
---

# Writing GitHub Issues

Write the shortest issue that still gives an implementer everything they need.

Prefer a clear work item over a record of how the problem was discovered.

## When this applies

This is the standard for **every GitHub issue title and body** this plugin writes or edits, whoever triggers it. That includes:

- `/github-workflow:report-issue`, including every autonomous filing that routes through it (`execute` finding a problem outside its own diff, `code-review` filing what it cannot fix, an audit run, a story sliced down to fit a session).
- Story issues created by `/github-workflow:feature-discovery` and `/github-workflow:repo-scaffolding`.
- A single story written by `/github-workflow:user-story` when it is destined for a GitHub issue.
- Any edit to an existing issue body, including the `## Dependencies` marker `/github-workflow:block-story` writes.
- Rewriting or tidying an issue a person asks you to simplify.

Apply it without being asked. There is no separate "concise mode".

## Precedence

- **This skill governs issue structure**: which sections exist, how long the body is, what gets cut, and how the title reads.
- `skills/_shared/banned-patterns.md` still applies in full. Its banned vocabulary, phrases and closing patterns are never acceptable in an issue.
- `skills/_shared/wording-standard.md` governs how everything else a person reads is worded. Where it asks for more explanation than an issue needs, this skill wins **inside the issue body only**.
- `skills/user-facing-communication/SKILL.md` governs the shape of what you say **about** the issue: what you filed, its current state, the issue named as well as numbered, and anything still outstanding. That is your reply, not the issue body, and it never reaches into the body.

The standards agree on the important part: explain the point in plain words. They differ on length. An issue is read by someone about to do the work, so it stays short.

## Core rules

- Start with the actual problem or required outcome.
- Use plain English and British spelling.
- Keep technical names, paths, APIs and identifiers exact.
- Preserve uncertainty. Do not turn "likely", "may" or an open question into a decision.
- Remove investigation history, debugging steps, grep results, failed theories and proof of work.
- Do not repeat the same information in multiple sections.
- Do not include implementation detail unless it changes what the implementer needs to do.
- Use bullets where they make the issue easier to scan.

## Title

The title is the work, said once, in the fewest words that still identify it.

- **Start with a verb** where the issue asks for a change: `Fix`, `Add`, `Remove`, `Split`, `Document`. A bug report may instead name the broken behaviour.
- **Sentence case.** No trailing full stop.
- **Roughly 70 characters or fewer**, so it survives GitHub's list views, the board and a notification email uncut.
- **Keep identifiers exact** — file paths, flags, API names.
- **No metadata in the title.** No `[BUG]`/`[STORY]`/`[DEBT]` prefix, no priority, no size, no sprint, no component tag, no issue number. GitHub renders the issue type, the labels and the fields beside the title in every view; repeating them there costs width and drifts out of step the moment one of them is edited.

Good:

> Fix accessibility labels on read-only Settings rows

> Remove stale accessibility comments

> Board column write fails when the project has over 100 items

Not this:

> [BUG] (High) Fix accessibility labels — Settings

> Investigation into why the settings screen sometimes reads wrong

The title belongs in GitHub's title field. Do not repeat it in the body.

## Classification

An issue says what kind of work it is **once**, through GitHub's native issue
type (`Bug`, `User Story`, `Chore`, `Feature`, `Epic`, …) and the org's
`Classification` field. Not through a title prefix, and not through a `type-*`
label — neither is written any more, and `wf pick` reads neither. A spec that
still names one has it stripped on the way in.

Lifecycle state (`status-ready`, `needs-refinement`, `status-blocked`) and
priority stay on labels: GitHub has no native field for the first, and the
second is dual-tracked with the org's `Priority` field.

## One write path

Every issue this plugin files is created by `wf issue-apply` from a spec, so
the title rules above, the native type and the field values are applied in one
place rather than reinvented per command. Do not call `gh issue create`
directly.

## Repository templates

Before writing a body, check whether the target repository publishes an issue template, following `templates/issue-template-resolution.md`. A template can come from the repository itself or from the organisation's `.github` repository, which supplies a default to every repo in the org that has none of its own.

Creating an issue through the API or `gh issue create --body-file` applies no template: the body is used exactly as supplied. So a project that has defined a template gets ignored unless you fetch it and fill it in yourself.

Where a template exists, use its headings, their wording and their order, even where they differ from the sections below. The template controls structure only. Everything else in this skill still applies inside it: keep the content concise, and remove empty guidance and placeholders. An empty section left for you is not an instruction to invent content.

Where there is no template, which is the common case, use the structure below. That is a normal outcome, not a gap worth reporting.

## Default structure

`## Summary` is the only section that is normally required.

Add other sections only when they contain useful information:

```markdown
## Summary

## Cause

## Changes

## Acceptance criteria

## Verification

## Dependencies

## Manual step

## Out of scope
```

Do not create empty sections.

### Summary

Usually 1-3 short paragraphs.

The first sentence should state what is wrong or what needs to happen.

The reader should understand the issue from the Summary alone.

### Cause

Use only when the known cause helps explain where or how to fix the issue.

Keep it short. Do not include the investigation used to find it.

### Changes

Use only when the required change is not already obvious.

Describe outcomes, not a development diary.

### Acceptance criteria

Use short, testable statements.

Usually 2-5 items.

Do not repeat the Changes section as acceptance criteria.

### Verification

Use only when verification needs something specific, such as a physical device, multiple environments or a regression check.

### Dependencies

Include only real dependencies or required sequencing.

Keep workflow-readable dependency markers exact, such as:

- `Depends on #N`
- `Blocked by #N`
- `After #N`
- `Requires #N`

### Manual step

Use when part of the work requires a person or permission the implementer will not have.

State exactly what needs to be done and why.

### Out of scope

Use only when closely related work is likely to expand the issue unnecessarily.

## Story issues

Stories follow the same rules.

Add specialised sections only when the implementer would otherwise have to guess:

- `## Business rules`
- `## Data model`
- `## API contract`
- `## UI/UX`

Do not add them by default.

Keep workflow markers such as `**Size estimate:**`, `## Dependencies`, `## Stories` and `## Architecture` exact when the repository automation depends on them.

## Rewriting an existing issue

When simplifying an issue:

1. Identify the single main problem or outcome.
2. Rewrite the Summary first.
3. Keep only facts that affect implementation, constraints or verification.
4. Remove duplicated reasoning and investigation history.
5. Preserve later corrections and genuine uncertainty.
6. Keep repository-template headings and machine-read markers intact.
7. Delete any section that no longer earns its place.

Do not preserve content just because it was in the original issue.

Apply the rewrite with a temp file and `--body-file`, following `templates/body-file-write.md`. Never pass a rewritten body inline.

## Style

Prefer:

> `ListRow` drops the accessibility label for non-interactive rows.

Over:

> The underlying cause appears to be related to the way `ListRow` handles accessibility properties in the non-interactive branch.

Prefer:

> No behaviour changes are needed.

Over:

> This change should be limited exclusively to comments and should not alter runtime behaviour.

Avoid filler such as:

- "For context"
- "It should be noted that"
- "As mentioned above"
- "The purpose of this issue is to"
- "Found while working on"

## Final check

Before returning an issue:

- Is the actual problem clear in the first sentence?
- Can the Summary stand on its own?
- Is every remaining section necessary?
- Is anything explained twice?
- Has uncertainty been preserved?
- Are repository-template headings and workflow markers intact?
- Can anything else be removed without making implementation or verification harder?

If yes, remove it.

See `references/examples.md` for worked examples.
