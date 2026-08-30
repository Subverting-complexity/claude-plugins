---
name: writing-github-issues
description: >-
  Creates and rewrites GitHub issues so they are short, clear and easy to
  scan, while preserving the technical facts, constraints and uncertainty
  needed to complete the work. Use when drafting, rewriting, simplifying
  or reviewing GitHub issues, bugs, technical stories, follow-up issues,
  acceptance criteria or issue descriptions.
---

# Writing GitHub Issues

Write GitHub issues that are easy to understand quickly.

The issue should contain only the information someone needs to
understand the problem, make the change and verify it.

Prefer a short issue over a comprehensive record of the investigation.

## When this applies

This is the standard for **every GitHub issue title and body** this
plugin writes or edits, whoever triggers it. That includes:

- `/github-workflow:report-issue`, including every autonomous filing
  that routes through it (`execute` finding a problem outside its own
  diff, `code-review` filing what it cannot fix, an audit run, a story
  sliced down to fit a session).
- Story issues created by `/github-workflow:feature-discovery` and
  `/github-workflow:repo-scaffolding`.
- A single story written by `/github-workflow:user-story` when it is
  destined for a GitHub issue.
- Any edit to an existing issue body, including the `## Dependencies`
  marker `/github-workflow:block-story` writes.
- Rewriting or tidying an issue a person asks you to simplify.

Apply it without being asked. There is no separate "concise mode".

## Precedence

- **This skill governs issue structure**: which sections exist, how long
  the body is, what gets cut, and how the title reads.
- `skills/_shared/banned-patterns.md` still applies in full. Its banned
  vocabulary, phrases and closing patterns are never acceptable in an
  issue.
- `skills/_shared/wording-standard.md` governs everything else a person
  reads: the plan you print, progress notes, pull request descriptions,
  review comments, questions and chat replies. Where it asks for more
  explanation than an issue needs, this skill wins **inside the issue
  body only**.

The two standards agree on the important part: explain the point in
plain words. They differ on length. An issue is read by someone about to
do the work, so it stays short.

## Title and body are separate fields

The title goes in GitHub's title field. The body starts at `## Summary`.

Do not repeat the title as a heading inside the body. Where a project
uses issue prefixes (`[BUG]`, `[SECURITY]`, `[ARCH]`, `[DEBT]`), the
prefix belongs on the title and nowhere else.

## Core rules

### Start with the actual point

The first sentence should say what is wrong or what needs to happen.

Good:

- There are 2 accessibility comments that still describe a prompt asking
  the reader whether to jump to a position pulled from another device,
  but that prompt no longer exists.
- Read-only Settings rows with a value are currently read as 2 separate
  accessibility elements.
- The lock-screen playback timeline is incorrect for recordings and
  documents using the fallback playback engine.

Avoid opening with:

- "Found while working on..."
- "For context..."
- "During investigation..."
- "This issue is part of..."
- "This issue was identified when..."
- A history of how the problem was discovered.

Include discovery history only when it materially affects the scope or
implementation.

### Remove anything that is not directly useful

Keep information when it helps answer at least one of these questions:

- What is wrong?
- What should happen instead?
- Why is it happening, if that matters to the fix?
- What needs to change?
- What constraints need to be preserved?
- How do we verify the work?
- Is anything blocked or deliberately excluded?

Remove:

- Investigation history.
- Repeated explanations of the same behaviour.
- Speculation about how the problem originated unless relevant to the fix.
- References to related issues that add history but do not affect the work.
- Detailed justification for something already obvious from the problem.
- File-by-file narration.
- Searches, greps and debugging steps used to prove the issue.
- Code snippets that are not needed to understand or make the change.
- Long explanations of why something matters when the impact is already
  clear.
- Implementation alternatives when there is already a clear required
  approach.

Do not preserve information merely because it existed in the original
issue.

### Preserve meaningful uncertainty

Do not make the issue more certain than the available information.

If the source says something is likely, appears to be the cause, or
still needs to be decided, preserve that. Use wording such as "likely",
"appears", "should", "may", "This will likely need...", "Either approach
may work...".

Do not convert an open question into a decision.

### Use plain English

