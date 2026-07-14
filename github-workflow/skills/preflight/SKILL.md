---
name: preflight
description: >-
  Check project configuration health before running workflow commands.
  Verifies critical files exist, required sections are present, and
  settings are consistent. Invoked automatically by other commands —
  can also be run directly as a diagnostic. Trigger on "check my
  config", "preflight", or "validate setup".
---

# Preflight Check

Verify project configuration is complete and consistent before running
workflow commands.

When you report results to the user, follow
`skills/_shared/wording-standard.md` and avoid
`skills/_shared/banned-patterns.md`: say what is wrong and what to do
about it in plain language a reader who is not involved in this codebase
can act on.

## 1. Startup checks (one shell round-trip)

Run suppression, GitHub-CLI auth, `ClaudeProject.md`, and `CLAUDE.md` in a
**single** block so the common path costs one round-trip instead of four —
and so a suppressed project pays for none of the auth/grep work. (None of
these checks contain a code-fence delimiter, so they are safe in an
auto-run block — see issue #33.)

```!
if [ -f .claude/preflight-passed.txt ]; then
  echo "PREFLIGHT_ALREADY_PASSED"
elif [ -f .claude/preflight-dismiss.md ]; then
  echo "PREFLIGHT_SUPPRESSED"
else
  echo "PREFLIGHT_ACTIVE"
  crit=0

  # GitHub CLI auth (CRITICAL)
  if gh auth status >/dev/null 2>&1; then
    echo "OK gh-auth"
  else
    echo "CRITICAL gh-auth: not authenticated — run 'gh auth login'"; crit=1
  fi

  # ClaudeProject.md: existence (CRITICAL), placeholders (WARNING), sections (CRITICAL)
  if [ -f ClaudeProject.md ]; then
    echo "OK file-ClaudeProject"
    # grep -c prints "0" (and exits 1) when there are no matches, so swallow
    # the exit code with `|| true` rather than `|| echo "0"`.
    placeholders=$(grep -cE '\{(org|repo|name|id|package_manager|quality_gate_command|branch_pattern|default_branch|n|criteria|path/to/doc)\}' ClaudeProject.md 2>/dev/null || true)
    placeholders=${placeholders:-0}
    if [ "$placeholders" -gt 0 ]; then
      echo "WARNING placeholders: $placeholders unreplaced template placeholder(s)"
      grep -nE '\{(org|repo|name|id|package_manager|quality_gate_command|branch_pattern|default_branch|n|criteria|path/to/doc)\}' ClaudeProject.md 2>/dev/null | head -5
    fi
    for section in "## Identity" "## Package Manager" "## Quality Gate" "## Branch Convention" "## Label Map"; do
      slug=$(echo "$section" | sed 's/## //; s/ /-/g' | tr '[:upper:]' '[:lower:]')
      if grep -q "$section" ClaudeProject.md 2>/dev/null; then
        echo "OK section-$slug"
      else
        echo "CRITICAL section-$slug: $section section missing"; crit=1
      fi
    done
  else
    # Check for common alternative config filenames before reporting missing
    alt=""
    for candidate in project.config.md ProjectConfig.md claude-project.md .claude/project.md; do
      if [ -f "$candidate" ]; then alt="$candidate"; break; fi
    done
    if [ -n "$alt" ]; then
      echo "CRITICAL file-ClaudeProject: ClaudeProject.md not found but '$alt' exists — rename it to ClaudeProject.md"
      echo "CONFIG_RENAME_CANDIDATE: $alt"
    else
      echo "CRITICAL file-ClaudeProject: ClaudeProject.md not found — run /github-workflow:setup"
    fi
    crit=1
  fi

  # CLAUDE.md (WARNING-level)
  if [ -f CLAUDE.md ]; then
    echo "OK file-CLAUDE"
    if grep -q "ClaudeProject.md" CLAUDE.md 2>/dev/null; then
      echo "OK claude-ref"
    else
      echo "WARNING claude-ref: CLAUDE.md does not reference ClaudeProject.md"
    fi
  else
    echo "WARNING file-CLAUDE: CLAUDE.md not found"
  fi

  # Ecosystem tools onboarding nudge (informational — never blocks, never
  # CRITICAL). Speak up only when the project is configured (ClaudeProject.md
  # present) but has neither opted in (.claude/ecosystem.md) nor explicitly
  # opted out (.claude/ecosystem-declined). Declining once writes the marker,
  # which silences this permanently.
  if [ -f ClaudeProject.md ] && [ ! -f .claude/ecosystem.md ] && [ ! -f .claude/ecosystem-declined ]; then
    echo "ECOSYSTEM_TIP: companion tools (Graphify/RTK/etc.) not set up — optional"
  fi

  # One verdict token for the cheap checks above. "OK" means nothing here is
  # CRITICAL — the only CRITICALs still possible come from the by-hand
  # required-board checks in Section 2, which apply *only* on a
  # board-column/both ready-gate. On the common label/none gate, a cheap
  # verdict of OK is the whole verdict: return silently, no report.
  if [ "$crit" -eq 0 ]; then
    echo "PREFLIGHT_CHEAP_VERDICT: OK"
  else
    echo "PREFLIGHT_CHEAP_VERDICT: CRITICAL"
  fi
fi
```

**React to the token, do not re-derive it.** The block prints exactly one
of three lead tokens — branch on it without re-reading files:

- `PREFLIGHT_ALREADY_PASSED` — preflight already passed earlier this
  session (the marker exists). **Return silently and immediately**; run no
  further checks. The calling command proceeds.
- `PREFLIGHT_SUPPRESSED` — the user dismissed preflight reminders. Skip all
  remaining checks, return silently, and let the calling command proceed.
  They can re-enable by deleting `.claude/preflight-dismiss.md` or running
  `/github-workflow:setup`.
- `PREFLIGHT_ACTIVE` — the checks ran. Read `PREFLIGHT_CHEAP_VERDICT`: if it
  is `OK` **and** the ready-gate is `label` or `none` (no required board —
  confirm from the config already in context, no file re-read), there are no
  further CRITICAL checks to run. Write the pass marker (Section 3) and
  return silently. Only continue to the by-hand checks below when the gate is
  `board-column`/`both` (a required board can be CRITICAL) or
  `PREFLIGHT_CHEAP_VERDICT` is `CRITICAL`.

**`CONFIG_RENAME_CANDIDATE` — alternative config file found.** If the
block printed a `CONFIG_RENAME_CANDIDATE: {path}` line, a file with the
right content but the wrong name exists. Use `AskUserQuestion` to offer:
- **"Rename to ClaudeProject.md (Recommended)"** — rename the file
  (`git mv {path} ClaudeProject.md`), re-run the startup checks, and
  continue.
- **"Run setup instead"** — invoke `/github-workflow:setup`, which will
  create a fresh `ClaudeProject.md`.

**`ECOSYSTEM_TIP` is informational, not a finding.** If the block printed an
`ECOSYSTEM_TIP` line, the project is configured but has not opted into *or*
out of the companion tools. It is **never** CRITICAL or WARNING and never
gates a command. The only thing it changes: when you would otherwise return
silently (everything OK, or WARNINGs-but-no-CRITICAL), print **one** plain
line first — e.g. "Tip: companion tools like Graphify aren't set up. Run
`/github-workflow:setup ecosystem` to enable them, or skip — it's optional."
Then proceed exactly as before (write the pass marker, return control). It
shows at most once per session (the pass marker short-circuits later runs),
and once the user sets up or declines it stops entirely. If no `ECOSYSTEM_TIP`
line was printed, say nothing about ecosystem tools.

## 2. Run diagnostics

**Fast path (the common, healthy case).** Only **CRITICAL** items can
block a command (gh auth, `ClaudeProject.md` + its required sections, a
*required* board, `board-columns-incomplete`). Everything else is a
WARNING that proceeds on a default. The one-shot block above already ran
the cheap CRITICAL file/auth/section checks; the only checks left are the
**by-hand** ones below (quality gate, ready-gate/board), and the board
network check runs **only if a board is required or configured**. If
nothing is CRITICAL, **return silently and let the command proceed** — do
not compose a findings report. The WARNING-level results (placeholders,
label-map completeness, CLAUDE.md, quality gate, review config) only ever
print one informational line and never block.

Collect the output from the block above and the by-hand checks below.

**Reuse, don't re-read.** Several calling commands (`execute`,
`code-review`, `block-story`) auto-load the full `ClaudeProject.md` into
context before invoking preflight. When that copy is already present,
evaluate the by-hand checks (quality gate, ready-gate/board) against it —
do **not** open `ClaudeProject.md` again. Only read the file if it is not
already in context.

