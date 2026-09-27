# Release notes on the PR

`execute` and `bulk-execute` follow this the moment the pull request opens, before its review, so the reviewer checks the notes and any merge, by the run, a queued auto-merge or a person, has notes to write. `pr-review` and the settle step that starts each run follow its last section when a pull request has no notes.

## Write the notes

Write the release notes each issue the PR closes will carry once it is Done. Read `skills/release-notes/SKILL.md` and follow its **When another skill calls this** section for each issue: in `execute` the change is the whole branch; in `bulk-execute` it is only that story's commits, so each story gets its own text; for a merged pull request it is the whole merged diff. Write the result with the Write tool, never through a shell string, to `.claude/release-notes.json`:

```json
{"41": {"user": "* The Library header is more compact.", "internal": "* Moved header state into one store."}}
```

A blank text leaves that field blank, and the Done write still lands. Never write `Shipped in version`: the project's release script stamps it. Writing the notes asks nothing of the user and needs no reply.

## Post them on the PR

Post the notes JSON as one PR comment. `wf post-merge` and `wf settle-merged` read the newest such comment when no `--notes` file is given, so a merge finished outside the run that wrote them still writes them. Write the body to `.claude/release-notes-comment.md` with the Write tool, then run `gh pr comment <number> --repo <org>/<repo> --body-file .claude/release-notes-comment.md`. The body is exactly:

````markdown
<!-- synergy:release-notes -->
Release notes, written into each issue's fields when it is settled as Done.

```json
{"41": {"user": "* ...", "internal": "* ..."}}
```
````

The newest such comment wins, so post a new one rather than editing when the notes change.
