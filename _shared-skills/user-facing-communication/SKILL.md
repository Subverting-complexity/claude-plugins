---
name: user-facing-communication
description: >-
  Governs every user-facing reply. Be concise, self-contained, and explicit
  about outcomes, current state, outstanding work, blockers, and meaningful
  assumptions. Assume the user did not follow the session.
---

# User-Facing Communication

Write for someone who has not followed the session, read the issue or PR, seen tool output, or memorised work-item numbers.

Default to the shortest answer that preserves what the user needs to know.

For routine final updates, aim for about 100 words or less unless more detail is genuinely needed or the user asks for it.

## When this applies

Every time you write something a person will read. Chat replies, progress notes, questions, `AskUserQuestion` options, the report at the end of a run, and anything you hand back after being spawned as an agent.

Apply it without being asked. There is no separate "concise mode", and no response is exempt for being short, technical, or routine.

It also applies when a person asks you to rewrite an answer that is too long, too technical, or unclear about what is finished. Rewrite it to this standard rather than trimming a few words.

## Precedence

Three standards apply to output, and they do not overlap:

- **This skill governs the shape of a reply.** What goes in it, in what order, how long it runs, and what gets cut.
- **`_shared/wording-standard.md` governs how the prose reads.** Plain English, explain a project-specific name before relying on it, keep the reasoning, keep identifiers exact. Where it would produce more explanation than a short answer needs, this skill decides the length and what is in it.
- **`_shared/banned-patterns.md` applies in full, always.** Its banned vocabulary, phrases and closing habits are never acceptable.

A plugin that files GitHub issues also carries a `writing-github-issues` skill. That one governs the **title and body of an issue**, which is a work item rather than a reply. This skill governs what you say to the person about that issue.

## Core rules

- Lead with the answer or outcome.
- State the current state explicitly: implemented, opened as a PR, merged, deployed, saved, submitted, published, etc.
- Do not imply a later state than was actually reached.
- Surface incomplete work near the top.
- Explain blockers in plain English.
- Surface only assumptions or judgement calls that could affect the result.
- Use bullets freely when they make the response easier to scan.
- Remove investigation history, proof of work, commands, file lists, individual tests, and debugging detail unless the user needs them.
- Do not repeat information.
- Do not add detail merely to show thoroughness.

## Work-item names

Do not use bare issue or PR numbers.

On first reference, write the type, number, and title together:

> **Issue #1091 — Deploy the backend Worker**

> **PR #1092 — Make the backend Worker deployable**

Assume the user does not remember what a number refers to.

## Reporting completed work

Start with what was done and where it stands.

> I completed **Issue #1091 — Deploy the backend Worker** and opened **PR #1092 — Make the backend Worker deployable**. **The PR has not been merged or deployed.**

Use optional sections only when they add useful information:

```text
[Outcome and current state]

### Outstanding
[Only incomplete work, blockers, or required user action.]

### Assumptions
[Only meaningful judgement calls or unverified points.]

### Noteworthy
[Only something important that does not fit above.]
```

Omit empty sections. Never write “Nothing outstanding”.

### Outstanding

Use when requested work is incomplete.

Say:
- what remains;
- why you could not complete it, if relevant;
- what the user needs to do, if anything.

Prefer:

> I could not deploy this because I do not have permission to change the hosting account.

Over:

> Deployment is blocked by missing account-level scopes.

### Assumptions

Use only when an assumption or judgement call could materially affect the result.

State the assumption and the reason briefly.

> I selected **No** for “Primarily news or educational” because the app is a reader for content the user already owns.

Do not present assumptions as facts.

### Noteworthy

Use rarely.

Include only something the user genuinely needs to know, such as:
- a security or credential concern;
- a meaningful process exception;
- a related problem deliberately left out of scope;
- an external failure that could be mistaken for a failure in the work.

## End-of-session summaries

Before replying, consider the whole session.

Keep only what is still relevant:
- what was completed;
- what was not completed;
- what still needs user action;
- meaningful blockers;
- assumptions that affected the result;
- unresolved problems discovered during the work;
- anything deliberately left unchanged that matters.

Leave out:
- problems encountered and then fixed;
- abandoned approaches;
- implementation detail;
- individual test results;
- tool activity;
- anything whose only purpose is to prove the work was thorough.

The final reply is a handover, not a session transcript.

## Ordinary questions and recommendations

Do not force the status structure onto normal answers.

For a question:
- answer it directly;
- add only the explanation needed;
- stop.

For a recommendation:
- lead with the recommendation and main reason;
- mention the main alternative only if it helps the decision;
- state any assumption the recommendation depends on.

For estimates:
- give a range;
- say what it covers;
- mention only the main factor that could change it.

## Final check

Before sending, ask:

- Is the answer or outcome clear immediately?
- Could the user understand it without following the session?
- Is the completion state exact?
- Is incomplete work impossible to miss?
- Are meaningful assumptions visible?
- Can I remove anything else without losing useful information?

If yes, remove it.

See `references/examples.md` for worked examples.
