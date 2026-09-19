---
name: writing-github-issues
description: 'The standard for writing or rewriting a GitHub issue title and body: short, problem first, only what is needed to build or verify it.'
---

# Writing GitHub Issues

The entry point for **GitHub issue titles and bodies**. It is one of two entry points over `skills/_shared/body-standard.md`, which is the single standard for every body this plugin writes into GitHub. Read that file first. This one adds only what is specific to an issue.

The counterpart entry point is `skills/pr-body/SKILL.md`, which does the same job for pull request descriptions. An issue and a pull request are written the same way on purpose: same wording, same section names, same no-wrapping rule.

Write the shortest issue that still gives an implementer everything they need.

Prefer a clear work item over a record of how the problem was discovered.

## When this applies

This is the standard for **every GitHub issue title and body** this plugin writes or edits, whoever triggers it. That includes:

- `/synergy:report-issue`, including every autonomous filing that routes through it (`execute` finding a problem outside its own diff, `pr-review` filing what it cannot fix, an audit run, a story sliced down to fit a session).
- Story issues created by `/synergy:feature-discovery`.
- A single story written by `/synergy:user-story` when it is destined for a GitHub issue.
- Any edit to an existing issue body.
- Rewriting or tidying an issue a person asks you to simplify.

Apply it without being asked. There is no separate "concise mode".

## Precedence

- `skills/_shared/body-standard.md` is the base, and all of it applies to an issue.
- **This skill decides which of its sections an issue uses**, how long the body runs, and the conventions GitHub itself needs: classification, the write path, templates, and scope.
- `skills/user-facing-communication/SKILL.md` governs the shape of what you say **about** the issue: what you filed, its current state, the issue named as well as numbered, and anything still outstanding. That is your reply, not the issue body, and it never reaches into the body.

The standards agree on the important part: explain the point in plain words. They differ on length. An issue is read by someone about to do the work, so it stays short.

## Title

Follow the title rules in `skills/_shared/body-standard.md`. The title is the work, said once, in the fewest words that still identify it.

The only prefixes a title carries are `[Manual] ` and `[Browser] `, written exactly like that, square brackets, capital letter, one trailing space. They say who does the work, never what kind of work it is. Only when the issue needs one of these prefixes, read `references/scope-and-hierarchy.md` → **Scope: one issue, one party**.

Good:

> Fix accessibility labels on read-only Settings rows

> Remove stale accessibility comments

> Report export fails when a report has over 100 rows

Not this:

> [BUG] (High) Fix accessibility labels — Settings

> Investigation into why the settings screen sometimes reads wrong

## Classification

An issue says what kind of work it is **once**, through GitHub's native issue type (`Bug`, `User Story`, `Chore`, `Feature`, `Epic`, …) and the org's `Classification` field. Not through a title prefix, and not through a `type-*` label — neither is written any more, and `wf pick` reads neither. A spec that still names one has it stripped on the way in.

**Nor through any other label.** An issue's state is its `Stage` field; how urgent, how big and whose it is are the org's `Priority`, `Effort` and `Ownership` fields. You do not write any of those four when filing: `wf issue-apply` sets the three fields from the spec and writes the stage from the issue's own state. The workflow puts no label on an issue.

**Choosing a `Classification`.** `kind` sets a default; name a better one in `fields` when it fits. For a bug, prefer **Regression** when something previously worked and broke, or **Performance** when the defect is speed or memory. For a feature, prefer **Enhancement** when it improves something that already exists, **Integration** when it connects an external system, **Documentation** when it tracks docs only, or **Performance** when speed is the point.

**Adding areas.** Also add each area the work touches (`Front end`, `Back end`, `API`, `Database`, `Mobile`, `Infrastructure`, `Build and deploy`, `Testing`), but only options the org's `Classification` field defines: `wf.sh org-capabilities` lists them under `field_map`, and `wf issue-apply` refuses an option the org does not have. Always name one kind-of-change value beside them, for example `"field-type": ["Bug Fix", "Front end"]`. A `field-type` in `fields` replaces the `kind` default, and an issue carrying only areas is left out of maintenance mode.

