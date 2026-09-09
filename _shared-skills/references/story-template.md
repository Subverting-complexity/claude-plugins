# Story Template

Each story is a single-session unit of work for an autonomous agent.

A story is an issue, so it is written the way every other issue is written: open with the actual point, and include only what someone needs to understand the work, make the change and verify it. Prefer a short story over a comprehensive record of the discovery session.

Where the plugin provides a `writing-github-issues` skill (github-workflow does), that skill is the full standard and this template is its story shape. Read it before writing stories destined for GitHub.

## The usual shape

Most stories need three sections:

```markdown
## Summary
What this story delivers and why, in 1-3 short paragraphs. The reader
should understand the story from this section alone.
**Size estimate:** small | medium | large

## Changes
What has to change, as outcomes rather than a development diary. Exact
paths, identifiers and configuration values where they are needed.

## Acceptance criteria
- [ ] Specific, verifiable criterion
- [ ] The agent can self-evaluate each one
```

A very small story may be a Summary and acceptance criteria alone.

Write each paragraph on **one single line**. Never hard-wrap prose at 72, 80 or any other column: the tracker reflows markdown to the reader's own width, so wrapping only fixes the breaks where they suit nobody and makes the story painful to edit later.

## Sections to add only when they carry information

Each of these is optional. An empty or obvious one is worse than none, and none of them may repeat what the Summary already said.

| Section | Add it when |
| ------- | ----------- |
| `## Business rules` | Concrete, testable rules the implementer would otherwise guess. Numbered. |
| `## Data model` | Tables or entities created or modified. Markdown table: Column, Type, Description. |
| `## API contract` | Method, path, request and response shape, status codes, auth. |
| `## UI/UX` | Where it appears, the user flow, and the loading, empty, error and success states. |
| `## Edge cases` | Scenarios whose expected behaviour is not obvious. Scenario, then expected behaviour. |
| `## Verification` | Verification needs more than the acceptance criteria convey: a physical device, several environments, a regression check, specific commands. |
| `## Dependencies` | Rarely. A dependency between two issues is a native blocked-by edge, not a sentence; use this section for the *reason*, or for a dependency on something outside GitHub. |
| `## Out of scope` | There is a realistic risk the work expands into something that should stay separate. |
| `## Manual step` | The story cannot be finished until a person does something no agent can do. Say exactly what, and why. A story with this section also takes the `[Manual]` title prefix and `Ownership` set to `Human`, so it is visible in a list and never picked up by an agent that cannot finish it. Work a person must do that belongs to a *different* story is that story, linked by a native blocked-by edge. |

Do not reach for these out of habit, and do not add a "Definition of done" section: the acceptance criteria and the project's quality gate already cover it.

## Two conventions the workflow reads

- `**Size estimate:** {size}` sits in the Summary. The `Effort` field mirrors it.
- A dependency is a **native blocked-by edge**, written from a spec's `blocked_by` by `wf issue-apply`. Selection skips a story with an open edge, and `wf unblock` releases it when every edge closes. Prose is not parsed, so a `Blocked by #N` sentence with no edge behind it holds nothing back.

## What not to include

- How the story was discovered, or which part of the interview produced it.
- Justification for something the Summary already makes obvious.
- File-by-file narration of the intended implementation.
- Alternatives, when the approach is already settled. Where it is not settled, keep the uncertainty in the words the discovery used ("this will likely need either...").

A story too vague to implement gets refined, or its card moved to the board's Needs refinement column so nothing picks it up. Never pad a thin story with invented detail to make it look complete.