Use British English. Prefer "behaviour" over "behavior", "prioritise"
over "prioritize", "licence" for the noun, "analyse" over "analyze".

Keep technical names, paths, classes, APIs and identifiers exact,
including American spellings inside them. A setting called
`color-scheme` stays `color-scheme`.

Use normal technical language where it is clearer than explaining the
same concept in generic terms. Do not make the writing overly formal.

### Keep sentences direct

Prefer:

> `ListRow` drops the accessibility label for non-interactive rows.

Over:

> The underlying cause of this behaviour appears to be related to the way
> in which `ListRow` handles accessibility properties within the
> non-interactive branch.

Prefer:

> No behaviour changes are needed.

Over:

> This change should be limited exclusively to comments and should not
> result in any changes to the existing runtime behaviour.

### Do not repeat information across sections

If the Summary already explains the problem, do not explain it again
under Cause or Changes. Each section should add new information.

## The repository's own template comes first

Before writing a body, check whether the target repository publishes an
issue template, following `templates/issue-template-resolution.md`. A
template can come from the repository itself or from the organisation's
`.github` repository, which supplies a default to every repo in the org
that has none of its own.

Creating an issue through the API or `gh issue create --body-file`
applies no template: the body is used exactly as supplied. So a project
that has defined a template gets ignored unless you fetch it and fill it
in yourself.

**Where a template exists, its structure wins.** Keep its headings, their
wording and their order, even where they differ from the sections below.
Everything else in this skill still applies inside them: open with the
actual point, write only what someone needs to do the work, cut the
investigation history, and keep any uncertainty the source had. A
template tells you which sections to write. It does not license a longer
issue, and an empty section it left for you is not an instruction to
invent content.

Where no template exists, which is the common case, use the structure
below. That is a normal outcome, not a gap worth reporting.

## Structure

`## Summary` is the only section that should normally be required.

Add other sections only when they contain useful information. The usual
order is:

```markdown
## Summary

## Cause

## Changes

## Acceptance criteria

## Verification

## Dependencies

## Out of scope
```

Do not create empty sections. Do not use every section by default.

A small issue may only need:

```markdown
## Summary

## Changes

## Acceptance criteria
```

A very small issue may only need:

```markdown
## Summary

## Acceptance criteria
```

### Summary

Usually 1-3 short paragraphs. Explain:

1. What is currently happening.
2. What should happen instead, if it is not already obvious.

The reader should understand the issue from this section alone. Do not
turn the Summary into an executive essay.

### Cause

Include only when the cause is known and helps someone understand the
required change. Keep it short. Do not include the investigation used to
discover the cause.

Prefer:

> `SettingsRow` creates the correct accessibility label, but `ListRow`
> drops it for non-interactive rows.

Not:

> Investigation showed that `SettingsRow` correctly builds the
> accessibility label and passes it down. Looking further into
> `ListRow`, the interactive branch applies the relevant properties to
> its `Pressable`, while the non-interactive branch returns the content
> view directly...

### Changes

Use when the required implementation is not obvious from the Summary.

Describe outcomes, not a development diary. Use bullets when there are
multiple distinct changes. Include exact paths, identifiers or
configuration values when they are needed to complete the work. Do not
prescribe implementation details unnecessarily.

### Acceptance criteria

Use short, testable statements. Usually 2-5 items.

Prefer:

- The comments no longer reference a cross-device position prompt.
- The comments describe the playback error that currently triggers the
  behaviour.
- No functional changes.

Avoid acceptance criteria that simply repeat implementation steps.

### Verification

Use when verification needs additional explanation, such as
physical-device testing, multiple environments, regression checks,
manual account checks, or specific commands or queries.

Do not add a separate Verification section when the acceptance criteria
already cover it adequately.

### Dependencies

Only include actual dependencies or required sequencing. Do not list
loosely related issues.

This section is machine-read, so keep the markers exact (see **Markers
the workflow depends on** below).

### Manual step

A `## Manual step` section may be used when part of the work cannot be
completed by the agent or developer doing the rest of the issue. State
exactly what a person needs to do and why.

### Out of scope

Use only when there is a realistic risk that the work will expand into
something that should remain separate. Keep it short.

## Story issues

A story is an issue, so it follows everything above. `## Summary` opens
it, and every other section has to earn its place.

