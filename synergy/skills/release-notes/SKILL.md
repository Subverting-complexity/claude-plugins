---
name: release-notes
description: 'Write user and internal release notes for a branch, PR or story, shown under the area epic each issue sits in. Trigger on release notes or "what shipped".'
---
# Release Notes

Writes two short texts for one change: **user release notes**, what someone using the product would notice, and **internal release notes**, what changed under the hood. They are the values `execute` and `bulk-execute` write to the org's `User release notes` and `Internal release notes` issue fields when a story reaches Done, and a person can ask for them on any branch.

Each story's notes are written to be concatenated. A project builds its changelog by collecting the notes of every closed issue in a release, grouping the user lines by each issue's area and putting the internal lines last, so each line must stand on its own beside lines written for other stories:

```
User-facing

Library and reading
* Scrolling mode no longer freezes or stops after a fling, and scrolls more smoothly overall.
* Fixed two imports of the same file colliding and failing.

Settings
* Settings has been reorganised into grouped rows with icons and clearer wording.

Behind the scenes
* Backfilled data checksums for older imported books.
* Cleaned up the test suite and build tooling.
```

Read `_shared/wording-standard.md` and `_shared/banned-patterns.md` before writing. Both apply to both texts. `skills/user-facing-communication/SKILL.md` shapes what you say to the person **around** the notes, not the notes themselves.

## Process

1. Read the change and group it by what a user would notice, following `_shared/reading-changes.md`. The input is the current branch (the default), a pull request number, one story's commits inside a branch, or pasted notes.
2. Write each user-facing group as one user line.
3. Write each internal-only group, and the internal part of a user-facing group worth recording, as one internal line.
4. Merge lines that say the same thing, and drop anything too small to mention: a typo, a version bump, a renamed variable.

## Areas

The notes never name an area. An issue's area is the nearest area epic above it in its parent chain (`references/area-epics.md`), and the changelog groups each issue's lines under that epic's title. That is one source every release tool reads, and a person fixes a wrong area by moving the issue, not by editing the text.

So this skill takes no area decision. A change a user would notice in two areas stays one issue with one area: say what changed in plain words, and the person reviewing the release can move the line.

**Run by hand** on a branch or pull request, show the area the notes will be grouped under, so the output looks like the final changelog. Take the issue from the pull request's closing issue or the number in the branch name, then run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" areas --issue {number}` and use `area.title` as the heading. With no issue, or `area` null, show the lines with no heading and say the issue sits under no area epic.

## Output format

Two blocks, in this order, each inside its own fenced code block so it can be copied:

```
User release notes

* Scrolling mode no longer freezes or stops after a fling, and scrolls more smoothly overall.
```

```
Internal release notes

* Laid the groundwork for full-text search in books.
```

The first line of each block is its label and is not part of the field value. Neither block names an area. Only when run by hand does the user block carry one heading line, the area from **Areas**, between the label and the lines; it is display only and never part of the field value.

A block with nothing to say reads `None.` under its label: a chore or internal fix has no user release notes, and a wording-only change may have no internal ones. Never invent a user-facing effect to fill the block.

## Writing rules

- **One line per change**, starting `* `, one or two sentences, understandable without the rest of the list.
- **User lines describe the product as it now is.** Lead with the thing a user knows and what it now does: "The Library header is more compact, with a collapsible search field", "Scrolling mode no longer freezes after a fling". A fix may start "Fixed": "Fixed two imports of the same file colliding and failing." No code identifiers, no jargon, nothing a user could not see.
- **Internal lines say what the team would want to know**, in past tense: "Backfilled data checksums for older imported books", "Ported gesture handling from the sibling apps". They may name a part of the system, a service, a migration or a configuration setting, but describe behaviour rather than list files, and still read as plain English.
- **Keep it short.** Most stories need one user line and one internal line. More than four lines in a block means the grouping is too fine.
- **No em dashes**, and nothing from `_shared/banned-patterns.md`.

## When another skill calls this

`execute` and `bulk-execute` read this file before the merge and follow it for each story, with no reply to the user in between. They need the two texts as data, not the two blocks: for each story, the user text is the user block without its label line, and the internal text is the internal block without its label line. Neither carries an area heading, so skip the **Run by hand** step. A block that reads `None.` becomes an empty string, so the field is left blank. The calling workflow says where to write them.
