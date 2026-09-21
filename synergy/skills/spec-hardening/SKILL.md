---
name: spec-hardening
description: 'Test a spec against the codebase before it is built: gaps, conflicts, vague wording, missing cases. Changes nothing; any host. Trigger on "harden this spec" or "is this spec solid".'
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

Read one spec and test it against the codebase it will be built in, then report what it misses, gets wrong or leaves open, so the gaps are settled before anyone writes code. **Change nothing**: no edits to the spec, no commits, comments, labels or filed issues. The person reading the report decides what goes back into the spec.

**The report stays in this conversation.** Return it here and nowhere else: never post it as a comment on an issue, pull request or work item, on GitHub or on any other platform, and never write it to a file unless the person asks. Do not remark on where the repository is hosted.

This is the check made before building. `/synergy:verify-feature` is the same kind of read made after the code exists, and `/synergy:grill` is the interview that settles the open questions this skill finds.

Read `CLAUDE.md` for project rules if it exists.

## Output standard

Everything a person reads follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear.

## Step 1: Get the spec

- **A GitHub issue number or URL:** `gh issue view <n> --comments`. Read the comments too, because decisions and corrections often live there. On a repository hosted anywhere other than GitHub, ask for the spec as text or a file, and never use that platform's own tools.
- **A file path:** read it whole.
- **Pasted text, or the spec already in the conversation:** use it as it stands.
- **Nothing given and no spec in the conversation:** ask for it in one plain-text question with no options, then stop.

Restate it before going on, in three lines: what it is meant to achieve, who it is for, and what it says is out of scope. If any of the three is missing from the spec, say so: that is the first finding. If you had to guess the purpose, say "This spec appears to be for X. Testing it against that; correct me if not."

Then number each requirement and acceptance criterion as `R1`, `R2` and so on, in the spec's own order, so findings can point at them. Quote the spec's own words when pointing at one.

## Step 2: Ground it in the codebase

Everything below is read from the code, never assumed. If `.claude/ecosystem.md` exists, use the tools it lists first (Graphify to trace connections, Fallow for existing equivalents). If it does not, work by hand and say nothing about tools.

- **Every named thing.** For each file, class, endpoint, table, field, setting, screen or command the spec names, find it. Note whether it exists, whether it does what the spec says it does, and whether the spec's name for it matches the code's.
- **The place it lands.** Find the nearest existing feature that works the way this one would, and read how it is built: its layers, its data, its permission checks, its errors, its tests. The spec should agree with that pattern or say why it departs from it.
- **What it reaches.** For every module the spec would change, read the whole file, what it imports and what imports it. Find each caller and consumer, including implicit ones: reflection, serialisation, config, scheduled jobs, stored data and other services.
- **What already exists.** Search for code that already does what the spec asks for, by what it does (the rule, the field, the message), not by name. The spec may be asking for something that is there, or something that is half there.
- **The existing data.** For any change to a stored shape, a status, a default or a rule, find what already holds the old shape, and what reads it.
- **The constraints the code already carries.** Permissions, validation, limits, timeouts, rate limits, feature flags, environment differences, and the conventions and rules in `CLAUDE.md`.
- **How it would be tested.** Find the test setup and the nearest tests, so a spec can be judged on whether its criteria could be checked with what exists.

If the codebase has nothing relevant, for example a new project, say the codebase check was limited and test the spec against itself and against the standard behaviour of the stack it names.

## Step 3: Look for problems