`[Manual]` and `[Browser]` are not classifications and are not covered by that rule. They say who has to do the work, not what kind of work it is, and nothing native records either. Only when the issue needs one of these prefixes, read `references/scope-and-hierarchy.md` → **Scope: one issue, one party**.

## Hierarchy and party scoping

Only when the issue needs a parent (an area or a feature), or needs scoping to a single party (`[Manual] `, `[Browser] ` or an unprefixed code-agent issue), read `references/scope-and-hierarchy.md` and follow it: **Hierarchy: area, feature, story** covers parenting; **Scope: one issue, one party** covers the three parties, marking a scoped issue, and splitting an issue that needs two parties.

## One write path

Every issue this plugin files is created by `wf issue-apply` from a spec, so the title rules above, the native type and the field values are applied in one place rather than reinvented per command. Do not call `gh issue create` directly.

## Repository templates

When creating an issue, and only then, check before writing the body whether the target repository publishes an issue template, following `templates/issue-template-resolution.md`. A template can come from the repository itself or from the organisation's `.github` repository, which supplies a default to every repo in the org that has none of its own. Rewriting an existing issue skips this: keep the headings it already has.

Creating an issue through the API or `gh issue create --body-file` applies no template: the body is used exactly as supplied. So a project that has defined a template gets ignored unless you fetch it and fill it in yourself.

Where a template exists, use its headings, their wording and their order, even where they differ from the sections below. The template controls structure only. Everything else in this skill still applies inside it: keep the content concise, and remove empty guidance and placeholders. An empty section left for you is not an instruction to invent content.

Where there is no template, which is the common case, use the structure below. That is a normal outcome, not a gap worth reporting.

## Default structure

An issue draws on the section vocabulary in `skills/_shared/body-standard.md`, in that order. `## Summary` is the only section normally required, and most filings are a Summary and acceptance criteria. Add another section only when it carries information an implementer needs, and never leave one empty.

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

The body standard says what each section is for. These are the issue-specific calls on when to include one:

| Section | Include it when |
| ------- | --------------- |
| `## Summary` | Always. Usually 1 to 3 short paragraphs, and the reader understands the issue from it alone. |
| `## Cause` | The cause is known and tells the implementer where the fix belongs. Not the investigation that found it. |
| `## Changes` | The required change is not already obvious from the Summary. |
| `## Acceptance criteria` | Almost always. 2 to 5 testable statements, and never a restatement of `## Changes`. |
| `## Verification` | Verifying needs something specific: a physical device, several environments, a regression check. |
| `## Dependencies` | Rarely. A dependency is a native blocked-by edge, written by `wf issue-apply` from the spec's `blocked_by` and read by everything; prose is not parsed and does not block anything. Use the section only to explain *why* the sequencing exists. |
| `## Manual step` | The issue cannot be closed by a code agent. The title then takes `[Manual] ` or `[Browser] `, and `Ownership` says which. Only for the rules behind this, see `references/scope-and-hierarchy.md` → **Scope: one issue, one party**. |
| `## Out of scope` | Closely related work is likely to expand the issue unnecessarily. |

## Story issues

Stories follow the same rules.

Add specialised sections only when the implementer would otherwise have to guess:

- `## Business rules`
- `## Data model`
- `## API contract`
- `## UI/UX`

Do not add them by default.

Keep workflow markers such as `## Dependencies`, `## Stories` and `## Architecture` exact when the repository automation depends on them.

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

## Final check

Run the checklist in `skills/_shared/body-standard.md` (**Before you post it**), plus these, which only apply to an issue:

- Are the repository template's headings intact, where one applied?
- If there is a `## Manual step`, does the title start `[Manual] ` or `[Browser] `, and does `Ownership` say `Human` or `Browser agent` to match?
- Does this issue need only **one** party to close it? If a second party has to act before it is done, that half is its own issue, and the dependency between them is a native blocked-by edge.

When you are unsure of the shape, see `references/examples.md` for worked examples.
