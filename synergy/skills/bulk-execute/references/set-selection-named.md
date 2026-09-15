# Bulk Execute — Phase 1, Path A (named stories)

Read this only if the user named stories (`$ARGUMENTS.story_numbers` is present). **Claiming the set**, **Recording the set** and **Dropping a story** are in `set-selection.md`, and the two rules that hold throughout are at its top.

## Path A — the user named the stories

`$ARGUMENTS.story_numbers` is present, e.g. `/synergy:bulk-execute 41 43 47`. The choice has been made, so do not re-litigate relatedness: a person who names three issues is asserting they belong together, and that assertion outranks the heuristics below. Two things still apply — the size cap, and the fact that a story which cannot be worked cannot be built.

**1. Validate each named story in one batch.** Read the pool once — it is the answer to "is this story available", because it *is* the blank-or-`Backlog` stage issues with the unavailable already filtered out:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" candidates --mode {mode} --limit 0
```

Then read each named number for its own content:

```
gh issue view {number} --repo {org}/{repo} --json state,assignees,title,body,milestone
```

That JSON deliberately does not ask for labels. No label says what stage an issue is at, how urgent the story is or who owns it, so there is nothing in a label list to decide on — the stage is the `Stage` field's answer, which `wf candidates` has already given.

Drop a named story, with a one-line reason in your report, when it is:

- **closed** — nothing to build;
- **already in flight** — its stage is `In Review`, or an open pull request already closes it. Ask once per number:
  ```bash
  bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" sibling-pr {number}
  ```
  Exit 0 with `found: 0` means nothing closes it; exit 20 means the lookup failed, so say so rather than assuming it is free. Report any PR found by number and title and say `/synergy:pr-review` handles it;
- **assigned to someone else** — another agent or person owns it;
- **empty** — no Context and no Requirements anywhere in the body, comments or linked docs, so any implementation would be a guess;
- **not in the pool** — the number came back in none of the `wf candidates` entries, so it is not an unassigned, available issue a code agent may take. Its stage is `Needs refinement`, `Parked`, `Blocked` or `Non-code`, or its `Ownership` is not `Code agent`. Read the reason off the issue's fields and name it; `pick --issue` refuses the same story anyway, so claiming it would only fail later.

If a named story is at `In Review` but **no** open PR is found, check for a **closed, unmerged** PR (`closingIssuesReferences`, `states: CLOSED`). If there is one, the PR was abandoned: reset the issue automatically — unassign, set the stage to `Backlog` (`wf stage-set {number} --stage stage-backlog`), comment `"Resetting — PR #{N} closed without merge."` — and keep it in the set. If there is no closed PR either, surface the inconsistency and drop it.

**2. Cap the size.** More than `--size` stories (default 5, which is also the maximum) were named. Keep the first `--size` in the order the user gave them, and say which were left out and that they stay in the pool. Do not silently build more than the cap: the cap is what keeps the pull request reviewable.

**3. Warn, but obey, on a set that looks unrelated.** If the named stories share nothing by the rules in Path B (`references/set-selection-open.md`), say so in one sentence in your report and build them anyway. The user's instruction stands; your job is to make the consequence visible, not to override it.

**4. Put the survivors in build order and name the lead.** Same rule as Path B step 3: every story comes after the stories in the set it depends on, and stories with no dependency between them keep the order the user gave them. That is `plan_bulk_order` in `scripts/wf_core.py`. The first story in build order is the **lead** — it names the branch, and it is the one story never dropped while any code exists.

Then go to **Claiming the set**.
