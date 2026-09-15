---
name: pr-body
description: 'Write a pull request title and description from committed changes or notes. Trigger on documenting a PR or summarising a branch.'
---

# PR Description Skill

The entry point for **pull request titles and bodies**. It is one of two entry points over `_shared/body-standard.md`, which is the single standard for every body this plugin writes into GitHub. Read that file first. This one adds only what is specific to a pull request.

The counterpart entry point is `writing-github-issues`, which does the same job for issue bodies. An issue and a pull request are written the same way on purpose: same wording, same section names, same no-wrapping rule.

**Two formats, chosen by the repository, never by preference.** A repository with a `ClaudeProject.md` uses the fixed shape below, always, because `execute`, `bulk-execute` and `pr-review` read and extend these bodies and a description that varies per pull request cannot be extended reliably. Only when the repository has no `ClaudeProject.md`, or the platform is not GitHub, use the component-section format in `references/component-format.md` instead; read that file and skip the rest of this one. Never mix the two in one body.

`_shared/banned-patterns.md` applies in full. `skills/user-facing-communication/SKILL.md` shapes what you say to the person **around** the description: lead with the outcome and the current state, keep it short, surface anything outstanding or assumed. It governs your reply, not the description.

---

## The body

Three sections, these names, this order, on every pull request:

```markdown
## Summary

## Changes

## Test plan
```

Do not rename them, reorder them, merge them, or add a top-level section in their place. A reviewer opening any pull request should find the same three headings in the same order every time.

Two additions are allowed, and only when they carry information:

| Extra section | Add it when |
| ------------- | ----------- |
| `## Manual step` | The change is not complete until a person does something the reviewer cannot do, such as granting access, running a migration or setting a secret. Say exactly what, and why it could not be automated. |
| `## Quality gate failed` | The caller says the quality gate failed. It is the one section that goes **above** `## Summary`, and it carries the last error output. |

Where the platform links issues, the closing keywords go at the very end of the body, under no heading, one line per issue:

```
Closes #42
```

### Summary

Two to four plain-English sentences on the goal, the approach and the impact, written so a reviewer who has not seen the diff or the originating conversation can follow it. Include it always; on a one-line typo fix, one sentence is enough.

### Changes

Bullets, following the bullet rules in `_shared/body-standard.md`. Group them under `###` sub-headings named after the component, module, service or file group only when the change touches more than three separate areas.

### Test plan

How the change was verified, as bullets: the commands run, the tests added or updated, and anything checked by hand. Say plainly if part of it is unverified.

Only leave this section out when there is genuinely nothing to run and nothing to check.

---

## Output structure

When the user asks for a description rather than having one posted for them, return two separate, independently copyable markdown blocks.

**Block 1 — Title.** A code block containing only the title, so it copies cleanly into the title field. Title rules are in `_shared/body-standard.md`.

**Block 2 — Description body.** A code block containing the full body in markdown.

---

## Examples

When you want a model body to follow, see `references/examples.md` for worked examples.
