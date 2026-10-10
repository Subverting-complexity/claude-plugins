# Areas

An **area** is one part of the product, such as Library or Listening. Release notes are grouped by area, so every issue belongs to exactly one. Areas are required, not opt-in, and each repository keeps its own list.

This file keeps the name `area-epics.md` because other files cite it. Area epics were removed in 19.0.0: GitHub allows a parent at most 100 sub-issues, so an area held in the parent chain filled up and refused new issues.

## Where an area lives

- **The list** is the `## Areas` table in `ClaudeProject.md`: a name, one sentence on what the area covers, and a colour. A person decides the rows.
- **An issue's area** is its 1 `area: {name}` label. Nothing reads the parent chain for it, and no issue needs a parent.
- **The labels** come from the table. `wf labels-ensure` creates each one the repository lacks.

A parent is still allowed, and it means only grouping: a `Feature` under an `Epic`, a `User Story` under a `Feature` or an `Epic`. A `Bug` or a `Chore` may sit under anything.

## Choosing an area

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" areas
```

It prints `{"status":"ok","areas":[{"name","description","label"}],"count":N}`, the rows of the table, and reads nothing from GitHub. Choose the row whose `description` best covers the work and put its `name` in the `area` key of the spec entry:

```json
{"issues": [{"title": "Import a book from a folder", "kind": "story",
             "area": "Library",
             "fields": {"field-priority": "Medium", "field-effort": "Low",
                        "field-ownership": "Code agent"}}]}
```

When nothing fits well, choose the closest row and say so in one line of the issue body, so a person can move the issue or add a row. Do not add a row to hold one issue.

`wf issue-apply` writes the label with the issue. It refuses a new entry that has no `area`, with exit 22, and a name the table does not have. An update entry that names another area replaces the old label, so the issue never carries 2. `"state": "area"` is refused: it filed an area epic.

`wf areas --issue N` prints the area issue N carries, from its label alone. `area` is `null`, with a `reason`, when the issue has no area label, has more than 1, or has one that names no row. An issue filed by hand gets its label through `wf area-set` when `execute` or `bulk-execute` picks it, and `wf issue-audit` reports `no-area-label` and `many-area-labels` for each open issue.

## A repository with no areas table

Preflight fails with `areas-table`, and its `fix` says which of 2 cases applies.

**The repository never had area epics.** Agree the areas with a person, write the `## Areas` table (`/synergy:setup` asks for the rows and writes it), then run `wf labels-ensure`. Give each open issue its label with `wf area-set`.

**The repository has area epics**, each an `Epic` whose `Stage` is `Area`. Move it, once, in this order.

1. **Write the table with the `epic` column.** Give each row the number of its area epic. Each area epic needs exactly one row. Include an area epic that is already closed: a merge closes one whose sub-issues are all closed and sets its `Stage` to `Done`, so preflight no longer lists it and only its row tells the move what it was.

2. **Create the labels.**

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" labels-ensure
   ```

3. **Do a dry run.** It prints the counts per area and writes nothing.

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" area-backfill --dry-run
   ```

   If the status is `refused`, `stops` names the cause: an area epic with no row, a row whose epic is not an area epic, or a label that does not exist. Correct the table or run `labels-ensure`, then do the dry run again. Read `no_area`: each issue there reaches no area epic and gets no label, so give it one with `wf area-set`. Read `differs`: each issue there carries another area label than the one it resolves to, and the command leaves it as it is.

4. **Run it.** It labels every issue, open and closed, so notes for an old release keep their headings.

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" area-backfill
   ```

   If the status is `partial`, run it again. An issue that has its label is skipped, so the second run finishes the rest.

5. **Close the area epics.** Do this only after a person agrees.

   ```bash
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" area-backfill --close-epics
   ```

   The command closes the epics only when its own read finds no issue left to label and nothing in `differs`. Otherwise it closes nothing and `close_refused` says why. The parent links stay. An epic left open is an ordinary `Epic` to a merge: `wf post-merge` closes it when its last sub-issue closes. The `preflight --fix` sweep leaves an epic at `Stage` `Area` alone.

`wf area-backfill` and preflight are the only code that reads the `Area` stage, and only for this move. The org's `Stage` field no longer needs the option. A project's own release script that reads the area from the parent chain must read the label instead.
