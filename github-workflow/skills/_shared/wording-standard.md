<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->
# Plain-English Wording Standard

This is the shared standard for **every piece of text a person reads**,
in any skill or command in this plugin. That includes the plan you print
before building, progress notes while you work, the final summary,
interview questions, `AskUserQuestion` options, pull request
descriptions, code review comments, and the explanation in any chat
reply. If a human will read it, this standard applies.

The reader often has **no prior context on this codebase**. Assume a
technically capable reader who is **not involved in this particular
project** — they follow conceptual and architectural points fine, but
they do not know this codebase's specific names, files, components, or
conventions. The agent may be running autonomously (for example through
`execute` or a scheduled routine), so the person reading has
not seen the diff, the codebase, or the conversation. Write so they can
follow the change without already knowing its internals.

## This standard governs the prose; another governs the shape

`skills/user-facing-communication/SKILL.md` decides **what goes in a
reply and in what order**: lead with the outcome and the current state,
say plainly what is finished and what is not, surface anything
outstanding, blocked or assumed, and cut the investigation history and
proof of work. It applies to every response, without being asked.

This file decides **how that text reads**: plain English, explain a
project-specific name before relying on it, keep the reasoning and the
uncertainty, keep identifiers exact. Where the two meet, the shape
standard decides the length and the content, and this one decides the
wording. `_shared/banned-patterns.md` applies to both, always.

Read the shape standard before you write a report, a progress note, a
question, or the summary that ends a run.

## The standard

- **Explain at a high level first.** Lead with what the change does and
  why it matters, in plain words. Concepts and architecture are fair game
  — the reader can follow those. What they cannot follow is unexplained
  project-specific detail, so the technical specifics support the
  explanation rather than replace it.

- **Explain what project-specific things are.** When you name a
  component, pattern, file, setting, or identifier from this codebase,
  say what it is and what role it plays before relying on it. The reader
  knows software in general but does not know that `InviteService` is the
  thing that sends invites or that this project uses a particular
  pattern. A symbol on its own carries no meaning to them.

- **Never let identifiers stand in for an explanation.** A line like
  `Pending → Expired on expiry; GET idempotent` names mechanics without
  explaining them. Say what happens and why in plain words, then name the
  identifier. The reader cannot infer the concept from the symbol.

- **State both the problem and the proposed solution.** Every question
  and every recommendation should say what is being decided and what you
  propose to do about it. Don't ask "Which expiry strategy?" — explain
  that invites currently never expire, why that is a problem, and what
  you recommend instead.

- **Be concise. Plain does not mean long.** Say the thing in as few
  words as carry the meaning, then stop. Do not pad with restatement or
  background the reader did not ask for. Bullets are good. One clear
  concept per sentence is good. The goal is easy to understand, not
  wordy.

- **Write statements a reader can follow, not fragments.** Avoid
  telegraphic shorthand like "Expiry: 7 days, configurable". Write
  "Invites expire after 7 days by default, and that period is
  configurable." Each sentence should be a complete, understandable
  statement on its own.

- **Always include the why.** State the recommendation, then a short
  plain-language reason for it. A reader without context cannot judge a
  recommendation that arrives with no rationale.

- **Avoid or define jargon.** Spell out shorthand and abbreviations the
  first time they appear. Do not assume the reader fills the gap. Plain
  English does not mean vague — it means a non-expert in this particular
  change can still follow it.

- **Keep precision, in service of the explanation.** Format identifiers
  as code so they stay exact: state names, settings, methods, endpoints,
  and file paths in backticks (`Pending`, `InviteExpiry`, `POST`,
  `src/auth/login.ts`). Use them to anchor the plain-English point, not
  in place of it.

- **Give each point room to breathe.** Use a bullet per point with a
  blank line between them, and a short bold label where it helps.

This applies to `AskUserQuestion` option **labels and descriptions** as
much as to free-text prose. The option text is often all an autonomous
reader sees, so it must carry the problem and the proposed solution on
its own.

## Exception: GitHub issue titles and bodies

A plugin that files GitHub issues carries a `writing-github-issues`
skill (github-workflow does). Where it exists, it governs the title and
body of an issue: which sections there are, how long the body runs, and
what gets cut. An issue is read by someone about to do the work, so it
is shorter than this standard would otherwise produce, and it leaves out
the investigation that found the problem.

Everything else you write still follows this standard, including the
comment you post on an issue, and what you tell the person about the
issue you filed. `_shared/banned-patterns.md` applies to all of it, and
`skills/user-facing-communication/SKILL.md` still shapes the reply.

## Before you send anything

Reread your output once with the reader in mind. Remove the patterns in
`_shared/banned-patterns.md`. Check that a technically capable person who
is not involved in this codebase could read it and understand what
changed and why. If a line names a project-specific component or
identifier without saying what it is, explain it. If a line is just a
string of identifiers or a clipped fragment, rewrite it as a plain
statement.

Then run the shape check in
`skills/user-facing-communication/SKILL.md`: the outcome and the current
state are in the first sentence, anything outstanding or assumed is
visible, work items are named as well as numbered, and nothing is there
only to show the work was done thoroughly.

## Example

Terse and hard to parse for someone without context:

> Expiry: 7 days, configurable (InviteExpiry setting). On expiry,
> Pending → Expired. GET landing is idempotent + re-openable while
> Pending (SafeLinks-safe); accept is single-success.

Clear and easy to read:

> - **Expiry:** Invites expire after 7 days by default. This is
>   configurable through an `InviteExpiry` setting. When an invite
>   expires, its status changes from `Pending` to `Expired`.
>
> - **Landing page:** The `GET` landing page is idempotent and
>   re-openable while the invite is still `Pending`. This makes it safe
>   for tools such as SafeLinks to open the link without consuming the
>   invite.
>
> - **Acceptance:** Accepting the invite is single-use. The first valid
>   `POST` changes it from `Pending` to `Accepted`. Any later `POST`
>   shows an "already accepted" message.

See also `_shared/banned-patterns.md` for words, phrases, and structural
habits that must never appear in output. This standard is about being
clear, high-level, and complete; banned-patterns is about what to avoid.
Both apply to all output.
