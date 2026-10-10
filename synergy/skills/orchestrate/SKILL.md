---
name: orchestrate
description: 'Run bulk-execute in rounds over an Epic, Feature, story list or the open pool, checking each round against GitHub. Trigger on "orchestrate" or "work through this Epic".'
argument-hint: '[--parent N | issue# issue# ...] [--mode story|feature|maintenance] [--rounds N] [--daily-percent N] [--on-limit stop|wait] [--dry-run]'
arguments:
  - name: parent
    description: 'An Epic or Feature number. Every round works the stories under it. Cannot be combined with story numbers.'
  - name: story_numbers
    description: 'Optional list of issue numbers, e.g. "41 43 47". Each round gets only the numbers the ledger still shows as waiting. With neither this nor a parent, the scope is the open pool.'
  - name: mode
    description: 'Selection mode passed to every round: story (default), feature or maintenance.'
  - name: rounds
    description: 'The most rounds to run. Default 5.'
  - name: quota
    description: 'Optional Claude plan limit settings, passed to wf quota unchanged: --five-hour-ceiling, --weekly-ceiling, --daily-percent, --on-limit stop|wait, --max-wait-hours, --on-unknown continue|stop.'
  - name: dry_run
    description: '--dry-run shows the ledger, the plan limit decision and the first round, and starts nothing.'
---

# Orchestrate

Run `/synergy:bulk-execute` as a series of rounds until the scope is done or a stop condition holds. You plan, start one agent per round, read its report, check the report against GitHub and keep a ledger. You do not write code, review code or merge anything yourself: the round does that.

**Use `/synergy:bulk-execute` instead** for one round, and `/synergy:execute` for one story.

## Output standard

Everything a person reads follows `skills/_shared/wording-standard.md` for how it reads, `skills/user-facing-communication/SKILL.md` for what it contains and in what order (outcome and current state first, then anything outstanding, blocked or assumed, no investigation history), and `skills/_shared/banned-patterns.md` for what must never appear. Every reply, not only the last one.

**Name every work item.** Write each issue and pull request as its type, number and title together, such as `Issue #41 — Resolve labels by purpose key` or `PR #52 — Resolve labels by purpose key`. Do this in every sentence, list, table and question, not only the first time. Never write a bare number.

## Is this the right skill?

Stop without starting a round if any of this holds:

- **The repository is not on GitHub.** The session was told it is hosted on Azure DevOps, GitLab, Bitbucket or an unrecognised remote. Say this workflow needs GitHub, and offer `/synergy:build` for local work.
- **Story numbers and a parent are both given.** Say they cannot be combined and ask which to use.
- **The only number is inside a branch name.** `feature/1963-seo-fix` names a branch, not a story. Ask what to do with the branch.

## Settings

- **Scope**: `--parent N` for an Epic or Feature, a list of story numbers, or the open pool when neither is given.
- **Mode**: `story` by default. Pass it to every round unchanged.
- **Round limit**: 5 by default.
- **Claude plan limits**: see the next section. Every setting has a default, so no flag is needed.

## Claude plan limits

A Claude plan has a 5-hour limit and a weekly limit. A round starts only when it is expected to end inside both, and inside the share of the week used up to now. `wf quota` makes that decision, so do not work it out yourself.

| Setting | Default | What it does |
|---|---|---|
| `--five-hour-ceiling` | 85 | A round must end at or below this percent of the 5-hour limit. |
| `--weekly-ceiling` | 90 | A round must end at or below this percent of the weekly limit. |
| `--daily-percent` | 14.3 | The percent of the weekly limit that each day of the week adds to the allowance. On day 3 the run may take the weekly limit to 42.9%. A day is 24 hours counted from the weekly reset, and an unused part stays available until that reset. |
| `--round-reserve-five-hour` | 15 | The percent of the 5-hour limit one round is taken to cost, until a round is measured. |
| `--round-reserve-weekly` | 3 | The same for the weekly limit. |
| `--on-limit` | `stop` | At a limit, `stop` ends the run and names the time it can continue. `wait` pauses until then. |
| `--max-wait-hours` | 5 | With `wait`, a longer pause than this ends the run instead. |
| `--on-unknown` | `continue` | What to do when the limits cannot be read: `continue` or `stop`. |

A person sets their own defaults in `~/.claude/synergy/quota.json`, with the same names written with underscores, such as `{"daily_percent": 10, "on_limit": "wait"}`. A flag on the command overrides the file. The file is personal because the limits belong to an account, not to a repository.

**The plan limit check**, used before the first round and after every round:

