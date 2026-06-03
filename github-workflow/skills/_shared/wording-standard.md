<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->
# Plain-English Wording Standard

This is the shared standard for how workflow skills should word the
things a person reads: interview questions, `AskUserQuestion` options,
pull request descriptions, and code review comments.

The reader often has **no prior context**. The agent may be running
autonomously (for example through `execute` or a scheduled routine), so
the person answering a question or reading a PR has not seen the
reasoning that led up to it. Write for that reader: someone smart who
does not have the diff, the codebase, or the conversation in front of
them.

Every writing skill that asks questions or produces written output for a
human references this file.

## The standard

- **State both the problem and the proposed solution.** Every question
  and every recommendation should say what is being decided and what you
  propose to do about it. Don't ask "Which expiry strategy?" — explain
  that invites currently never expire, why that is a problem, and what
  you recommend instead.

- **Write in complete sentences.** Avoid telegraphic fragments like
  "Expiry: 7 days, configurable". Write "Invites expire after 7 days by
  default. This is configurable through an `InviteExpiry` setting."

- **One idea per sentence.** Break dense compound statements apart
  rather than stacking clauses with parentheses and slashes.

- **Always include the why.** State the recommendation, then a short
  plain-language reason for it. A reader without context cannot judge a
  recommendation that arrives with no rationale.

- **Avoid or define jargon.** Spell out shorthand and abbreviations the
  first time they appear. Do not assume the reader fills the gap. Plain
  English does not mean vague — it means a non-expert in this particular
  change can still follow it.

- **Keep precision.** Format identifiers as code: state names, settings,
  methods, endpoints, and file paths in backticks (`Pending`,
  `InviteExpiry`, `POST`, `src/auth/login.ts`). Being readable does not
  mean dropping the specifics.

- **Give each point room to breathe.** Use a bullet per point with a
  blank line between them, and a short bold label where it helps.

This applies to `AskUserQuestion` option **labels and descriptions** as
much as to free-text prose. The option text is often all an autonomous
reader sees, so it must carry the problem and the proposed solution on
its own.

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
clear and complete; banned-patterns is about what to avoid. Both apply.