**Run expensive checks only when needed.** Network calls here are
conditional and rare. The board-identity `gh api` query runs **only when a
board is required** (ready-gate `board-column`/`both`); for the common
`label` ready-gate, skip it entirely — board writes are best-effort and
`templates/board-resolution.md` re-verifies identity at write time, so a
preflight network round-trip every command is wasted tokens and latency.
The auto-merge repo-setting and CI-gate checks run **only when
`auto-merge-on-approval` is `enabled`** in `review.config.md` (an opt-in,
off-by-default feature). None of these calls run in the default
configuration.

> The GitHub-CLI, `ClaudeProject.md` (existence, placeholders, required
> sections), and `CLAUDE.md` checks all run in the one-shot block in
> Section 1 above. The remaining checks below are read by hand because
> they need value extraction or a `gh` API call that an auto-run block
> cannot do reliably (issue #33).

### Quality gate command

Read this one by hand — do **not** use an auto-run (`!`-prefixed) block.
The quality-gate command lives inside a fenced code block in
`ClaudeProject.md`, and an auto-run block cannot contain a code-fence
delimiter without truncating itself mid-command (this previously emitted
a bash "unexpected EOF" error on every preflight run — issue #33).

Open `ClaudeProject.md`, find the `## Quality Gate` section, and read the
command inside its fenced code block. Then classify:

- Section missing, command empty, or still the literal
  `{quality_gate_command}` placeholder → emit
  `WARNING quality-gate: not configured or has template placeholder`.
- Otherwise → emit `OK quality-gate: {command}`.

### Ready-gate and project board

Read this by hand — board identity needs a `gh` API call plus value
extraction from `ClaudeProject.md` tables, which an auto-run (`!`) block
cannot do reliably (and the `gh` query below contains a code fence,
which would truncate an auto-run block — see issue #33).

1. Open `ClaudeProject.md`. In `## Ready Gate`, read the `ready-gate`
   value (`label`, `board-column`, `both`, or `none`).
2. A board is **required** when `ready-gate` is `board-column` or
   `both`. It is **optional** (best-effort board updates only) when
   `ready-gate` is `label` or `none` — neither needs a board, since
   neither uses a "Ready" column to gate pickup.
3. In `## Project Board`, read `project-node-id`, `project-title`, and
   the Status option ids.

Classify:

- **Board required but not configured** — a board is required and the
  `## Project Board` section is missing, or `project-node-id` is absent,
  `n/a`, or still a `{placeholder}`:
  emit `CRITICAL board-config: ready-gate '{gate}' requires a project board, but none is configured`.
- **Ready column missing** — `ready-gate` is `board-column` or `both`
  and the "Ready" Status option id is `n/a` or absent:
  emit `CRITICAL board-ready-option: ready-gate '{gate}' needs a "Ready" board column, but no Ready Status option id is configured`.
- **Active lifecycle columns missing** — a board **is** configured
  (`project-node-id` is real) but one or more of the three active
  workflow columns is absent. This is a **local table read, no network
  call** — check the `### Status Options` rows for `col-in-progress`,
  `col-in-review`, and `col-blocked`; any whose Option ID is `n/a`,
  absent, or still a `{placeholder}` is missing. If any are missing:
  emit `CRITICAL board-columns-incomplete: board is configured but missing lifecycle column(s) {names}` —
  the board cannot mirror the issue lifecycle until those columns exist.
  Run this **whenever a board is configured**, independent of ready-gate;
  setup creates these columns and records their option ids. A project with
  **no** board configured produces no finding here (the board is
  optional). The label ⇄ column pairing is in
  `templates/default-labels.md` → Board Columns. This is a **presence**
  check only (is an id recorded at all). Whether a recorded id still
  matches the live column — *staleness* — is a different question: it is
  validated by the live network check below on required boards, and on
  every board write by `templates/board-resolution.md` Step 4 (which now
  resolves the option id live by column name, so a stale snapshot
  self-heals at write time rather than misrouting an issue).
- **Board identity + snapshot freshness (required boards only)** — run this
  network check **only when the board is required** (ready-gate
  `board-column`/`both`). One query resolves the title **and** the live
  Status options, so both checks share a single round-trip:

  ```
  gh api graphql -f query='query($id:ID!){ node(id:$id){ ... on ProjectV2 {
    title
    field(name:"Status"){ ... on ProjectV2SingleSelectField { options { id name } } }
  } } }' -F id='<project-node-id>' --jq '{title:.data.node.title, options:.data.node.field.options}'
  ```

  - Resolves and the title **matches** `project-title` →
    emit `OK board-identity: '{project-title}'`.
  - Does not resolve, or the resolved title **differs** from
    `project-title` → emit
    `CRITICAL board-identity: stored project-node-id resolves to '<resolved>' but project-title is '<configured>'`
    (or `... does not resolve to a ProjectV2`).
  - **Snapshot freshness** — for each lifecycle column recorded in
    `### Status Options`, find the live option with the matching name and
    compare its id to the snapshotted Option ID. Any that differ (or whose
    name no longer exists live) → emit
    `WARNING board-snapshot-stale: column(s) {names} recorded id(s) no longer match the live board; run /github-workflow:setup to refresh the snapshot`.
    This is a WARNING, not CRITICAL — write-time live resolution
    (`board-resolution.md` Step 4) keeps moves correct regardless; the
    warning just prompts a cleanup so the snapshot stays honest.
- **Best-effort board (`label`/`none` ready-gate)** — do **not** make the
  network call. Board writes are best-effort and `board-resolution.md`
  both verifies identity and resolves the column id live at write time, so
  a stale title or stale option id is caught and self-healed there, not on
  every preflight. No finding here.
- **Board not required and not configured** — no finding. A `label` or
  `none` ready-gate with no board section is valid.

### Label-map completeness

```!
if [ -f ClaudeProject.md ]; then
  # Extract the ## Label Map section body (subsections use ###, which
  # does not match the ^## top-level header that ends the range). Pure POSIX
  # shell (no awk) so preflight runs even where awk is absent from PATH.
  labelmap=$(f=0; while IFS= read -r line || [ -n "$line" ]; do
      if [ "$f" -eq 1 ]; then case "$line" in '## '*) break ;; esac; printf '%s\n' "$line"; fi
      [ "$line" = "## Label Map" ] && f=1
    done < ClaudeProject.md)
  missing=0
  for purpose in priority-critical priority-high priority-medium priority-low \
                 type-story type-bug type-security type-arch type-debt \
                 status-ready needs-refinement status-in-progress status-parked \
                 status-blocked status-in-review status-needs-attention \
                 claude-authored; do
    if printf '%s\n' "$labelmap" | grep -q "$purpose"; then
      :
    else
      echo "WARNING label-map: no label mapped for purpose '$purpose'"
      missing=1
    fi
  done
  [ "$missing" -eq 0 ] && echo "OK label-map: all expected purposes mapped"
fi
```

### Review configuration

```!
# Review is "in play" when ClaudeProject.md references a review state-label
# file. If so, that file must exist or review-state labelling silently breaks.
if [ -f ClaudeProject.md ] && grep -q 'review\.config\.md' ClaudeProject.md 2>/dev/null; then
  path=$(grep -oE '[A-Za-z0-9._/-]*review\.config\.md' ClaudeProject.md | head -1)
  path=${path:-docs/review.config.md}
  if [ -f "$path" ]; then
    echo "OK review-config: $path present"
    if grep -qE 'auto-merge-on-approval' "$path" 2>/dev/null && grep -E 'auto-merge-on-approval' "$path" | grep -qiE 'enabled'; then
      echo "AUTO_MERGE_ENABLED — run references/review-auto-merge-checks.md"
    fi
  else
    echo "WARNING review-config: $path referenced by ClaudeProject.md but not found"
  fi
fi
```

If the block above printed `AUTO_MERGE_ENABLED`, the opt-in auto-merge
feature is on — read `references/review-auto-merge-checks.md` and run its
safety checks (repo `Allow auto-merge` setting + CI gate). Otherwise skip
it entirely; in the default configuration (no `review.config.md`, or
auto-merge disabled) those checks never run.

## 3. Evaluate results

Read all output from the checks above. Categorize:

- **CRITICAL** — the workflow **cannot proceed and has no usable
  default**: gh not authenticated, ClaudeProject.md missing, a required
  section absent, a **required** board (ready-gate `board-column`/`both`)
  unconfigured or its stored identity mismatched, or a **configured board
  missing its active lifecycle columns** (`board-columns-incomplete`).
  Only these trigger the wizard. The board-columns case is the one board
  gap that escalates even though board *moves* are best-effort: a board
  that exists but cannot mirror the lifecycle is a real misconfiguration
  the user must resolve (setup creates the columns), not a default-covered
  gap.
- **WARNING** — something is missing **but a default covers it**, so the
  workflow proceeds: an unmapped label purpose (resolves to its default
  name via `templates/default-labels.md`), unreplaced placeholders,
  CLAUDE.md missing, quality gate not set, a referenced
  `review.config.md` missing, a **required** board whose recorded column
  option-ids no longer match the live board (`board-snapshot-stale` —
  write-time live resolution keeps moves correct; the warning just prompts
  a snapshot refresh), `auto-merge-on-approval` enabled while the
  repo's "Allow auto-merge" setting is off (reviews still run; only the
  queued-merge step is affected), or `auto-merge-on-approval` enabled with
  **no CI gate** — neither GitHub required status checks nor
  `require-ci-before-merge` (an approved PR could merge with no CI
  guarantee; `/github-workflow:setup harden` wires up the gate).
  **Defaults are not
  a failure** — every label, the issue lifecycle states, and the
  review-state labels all have defaults, so a missing mapping is never
  critical on its own. (Best-effort board identity is **not** checked
  here — it is verified at write time by `templates/board-resolution.md`.)
- **OK** — check passed.

**Defaults-first principle.** Everything that *can* default *does* default
at runtime. The wizard exists only for the few things that genuinely have
no default (identity, auth, required board). Never escalate a
default-covered gap to the wizard.

**If every check is OK**: proceed silently — do not mention preflight to
the user. (The one exception is the `ECOSYSTEM_TIP` line described in
Section 1: if it was printed, emit that single optional-tools line first,
then continue.) Write `.claude/preflight-passed.txt` (creating `.claude/`
if it does not exist) so subsequent commands in this session can skip
the redundant re-run:

```
mkdir -p .claude
echo "preflight-passed" > .claude/preflight-passed.txt
```

Return control to the calling command.

**If there are WARNINGs but NO CRITICAL items**: do **not** prompt or run
the wizard. Print one concise line noting what is using defaults — e.g.
"Using default labels for {purposes}; run `/github-workflow:setup` to
customise" — then write `.claude/preflight-passed.txt` (same command as
above) and return control to the calling command. The command resolves
the missing names through `templates/default-labels.md` (and creates any
missing GitHub labels with the guarded create-if-missing pattern) on its
own.

**If any CRITICAL item is present**: continue to step 4 (the wizard).

## 4. Present findings and ask (CRITICAL only)

Reached only when at least one CRITICAL item exists. Show a brief summary
using these markers:

- `[pass]` for OK items — list these first, briefly
- `[action needed]` for CRITICAL items
- `[recommended]` for WARNING items — list them as informational
  (they are proceeding on defaults), not as reasons to configure

Then use `AskUserQuestion` with these options:

- **"Configure now (Recommended)"** — Run `/github-workflow:setup` to
  resolve the issues. After setup completes, the calling command
  continues with the updated configuration.
- **"Continue anyway"** — Proceed with the current command. Preflight
  will check again next time.
- **"Don't remind me"** — Suppress preflight checks until the user
  runs `/github-workflow:setup` or deletes
  `.claude/preflight-dismiss.md`.

## 5. Handle the response

**Configure now**: Invoke `/github-workflow:setup`. Once setup is done,
return to the calling command. Tell the user to re-run the command they
originally asked for, since the configuration loaded at the start of
the command was stale.

**Continue anyway**: Return immediately. The calling command proceeds
with whatever configuration is available. Next invocation of any
command will re-run preflight.

**Don't remind me**: Create `.claude/preflight-dismiss.md` with this
content:

```
# Preflight checks dismissed

Configuration checks have been suppressed. To re-enable:

- Delete this file, OR
- Run `/github-workflow:setup`
```

Then return. The calling command proceeds.