- **Conflicts with the code.** Names something that does not exist or is called something else. Assumes behaviour the code does not have. Contradicts an existing rule, permission, schema, constraint or convention. Depends on work that has not been done.
- **What it leaves out.** Surfaces Step 2 found that the spec never mentions: consumers of a changed export, stored data that needs migrating, permission checks, configuration, settings and defaults, error messages, notifications, audit or logging, documentation, existing tests that will now fail.
- **Cases it does not cover.** For each requirement, walk zero, one, many and the maximum, empty and null, negative and out-of-range, the same request twice, two people at once, a half-finished operation, a dependency that is down or slow, a user without permission, and data from before this change. Report only the cases the code shows can happen here.
- **Wording that cannot be built or checked.** Words such as "fast", "secure", "appropriate", "as needed" or "similar to" with no value or reference. A requirement with two reasonable readings. A number, limit, format or default left unstated. A passive sentence that hides who or what acts.
- **Inconsistency within the spec.** Two requirements that cannot both hold. One term used for two things or two terms for one. A requirement with no acceptance criterion. A criterion that tests nothing the requirements ask for.
- **Criteria that cannot be verified.** Each acceptance criterion should be something a person or a test can pass or fail with the setup Step 2 found. Flag one that needs data, access or a state the project has no way to reach.
- **Change and rollout.** No way to turn it off or undo it. No plan for existing data, existing users or a partly deployed system. A breaking change to an interface other things use.
- **Scope.** No stated boundary. Two features hiding in one spec. Too large to build and review as one piece, with a suggested split where the code shows a natural seam.
- **Qualities the code shows matter here.** Security and privacy of the data involved, load on a path that is already hot, accessibility of a screen, and what an operator would need to see when it breaks. Raise these only where the code makes them relevant.

Report only what would change what is built or how it is tested if the author acted on it. Taste and style are left out. A small, objective blemish, such as a typo or an inconsistent name, goes under Nitpicks.

## Step 4: Write each problem as a comment

Each problem is a short comment to the person who wrote the spec:

1. What the spec says, pointing at it by `R` number and quoting the words that matter.
2. What the codebase shows, naming the exact file, method or field in backticks, in one plain sentence. If the code cannot confirm it, say so conditionally ("if anything downstream reads `status` ...").
3. What follows if the spec stays as it is, in plain words.
4. A real question where the answer depends on intent, or the specific wording or requirement to add where the answer is clear.

Keep the uncertainty that is there, ask questions rather than issue instructions when intent is unclear, do not paste code back, and stop once the point and the question are clear. Severity goes in the heading, never in the prose. Never present a guess about the code as a finding: if a claim could not be checked, put it under Could not check.

Only when there are problems to present, read `skills/tone/SKILL.md` and apply it to them, so they read in the user's own voice.

## Step 5: Report

In this order, skipping any section with nothing in it rather than writing "none found":

**Verdict.** Answer "is this spec ready to build?" with yes, no or conditionally in the first sentence. Then one short paragraph: what the spec covers well, and the two or three problems that matter most. Give the counts as `2 blocking, 5 worth resolving, 3 nitpicks`.

**How I read it.** The three lines from Step 1, then the numbered requirements as a compact list, one line each. This lets the author see straight away if the spec was misread.

**What it touches.** The parts of the codebase the spec reaches, as a short list: each module, screen, endpoint, table or job, the existing feature it most resembles, and which consumers outside the spec depend on what it changes.

**Problems at a glance.** A table with one row per Blocking and Worth-resolving problem, so the whole picture fits on one screen:

```
| # | Severity | Where in the spec | Problem |
|---|----------|-------------------|---------|
| 1 | Blocking | R3 | Names `OrderExport`, which does not exist; `InvoiceExport` does the same job |
```

**Problems.** Blocking first, then Worth resolving, each under a heading that carries the number, the location in the spec and the severity, with the comment from Step 4 under it:

```
#### 1. R3, export format (Blocking)
```

`Blocking` means the spec is wrong about the code, or two parts of it cannot both be built, or a build would have to guess something that changes the result. `Worth resolving` means the spec can be built as written but probably should change first.

**Cases the spec does not cover.** A short checklist of the edge cases from Step 3 that apply, each in one line with the requirement it belongs to, so the author can add or rule out each one.

**Nitpicks.** One line each, kept apart from the problems: where in the spec and what to change.

**Could not check.** Anything the spec relies on that the code could not confirm, and why, for example a service outside this repository. One line each.

**What to do next.** For each Blocking and Worth-resolving problem, in the order that unblocks the others: what to change in the spec, what goes wrong in the build if it stays, and rough effort (trivial, small or medium). Where a problem ended in a question, the next step is the author's answer; repeat the question. When several open questions need deciding, say the person can run `/synergy:grill` on the spec to settle them.

If the spec holds up, say so in one sentence and stop.
