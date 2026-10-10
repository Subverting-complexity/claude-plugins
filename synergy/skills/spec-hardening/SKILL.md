---
name: spec-hardening
description: 'Test a spec against the codebase before it is built: what would break the build or leave a builder guessing. Changes nothing; any host. Trigger on "harden this spec" or "is this spec solid".'
arguments:
  - name: spec
    description: 'Optional GitHub issue number or URL, a file path, or the spec text itself. Defaults to the spec in the conversation.'
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(git diff *)
  - Bash(git log *)
  - Bash(git status *)
  - Bash(git show *)
  - Bash(git branch *)
  - Bash(git ls-files *)
  - Bash(gh issue view *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(find *)
  - Bash(grep *)
  - Bash(rg *)
---

# Spec Hardening

Read one spec, test it against the codebase it will be built in, and report the few things that would make the build fail, undo the spec's own goal, or leave the builder guessing at behaviour someone will see. **Change nothing**: no edits to the spec, no commits, comments, labels or filed issues. The person reading the report decides what goes back into the spec.

**The report stays in this conversation.** Return it here and nowhere else: never post it as a comment on an issue, pull request or work item, on GitHub or on any other platform, and never write it to a file unless the person asks. Do not remark on where the repository is hosted.

This is the check made before building. `/synergy:verify-feature` is the same kind of read made after the code exists, and `/synergy:grill` is the interview that settles open questions.

Read `CLAUDE.md` for project rules if it exists.

## Output standard

Everything a person reads follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear.

## How much to report

A hardening report is short. Most specs have none to four problems worth raising, and a spec with none should get a one-line answer. Never pad a report to look thorough.

Raise a problem only if it passes both tests:

1. **It matters.** If the spec is built exactly as written, the build or its tests fail, the spec's own goal is not met or is undone, data is lost or corrupted, or someone sees behaviour the spec's author would not have chosen.
2. **A builder would not catch it anyway.** A competent developer working from this spec and the code would not notice it and handle it in the normal course of the work.

Leave these out, even when they are true:

- Tests, fixtures, snapshots, file names and call sites that follow mechanically from a change the spec already asks for.
- A wrong or loose explanation in the spec whose conclusion is right.
- Missing boilerplate: an out-of-scope section, a rollout plan or a test plan, unless the code shows the change is risky without one.
- Edge cases the code does not show can happen here, and cases whose right handling is obvious.
- Wording, naming, ordering and style.
- Things that could not be checked, unless one would change the verdict.

When unsure whether something passes, leave it out.

## Step 1: Get the spec

- **A GitHub issue number or URL:** `gh issue view <n> --comments`. Read the comments too, because decisions and corrections often live there. On a repository hosted anywhere other than GitHub, ask for the spec as text or a file, and never use that platform's own tools.
- **A file path:** read it whole.
- **Pasted text, or the spec already in the conversation:** use it as it stands.
- **Nothing given and no spec in the conversation:** ask for it in one plain-text question with no options, then stop.

Work out what the spec is meant to achieve. If you had to guess, say so in the report.

## Step 2: Ground it in the codebase

Read the code; never assume. If `.claude/ecosystem.md` exists, use the tools it lists first (Graphify to trace connections, Fallow for existing equivalents). If it does not, work by hand and say nothing about tools.

- Find every file, class, endpoint, table, field or setting the spec names, and check it exists and does what the spec says.
- Find the nearest existing feature that works the way this one would, and read how it is built. The spec should agree with that pattern or say why it departs.
- For each module the spec changes, find what depends on it, including implicit dependants: reflection, serialisation, config, scheduled jobs and stored data.
- Search for code that already does what the spec asks for, by what it does rather than by name.
- For any change to a stored shape, a default or a rule, find the data and the code that holds the old shape.
- Note the constraints the code already enforces (permissions, validation, limits) and any test that guards the behaviour being changed.

If the codebase has nothing relevant, for example a new project, say the check against the code was limited, and test the spec against itself.

## Step 3: Look for problems

Use this as a list of where to look, not a list to fill. Most specs have nothing under most of it.

- **The spec is wrong about the code.** It names something that does not exist, assumes behaviour the code does not have, or contradicts a rule, schema or constraint the code enforces. Existing data or configuration that will behave differently once the change lands.
- **Two parts cannot both hold.** Requirements that contradict each other, or a requirement the codebase makes impossible as described.
- **A guess that changes the result.** A value, format, rule or behaviour left open where the builder would have to choose and the choice is visible to a user or operator.
- **Something the spec never mentions that the code shows is affected.** A consumer, a stored value, a permission check or a second place the same rule lives, where missing it gives wrong results.
- **A case the code shows will occur, handled wrongly.** Existing data in the old shape, a second concurrent request, a dependency that fails, and empty or missing values, but only where the spec as written produces a wrong outcome.

## Step 4: Write each problem

Each problem is a short comment to the person who wrote the spec, in three to five sentences:

1. What the spec says, quoting the words that matter and naming the section.
2. What the code shows, naming the exact file, method or field in backticks. If the code cannot confirm it, say so conditionally ("if anything downstream reads `status` ...").
3. What goes wrong if it is built as written.
4. A real question where the answer depends on intent, or the specific change to make where it is clear.

Keep the uncertainty that is there, ask rather than instruct when intent is unclear, do not paste code back, and stop once the point and the question are clear. Never present a guess about the code as a finding.

Only when there are problems to present, read `skills/tone/SKILL.md` and apply it to them, so they read in the user's own voice.

## Step 5: Report

In this order. Each problem appears once, and a section with nothing in it is left out.

**Verdict.** The first sentence answers "is this spec ready to build?" with yes, no or conditionally. Then, in a sentence or two, say what the one or two biggest problems are, or that the spec holds up. If the purpose was a guess, say so here.

**Problems.** Blocking first, then Worth resolving, each under a heading with the location in the spec and the severity, and the comment from Step 4 under it:

```
#### 1. Migration version (Blocking)
```

`Blocking` means it breaks the build or undoes the spec's goal. `Worth resolving` means the spec can be built but a builder would have to guess something a user or operator will see. Nothing lower is reported.

**Touches outside the spec.** Only if Step 2 found a consumer or part of the system the spec does not mention and that a builder would probably overlook, and only if it is not already covered by a problem above. One line each.

Then stop. When more than two problems end in a question, add one line saying the person can run `/synergy:grill` on the spec to settle them.
