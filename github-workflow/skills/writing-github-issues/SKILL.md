---
name: writing-github-issues
description: >-
  Creates and rewrites GitHub issues so they are short, clear and easy to act on.
  Lead with the actual problem, keep only information needed to implement or
  verify the work, preserve uncertainty, and remove investigation history.
---

# Writing GitHub Issues

The entry point for **GitHub issue titles and bodies**. It is one of two entry points over `skills/_shared/body-standard.md`, which is the single standard for every body this plugin writes into GitHub. Read that file first. This one adds only what is specific to an issue.

The counterpart entry point is `skills/pr-body/SKILL.md`, which does the same job for pull request descriptions. An issue and a pull request are written the same way on purpose: same wording, same section names, same no-wrapping rule.

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

- `skills/_shared/body-standard.md` is the base. It carries the no-wrapping rule, the section vocabulary, the Summary and bullet rules, the title rules, and what never appears in a body. All of it applies to an issue.
- **This skill decides which of those sections an issue uses**, how long the body runs, and the conventions GitHub itself needs: classification, the write path, templates, and `[Manual]`.
- `skills/_shared/banned-patterns.md` applies in full. Its banned vocabulary, phrases and closing patterns are never acceptable in an issue.
- `skills/_shared/wording-standard.md` governs how everything else a person reads is worded. Where it asks for more explanation than an issue needs, the body standard and this skill win **inside the issue body only**.
- `skills/user-facing-communication/SKILL.md` governs the shape of what you say **about** the issue: what you filed, its current state, the issue named as well as numbered, and anything still outstanding. That is your reply, not the issue body, and it never reaches into the body.

The standards agree on the important part: explain the point in plain words. They differ on length. An issue is read by someone about to do the work, so it stays short.

## Title

Follow the title rules in `skills/_shared/body-standard.md`. The title is the work, said once, in the fewest words that still identify it: verb first, sentence case, roughly 70 characters, identifiers exact, no metadata prefix.

The one prefix a title carries is `[Manual]`, written exactly like that, square brackets, capital M, one trailing space. See **Issues that need a person** below.

Good:

> Fix accessibility labels on read-only Settings rows

> Remove stale accessibility comments

> Board column write fails when the project has over 100 items

Not this:

> [BUG] (High) Fix accessibility labels — Settings

> Investigation into why the settings screen sometimes reads wrong

The title belongs in GitHub's title field. Do not repeat it in the body.

## Classification

An issue says what kind of work it is **once**, through GitHub's native issue type (`Bug`, `User Story`, `Chore`, `Feature`, `Epic`, …) and the org's `Classification` field. Not through a title prefix, and not through a `type-*` label — neither is written any more, and `wf pick` reads neither. A spec that still names one has it stripped on the way in.

Lifecycle state (`status-ready`, `needs-refinement`, `status-blocked`) and priority stay on labels: GitHub has no native field for the first, and the second is dual-tracked with the org's `Priority` field.

`[Manual]` is not a classification and is not covered by that rule. It says who has to do the work, not what kind of work it is, and nothing native records it. See **Issues that need a person** below.

## Issues that need a person

Some issues cannot be finished by an agent. Granting an organisation owner's permission, adding a secret, buying a domain, approving a store submission, clicking through a third-party console: an agent can describe the step but cannot perform it.

Mark those issues the same way every time, so they are obvious in a list and never get picked up by an agent that cannot finish them:

1. **Prefix the title with `[Manual]`.** Exactly that spelling, at the very start, followed by one space. The rest of the title follows the normal rules, so `[Manual] Grant the Cloudflare GitHub App access to the org`.
2. **Apply the `status-blocked` lifecycle label**, in place of `status-ready` or `needs-refinement`, resolved through the project's label map like any other label. It is the existing lifecycle label for work that cannot proceed without something outside the agent's reach, it puts the issue in the Blocked column, and story selection already skips it.
3. **Include a `## Manual step` section** saying exactly what a person must do and why an agent cannot do it.

Those three go together. An issue has all of them or none of them.

**When it applies:** the issue cannot be closed until a person acts. That includes an issue whose work is mostly automatable but has one human prerequisite, because the issue is not done until that prerequisite is met.

**When it does not:** work a person has to do that belongs to a *different* issue is not a manual step here. Record it under `## Dependencies` as `Blocked by #N`, or under `## Out of scope`, and leave this issue unprefixed.

`[Manual]` is the only prefix `wf issue-apply` leaves on a title. It strips `[BUG]`, `[STORY]` and the rest, because the native issue type already says what kind of work an issue is. Nothing native says a person has to do it, which is why this one is carried in the title.

## One write path

Every issue this plugin files is created by `wf issue-apply` from a spec, so the title rules above, the native type and the field values are applied in one place rather than reinvented per command. Do not call `gh issue create` directly.

## Repository templates

Before writing a body, check whether the target repository publishes an issue template, following `templates/issue-template-resolution.md`. A template can come from the repository itself or from the organisation's `.github` repository, which supplies a default to every repo in the org that has none of its own.

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
| `## Dependencies` | There is real sequencing. Keep the markers exact, because the workflow parses them: `Depends on #N`, `Blocked by #N`, `After #N`, `Requires #N`. |
| `## Manual step` | The issue cannot be closed until a person acts. The title then takes `[Manual]` and the issue takes `status-blocked`. See **Issues that need a person** above. |
| `## Out of scope` | Closely related work is likely to expand the issue unnecessarily. |

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

## Final check

Run the checklist in `skills/_shared/body-standard.md` (**Before you post it**), plus these two, which only apply to an issue:

- Are the repository template's headings intact, where one applied?
- If there is a `## Manual step`, does the title start `[Manual] ` and does the issue carry `status-blocked`?

See `references/examples.md` for worked examples.
