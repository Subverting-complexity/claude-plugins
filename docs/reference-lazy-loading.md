# Lazy-loading reference files in skills

How this repo keeps a skill's *hot path* — the instructions loaded into context on every invocation — small while still carrying full detail for the rare paths. Used most heavily by `github-workflow`'s `code-review` and `execute` skills.

## Why

A skill's `SKILL.md` body is read in full every time the skill runs, so every line spends instruction tokens whether or not the run needs it (`check-budgets.sh` ratchets these body line counts). But much of a workflow is conditional: auto-merge only fires on an Approved verdict, duplicate reconciliation only when two PRs close the same issue, read-only overrides only under `--read-only`. Inlining those paths makes every run pay for the one-in-ten case.

## The pattern

Split the conditional detail into `references/*.md` files next to the skill, and leave a **dispatch stub** in `SKILL.md` at the point where the path branches:

> If <trigger condition>, load `references/<file>.md` and follow it.

The stub states the trigger, a one-line summary of what the reference does, and where control resumes — enough to route correctly without the detail. The reference file opens by restating its trigger ("Read this when …") so a model landing in it can confirm it belongs there. References may themselves load further references at the point of need — e.g. code-review's `auto-merge.md` loads `conflict-resolution.md` only when the PR is actually conflicting.

## Exemplar: code-review

`github-workflow/skills/code-review/SKILL.md` keeps the every-run review loop (find, claim, read, evaluate, fix, post, label) inline and defers the rest to references loaded on their triggers: `read-only-mode.md`, `duplicate-reconciliation.md`, `rework-cascade.md`, `re-review.md`, `auto-merge.md` (which loads `conflict-resolution.md`), `review-workflow.md` (label lookup and the Step 10 fallback), and `review-config-guide.md`. Its "Reference Material" section lists each file with its trigger. `execute` follows the same shape (`finish.md`, `review-and-merge.md`, `escape-hatches.md`, `audit-mode.md`, …), and `review-and-merge.md` in turn loads code-review's `auto-merge.md` rather than restating the merge mechanics — a reference may be shared across skills.

## When to extract a new reference

Extract when detail is needed **only on some runs** — a conditional branch, a fallback used only when a tool is missing or errors, an error-recovery path — and it is long enough that inlining costs every run more than a stub would. Keep inline what every run executes; the stub must preserve step ordering and any hard rules (the "one sanctioned merge/close" kind stay visible in `SKILL.md`'s Rules). Rationale files (`*-rationale.md`) are a separate convention: maintainer background, never loaded at runtime.
