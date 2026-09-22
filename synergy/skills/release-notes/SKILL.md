---
name: release-notes
description: 'Write user and internal release notes for a branch, PR or story, shown under the area epic each issue sits in. Trigger on release notes or "what shipped".'
---
# Release Notes

Writes two short texts for one change: **user release notes**, what someone using the product would notice, and **internal release notes**, what the team needs to know that the user notes do not say. They are the values `execute` and `bulk-execute` write to the org's `User release notes` and `Internal release notes` issue fields when a story reaches Done — or, when a merge is finished by a standalone `pr-review` pass instead, the values that step's auto-merge fallback writes in their place — and a person can ask for them on any branch.

Each story's notes are written to be concatenated. A project's release tooling builds its changelog by collecting the notes of every closed issue in a release, adding a heading for each issue's area and putting the internal lines last. This is what the **tooling** builds, never what you write:

```
User-facing

Library and reading
* Scrolling mode no longer freezes or stops after a fling, and scrolls more smoothly overall.
* Fixed two imports of the same file colliding and failing.

Behind the scenes
* Backfilled data checksums for older imported books.
```

The headings come from the tooling. The text you write is only the `* ` lines, and each must stand on its own beside lines written for other stories.

Read `_shared/wording-standard.md` and `_shared/banned-patterns.md` before writing. Both apply to both texts. `skills/user-facing-communication/SKILL.md` shapes what you say to the person **around** the notes, not the notes themselves.

## Process

1. Read the change and group it by what a user would notice, following `_shared/reading-changes.md`. The input is the current branch (the default), a pull request number, one story's commits inside a branch, or pasted notes.
2. Sort each group with **Which block** below, and write each user-facing group as one user line.
3. Write an internal line only for what **Which block** says belongs there.
4. Merge lines that say the same thing, drop anything too small to mention (a typo, a version bump, a renamed variable), then check every line against **Writing rules**.

## Which block

- **User** means a person using the product, never a developer, tester or the team. Developer and test tooling, the test suite, CI, build and release tooling, documentation, store listing and questionnaire text, and code comments are internal, however visible they are to the team.
- **An internal line never restates a user line.** For a user-facing change, write an internal line only when it records something the user line does not: a migration to apply, a new dependency or build, a secret or setting to configure, a new route or interface, a limit or plan gate, a known gap. If the only internal line would repeat the user line in code terms ("Rendered a reset button in the voice settings screen"), the internal block is `None.`
- **Never both `None.`** Every merged story gets at least one line. A change with nothing a user notices gets an internal line.

## Areas

The notes never name an area, a section or a part of the product as a heading or a label line, even when the change touches several. An issue's area is the nearest area epic above it in its parent chain (`references/area-epics.md`), and the tooling adds that heading. A person fixes a wrong area by moving the issue, not by editing the text.

**Run by hand** on a branch or pull request, say which area the lines will sit under, in a sentence outside the code blocks, so it is never copied into a field. Take the issue from the pull request's closing issue or the number in the branch name, then run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" areas --issue {number}` and name `area.title`. With no issue, or `area` null, say the issue sits under no area epic.

## Output format

Two blocks, in this order, each inside its own fenced code block so it can be copied:

```
User release notes

* Scrolling mode no longer freezes or stops after a fling, and scrolls more smoothly overall.
```

```
Internal release notes

* Added migration 0018, which needs applying to each deployed database.
```

The first line of each block is its label and is not part of the field value. Everything after it is `* ` lines and nothing else. A block with nothing to say reads `None.` under its label. Never invent a user-facing effect to fill the block.

## Writing rules

- **One change per line**, starting `* `, one or two sentences, at most 40 words. Every line stands alone: never a line that continues, qualifies or caveats the one before ("Turn this off in Reader settings", "None of it can fail a release"). Fold the caveat into its line or drop it.
- **Plain text only.** No bold, no backticks, no links, no headings, no issue or pull request numbers, no file paths.
- **User lines describe the product as it now is**, in the present tense: "You can now search the text of a book", "The reader's header is now one row". A fix starts "Fixed". Never "Added" or "Implemented" (that is the internal voice), never a commit-style imperative ("Fix Library sort"), no code identifiers. Name a screen or setting exactly as the product shows it, and write a path as `Settings > Library`.
- **Internal lines are past tense and start with a verb**: "Added", "Moved", "Fixed", "Removed". They may name a service, route, migration, dependency, plan limit or setting key someone would search for, but not files or functions, and still read as plain English.
- **Keep it short.** Most stories need one user line and at most one internal line. Three lines in a block is the ceiling; more means the lines are describing implementation steps rather than changes.
- **No em dashes**, and nothing from `_shared/banned-patterns.md`.

`post-merge` enforces the mechanical part before writing a field: it drops heading and label lines, strips bold and code marks, writes every line as `* `, and drops a repeated line or an internal line that repeats a user line. The rest is yours.

## When another skill calls this

`execute` and `bulk-execute` read this file before the merge and follow it for each story, with no reply to the user in between. `pr-review`'s auto-merge fallback (`references/auto-merge.md` step 6) reads it the same way, only when a merge finishes without `execute`/`bulk-execute` having already written `.claude/release-notes.json`. They need the two texts as data, not the two blocks: for each story, the user text is the user block without its label line, and the internal text is the internal block without its label line. Skip the **Run by hand** step. A block that reads `None.` becomes an empty string, so the field is left blank. The calling workflow says where to write them.
