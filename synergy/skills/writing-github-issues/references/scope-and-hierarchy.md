# Writing GitHub issues — hierarchy and party scoping

Read this only when an issue needs a parent (an epic or feature relationship) or needs to be scoped to a single party (`[Manual] `, `[Browser] ` or an unprefixed code-agent issue). Most issues need neither: a straightforward bug or chore carries no parent and no prefix.

## Hierarchy: epic, feature, story

The native types are a tree, not a flat list. A `User Story` sits under a `Feature`, and `wf issue-apply` refuses one without that parent, or under the wrong type, wherever the org has `Feature` enabled. A `Feature` sits under an `Epic` when the work has one. An epic groups several features toward one outcome, so a feature that would be an epic's only child is filed on its own rather than under an epic that restates it; a feature that does have a parent must have an `Epic` one. `Bug` and `Chore` sit outside the tree: a parent is allowed on either and never required.

Attach before creating. Where the work belongs to an epic or feature that already exists, name it as the `parent` by issue number rather than filing a second one.

The parent is GitHub's native Parent issue relationship, which the spec's `parent` writes. It is not a sentence in the body; a body line saying "Part of #N" parents nothing.

## Scope: one issue, one party

Three parties do work on a backlog, and they cannot substitute for each other.

| Party | What it is | `Ownership` | Prefix |
| --- | --- | --- | --- |
| **Code agent** | Changes the repository. Produces a commit. | `Code agent` | none |
| **Browser agent** | Drives a web console a person has already signed into. Produces a saved form. | `Browser agent` | `[Browser] ` |
| **Human** | Everything neither of the others can reach. Produces neither. | `Human` | `[Manual] ` |

**Every issue is scoped to exactly one of them.** Not "mostly a code agent", not "an agent, then someone presses save". One. This is the rule that matters, and the rest of this section is what follows from it.

### What each party can do

**Code agent.** The common case, so it carries no prefix. It still carries the field: `Ownership` is required on every issue, and an issue that does not say who owns it is not offered to a code agent at all.

**Browser agent.** Filling non-credential fields, pressing save, reading identifiers back out of a console. It **cannot** sign in, clear two-factor, download a file, accept an agreement, or touch anything financial. When it meets one of those it stops and hands back rather than working around it. Because it needs a session a person opened, a `[Browser]` issue is not picked up on its own either.

**Human.** A physical device in someone's hand, money, a legal agreement, a credential being moved, a business decision. Signing in, downloading, accepting terms and making a declaration to a third party are human every time, even when the work around them is console clicking. A device pass is human, not browser: a browser agent has no phone, no speaker and no screen reader.

### Marking a scoped issue

Both scoped parties take two things together, both or neither:

1. **The `Ownership` field**, set to `Browser agent` or `Human`. This is the one that does the work: it is the only thing selection reads, so it is what keeps the issue out of the code agent's pool. `wf issue-apply` sets its stage to **Non-code** from it, without being asked.
2. **The prefix**, exactly as spelled above, at the very start, followed by one space. `[Manual] Grant the Cloudflare GitHub App access to the org`. `[Browser] Set the authorised redirect URIs on the web OAuth client`. This is for a person reading a list; nothing selects on it.

**Non-code is not Blocked.** The plugin's `Blocked` means one thing only — an open native blocked-by edge — and `wf unblock` releases anything with edges once they all close. Non-code work parked at `Blocked` is one sweep away from being handed to an agent that cannot do it, which is exactly what happened: both issues the first sweep would have released were `[Manual]` device passes whose blockers had closed.

Include a `## Manual step` section saying what has to happen and why the other two parties cannot do it.

### When an issue needs two parties, split it

**This is the rule that replaces the old one.** An issue that is mostly automatable with one human prerequisite used to be marked `[Manual]` and left whole. Do not do that. Raise the other party's work as its own issue, scope it, and link the two with a native blocked-by edge.

The old shape looks finished and is not. A code story that does its half and says "then a person sets the value" sits in Backlog, gets picked up, gets a merged pull request, and the console step is never done because it never had an issue of its own.

Ask what the issue produces: a commit, a saved console form, or neither. **Two answers means two issues.**

Where the two halves interleave, say so in both, in order, rather than leaving it to whoever picks one up. Two issues that hand back and forth once is normal and fine; four issues for four alternating steps is not.

**When none of this applies:** work a person has to do that belongs to a *different* issue is not a manual step here. Record it as a native blocked-by edge, and leave this issue unprefixed.

`[Manual]` and `[Browser]` are the only prefixes `wf issue-apply` leaves on a title. It strips `[BUG]`, `[STORY]` and the rest, because the native issue type already says what kind of work an issue is. Nothing native says **who** has to do it, which is why these two are carried in the title.
