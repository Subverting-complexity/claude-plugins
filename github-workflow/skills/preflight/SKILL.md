---
name: preflight
description: >-
  Check project configuration health before running workflow commands.
  Verifies critical files exist, required sections are present, and
  settings are consistent. Invoked automatically by other commands —
  can also be run directly as a diagnostic. Trigger on: "check my
  config", "is my project set up", "preflight", "config check",
  "validate setup", "check configuration".
---

# Preflight Check

Verify project configuration is complete and consistent before running
workflow commands.

## 1. Check suppression

```!
if [ -f .claude/preflight-dismiss.md ]; then
  echo "PREFLIGHT_SUPPRESSED"
else
  echo "PREFLIGHT_ACTIVE"
fi
```

If `PREFLIGHT_SUPPRESSED`, skip all remaining checks. Return silently
and let the calling command proceed. The user has dismissed preflight
reminders. They can re-enable by deleting `.claude/preflight-dismiss.md`
or running `/github-workflow:setup`.

## 2. Run diagnostics

Run every check below and collect the output.

### GitHub CLI

```!
if gh auth status >/dev/null 2>&1; then
  echo "OK gh-auth"
else
  echo "CRITICAL gh-auth: not authenticated — run 'gh auth login'"
fi
```

### ClaudeProject.md

```!
if [ -f ClaudeProject.md ]; then
  echo "OK file-ClaudeProject"

  # Unreplaced template placeholders.
  # grep -c already prints "0" (and exits 1) when there are no matches,
  # so swallow the exit code with `|| true` rather than `|| echo "0"`
  # (which would append a second "0" and break the -gt test below).
  placeholders=$(grep -cE '\{(org|repo|name|id|package_manager|quality_gate_command|branch_pattern|default_branch|n|criteria|path/to/doc)\}' ClaudeProject.md 2>/dev/null || true)
  placeholders=${placeholders:-0}
  if [ "$placeholders" -gt 0 ]; then
    echo "WARNING placeholders: $placeholders unreplaced template placeholder(s)"
    grep -nE '\{(org|repo|name|id|package_manager|quality_gate_command|branch_pattern|default_branch|n|criteria|path/to/doc)\}' ClaudeProject.md 2>/dev/null | head -5
  fi

  # Required sections
  for section in "## Identity" "## Package Manager" "## Quality Gate" "## Branch Convention" "## Label Map"; do
    slug=$(echo "$section" | sed 's/## //; s/ /-/g' | tr '[:upper:]' '[:lower:]')
    if grep -q "$section" ClaudeProject.md 2>/dev/null; then
      echo "OK section-$slug"
    else
      echo "CRITICAL section-$slug: $section section missing"
    fi
  done
else
  echo "CRITICAL file-ClaudeProject: ClaudeProject.md not found"
fi
```

### CLAUDE.md

```!
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
```

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

## 3. Evaluate results

Read all output from the checks above. Categorize:

- **CRITICAL** — the workflow will fail (gh not authenticated,
  ClaudeProject.md missing, required sections absent).
- **WARNING** — the workflow may misbehave (placeholders, CLAUDE.md
  missing, quality gate not set).
- **OK** — check passed.

**If every check is OK**: proceed silently. Do not mention preflight
to the user. Return control to the calling command.

**If any CRITICAL or WARNING**: continue to step 4.

## 4. Present findings and ask

Show a brief summary using these markers:

- `[pass]` for OK items — list these first, briefly
- `[action needed]` for CRITICAL items
- `[recommended]` for WARNING items

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
