# Release targets on the PR

Read this only when `wf release-targets --pr <number>` returned issues. That means `ClaudeProject.md` has a `## Release Targets` table, so each issue the pull request closes gets a `release: {target}` label at the merge. `wf post-merge` is a script and cannot judge where work ships, so you decide the targets now and they go on the pull request with the release notes.

## Decide

Each entry in `issues` is one issue the PR closes:

- **`targets`** — the names the Jev `target` check was sure of. Keep them.
- **`decide`** — the names left to you. Judge each one from the issue and from `folders`, the folders that issue's work touched. In a bulk PR the folders come from that story's own commits, so judge each story on its own.
- **`labels`** — the `release:` labels the issue already carries. They stay.

Jev is optional. When `jev` is `unavailable`, every name is under `decide`: decide them all and carry on. When `jev` is `used`, say so in one line of the final reply.

An issue can ship in more than 1 target. When no target applies, such as a refactor, a test or tooling, the issue ships in none.

## Write

Add the result to that issue's entry in `.claude/release-notes.json`, beside its texts:

```json
{"41": {"user": "* ...", "internal": "* ...", "targets": ["web", "backend"]}, "43": {"internal": "* ...", "targets": []}}
```

Use the names as `valid` gives them. An empty list means no target applies, and sets `release: internal`. Give every issue the PR closes a `targets` list: an issue with none is reported as a gap when the PR is settled.

Then post the notes comment as `on-the-pr.md` says. `synergy/references/release-labels.md` is the contract a project's release script reads these labels by.

## A merged PR under `needs_targets`

`wf settle-merged` lists a merged PR here when an issue it closed has no targets and no `release:` label. Decide and write as above. An issue that already has its notes needs only `{"targets": [...]}` as its entry. Then run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" post-merge --pr <number> --notes .claude/release-notes.json` and delete the file.
