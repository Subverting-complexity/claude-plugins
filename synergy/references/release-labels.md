# Release labels — the contract for a release script

A project that releases more than one thing (a mobile app, a web app, a backend) needs to know which closed issues belong in each release, and which it has already included. Two labels on each issue say so. This file is the contract between the plugin, which sets the first label, and the project's own release script, which reads it and sets the second.

## The labels

Each row of the `## Release Targets` table in `ClaudeProject.md` names one release target. `wf labels-ensure` creates 2 labels for each row, and 2 more for work that ships to nobody outside the team:

| Label | Meaning | Set by |
| --- | --- | --- |
| `release: {target}` | The issue's work ships in this target. | The plugin, when the pull request that closes the issue merges. |
| `released: {target}` | A release of this target has included the issue. | The release script. |
| `release: internal` | The work ships in no target: a refactor, a test, tooling. | The plugin. |
| `released: internal` | A release has included the internal issue. | The release script. |

A repository whose table has no row has none of these labels, and a merge there sets none.

## What the plugin does

- **Before the merge**, `execute` and `bulk-execute` decide each issue's targets where they write its release notes, with `wf release-targets --pr N`. The targets go on the pull request in the release-notes comment, as a `targets` list for each issue (`skills/release-notes/references/release-targets.md`). An issue can have more than 1 target. An empty list means no target applies.
- **At the merge**, `wf post-merge` adds a `release: {target}` label to each issue the pull request closes, for each of its targets, or `release: internal` for an empty list. So each such issue ends with at least 1 `release:` label.
- **After a merge with no agent present**, such as one GitHub made from the queue or a person made by hand, the next `wf settle-merged` adds the labels from the comment. A merged pull request with no targets on it is listed under `needs_targets`, and the run decides them then.
- The plugin **never removes** a `release:` or `released:` label, and never adds a `released:` label.

## What a release script does

For a release of `{target}`:

1. **Find what waits.** An issue waits for `{target}` while all 3 hold: it is closed, it has `release: {target}`, and it lacks `released: {target}`.

   ```bash
   gh issue list --state closed --label "release: {target}" --search '-label:"released: {target}"' --json number,title --limit 500
   ```

2. **Take the internal work too, once.** The first release of any target after an internal issue closes also takes it: each closed issue that has `release: internal` and lacks `released: internal`. Internal work then appears in 1 release and no later one.
3. **Build the release notes** from the `User release notes` and `Internal release notes` fields of those issues, grouped by each issue's `area:` label.
4. **Mark each issue shipped.** Add `released: {target}`, or `released: internal` for an internal issue, and write the version into the `Shipped in version` field. Do both only after the release has succeeded, so a failed release leaves every issue waiting.

An issue with 2 targets waits for each one separately: a release of `web` adds `released: web` and leaves the issue waiting for `mobile`.

## What the contract leaves out

- The plugin has no command that lists what waits for a release or marks it shipped. Each repository's own release script does that, because each one builds and ships in its own way.
- A `released:` label is not removed when an issue is reopened. A project that reopens shipped work decides for itself what its next release says about it.
