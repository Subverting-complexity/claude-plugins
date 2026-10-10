# Area epics

Every project that uses this plugin organises its issues under **area epics**. Release notes are grouped by area, so every finished issue has to resolve to exactly one area. Areas are required, not opt-in, and each repository keeps its own list.

## The hierarchy

- **Area.** An `Epic` whose `Stage` is `Area`: one permanent part of the product, such as Library or Listening. It is never closed. Its body says what the area covers, in a sentence or a short list, because that is what an agent reads to choose an area.
- **Feature.** A piece of planned work, under an area.
- **User Story.** One buildable slice, under a feature. When no feature fits, it goes directly under an area rather than under a feature invented to hold it.
- **Bug** and **Chore.** Under a feature, or directly under an area.

An issue's area is the nearest area epic above it in its parent chain. An `Area` issue is never picked, never closed by `wf post-merge` or `preflight --fix`, and never moved by `wf board-sync`, and `wf issue-audit` does not ask it for `Priority`, `Effort` or `Ownership`.

Planned work no longer gets an `Epic` of its own. What used to be an epic is a `Feature` under an area, and what used to be a feature under that epic is a story, or a feature beside it.

## Choosing an area

List the open area epics and read their bodies:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" areas
```

It prints `{"status":"ok","areas":[{"number","title","url","body"}],"count":N,"rows":[{"name","description","epic"}]}`. Pick the area whose body best covers the work. When nothing fits well, file under the closest area and say so in one line of the issue body, so a person can move it or add an area. Do not create an area to hold one issue: an area is a permanent part of the product, and adding one is a decision for a person.

`rows` is the `## Areas` table in `ClaudeProject.md`, and it is empty in a project that has no table. Every issue also carries exactly 1 `area: {name}` label, so release notes can place it without a parent. Choose the row whose `description` best covers the work and put its `name` in the `area` key of the spec entry, beside `parent`:

```json
{"issues": [{"title": "Import a book from a folder", "kind": "story",
             "parent": 310, "area": "Library",
             "fields": {"field-priority": "Medium", "field-effort": "Low",
                        "field-ownership": "Code agent"}}]}
```

`wf issue-apply` writes the label with the issue. In a project with an Areas table it refuses a new entry that has no `area`, with exit 22, and a name the table does not have. An area epic (`"state": "area"`) needs none. An update entry that names another area replaces the old label, so the issue never carries 2. A row's `epic` is the number of the open area epic whose title is the row's name, or `null`. An issue filed before this, or by hand, gets its label when `execute` or `bulk-execute` picks it, through `wf area-set`.

## Moving an existing project onto areas

Preflight warns `area-epics` while the repository has no open area epic, and `wf issue-audit` reports `no-area` for each open issue whose parent chain reaches none. Work through it in this order.

1. **Create the area epics.** One `Epic` per permanent part of the product, at `Stage` `Area`, with a body saying what it covers. Agree the list with a person first. Through `wf issue-apply`, give each entry `"kind": "epic"` and `"state": "area"`; such an entry needs no `Priority`, `Effort` or `Ownership`. By hand, create the `Epic` in GitHub and set its `Stage` to `Area`.

   ```json
   {"issues": [{"key": "area-library",
                "title": "Library",
                "body_file": ".claude/area-library-body.md",
                "kind": "epic",
                "state": "area"}]}
   ```

2. **Retype each existing epic to a `Feature` under its main area, and move its child features up beside it.** The child features become direct children of the same area, so the tree stays area, feature, story. Put both in one spec, as update entries naming each issue's `number`, so no feature is left sitting under another feature (which `issue-apply` refuses):

   ```json
   {"issues": [{"number": 120, "kind": "feature", "parent": 301},
               {"number": 121, "parent": 301},
               {"number": 122, "parent": 301}]}
   ```

   A retyped epic becomes work, so it needs `Priority`, `Effort` and `Ownership`, either already on the issue or in its entry; an old epic often has none, and then `issue-apply` refuses the whole spec before writing anything. `"kind": "feature"` also writes a `Classification` of `New Feature`.

   Here #120 was the epic, #121 and #122 were its features, and #301 is the area. Where the old epic's work spans two areas, choose its main one; a child feature that clearly belongs to another area goes under that one instead.

3. **Attach what has no parent.** Give each parentless bug, chore and feature a `parent`: an area, or an open feature in that area when one clearly fits. A story needs a parent too: a feature, or the area directly when no feature fits.

4. **Check.** Run `wf issue-audit` (`references/setup-issues.md`) and fix each `no-area` it still reports. Repeat until none is left.
