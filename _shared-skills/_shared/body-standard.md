# Body Standard

One standard for **every body this plugin writes into a tracker or forge**: a
GitHub issue, a pull request description, a merge request description, a work
item, and any comment posted on one. They are read the same way, by the same
people, in the same views, so they are written the same way.

Entry points sit on top of this file and hold only the part that actually
differs, which is **which sections a body has**:

| Entry point | Governs | Its own section shape |
| ----------- | ------- | --------------------- |
| `skills/pr-body/SKILL.md` (github-workflow) | GitHub pull request titles and bodies | Fixed: `## Summary` → `## Changes` → `## Test plan`, then the `Closes #N` lines |
| `skills/pr-description/SKILL.md` (local-workflow) | Pull request titles and bodies on any platform | `## Summary`, then one `##` section per component |
| `writing-github-issues` (github-workflow only) | GitHub issue titles and bodies | `## Summary` plus only the sections that carry information, the `[Manual]` convention, and the single write path |

The two pull request entry points are deliberately different and neither is
synced onto the other. github-workflow's is fixed because `execute`,
`bulk-execute` and `code-review` read and extend those bodies, and a shape
that varies per pull request cannot be extended reliably. local-workflow's
description is written for whoever is about to read the diff, with no
automated loop behind it, so it groups by component instead.

Where a plugin does not ship the issue entry point, this file plus
`references/story-template.md` is the whole standard for a work item.

Everything below applies to all of them. No entry point restates it, and
none may contradict it.

---

## 1. Never hard-wrap

Write each paragraph as **one single line**, however long it runs. Never
break prose across lines at 72, 80 or any other column.

GitHub, GitLab, Azure DevOps and Bitbucket all reflow markdown to the width
of whoever is reading it. A hard-wrapped paragraph is not tidier: it fixes
the line breaks at a width that suits nobody, it wraps a second time in a
narrow pane or a notification email, and it makes the body painful to edit,
because changing one word means rewrapping the paragraph.

Correct:

```markdown
Read-only Settings rows with a value are currently read as 2 separate accessibility elements. `SettingsRow` creates the correct accessibility label, but `ListRow` drops it for non-interactive rows.
```

Not this:

```markdown
Read-only Settings rows with a value are currently read as 2 separate
accessibility elements. `SettingsRow` creates the correct accessibility
label, but `ListRow` drops it for non-interactive rows.
```

The only line breaks a body has are the ones markdown needs: between
paragraphs, between list items, around headings, and inside fenced code
blocks. A bullet that runs long stays on one line too.

---

## 2. The sections are fixed, not invented per body

Each entry point names the sections its bodies use. Use those names, that
spelling, that order, every time. Do not rename a section, reorder them,
merge two into one, or invent a top-level heading in place of one. Pick the
shape from the entry point for what you are writing, not from the last body
you happened to see.

Where an entry point uses the shared section names, they mean the same thing
in an issue as in a pull request:

| Section | What goes in it |
| ------- | --------------- |
| `## Summary` | The point, in plain sentences. Always present, always first. |
| `## Cause` | The known cause, when it tells the reader where the fix belongs. |
| `## Changes` | What changed or has to change, as bullets. Outcomes, not a development diary. |
| `## Acceptance criteria` | Short, testable statements. Usually 2 to 5. |
| `## Test plan` | How the change was verified: commands run, tests added, anything checked by hand. |
| `## Verification` | What verifying needs beyond the obvious: a physical device, several environments, a regression check. |
| `## Dependencies` | Real ordering constraints only, as exact markers (`Depends on #N`, `Blocked by #N`). |
| `## Manual step` | The work cannot be finished until a person does something no agent can do. Say exactly what, and why. |
| `## Out of scope` | Closely related work that must not be pulled in. |

Never add a section outside that list, except the component headings
local-workflow's pr-description calls for, which are named after the module,
service or file group they cover. In particular, no Notes, no Background, no
Context, no Risks, no Screenshots heading with nothing under it, and no
closing paragraph that restates what the body already said.

