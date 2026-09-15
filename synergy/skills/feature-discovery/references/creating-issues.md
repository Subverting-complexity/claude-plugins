# Feature Discovery — Creating issues on GitHub

Read this only when the user has approved the plan and accepted the offer to create the stories as GitHub issues. "Deferred speccing" and the other sections it names are in `SKILL.md`.

0. Write each title and body to the `writing-github-issues` standard (its story shape is `references/story-template.md`). The interview produces far more material than a story needs, so this is where most of it gets left behind: no discovery history, no restating the Summary under another heading, and no section that would be empty. Write each paragraph on one unwrapped line (`_shared/body-standard.md`).

   A story that cannot be finished without a person, because it needs a permission or an approval no agent can give, is marked three ways together: `[Manual]` at the front of the title, `Ownership` set to `Human`, and a `## Manual step` section saying what has to be done and why. The field is the one that matters — it is what keeps the story out of the code agent's pool, and `issue-apply` sets its stage to `Non-code` from it.

   Check once, before the first issue, whether the repository publishes an issue template, either its own or one inherited from the organisation's `.github` repository. Where one applies, every story uses its headings and order. This is resolved through `templates/issue-template-resolution.md`; the result is cached, so check once rather than per story.
1. **One write for the whole set.** Every issue is created by `wf issue-apply` from a single spec — title, body, native issue type, field values, labels, parent and dependency edges together. Not a `gh issue create` loop, and not create-then-upgrade: an issue that exists for a few seconds carrying only labels is what put half-classified stories in the backlog.

   The command works in dependency order for you. Entries reference each other by `key` before any of them has a number, parents are created before children, and edges are written last, so the whole tree is one command whatever its shape.

   Write each story's body to its own file in `.claude/` with the Write tool, then the spec beside them:

   ```bash
   mkdir -p .claude
   cat > .claude/discovery-spec.json <<'JSON'
   {"issues": [{"key": "epic",
                "title": "{epic title}",
                "body_file": ".claude/epic-body.md",
                "kind": "epic",
                "fields": {"field-priority": "{Urgent|High|Medium|Low}",
                           "field-effort": "{Low|Medium|High}",
                           "field-ownership": "Code agent",
                           "field-origin": "Feature Discovery"}},
               {"key": "feature-1",
                "title": "{feature title}",
                "body_file": ".claude/feature-1-body.md",
                "kind": "feature",
                "parent": "epic",
                "fields": {"field-priority": "{Urgent|High|Medium|Low}",
                           "field-effort": "{Low|Medium|High}",
                           "field-ownership": "Code agent",
                           "field-origin": "Feature Discovery"}},
               {"key": "story-1",
                "title": "{story title}",
                "body_file": ".claude/story-1-body.md",
                "kind": "story",
                "parent": "feature-1",
                "blocked_by": ["{other key or issue number}"],
                "fields": {"field-priority": "{Urgent|High|Medium|Low}",
                           "field-effort": "{Low|Medium|High}",
                           "field-ownership": "Code agent",
                           "field-type": ["New Feature", "{area}"],
                           "field-origin": "Feature Discovery"}}]}
   JSON
   bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" issue-apply .claude/discovery-spec.json
   ```

   - Each body goes in its own file and the entry names it (`body_file`) rather than carrying the text, so fenced code, backticks, `$` and quotes survive intact. The rule is stated once in `templates/body-file-write.md`.
   - `kind` supplies the native type **and** the `Classification` value together (a story → User Story / New Feature, a feature → Feature, an epic → Epic), so neither is chosen by hand. Use `spike` for a research story.
   - `field-type` adds each area the entry's work touches, beside the kind's value (`writing-github-issues` → **Adding areas**). It replaces the `kind` default, so it always names that value too, never areas alone. Leave it out where the work touches no area or the org defines no area options.
   - `parent` is required on every story, naming its feature, and set on a feature that belongs to an epic, by spec `key` or by the issue number of one that already exists. Drop the epic entry and the feature's `parent` when the work is a single feature. An epic takes none.
   - **No labels at all**, and no `[STORY]` title prefix. The native type classifies the issue and the fields carry everything a decision reads; `issue-apply` strips a retired label or a type prefix if a spec still names one, and says that it did.
   - `field-effort` comes from the story's size estimate: large → **High**, medium → **Medium**, small → **Low**.
   - `field-priority`, `field-effort` and `field-ownership` are **required on every entry** — they are the pool's order, its size ceiling and whether a code agent may take the story at all, and `issue-apply` refuses a spec that leaves one blank. `field-ownership` is `Code agent` for a story a code agent will build, and `Browser agent` or `Human` for one it cannot.
   - `blocked_by` writes a native edge, and `issue-apply` then sets the stage to `Blocked` for any entry whose edges point at something still open.
   - Add `"milestone": "{title}"` to an entry in sprint mode. It must name an open milestone.
2. Name every dependency in the entry's `blocked_by`. Where the dependency is another entry in the same spec and has no number yet, reference it by `key` and `issue-apply` resolves it once both exist.
3. **Do not set a stage by hand.** `issue-apply` writes every stage from the issue's own fields: one owned by a person or a browser agent goes to `Non-code`; one whose edges point at something still open goes to `Blocked`; everything else goes to `Backlog`, which is what available means. A **deferred** story (see "Deferred speccing" in `SKILL.md`) is the one case the fields cannot express, because nothing on the issue says its spec is thin — say so with `"state": "refinement"` on the entry, which is read before the edges and sets the stage to `Needs refinement`.
4. **Read the exit code.** **0** created them, and every issue number is written back into the spec file, so a re-run after a partial failure completes the remainder rather than filing duplicates. **21** (`no-capabilities`) means the org defines no types or fields — report that the stories could not be classified rather than filing them unclassified by hand. **22** means the spec is wrong (an unknown label, a milestone that is not open, a missing required field, a story with no feature parent, or an org that defines no `Priority`, `Effort` or `Ownership` field at all), so fix it and re-run. **23** and **24** mean the issues exist but some metadata did not land, so name what failed and carry on.

   Where the command is unavailable, say so and stop rather than hand-writing the mutations.
5. After creation, check the dependency graph against the edges `issue-apply` reports back, not against anything in the bodies — a body never records a dependency. `issue-apply` reads each body back in the same request, so body corruption is already reported; only if it flagged a mismatch, apply the corruption test and retry in `templates/body-file-write.md`.
6. Present a summary: issue numbers, titles, native type, priority and effort, and the dependency graph with issue numbers filled in.

**Leave the assignee blank.** Do not assign created stories to anyone — not the creator, not an agent. Pass no `--assignee`/`--add-assignee` on creation and do not edit issues to assign them afterward. Backlog stories must enter the unassigned pool so `execute` can select them; assignment happens only at claim time, never at creation.
