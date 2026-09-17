# Bulk-execute — substitutions for execute's escape hatches

Read this alongside `skills/execute/references/escape-hatches.md` once a run has left the happy path, for what a set changes in each hatch.

- **Blocked.** One story blocking does not block the run. Drop it (`references/set-selection.md`, **Dropping a story**, then `/synergy:block-story` for it) and carry on. Block the whole run only when the set drops below one buildable story and no code exists yet.
- **Dependency.** A dependency *inside* the set needs no hatch: `plan-set` already built it into the waves. A dependency on an open issue *outside* the set that appears mid-run drops that story. Never chain a bulk branch off another feature branch.
- **Too large.** Shrink the group, do not slice a story. Leave the dropped ones in the pool for their own run.
- **Failure reporting.** Comment the failure on **every** claimed issue before exiting and set each to `Needs attention`. Once the pull request is open, comment on the PR instead and leave the stages at `In Review`.
