---
name: grill
description: 'Interview the user hard about a plan until every open question is answered or deferred. Trigger on "grill me", "stress-test this" or "poke holes in this".'
---
# Grill

Question a plan until its weak points are found and each open question has an answer or has been parked on purpose. The interview is worth running only if it changes something: a session in which the user agrees with everything and never has to stop and think has not found the parts of the plan nobody has decided yet.

This skill is the one interview procedure in this plugin. Run it directly to stress-test a plan, or let `feature-discovery` run it as its interview. When another skill runs it, that skill supplies the subject and a list of topics that must be covered before the grill closes; everything about how the questions are asked lives here.

## Output standard

Everything a person reads — plans, questions, findings, summaries, and anything posted or committed — follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, every work item named as well as numbered, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

## No person present

A grill needs somebody to answer it. When nobody is there, because the session is an agent run, a scheduled routine, or a subagent, do not answer the questions yourself and do not carry on as if a guess were a decision.

1. Do the research and the mapping below as normal.
2. Write down every question you would have asked, each with your recommendation and why, grouped by topic.
3. Put that record where the next person will see it, and stop. When the subject is a GitHub issue: post the questions as a comment on it (written to the `writing-github-issues` standard and `_shared/body-standard.md`), then set its `Stage` to `Needs refinement` so no code agent picks it up before a person has answered: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" stage-set {number} --stage stage-refinement`. When there is no issue, the record is the reply that ends the session.

A calling skill that is itself running unattended inherits this rule: it stops at the same point and reports the open questions rather than producing stories from guesses.

## How a grill runs

1. **Get the plan.** If the user has not described it yet, ask them to, in one plain-text question with no options.
2. **Look before asking.** Read what can answer questions without the user: the codebase, the README and project docs, the issue and its comments, anything they linked. See **Checking the sources first**.
3. **Find where it will break.** Before the first question, decide which parts of this plan are most likely to fail or have not really been decided. Use **Where to push** as the checklist. Those are the first batch.
4. **Question in batches.** Hardest topic first, one topic per turn. See **Pacing**.
5. **Keep a record.** Track privately what has been settled, what was deferred and why, and which answers conflict. Do not show this record while the interview is running.
6. **Check coverage.** When a calling skill supplied topics that must be covered, go through them now and question any that are still open. Topics the research already answered count as covered.
7. **Close.** See **Closing**.

## Where to push

Questions about preferences are cheap to answer and reveal little. Questions about consequences find the gaps. Before each batch, pick the items below this plan has not yet been tested against, and skip the ones that do not apply to it.

- **How it fails.** When this breaks in production, who finds out, how, and what do they do next? A plan with no answer has only been pictured working.
- **What it rests on.** Name the thing the plan assumes but nobody has checked, and ask what happens if it turns out to be false.
- **What was left out rather than decided.** Vague phrasing, passive voice and "we'll just" usually mark a part nobody has decided. Ask about it directly.
- **The awkward user.** Someone with bad input, out-of-date data, the wrong permissions, or the same thing open twice. Plans are usually drawn for the user who does everything right.
- **The boundary.** What is this deliberately not doing? Scope with no stated edge grows during the build.
- **Decisions that cannot be undone.** Separate the choices that are cheap to reverse from those that are not. Spend the interview on the second kind and settle the first kind quickly.
- **What it replaces.** If something already exists, what happens to it, the data it holds and the people relying on it today?
- **Success at scale.** If usage is ten times what is expected, what gives way first?

## Pacing

A grill should move quickly. Most slow interviews are slow because they ask one small question at a time.

- **One topic per turn, every question on that topic together.** Three or four questions in a turn is normal.
- **Hardest first.** A foundational answer that changes can make later questions pointless, so find it early.
- **Push on a vague answer.** "It depends", "probably", and "we'll work that out" are not answers. Ask again with a sharper version of the question, and keep going until the answer is concrete or the user chooses to defer it and says why. Record a deferral with that reason; never skip a question silently.
- **Let a settled answer go.** When an answer is clear and holds up, acknowledge it briefly and move on. Do not repeat it back.
- **Drop questions an answer has made moot.** Mention it only if the user would otherwise wonder where the question went.
- **Raise a conflict in the same turn.** When an answer contradicts an earlier one, say so immediately and ask which stands.

## Asking a question

**Lead with a recommendation.** Every question states what you would choose and why, then asks whether the user agrees. A bare question leaves all the thinking to the user and hides where you think the risk is.

**Write for a reader with no context.** Follow `_shared/wording-standard.md` for every question, recommendation and option. The person answering may not have seen the reasoning behind the question, so state the problem and the proposed answer in full sentences, give the reason in plain language, and define jargon while keeping identifiers in backticks.

Hard to follow without context:

> Cache layer? Redis vs in-mem LRU, TTL 5m, invalidate on write.

Easy to follow:

> - **The problem:** Product lookups hit the database on every request, and the catalogue page makes dozens of them per load.
> - **Recommendation:** Add a read-through cache in front of `ProductRepository`, using the existing Redis instance rather than an in-memory `LRU` cache so every server instance shares it. Entries expire after 5 minutes, and an entry is cleared when its product is updated. Do you agree, or would you prefer a different store or expiry?

### Use `AskUserQuestion`

Every question with a bounded set of answers goes through the `AskUserQuestion` tool, not plain text: yes or no, choosing between approaches, confirming a recommendation, in or out of scope.

- 2 to 4 options per question, with short labels.
- The recommended option comes first, with "(Recommended)" at the end of its label.
- Up to 4 questions on the same topic in one call.
- Each label and description carries the problem and the proposed answer on its own, because it is often all the reader sees.
- The tool always offers "Other". If you want to add your own "Other" option, the question is open and belongs in plain text.
- A chosen option is the recorded decision unless it needs probing.

Plain text is only for three cases: the opening request to describe the plan, following up a vague answer (which needs the user's own words), and a question whose answer genuinely cannot be reduced to a few options.

## Checking the sources first

Never ask for anything the user would need to look up. Their time in the interview is for what only they know, which is what they intend.

When a source answers a question:

- Show what you found: the file or document, and the relevant detail, briefly.
- Say what you are recording because of it.
- Move on.

Never settle a question silently from a source. Give the user room to point out that the code is about to change.

## Closing

Propose closing when every significant question is answered or deferred with a reason, nothing still open blocks the next step, and any coverage list from a calling skill is complete.

End with a brief recap, in the conversation itself, readable in under a minute. Do not write a file or a document.

- **Decided:** the decisions, a line each.
- **Open:** each deferred question and the reason it was deferred.
- **Still shaky:** the one or two points that would still worry you if you owned this plan. Say it plainly. After an interview spent looking for weak points, the user is owed your honest read, not reassurance.

When a calling skill ran the grill, the recap hands control back to it and its next phase starts from these decisions.