**Never create an empty section.** A heading with a placeholder under it, or
with one line saying there is nothing to add, is worse than no heading.

---

## 3. Summary

The first sentence states the actual point: what is wrong, what is needed, or
what the change does. Not how it was found, not what was investigated.

The Summary stands alone. A reader who stops there understands the work
without opening the diff or the linked issue.

Write it as complete sentences in plain English, not bullets and not
telegraphic fragments. Two to four sentences is normal; one is fine for
something trivial.

Nothing below the Summary repeats it.

---

## 4. Bullets

- One point per bullet, each on its own single line.
- Lead with a verb: `Added`, `Removed`, `Refactored`, `Updated`,
  `Introduced`, `Renamed`, `Adjusted`, `Modified`, `Extracted`, `Simplified`.
- Wrap every identifier in backticks so it stays exact: class and method
  names, file paths, flags, config keys, states.
- Combine bullets that share an action or a parent concept, either inline
  (`Added tests: A, B, and C`) or with sub-bullets.
- Be specific. No "various improvements", no "general cleanup", no
  "miscellaneous fixes".
- No prose paragraphs inside a bullet list. The prose lives in the Summary.
- Group bullets under `###` sub-headings only when the body covers more than
  three separate areas. Below that, a flat list reads better than headings
  with one bullet each.

---

## 5. Titles

- Start with a verb where the work is a change: `Fix`, `Add`, `Remove`,
  `Split`, `Document`. A bug report may instead name the broken behaviour.
- Sentence case. No trailing full stop.
- Roughly 70 characters or fewer, so it survives list views, boards and
  notification emails uncut.
- Keep identifiers exact.
- **No metadata.** No `[BUG]`/`[STORY]`/`[DEBT]` prefix, no priority, no
  size, no sprint, no component tag, no issue number. The tracker renders the
  type, the labels and the fields beside the title already, and a copy in the
  title costs width and drifts out of step the moment one of them is edited.
- The one permitted prefix is `[Manual]`, on a work item a person has to
  finish. The issue entry point defines it.

The title lives in the title field. Never repeat it as a heading in the body.

---

## 6. What never appears in a body

- Investigation history, debugging steps, grep results, failed theories, or
  any other proof that the work was done thoroughly.
- The same information in two sections.
- Implementation detail that does not change what the reader has to do.
- Certainty the source did not have. Keep "likely", "may" and open questions
  as they were written.
- Anything in `_shared/banned-patterns.md`. It applies to bodies in full, and
  no entry point relaxes it.

---

## 7. Style

Say the thing. Do not describe yourself saying it.

Prefer:

> `ListRow` drops the accessibility label for non-interactive rows.

Over:

> The underlying cause appears to be related to the way `ListRow` handles accessibility properties in the non-interactive branch.

Prefer:

> No behaviour changes are needed.

Over:

> This change should be limited exclusively to comments and should not alter runtime behaviour.

Use plain English and British spelling. Avoid filler openers such as:

- "For context"
- "It should be noted that"
- "As mentioned above"
- "The purpose of this issue is to"
- "This pull request aims to"
- "Found while working on"

---

## 8. Before you post it

- Is the point clear in the first sentence?
- Does the Summary stand on its own?
- Is every section from the vocabulary above, and does every one carry
  information?
- Is anything said twice?
- Has uncertainty survived?
- Is every paragraph on a single line, with no hard wrapping?
- Are machine-read markers intact and exact (`Closes #N`, `Depends on #N`,
  `Blocked by #N`, `**Size estimate:**`)?
- Can anything else go without making the work harder to do or to verify?

If yes, remove it.

---

## Related standards

- `_shared/banned-patterns.md` — words, phrases and structural habits that
  never appear in any output, bodies included.
- `_shared/wording-standard.md` — how everything **else** a person reads is
  worded. A body is shorter than that standard would produce, and this file
  wins inside a body.
- `skills/user-facing-communication/SKILL.md` — the shape of what you say
  **about** the issue or pull request when you report back. That is your
  reply, not the body, and it never reaches into the body.
