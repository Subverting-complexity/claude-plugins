# Changelog

Notable changes to the plugins in this marketplace. Both plugins version
independently; each entry says which one it applies to.

See [README.md](README.md#picking-up-a-new-version) for how to pick up a
new version, and why a stale marketplace cache is the usual reason an
update appears to do nothing.

## github-workflow 11.2.1

**The marketplace listing and plugin description mention the Epic and Feature tree.** Both now say that a bulk run can take its set from the stories under one Epic or Feature, and that an Epic or Feature is closed once its last sub-issue closes. No behaviour changes.

## github-workflow 11.2.0

**`bulk-execute --parent N` chooses the set from an Epic or Feature.** `wf candidates --parent N` walks the sub-issues under it and returns the one set it offers: the stories of a single Feature, only those a code agent may take, plus any story in Blocked that has an open blocker and whose every open blocker is another story in the same set. Every other story is listed with the reason it was left out, and nothing is asked. Non-code work is never taken.

**A merge closes the Epic or Feature it finishes.** `wf post-merge` walks up from each issue it settles and closes any Epic or Feature whose sub-issues are now all closed, as completed, moving it to Done with a comment naming the child that finished it. Closing a Feature can finish its Epic in the same run. A container with no sub-issues is never closed, and a parent in another repository is left alone. A new `container-finished` preflight warning finds the ones that finished before this release, and `wf preflight --fix` closes them.

**`wf issue-apply` writes the title and body on an update.** An update entry's `title`, `body` or `body_file` used to be ignored, and the run still reported `ok`. Each is now compared with the issue and written only when it differs, listed in `changed`, and read back, so a mismatch is reported.

**A pull request is locked from the moment it is handed to review.** `wf handoff` takes the pull request's review claim before it releases the issue claims, so a scheduled `code-review` run can no longer claim a run's own pull request in the gap before that run's review starts. `wf claim --pr N --keep-held` keeps a claim the same checkout already holds, rather than reading its own lock as a rival's; without the flag a second session sharing the checkout still loses.

## github-workflow 11.1.0

**Two org fields are no longer part of the workflow.** The `field-parent` purpose key is gone: an issue's parent is GitHub's native Parent issue relationship, which `wf issue-apply` already writes from a spec's `parent`. The `field-retired` preflight check is gone too. An org that still defines either field now sees it reported as `field-unmapped`, like any other org field no purpose key names.

## github-workflow 11.0.0

**Every user story sits under a feature, and a feature under an epic when the work has one.** `wf issue-apply` refuses a spec that files a `User Story` with no `Feature` parent, or a story or feature under the wrong type, and writes nothing. A feature with no epic is allowed: an epic groups several features toward one outcome, and one invented to hold a single feature would only restate it. A parent that already exists is judged by its live type, and an update is judged by the parent it has or the one it names. The rule is enforced only where the org has the parent type enabled, and `Bug`, `Chore` and `Epic` need no parent. `feature-discovery` now plans stories under features, and features under an epic only when the outcome spans more than one; it attaches to an existing epic or feature before creating one. `issue-audit` reports an issue outside the tree as a `hierarchy` gap. This is the breaking change: a spec that filed parentless stories against an org with `Feature` enabled now exits 22.

**An epic is never offered as work.** `story` mode applied no type filter, so the pool offered a freshly filed epic beside its own stories. It now leaves `Epic` out in every mode.

**An update names only what it changes.** An update entry had to restate Priority, Effort and Ownership even when the issue carried all three. It is now refused only when a value it leaves out is missing from the issue too. A `TODO` it writes is still refused. The one-issue-one-party rule is judged against the title and owner the issue will have afterwards, so setting `Human` on an unprefixed issue is refused as a create would be.

**An update no longer moves a card it does not own.** Found live: setting one field on an in-progress issue moved its card back to Backlog, where a second agent could pick it up. An update writes only Backlog, Blocked and Non-code, and leaves a card in any other lane where it is. A spec entry can name a lane outright with `"state": "backlog" | "refinement" | "parked"`.

**`blocked_by` is the complete set.** A restated list removes the edges it omits, and `[]` releases them all; leaving the key out leaves the edges alone. A card in Blocked is re-placed once its last edge goes.

**An issue nobody owns goes to Needs refinement**, not Backlog, because nothing can route it.

**Preflight finds the rest of the retired workflow, and `--fix` clears what it safely can.** New checks: `board-retired` (a `Ready` column survives), `label-retired` (open issues still carry a label the fields replaced), `field-retired` (the org still defines `Status reason`), `field-options` (an option on a required field no decision knows) and `instructions-retired` (a `CLAUDE.md` or `ClaudeProject.md` still describes the `Ready` opt-in, `Status reason` or a lifecycle label). `--fix` now takes retired labels off open issues, and empties a `Ready` column into Backlog before deleting it, only once every card has moved. It never deletes an org field or rewrites somebody's instructions. `field-unpinned` is critical, as the code always had it.

**Instructions match the code.** Every command, skill, template and reference was swept for the `Ready` opt-in, `Status reason`, priority, state and scope labels, and dependencies written as prose.

**Action for maintainers:** delete the `Status reason` issue field in the org settings. Preflight reports it as a warning and will not delete it, because deleting an org field deletes its values on every issue in every repository the org owns.

## local-workflow 2.14.0

**`feature-discovery` plans epics, features and stories.** The shared skill now breaks work into three levels, attaching to an existing epic or feature before proposing a new one, where it used to add epics only for large scope. The synced body standard and story template carry the same wording sweep as github-workflow 11.0.0.

## github-workflow 10.1.2

**The listing describes the workflow it actually has.** The marketplace entry and the plugin's own description still said the plugin picks an issue "from your backlog" and supports "configurable label mappings", which 10.0.0 removed: the pool is a board column and there is one issue label left, deciding nothing. Both now say what a run reads — the board column is the status, and Priority, Effort and Ownership are org issue fields — and both carry `project-board` and `issue-fields` keywords. Metadata only; no behaviour changed.

## github-workflow 10.1.1

Everything here came out of running 10.1.0 against a live board for the first time.

**`--fix` no longer eats the prose around the `### Status Options` table.** It replaced the whole section, so on the repository this plugin is developed in it deleted four paragraphs, including the one recording why `col-backlog` kept its old option id through a rename. Only the table's own lines move now.

**A lane the board has and the file does not record is reported.** `board-column` checked one direction: a recorded option id the board no longer has. Adding a column produces the other — the lane exists and `ClaudeProject.md` still says `n/a` — which meant the run that created three columns reported a clean board while the file said it had none of them. Both directions warn, because `board-move` resolves a column by name at write time, so a stale snapshot costs a lookup rather than the move.

**Three commands stopped naming a flag that does not exist.** `wf issue-audit --apply` was in the unprioritised-candidate warning, the unset-optional-field comment written onto an issue, and the `field-absent` fix text. There is no such flag: the audit writes a spec and `wf issue-apply` applies it, which is deliberate, because the dependency edges in that spec are inferred and want a person's eye first.

**A clean `issue-audit` reports `spec_written: false`.** It reported `true` beside a null path, which read as "the file is there" every time somebody checked whether the backfill had run.

## github-workflow 10.1.0

**Preflight is one command, in Python, and it can repair what it finds.** The gate every workflow command runs first was half a Python command (`wf config-audit`, comparing `ClaudeProject.md` against the live repo, board and org) and half a set of shell blocks inside the skill (`gh auth status`, the required-section grep, the placeholder scan, the quality-gate read, the `CLAUDE.md` check). Two implementations of one question, and they disagreed: a board with no `Backlog` column was fatal on the Python side and absent on the shell side. `wf preflight` is now the whole gate — every `config-audit` check plus the file-level ones — and the skill runs it and reads its JSON rather than greping anything itself.

**`wf preflight --fix` repairs seven things, idempotently.** It creates a missing board column, rewrites the `### Status Options` table from the live board, deletes a surviving `## Ready Gate` or `## Agent Gating` section, deletes a deprecated label-map row, adds the `ClaudeProject.md` pointer to an existing `CLAUDE.md`, and puts an orphaned issue or a card in no lane into `Backlog`. Then it re-runs every check and reports the state it leaves behind rather than the state it found — which is what makes the second run of the command tell you whether the first one worked.

**Every finding says whether `--fix` would touch it, and why not when it would not.** `auto: true` with a `fixable` saying how; `auto: false` with a `fixable` saying why — the value is the project's to choose, or two configured things disagree and either could be right, or the repair happens in the org settings rather than through the API. The split is decided offline (`wf_core.FIXABLE_CHECKS`), so "would running `--fix` change anything?" is answerable without a network call.

**Adding a column no longer risks the board.** `updateProjectV2Field` replaces the whole option list rather than adding to it, so an existing option passed back without its colour is silently recoloured and one omitted entirely is deleted along with every card in it. The repair path makes its own uncached read that asks for each option's colour and description, and every lane's colour and description now live in `wf_core` beside its name, so the wizard and the repair write the same board.

**`handoff` stopped writing a lifecycle label.** It swapped `status-in-progress` for `status-in-review` on every issue and then moved the card as well. The move is the hand-off; the label was a second record of it that 10.0.0 retired everywhere else.

**Claim reaping reads the assignment, not a label.** A stale claim was detected by the absence of `status-in-progress` — a label 10.0.0 stopped applying, so every healthy in-flight claim would have looked abandoned and been reaped out from under the session holding it. An issue claim is now stale when the issue is closed, when nobody is assigned, or when a PR is already open for it. The pull-request half still reads its review-state label, because a pull request has no board card and that label is the only record of where it is.

## github-workflow 10.0.0

**Breaking: no label decides anything, anywhere.** The issue-side labels are retired outright — every `status-*`, every `priority-*`, the two scope labels, `needs-refinement` and `claude-ready`. What replaced them was already there: an issue's state is the board column its card sits in, and its priority, size and owner are the `Priority`, `Effort` and `Ownership` fields. 9.0.0 kept the labels as a human-readable mirror; a mirror that nothing reads is a second answer to every question the board already answers, and the two drift. The only issue label left is the `claude-authored` provenance marker. Pull request review-state labels (`needs-review`, `reviewing`, `approved`, `changes-requested`) are untouched — they describe a pull request, which has no board card.

**Human approval is a column, not a label.** `agent-gating` and the `claude-ready` label are gone. A person approves work by moving its card into `Backlog` and withholds approval by leaving it in `Needs refinement` or `Parked`. That was the last label driving a picker decision, so selection now reads structured state end to end: the column decides eligibility, native blocked-by edges exclude, `Priority` orders, `Effort` bounds, `Ownership` decides suitability. A `## Agent Gating` section left in an existing `ClaudeProject.md` is read and ignored, and `wf config-audit` reports it so it gets deleted rather than believed.

**Four fields are required; two are optional and comment instead of failing.** `Ownership`, `Status` (the board column), `Effort` and `Priority` must be set — `wf issue-apply` refuses a spec that leaves one blank, **and refuses one naming a field the org has never defined**, which is what let a repository run for weeks with no `Ownership` field while `config-audit` reported a clean configuration. `Classification` and `Origin` are optional: an issue created without one gets a comment naming it, never a refusal. `Status reason` has been removed from the plugin entirely — it was never read.

**A missing `Priority` sorts last and says so.** The `priority-*` label fallback is gone, so an issue with no `Priority` value sorts behind every issue that has one and is named on stderr with the command to backfill it. `wf candidates` reports `unprioritised_count` where it used to report `label_ordered_count`.

**`unblock` reads the board.** The sweep used to list every open issue carrying the blocked label. It now reads the `Blocked` column, which is where `issue-apply` puts blocked work, so the sweep and the writer agree by construction.

**`config-audit` catches two new ways a board can lie.** `board-orphan` is an open, unassigned issue with no card — invisible to the pool. `board-unset` is a card sitting in no lane — an issue with no state. Both are critical, because both silently shrink the pool. `field-absent` (the org defines no `Priority`, `Effort` or `Ownership`) is critical too; `field-absent-optional` warns.

### Upgrading

Run `/github-workflow:preflight` (or `wf config-audit`) first — it names everything that has to change. In summary: delete every retired row from `## Label Map` (keep `claude-authored`), delete any `## Agent Gating` and `## Ready Gate` section, and make sure the org defines `Ownership`, `Effort` and `Priority` as issue fields. Existing issues need no edit: `wf issue-apply` strips a retired label from any issue it writes, and `wf issue-audit --apply` backfills a missing field value. The retired labels can stay in the repository — deleting one strips it from every issue that ever carried it, which loses history for nothing.

## local-workflow 2.13.3

**The shared story template stopped naming labels.** `feature-discovery` and the story template described a manual story as carrying the `status-non-code` label and a thin one as carrying `needs-refinement`; neither label exists in github-workflow any more. Wording only — local-workflow has no board and no fields, so nothing behavioural changed.

## local-workflow 2.13.2

**`Ready` left the shared vocabulary.** `feature-discovery` suggested a `Ready` state alongside the github-workflow lifecycle it mirrors; that state no longer exists in either plugin. Wording only.

## github-workflow 9.0.0

**Breaking: the pick pool is the board's Backlog column, and a board is now required.** Selection used to be opt-in — an issue was invisible until somebody applied `status-ready` — and the four `ready-gate` settings each described a different way of asking for that opt-in. On the repository this plugin is developed in, that produced `no-candidates` while three perfectly workable issues sat in the backlog, and `wf config-audit` reported nothing wrong. Selection is now opt-out: every unassigned open issue in the board's `Backlog` column is available, and an issue leaves the pool by being moved somewhere else. A project with no board, or a board with no Backlog column, is a configuration error rather than an empty backlog.

**`Ready` is gone everywhere.** The `status-ready` label, the `col-ready` board column, the `## Ready Gate` section and the `ready-gate` setting have all been removed — from the picker, the label map, the board columns, the templates, the commands, the skills and the docs. A `## Ready Gate` section left in an existing `ClaudeProject.md` is read and ignored, so no project has to be edited before this version works; nothing consults it.

**A lifecycle label no longer decides anything.** It says what state an issue is in, for a person reading the issues list. The board column and the structured fields are what commands read. An available issue therefore carries **no** lifecycle label at all, which is why `report-issue`, `code-review` and `execute` no longer apply one when they file work.

**Ownership is a structured field.** `Ownership` (Code agent / Browser agent / Human) joins `Priority`, `Effort`, `Classification` and `Origin` in the mandatory set, so an org that defines it must carry a value on every issue the workflow creates, and the picker reads it first — the `browser-agent` and `human-required` labels remain the fallback for issues written before the field existed. `wf issue-audit` backfills it from an issue's scope rather than leaving a placeholder, because unlike the other mandatory fields this one has an answer for every issue.

**Effort orders the pool, and `--max-effort` narrows it.** Within a priority band, `Low` comes before `Medium` before `High`, and an issue with no estimate sorts as Medium rather than dropping to the end. `wf pick --max-effort low` and `wf candidates --max-effort low` exclude anything bigger, so a short session can ask for work that fits in it.

**`config-audit` fails on a board that cannot be picked from.** A new `board-lane` check reports a missing board, a `project-node-id` that resolves to nothing, and a missing `Backlog` column as critical, and every other missing lane as a warning. Three lanes were added for states that previously had nowhere to go — `Needs refinement`, `Parked` and `Needs attention` — so every lifecycle state now pairs with a column. That takes the board to nine lanes against the enum's eight colours, so 8.2.1's rule that no two share one is kept where it matters and relaxed once: `Parked` and `Done` both take the spare `GRAY`, and every lane an issue passes through on its way to being done still differs from its neighbours.

**Board placement is batched.** Placing thirteen issues used to cost four round trips each; it now costs four in total, whatever the size of the spec, because the Status field is read once per run and the card lookups, adds and column writes are each one aliased request.

### Upgrading

Run `/github-workflow:preflight` (or `wf config-audit`) first — it names everything that has to change. In summary: the project needs a board with a `Backlog` column, the org needs an `Ownership` issue field, and any issue still carrying `status-ready` should have the label removed and its card moved to Backlog. The `status:ready` label itself can then be deleted.

## github-workflow 8.3.0

**Every issue reaches the board, including the ordinary ones.** `issue-apply`
decided a lifecycle lane for each issue it touched and then returned early
whenever the answer was "nothing is wrong", which meant a created code issue
with no blockers got no board card at all — it existed in the repository and
nowhere on the board. That was survivable while the pick pool was a label
query. It is not survivable once the pool is a board column, so the pickable
case now places the card in Backlog like every other case places its own.

**An update that is no longer blocked stops saying it is.** The same early
return left `status-blocked` on an issue whose last dependency had closed, and
its card in Blocked, until the separate `wf unblock` sweep happened to scan it.
The phase now clears the stale label and moves the card. It also reads the
issue's live labels rather than the spec's: an update entry that did not
restate its labels looked unlabelled, so the one path that had to find a stale
label never found one. Dependencies are read for every issue whose lane is
being decided, not only those whose entry restated `blocked_by`, so a
legitimate `status-blocked` is never cleared on the strength of a spec that
simply did not mention it.

**`wf board-move` resolves the column before it adds the card.** The other way
round, an issue destined for a column the board does not have was added to the
board and *then* found to have nowhere to go: the add succeeded, the status
write did not, and the card landed in the board's `No Status` bucket while the
caller was told `moved: false`. A report saying nothing happened, beside a card
that appeared from nowhere, is worse than either. A bad column name now costs
one query and writes nothing, and the failure names the columns the board does
have. Identity and column resolution share that query, so the safer order is
also one round trip cheaper than the one it replaces.

**`report-issue` no longer moves the board by hand.** `issue-apply` does it,
from the issue's own state, so the command's separate board step — which aimed
`status-ready` issues at a `Ready` column many boards do not have — is gone.

## github-workflow 8.2.1

**No two board columns share a colour.** The suggested palette gave Backlog and
Done both GRAY, and Non-code the same ORANGE as In Review, so a board built from
it had two pairs that are indistinguishable in a column header and in every view
grouped by Status. It reached six of ten boards on the org this was written for
before anyone looked. Seven columns now take seven colours, with GRAY spare:
Backlog GREEN, Ready BLUE, In Progress YELLOW, In Review ORANGE, Blocked RED,
Non-code PINK, Done PURPLE.

Documentation only. Nothing reads these values at runtime; `setup` suggests them
when it creates a column, and `wf board-move` resolves a column by name.

## github-workflow 8.2.0

**A merge now releases the work it freed.** Nothing did this before. `wf
post-merge` settles only the issues a pull request *closes*, so a pull request
that closes none reports `settled: []`, which reads as a finished run and is
not: the issues waiting on that work keep their `status-blocked` label, and a
blocked issue is invisible to the picker. On the project this was written for,
a merge left two downstream issues sitting there until the user asked whether
anything had been unblocked.

**New command: `wf unblock`.** It reads every open issue carrying the blocked
label and sorts them five ways.

- **released** — every native blocked-by edge points at a closed issue. The
  label is removed, the board card moves to Backlog, and a comment says what
  happened and why.
- **rescoped** — browser or human work sitting in the blocked lane. The label
  is swapped for `status-non-code`, the card moves to Non-code, and a comment
  says nothing about the work itself has changed. Never released: see the
  non-code lane below.
- **held** — at least one blocker is still open. Untouched.
- **partials** — held, but a blocker has merged something in the last fourteen
  days. Reported, never acted on: a story that ships half of itself stays open
  with correct edges while whatever needed only that half is free, and no
  edge-based rule can see it. The merge has to name the blocker in its **pull
  request title** to count. A body mention is far too weak; tried against a
  real backlog it flagged ten of the eleven held issues.
- **no_edges** — labelled blocked with no dependency edge at all, so nothing
  here can speak to them. Counted rather than listed.

Nothing is released without at least one edge, and that rule is doing real
work rather than being cautious. Two thirds of one real backlog's blocked
issues have no edge, and they are waiting on a bank account, a device pass, a
store upload. Reading "no open blockers" as "release" would put every one of
them in front of an agent that cannot do any of them.

`--dry-run` reports without writing. `--issue N` limits the sweep to one issue.

**`wf post-merge` runs the sweep** and returns it as `unblocked`, whether or
not it settled anything. `--no-unblock` opts out. `wf pick` runs it too when it
finds nothing to pick — that hook already existed as `auto_ready_scan`, and it
had never once worked: it read the body prose rather than the edges, and it
swapped the blocked label for a `status-ready` label that projects on a `none`
ready gate do not have, so its single `gh issue edit` failed and nothing
changed. It now calls the same sweep as everything else.

**A new lane for work no code agent can do.** Browser-agent and human-required
issues used to be parked under `status-blocked`, which was the only label that
kept them out of the pool. That was a hazard rather than a convention: the
sweep above releases anything whose edges have all closed, and both issues its
first real run would have released were `[Manual]` device passes whose blockers
happened to close. They would have gone straight into the code agent's pool.

- New lifecycle label **`status-non-code`** and new board column **`Non-code`**
  (`col-non-code`). Setup creates both; the column is never required, and on a
  board that lacks it the failed move is reported while the label still keeps
  the issue out of the pool.
- New scope label purpose keys `scope-browser` (`browser-agent`) and
  `scope-human` (`human-required`), so the ownership rule is now mechanical
  rather than a sentence in a skill document.
- `status-blocked` goes back to meaning one thing: an open dependency edge.
- `wf issue-audit` reports scope drift — both scope labels on one issue, a
  title prefix that disagrees with the label, scoped work with no
  `status-non-code`, or that label on an issue nothing scopes.
- Scope wins over a dependency. An issue that is both ends up in the lane no
  sweep will release it from, because the scope is a property of the work and
  survives every blocker closing.

**Every issue `wf issue-apply` writes now lands in the lane its own state
names**, and its board card moves to match. Nothing did this in either
direction before: a spec could write a dependency edge and leave the issue with
no lifecycle label at all, so `pick` offered work whose dependency had not been
built yet, and the board showed it in Backlog while GitHub showed it blocked.
`mark_blocked` moves the card too, so an issue returned to blocked mid-run no
longer leaves its card in In Progress.

**The `## Dependencies` prose is gone, not fixed.** A dependency was written
twice, as a native edge and as body prose, and a parser read the prose back. It
was wrong in both directions on one real backlog: it missed a `## Blocked by`
heading whose references sat on the next line, and it read "Nothing. This
**was** blocked by #980" as a live dependency. The two graphs disagreed on nine
of the fourteen issues carrying both, with the prose stale every time.

A sentence is not structured data, so nothing parses one now. `wf issue-apply`
writes the edge and only the edge, `wf pick` and `wf candidates` read the edges
in a single query instead of one call per reference, and `wf candidates`
reports each candidate's `dependencies`, `dependencies_open`, `blocked` and
`scope`. **A body naming a blocker with no edge behind it is not blocked** —
which was already true in effect, since the parser could not see it either.
`wf issue-audit` no longer proposes an edge from prose; there is nothing to
propose from. Where a real dependency exists only as a sentence, add the edge.

## local-workflow 2.13.1

Shared-skill sync only. `body-standard.md`, `story-template.md` and
`feature-discovery` stop telling a writer that `Depends on #N` prose in an
issue body is parsed and holds work back. It is not, in either plugin: the
dependency is the native blocked-by edge, and `github-workflow` 8.2.0 removed
the parser that read the prose. Nothing in this plugin's own behaviour changed.

## github-workflow 8.1.0

**Every issue is now scoped to exactly one party**, and `writing-github-issues`
says which three: a code agent that changes the repository, a **browser agent**
that drives a web console someone has already signed into, and a human for
everything neither can reach.

The browser agent is new. It fills non-credential fields, presses save and reads
identifiers back out. It cannot sign in, clear two-factor, download a file,
accept an agreement or touch anything financial, and it hands back rather than
working around any of those. Because it needs a session a person opened, a
`[Browser]` issue stays out of the pickup pool like a `[Manual]` one.

- New title prefix `[Browser] ` and new scope label `browser-agent`, alongside
  the existing `[Manual] ` and `human-required`. The two scope labels are
  mutually exclusive, and either one is accompanied by `status-blocked`, which
  is what actually removes an issue from selection.
- `strip_title_prefix` already leaves any prefix outside `TITLE_PREFIX_KINDS`
  alone, so `[Browser]` survives with no code change. Its docstring now says so
  rather than naming only `[Manual]`.

**Behaviour change worth reading before upgrading.** The old rule said an issue
that is mostly automatable with one human prerequisite keeps its `[Manual]`
prefix and stays whole. That is reversed: **split it**. Raise the other party's
work as its own issue and link the two with `Blocked by #N` in both directions.

The old shape looks finished and is not. A code story that does its half and
says "then a person sets the value" sits in the backlog, gets picked up, gets a
merged pull request, and the console step is never done because it never had a
card of its own. The test is what the issue produces: a commit, a saved console
form, or neither. Two answers means two issues.

Issues already written under the old rule keep working. Nothing rewrites them,
and a `[Manual]` issue with a mixed body is still a valid `[Manual]` issue; it
is just no longer what this skill will write.

## github-workflow 8.0.2

**Fixed:** `board-move --column col-backlog` now finds the column. The purpose
key resolved to a column named `Todo`, which is what GitHub calls the first
column on a new Projects v2 board, while the purpose key itself and every other
reference in the plugin call it `Backlog` — `templates/default-labels.md`, the
`ClaudeProject.md` template and `commands/report-issue.md`. Any board renamed to
match its own configuration therefore took every board move except the one to
the backlog, and that one failed quietly, because a board mirrors the lifecycle
labels and a failed move is deliberately never fatal.

`setup` now renames a board's default `Todo` column to `Backlog` instead of
adopting the name, passing the existing option id back so nothing sitting in the
column moves. `BOARD_COLUMN_NAMES` has a test pinning its values, not only its
keys, since the values are what `board_move` looks a column up by.

## github-workflow 8.0.0 / local-workflow 2.13.0

**Breaking (github-workflow):** the `pr-description` skill is renamed
`pr-body`. Call `/github-workflow:pr-body` instead. local-workflow's
`pr-description` is unchanged and keeps its name, because the two now
write genuinely different bodies and a shared name hid that.

- **One standard behind every issue and pull request body.** The rules
  that were half-stated in `pr-description` and half in
  `writing-github-issues` now live once, in
  `skills/_shared/body-standard.md`: the section vocabulary, the Summary
  and bullet rules, the title rules, the style, and what never appears.
  Those skills are now entry points over it and hold only what genuinely
  differs, so an issue and a pull request read the same way. Each entry
  point has its own slash command, so the two pull request formats cannot
  be reached by mistake.

- **Bodies are never hard-wrapped.** Each paragraph is one line, however
  long it runs. GitHub reflows markdown to whoever is reading it, so
  wrapping at 72 or 80 columns only fixed the breaks where they suited
  nobody and made every later edit rewrap a paragraph. The worked
  examples in both skills were themselves wrapped, which is what taught
  the habit; they are not any more.

- **A pull request body has a fixed shape.** `## Summary`, `## Changes`,
  `## Test plan`, in that order, every time, with `Closes #N` at the end
  and no invented headings. Previously the body was a `##` section per
  component, so no two pull requests looked alike. `execute` and
  `bulk-execute` now build their bodies from that shape rather than
  describing their own.

- **The plugins' own instruction files are unwrapped too.** Every skill,
  command, template, reference and doc in the repo is now one paragraph per
  line. They were the examples the model copied when it wrapped a body, so
  the rule and the files that teach it now agree. Content is unchanged: the
  pass preserved every heading, table row, list item and fenced code block
  byte for byte.

- **Issues a person has to finish are marked uniformly** (github-workflow):
  `[Manual]` at the front of the title, the existing `status-blocked`
  label, and a `## Manual step` section saying what has to be done and
  why. The three go together. `[Manual]` is the only title prefix the
  workflow keeps, because nothing native records that an issue needs a
  human, and story selection already skips `status-blocked`.

## local-workflow 2.12.0

- **`feature-discovery` writes one spec.** Where the host plugin provides
  `wf issue-apply` (github-workflow does), the whole story tree — titles,
  bodies, native types, fields, labels, parents and dependency edges — is
  created in a single command rather than created and then upgraded. Each
  body goes in its own file that the spec names, so nothing is hand-built
  into a JSON string. No `type-*` label and no `[STORY]` title prefix is
  written any more.

## github-workflow 7.0.0

The native issue type is now the only thing that says what kind of work an
issue is, and one command writes every issue.

**Breaking.** A `type-*` label classifies nothing any more, on any project.

- **`type-*` labels are gone from the label map.** `type-story`,
  `type-bug`, `type-security`, `type-debt` and `type-arch` are no longer
  purposes the tooling knows how to use. `wf config-audit` reports a
  project whose `## Label Map` still maps one (`type-label-deprecated`,
  a warning) and tells you which rows to delete. The labels themselves can
  stay on old issues; nothing reads them.
- **`## Issue Prefixes` is gone** from the `ClaudeProject.md` template and
  the spec. Titles carry no `[BUG]`, `[STORY]` or `[DEBT]` prefix.
- **`wf pick --mode feature|maintenance` needs native issue types.** It
  filters on the `issueType` field alone; an issue the org has not typed is
  out of the pool and named on stderr instead of being guessed at from a
  label or a title prefix. A project whose backlog carries no native type at
  all now exits `no-capabilities` (21) saying so, where it used to filter by
  label. `--mode story` is unaffected. To migrate: enable issue types for the
  org, then run `wf issue-audit` and apply the spec it proposes — it reads
  the old `type-*` labels and `[PREFIX]` titles precisely so it can backfill
  from them.

**One write path for issues.** `report-issue` and `feature-discovery` both
create issues through `wf issue-apply` now — one spec carrying the title,
body, native type, `Classification`, field values, labels, parent, blockers
and milestone, applied and read back in one request. Neither calls
`gh issue create`, and neither creates a label-only issue and upgrades it
afterwards. That two-step is why the board held half-classified issues.

- `issue-apply` strips a `type-*` label and a `[BUG]`-style title prefix off
  every issue it writes, on every org, and reports what it dropped.
- New spec key **`body_file`**: name a file and the body is read from it, so
  fenced code, backticks, `$` and quotes are never hand-built into a JSON
  string. The spec file keeps saying `body_file` after a write-back.
- New spec key **`milestone`**: an open milestone's title, so sprint
  placement rides in the same write. A title that names no open milestone
  fails the spec before anything is written.
- **A body always goes in a file.** `templates/body-file-write.md` now says
  so as a rule and says how — write the file with the Write tool rather than
  a shell heredoc, and if it must be the shell, a quoted heredoc. This
  covers pull request bodies and comments too.

**How issues are named.** `writing-github-issues` now carries the title
standard explicitly: a verb-first outcome phrase, sentence case, no trailing
full stop, roughly 70 characters or fewer, identifiers exact, and no
metadata in the title at all — no kind prefix, no priority, no size, no
sprint, no component tag. GitHub renders the type, the labels and the fields
beside the title already.

## github-workflow 6.5.1

Three ways the picker and the config audit disagreed with their own
documentation.

- **`pick` now skips parked issues.** Under `ready-gate: none` the only
  lifecycle label it excluded was `status-blocked`, so a `status-parked`
  issue a human had deliberately set aside came straight back as a
  candidate — and so did one that was in review or needed attention. All
  six unavailable states are now filtered for every ready-gate, in one
  place, so a gate cannot have its own answer. `status-ready` is the only
  pickable lifecycle state; an issue carrying no lifecycle label at all
  stays eligible, which is what `ready-gate: none` relies on.
- **The `board-column` and `both` ready-gates worked at all.** Their query
  asked GitHub for 200 board items in one page, which is rejected outright
  with `EXCESSIVE_PAGINATION`, so `pick` failed with `candidate fetch
  failed` on every project using them. Now paged 100 at a time.
- **`config-audit` no longer warns about the one asymmetry it calls
  correct.** `Parent` is deliberately not pinned to `Epic` — an epic is the
  parent — and the audit said so in the fix text of the warning it raised
  about it. A correctly configured org now audits clean.

## local-workflow 2.11.1

- `feature-discovery` now says which of the two priority tracks orders the
  backlog: the native field, with the `priority-*` label as the fallback.

## github-workflow 6.5.0

`pick` now orders the backlog by the org's native **Priority** field and
reads the native **Classification** field, instead of inferring both from
labels.

- **The pool is ordered by the `Priority` field.** `Urgent → High →
  Medium → Low`, then lowest issue number, exactly as before. An issue
  whose field is empty falls back to its `priority-*` label, and `pick`
  says on stderr which candidates that applied to, so an unset field is
  visible rather than silent.
- **`candidates` reports it too.** Each entry carries its `priority` field
  value (`null` when unset) and the payload carries `label_ordered_count`.
- **Native type filtering works at all now.** The old lookup asked for 200
  issues in one page, which GitHub rejects with `EXCESSIVE_PAGINATION`, so
  every org silently fell back to labels. It is now paged 100 at a time.
- **Maintenance mode reads `Classification`.** A native `Feature` counts as
  maintenance work when its `Classification` says so (single- or
  multi-select). A `Feature` with no classification is routed by its
  declared kind rather than dropped.
- Labels remain the fallback throughout: no field value, an unrecognised
  option name, or a failed lookup all fall back to the label, and the
  workflow *state* labels (`status-ready`, `status-blocked`,
  `needs-refinement`, `claude-ready`) are unchanged — the org has no
  equivalent field for them.

## github-workflow 6.4.1

Claiming a story with `--checkout` crashed on any org that defines a
`Start date` field, and the start-of-run cleanup could delete tracked
files.

- Fixed: `wf pick --checkout` raised `ValueError: too many values to
  unpack` while stamping the start date, because `set_issue_fields`
  answers three values and two were read. It fired after the claim, the
  label, the assignment and the board move had all landed, so the run
  exited non-zero with no JSON result and looked failed when it had
  succeeded. Nothing showed it until an org defined the field, which is
  what makes the mutation reachable at all.
- Fixed: the board move and the start-date stamp are both best-effort,
  but an exception in either stopped `checkout_branch` from running,
  leaving a claimed story with no branch to work in. Both now report an
  unexpected failure in their own result message and the branch is
  created regardless.
- Fixed: the `execute` and `bulk-execute` start-of-run blocks swept
  `.claude/claim-*.sha` with a plain `rm -f`, which stages the deletion
  of those markers in a project that commits them, and can delete a PR
  claim held by a review session sharing the checkout. The sweep now
  covers untracked `claim-issue-*.sha` only.

## github-workflow 6.4.0 · local-workflow 2.11.0

Consolidation pass across both plugins. No behaviour changes to any
workflow; the changes are to what the instructions say and how much of
it there is.

- Changed: the output standard every skill and command carries is now one
  block naming the three files that govern a reply (how it reads, what it
  contains and in what order, and what must never appear) instead of two
  paragraphs restating them. Roughly 45% shorter, in about 30 files.
- Fixed: `code-review` Step 2 said both "make no changes and move on" and,
  a paragraph later, that a lost claim should be retried against other
  candidates. It now says the first, once. The undefined term "Acquire" is
  gone, and the claim-ordering rule is a heading sentence rather than a
  run-on inside an unrelated exit-code bullet.
- Fixed: `code-review` Step 7 skipped from 7d to 7f, and its "do not fix"
  list sat under *Push* rather than under triage. Renumbered to 7a–7e with
  the exclusions where the triage happens.
- Removed: the runtime-variant compiler in `sync-skills.sh` and
  `sync-skills.ps1` (~190 lines of duplicated logic). It compiled
  `github-workflow/templates/runtime/worktree-hygiene.md`, which nothing
  ever loaded. The rationale it stripped now lives in
  `docs/rationale/worktree-hygiene-rationale.md`, matching every other
  template, and the template itself is 30 lines shorter at runtime.
- Fixed: the instruction-token footprint budgets in CI sat ~48% above what
  the files actually measure, so the gate had been passing vacuously.
  Re-ratcheted to measured + 2%, and the accreted recalibration history
  replaced by one statement of the convention.
- Fixed: `banned-patterns.md` banned words the plugins require as names —
  *harness*, *ecosystem*, *framework*, backlog *refinement*. Names are now
  explicitly exempt; the ban is on reaching for the word as filler.
- Fixed: both plugin READMEs told you to install with `--plugin-dir` and
  said the marketplace was unpublished. `github-workflow`'s claimed 8 slash
  commands (there are 4) and listed its skills twice; `local-workflow`'s
  omitted `debugging`, `doc-writer`, `security-audit` and `preflight`, and
  described six shared skills as local-only.
- Fixed: the shared-skill count (15, was stated as 12), the `ClaudeProject.md`
  skill list, and a dangling path in `docs/rationale/bulk-execute-rationale.md`.
- Changed: the "how to edit a shared skill" procedure was written out in
  three places. `CLAUDE.md` now holds it; `README.md` and
  `_shared-skills/MANIFEST.md` point there.
- Moved: the internal consumer inventory out of the public marketplace
  README into `docs/consumers.md`.

## github-workflow 6.3.0

- Fixed: a capability lookup that came back `NOT_FOUND` was recorded as
  `owner_kind: user`, filing an organisation away as a personal account. GitHub
  returns that error when the signed-in account may not see the org at all, so
  the result was a cache saying the org has no issue types and no fields, with
  no expiry — after which every issue was created with no type, no field values
  and no error anywhere. `NOT_FOUND` now counts as a denial alongside
  `FORBIDDEN` and `UNAUTHORIZED`, and an empty result is only believed when it
  carries the current cache schema, so a cache written by an earlier version
  heals itself on the next run instead of waiting for someone to know about
  `--refresh`.
- Fixed: `issue-audit` reported a `Classification` gap on issues that were
  classified correctly. It required the value to agree with the issue's kind,
  but `Classification` is a multi-select describing what the work touches, so a
  story marked `Documentation` or `Performance` was telling the truth. It now
  reports only genuine incompatibilities — a story classified `Bug Fix`, a bug
  classified `New Feature`.
- Fixed: `issue-audit` checked every org field, including Start date, Target
  date, Parent and Status reason, which nobody sets on most issues. On one
  69-issue backlog that produced 275 findings that no amount of work could
  clear, which made the audit useless as a check. It now checks the four
  mandatory fields only. The same backlog now reports two findings, both real.
- Fixed: an untyped issue was routed by looking its declared kind up in the
  type map, which put `[CHORE]` in feature mode and made `[FEATURE]` and
  `[EPIC]` vanish from every mode. Feature and maintenance now have their own
  explicit kind sets.
- Changed: `issue-apply` says on stderr when a spec creates an issue that names
  no labels. Nothing else supplies them, so such an issue carries no ready-gate
  label and no priority and `pick` will never select it.
- Changed: `setup` gained an `issues` focus and a step that audits the
  backlog's metadata, so `issue-audit` is reachable from a command rather than
  only from the CLI. Its exit-21 guidance now separates "the account may not
  look" from "the org genuinely has none", which are opposite situations that
  read identically.
- Changed: `report-issue` lost a redundant step that re-applied labels the
  previous step had already set, and both of its command samples now include
  the lifecycle label — without it the issue is filed but never picked up.
- Changed: the audit spec path is reported relative to the repository, and
  `.claude/issue-audit-spec.json` is now ignored by git like every other `wf`
  scratch file.

## github-workflow 6.2.1

- Changed: the parent an issue's body claims is now read only under
  `issue-audit --parents`, and a routine audit no longer proposes one. 6.2.0
  added the parsing to backfill a hierarchy that had been written in prose and
  never applied, which it did. Going forward it re-derives something the
  pipeline already knows: `feature-discovery` writes `"parent"` into the spec
  that creates a story, so on a repo whose issues arrive that way every issue
  that names its epic in the first line was reported as a gap carrying a value
  it already had. The capability stays, because a backlog written before any of
  this existed and an issue typed into the GitHub UI still have nowhere else to
  say it — it just has to be asked for. `missing-parent`, `parent-closed` and
  `parent-differs` are `--parents` only.

  The dependency half is deliberately **not** gated. `parse_dependencies` is
  not backfill code at all: `wf pick`, `wf candidates` and the unblock sweep
  read it on every run, and before 6.2.0 it classed four stories on one backlog
  as meta-issues that `execute` could never select, and reported a fifth
  blocked on the strength of a prose mention.

## github-workflow 6.2.0

- Added: `issue-audit` now proposes the **parent** an issue's body claims. An
  issue whose first line says `Part of the Cadence Plus epic (#959)` and which
  GitHub renders as free-standing was invisible as a child — the epic showed no
  sub-issues, and nothing anywhere reported that the two disagreed. Nothing in
  the plugin had ever read that sentence, though `issue-apply` could already
  write the relationship, so the capability existed and the audit simply never
  asked for it. On the backlog this was found in, one epic had 21 issues
  claiming membership and zero children. An issue that already has *a* parent
  is reported and left alone: a deeper parent is usually the more specific
  truth, and reparenting would flatten a hierarchy somebody built on purpose.

- Fixed: `parse_dependencies` treated every bare `#N` under a `## Dependencies`
  heading as a blocker. Real bodies put all of this under that heading —
  `Changes the scope of #982 and #1000`, `Supersedes #981`, `None of the three
  manual tasks block it`, `Depends on nothing. #863 does not have to land
  first` — so the edges it proposed pointed the wrong way, named work the body
  says is explicitly *not* required, and made issues block each other for
  merely mentioning each other. Measured against one 70-issue backlog it
  proposed 44 edges of which seven formed cycles, and the whole set had to be
  discarded by hand. A marker now has to sit in front of the reference, a
  negated marker (`No longer blocked on #1004`) is excluded, and a clause about
  some other issue (an epic's status list) no longer contributes the epic's own
  edges.

- Fixed: a dependency marker only ever captured the **first** reference after
  it, so `Depends on #977 and #1032` silently became one edge. This was the
  quieter half of the same defect and cost roughly half the real edges in the
  backlog measured.

- Added: `Blocks #N` is read and folded onto the issue it names. The edge
  belongs to the other issue, so only a whole-repo pass can place it, and until
  now nothing did — in practice the provisioning task is the one that knows
  what it holds up, and none of that reached the graph.

- Added: `NATIVE_TYPE_PREFERENCES`, so an org that has added a `Chore` issue
  type gets `Chore` for `tech debt` and `chore` rather than the `Feature` that
  GitHub's five defaults force. `NATIVE_MAINTENANCE_TYPES` gains `Chore` with
  it, which is not cosmetic: without it a backlog that types its debt correctly
  empties its own `execute mode=maintenance` pool, because the filter kept only
  `Bug`.

- Fixed: `issue-apply` refuses a spec entry that leaves a mandatory field blank
  and does not first check whether the issue already carries one, so an entry
  the audit proposed purely to add a parent or an edge was rejected for
  "missing" a value that was sitting on the issue. The audit now repeats the
  existing value, which makes the write a no-op and lets the spec round-trip.

- Fixed: `skills/bulk-execute/references/set-selection.md` told an agent to
  return a dropped story to the backlog with a literal `--add-label
  status-ready`. A project that renamed the label, or that runs the `none`
  ready-gate and has no ready label at all, got the whole `gh issue edit`
  refused — including the unassign, so the story stayed claimed by an agent
  that had already walked away. Both label names now resolve through the
  project's label map, and the ready label is dropped entirely under the `none`
  gate.

## github-workflow 6.1.3

- Fixed: `setIssueFieldValue` declared its `issueFields` variable as
  `[IssueFieldCreateOrUpdateInput!]` where the input object requires
  `[IssueFieldCreateOrUpdateInput!]!`, so GitHub rejected **every** field write
  with "Nullability mismatch on variable $f". Nothing about the values being
  sent was wrong, which is why the failure read as a data problem. All issue
  field writes went through this one function, so while it was malformed no
  issue metadata reached GitHub at all: `issue-apply` set native types happily
  and then failed on all four mandatory fields, and `set_start_date` never
  stamped a date. Every existing test of that path mocked the layer the defect
  was in, so the query itself is now asserted directly.

## github-workflow 6.1.2

- Fixed: a failed org capability lookup was written to
  `.claude/issue-fields-cache.json` and then trusted forever, so the plugin fell
  back to labels in silence. `resolve_org_capabilities` only refused to cache a
  capability GitHub named in a `FORBIDDEN` error, but an under-scoped or expired
  token can also answer with empty `issueTypes` and `issueFields` and no error at
  all. An org answering with neither types nor fields is no longer cached, and an
  all-empty cached record is now re-queried rather than trusted, so a cache that
  was already poisoned heals itself without anyone knowing to pass `--refresh`. A
  user-owned repo genuinely has neither, so a new `owner_kind` key marks that
  empty as deliberate and keeps it a cache hit.

## github-workflow 6.1.1

- Fixed: on a type-capable org, `execute --mode feature`/`--mode maintenance`
  silently dropped an issue that had no native issue type set yet, instead of
  falling back to its `type-*` label or `[PREFIX]` title. An org with zero
  typed issues got an empty pool from either mode with no error — plain
  `execute` (story mode) was unaffected, which is why it went unnoticed.
  `filter_by_native_type` now classifies an untyped issue the same way the
  label path would, and `wf pick`/`wf candidates` report how many candidates
  were classified this way, pointing at `wf issue-audit` to backfill the
  native type.

## github-workflow 6.1.0

- `## Issue Types & Fields` in `templates/ClaudeProject.md` is a complete,
  required section with a capability row, a field-name table and a
  *Missing* table, so a repo scaffolded from it cannot end up without one.
- `/github-workflow:setup` writes that section from `wf org-capabilities`
  rather than a static default, and writes it **even when the org has no
  native types** — saying so explicitly instead of leaving it out.
- `CHANGELOG.md`, consumer-pickup instructions and a consumer inventory
  added.

## github-workflow 6.0.0 — breaking

The workflow's mechanism moved out of markdown procedures and into the `wf`
CLI. Three things break for an existing consumer.

### Metadata that was best-effort is now mandatory

Issue creation goes through `wf issue-apply`, which **refuses** a spec that
leaves `Priority`, `Effort`, `Classification` or `Origin` blank. Commands
that previously created an issue with empty fields — and reported success —
now fail naming the issue and the field.

This is the point of the release. In one consuming repo the old
best-effort path produced 7 typed issues out of 82, no field values at all,
and no error anywhere.

**What to do:** make sure the four fields exist in your org's *Issue
fields* settings before upgrading. `Origin` is the one GitHub does not
create by default. Then run `/github-workflow:setup` so
`ClaudeProject.md` carries a `## Issue Types & Fields` section written from
your org's live capabilities. `wf issue-audit` reports which of your
existing issues are missing metadata and writes a backfill spec; `wf
config-audit` reports configuration problems, including a missing section.

### The inline fallbacks are gone

`execute` and `bulk-execute` previously carried a markdown copy of the
selection and claim procedures, used when Python was unavailable. The copy
drifted, nothing tested it, and it has been deleted.

**Python ≥ 3.8 is now a hard prerequisite** for those commands. Without it
they fail naming the missing prerequisite rather than running a second,
untested implementation. Run `/github-workflow:setup wf` to pin a
dedicated virtualenv. `code-review` keeps its own PR-selection fallback,
which detects SHA-changed PRs that `wf` cannot.

### Nine markdown templates were deleted

Any repo-local documentation citing these by path is now broken:

`templates/issue-fields-resolution.md`, `templates/board-resolution.md`,
`templates/story-selection.md`, `templates/story-selection-auto-ready.md`,
`templates/claim-procedure.md`, `templates/sibling-pr-lookup.md`,
`templates/label-reference.md`, `templates/reap-claims.md`, and
`skills/execute/references/inline-fallback-prewarm.md`.

Their behaviour is now `wf claim`, `wf claim-release`, `wf claim-reap`, `wf
board-move`, `wf sibling-pr`, `wf handoff`, `wf pick`, `wf issue-apply` and
`wf org-capabilities`. The review-state label table and the label read-back
policy moved into `templates/default-labels.md`; every `*-rationale.md`
moved to `docs/rationale/`, out of the agent read path.

### Also in this release

- New exit code **27 `lost`** — a claim another agent holds.
- `wf claim` applies the human-visible ownership marker (assignment plus
  the in-progress label, or the `reviewing` label on a PR), so ownership
  outlives the session that took the lock.
- `wf pick --checkout` sets the `Start date` field where the org has one.
- `## Issue Types & Fields` is a **required** section of
  `ClaudeProject.md`. It is required even on an org with no native types,
  because "this org has none" and "nobody wrote this section" otherwise
  look identical at runtime.

## local-workflow 2.10.0

- `feature-discovery` creates issues through `wf issue-apply` under
  github-workflow, so a discovery run classifies what it files instead of
  leaving the fields blank. No change on the local path.