1. Read the limits. If the session has the `mcp__ccd_session_mgmt__get_usage` tool, which the Claude desktop app provides, call it. Take `percentUsed` and `resetsAt` from the window labelled `5-hour limit` and from the one labelled `Weekly · all models`. If the session has no such tool, or `plan.status` is not `ok`, there is no reading.
2. Run `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" quota --five-hour-used {n} --five-hour-resets {time} --weekly-used {n} --weekly-resets {time}`, with every plan limit flag the person gave. With no reading, leave those 4 flags out. After a round, add `--before-five-hour {n} --before-weekly {n}` with the reading taken before that round, so the command measures what a round costs.
3. Act on `decision`. `go`: continue. `stop`: do not start a round, and report `reason` and `resume_at`. `wait`: tell the person the time in `resume_at`, start `sleep {wait_seconds}` as a background command, do nothing until it ends, then do this check again from step 1.

When the result has `unknown: true`, the limits were not checked. Say so in the final report.

## Before the first round

1. Run `/synergy:preflight`. If it reports a problem that blocks work, stop and report it.
2. Read the GitHub API quota with `gh api rate_limit --jq '.rate.remaining'`. If it is below **300**, stop and say so.
3. Do the plan limit check. On `stop`, stop and say so.
4. List the open stories in scope with number, title, `Effort`, `Priority` and `Stage`, and keep the list as the **ledger**. Use `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" candidates --parent {N} --limit 0` for a parent, `wf candidates --mode {mode} --limit 0` for the open pool, and `gh issue view` for each named story.

Each story in the ledger has one state: `waiting`, `built`, `merged`, `dropped` (with a reason) or `excluded` (with a reason).

**With `--dry-run`, stop here.** Do the plan limit check and build the ledger even if the check says `stop`. Then report the ledger, each of the 3 plan limit checks with its used, after-round and limit figures, the day of the week and the percent allowed by that day, the decision, the settings in use, and the exact task the first round would get. Start no agent and change nothing.

## Each round

1. Start **one** agent with `subagent_type: "synergy:Builder"` and `isolation: "worktree"`, and wait for it to finish (`run_in_background: false`). Never run 2 rounds at the same time, because 2 rounds would claim and merge against the same stories.
2. Give it this task, with the scope arguments filled in: `Run /synergy:bulk-execute {scope arguments} --mode {mode}. Follow the skill exactly. Do not pass --bypass-ci or --no-merge.` Then ask it to report, as the last lines of the task: each story claimed, built, merged, dropped or excluded, by number and title, with the reason for each one dropped or excluded; each pull request by number and title, with its merge state; whether `.claude/self-review.flag` existed, which means the review ran inline; whether the quality gate failed; any story the `unblocked` sweep released; and any issue filed during the run.
   - For `--parent`, pass `--parent {N}`.
   - For a story list, pass only the numbers the ledger still shows as `waiting`.
   - For the open pool, pass no numbers.
3. When the agent returns, **check its report against GitHub**. Do not trust the report alone. Run `git fetch`. For each pull request it says it merged, run `gh pr view {pr} --json state,mergedAt`. For each story it says it closed, run `gh issue view {story} --json state`. Where GitHub disagrees with the report, GitHub is right: record that.
4. Update the ledger. Add each story released by the `unblocked` sweep if it is in scope.
5. Read the API quota again, and do the plan limit check again.

## Stop conditions

Check after each round. Stop, and do not start another round, if any of these is true:

- The round claimed nothing, or `plan-set` returned `no-candidates` or `all-blocked`.
- No story in scope is still `waiting`.
- A pull request from the round did not merge. Report the condition that stopped it. If the project has `Auto-Merge on Approval` off in `docs/review.config.md`, every round ends at an approved pull request by design: say that, and say the setting is the cause.
- The quality gate failed, or the round ended with an error or a timeout.
- The API quota is below **300**.
- The plan limit check says `stop`.
- The round limit is reached.
- The same story was dropped in 2 rounds. Do not try it a third time.

If the review ran inline in a round, continue, but say so in the final report. An inline review is weaker than an independent one.

## Final report

Write it for a person who did not watch the run.

1. **The outcome first**: how many rounds ran, which stories merged, and whether work in scope is still open.
2. **A table** with these columns: story (number and title), final state, pull request (number and title) and reason (for dropped or excluded).
3. **What is outstanding or needs a person**: pull requests left open, stories dropped twice, inline reviews, `Stage` updates that failed, and issues filed during the run.
4. **The Claude plan limits**: the 5-hour and weekly percent at the start and at the end, each pause, and whether the limits could not be read.
5. **Why the run stopped.** For a plan limit, give the time the run can continue.
