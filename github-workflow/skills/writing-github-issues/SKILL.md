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
- Any edit to an existing issue body.
- Rewriting or tidying an issue a person asks you to simplify.

Apply it without being asked. There is no separate "concise mode".

## Precedence

- `skills/_shared/body-standard.md` is the base. It carries the no-wrapping rule, the section vocabulary, the Summary and bullet rules, the title rules, and what never appears in a body. All of it applies to an issue.
- **This skill decides which of those sections an issue uses**, how long the body runs, and the conventions GitHub itself needs: classification, the write path, templates, and scope.
- `skills/_shared/banned-patterns.md` applies in full. Its banned vocabulary, phrases and closing patterns are never acceptable in an issue.
- `skills/_shared/wording-standard.md` governs how everything else a person reads is worded. Where it asks for more explanation than an issue needs, the body standard and this skill win **inside the issue body only**.
- `skills/user-facing-communication/SKILL.md` governs the shape of what you say **about** the issue: what you filed, its current state, the issue named as well as numbered, and anything still outstanding. That is your reply, not the issue body, and it never reaches into the body.

The standards agree on the important part: explain the point in plain words. They differ on length. An issue is read by someone about to do the work, so it stays short.

## Title

Follow the title rules in `skills/_shared/body-standard.md`. The title is the work, said once, in the fewest words that still identify it: verb first, sentence case, roughly 70 characters, identifiers exact, no metadata prefix.

The only prefixes a title carries are `[Manual] ` and `[Browser] `, written exactly like that, square brackets, capital letter, one trailing space. They say who does the work, never what kind of work it is. See **Scope: one issue, one party** below.

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

**Nor through any other label.** An issue's state is the board column its card is in; how urgent, how big and whose it is are the org's `Priority`, `Effort` and `Ownership` fields. You do not write any of those four when filing: `wf issue-apply` sets the three fields from the spec and places the card from the issue's own state. The only label an issue gets is `claude-authored`.

`[Manual]` and `[Browser]` are not classifications and are not covered by that rule. They say who has to do the work, not what kind of work it is, and nothing native records either. See **Scope: one issue, one party** below.

## Hierarchy: epic, feature, story

The native types are a tree, not a flat list. A `User Story` sits under a `Feature`, and `wf issue-apply` refuses one without that parent, or under the wrong type, wherever the org has `Feature` enabled. A `Feature` sits under an `Epic` when the work has one. An epic groups several features toward one outcome, so a feature that would be an epic's only child is filed on its own rather than under an epic that restates it; a feature that does have a parent must have an `Epic` one. `Bug` and `Chore` sit outside the tree: a parent is allowed on either and never required.

Attach before creating. Where the work belongs to an epic or feature that already exists, name it as the `parent` by issue number rather than filing a second one.

The parent is the native relationship the spec's `parent` writes. It is not a sentence in the body and not the org's `Parent` field; a body line saying "Part of #N" parents nothing.

## Scope: one issue, one party

Three parties do work on a backlog, and they cannot substitute for each other.

| Party | What it is | `Ownership` | Prefix |
| --- | --- | --- | --- |
| **Code agent** | Changes the repository. Produces a commit. | `Code agent` | none |
| **Browser agent** | Drives a web console a person has already signed into. Produces a saved form. | `Browser agent` | `[Browser] ` |
| **Human** | Everything neither of the others can reach. Produces neither. | `Human` | `[Manual] ` |

**Every issue is scoped to exactly one of them.** Not "mostly a code agent", not "an agent, then someone presses save". One. This is the rule that matters, and the rest of this section is what follows from it.

### What each party can do

**Code agent.** The common case, so it carries no prefix. It still carries the field: `Ownership` is required on every issue, and an issue that does not say who owns it is not offered to a code agent at all.

**Browser agent.** Filling non-credential fields, pressing save, reading identifiers back out of a console. It **cannot** sign in, clear two-factor, download a file, accept an agreement, or touch anything financial. When it meets one of those it stops and hands back rather than working around it. Because it needs a session a person opened, a `[Browser]` issue is not picked up on its own either.

**Human.** A physical device in someone's hand, money, a legal agreement, a credential being moved, a business decision. Signing in, downloading, accepting terms and making a declaration to a third party are human every time, even when the work around them is console clicking. A device pass is human, not browser: a browser agent has no phone, no speaker and no screen reader.

### Marking a scoped issue

Both scoped parties take two things together, both or neither:

1. **The `Ownership` field**, set to `Browser agent` or `Human`. This is the one that does the work: it is the only thing selection reads, so it is what keeps the issue out of the code agent's pool. `wf issue-apply` puts the card in the board's **Non-code** column from it, without being asked.
2. **The prefix**, exactly as spelled above, at the very start, followed by one space. `[Manual] Grant the Cloudflare GitHub App access to the org`. `[Browser] Set the authorised redirect URIs on the web OAuth client`. This is for a person reading a list; nothing selects on it.

**Non-code is not Blocked.** Blocked means one thing only — an open native blocked-by edge — and `wf unblock` releases anything sitting there once those edges close. Non-code work parked in Blocked is one sweep away from being handed to an agent that cannot do it, which is exactly what happened: both issues the first sweep would have released were `[Manual]` device passes whose blockers had closed.

Include a `## Manual step` section saying what has to happen and why the other two parties cannot do it.

### When an issue needs two parties, split it

**This is the rule that replaces the old one.** An issue that is mostly automatable with one human prerequisite used to be marked `[Manual]` and left whole. Do not do that. Raise the other party's work as its own issue, scope it, and link the two with a native blocked-by edge.

The old shape looks finished and is not. A code story that does its half and says "then a person sets the value" sits in Backlog, gets picked up, gets a merged pull request, and the console step is never done because it never had a card of its own.

Ask what the issue produces: a commit, a saved console form, or neither. **Two answers means two issues.**

Where the two halves interleave, say so in both, in order, rather than leaving it to whoever picks one up. Two issues that hand back and forth once is normal and fine; four issues for four alternating steps is not.

**When none of this applies:** work a person has to do that belongs to a *different* issue is not a manual step here. Record it as a native blocked-by edge, and leave this issue unprefixed.

`[Manual]` and `[Browser]` are the only prefixes `wf issue-apply` leaves on a title. It strips `[BUG]`, `[STORY]` and the rest, because the native issue type already says what kind of work an issue is. Nothing native says **who** has to do it, which is why these two are carried in the title.

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
| `## Dependencies` | Rarely. A dependency is a native blocked-by edge, written by `wf issue-apply` from the spec's `blocked_by` and read by everything; prose is not parsed and does not block anything. Use the section only to explain *why* the sequencing exists. |
| `## Manual step` | The issue cannot be closed by a code agent. The title then takes `[Manual] ` or `[Browser] `, and `Ownership` says which. See **Scope: one issue, one party** above. |
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

Run the checklist in `skills/_shared/body-standard.md` (**Before you post it**), plus these two, which only apply to an issue:

- Are the repository template's headings intact, where one applied?
- If there is a `## Manual step`, does the title start `[Manual] ` or `[Browser] `, and does `Ownership` say `Human` or `Browser agent` to match?
- Does this issue need only **one** party to close it? If a second party has to act before it is done, that half is its own issue, and the dependency between them is a native blocked-by edge.

See `references/examples.md` for worked examples.