Stories may add these sections when they carry information the
implementer would otherwise have to guess. Each one is optional, and an
empty or obvious one is worse than none:

- `## Business rules` for concrete, testable rules, numbered.
- `## Data model` for tables or entities created or modified, as a
  markdown table (Column, Type, Description).
- `## API contract` for method, path, request and response shape, status
  codes, auth.
- `## UI/UX` for where it appears, the user flow, and the loading,
  empty, error and success states.

Two conventions come from the workflow rather than the writer:

- The size estimate goes in the Summary as
  `**Size estimate:** small | medium | large`. `feature-discovery` sets
  it and the `Effort` field mirrors it.
- A story too vague to implement gets the `needs-refinement` label
  rather than a padded body. Do not pad a thin story with invented
  detail to make it look complete.

Do not reach for the story sections out of habit. Most stories are a
Summary, Changes and Acceptance criteria.

## Markers the workflow depends on

Some text in an issue body is parsed by the workflow, not just read.
Cutting or renaming it breaks automation, so it is never "information
that is not directly useful":

- `## Dependencies` holding `Depends on #N`, `Blocked by #N`,
  `After #N` or `Requires #N`. Story selection skips a story whose
  dependency is still open, and `execute` auto-unblocks an issue when
  the blocking issue closes.
- `**Size estimate:** {size}` in the Summary of a story.
- `## Stories` and `## Architecture` blocks written into an issue by a
  prior discovery session. `execute` reads them to decide whether the
  interactive discovery gate can be skipped.

Keep these exact. Everything else in the body is yours to cut.

## Titles

Use a short title that describes the outcome.

Prefer:

- Fix accessibility labels on read-only Settings rows
- Remove stale accessibility comments
- Fix lock-screen playback progress

Avoid:

- Accessibility issue relating to incorrect handling of accessibility
  labels within Settings rows

Do not include background or investigation history in the title.

## Rewriting an existing issue

When simplifying an existing issue:

1. Identify the single main problem or outcome.
2. Write the Summary first without looking at the existing section
   structure.
3. Identify only the technical facts required to complete the work.
4. Remove investigation history and duplicated reasoning.
5. Add optional sections only where the remaining information needs
   them.
6. Preserve genuine constraints, dependencies and uncertainty.
7. Prefer later clarifications or corrections when they supersede
   earlier information.
8. Check that the issue can be understood without reading a related
   issue unless that issue is an actual dependency.
9. Remove anything that does not materially help implementation or
   verification.

Do not treat the original structure as something that needs to be
preserved, with one exception: where the issue was opened from the
repository's template, its headings are the project's convention rather
than one author's choice. Keep them and cut within them.

Carry the machine-read markers across unchanged (see above). When an
issue has comments, prefer the latest correction in the thread over the
original body where the two disagree.

Apply the rewrite with a temp file and `--body-file`, following
`templates/body-file-write.md`. Never pass a rewritten body inline.

## Writing style

The writing should be practical, concise, plain English, technically
precise, neutral rather than formal, easy to scan, and direct without
becoming abrupt.

Use digits for specific counts where natural: "There are 2 comments...",
"Test at 1x and 2x."

Avoid unnecessary intensifiers: "significantly", "particularly",
"importantly", "notably", "in one respect", "it is worth noting".

Avoid filler: "In order to", "With that being said", "As mentioned
above", "It should be noted that", "The purpose of this issue is to".

Do not add confidence, rationale or conclusions that are not supported
by the source.

## Examples

Four worked examples, from a two-section issue to a larger
infrastructure story, are in `references/examples.md`. Read them when
you are unsure how much to cut, or before rewriting a long existing
issue.

## Final check

Before returning an issue, ask:

- Can the Summary be understood on its own?
- Is the first sentence the actual point?
- Is every remaining paragraph useful for completing or verifying the
  work?
- Is anything explained twice?
- Can any section be removed entirely?
- Has uncertainty been preserved?
- If the repository has a template, does the body use its headings, with
  no leftover guidance comments or unfilled placeholders?
- Are the machine-read markers intact?
- Is the issue shorter than the source without losing information that
  affects the work?

If a sentence does not help someone understand, implement or verify the
issue, remove it.
