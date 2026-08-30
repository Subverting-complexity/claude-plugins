---
name: preflight
description: >-
  Lightweight read-only check that a local project is ready to work in:
  git repo state, working tree, CLAUDE.md, ecosystem config, and a
  discoverable quality gate. Reports pass/warn with one next step per
  warning — validates only, never mutates. Trigger on "preflight",
  "check my setup", or "is this project ready".
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(git status *)
  - Bash(git branch *)
  - Bash(git rev-parse *)
  - Bash(ls *)
  - Bash(grep *)
---

# Preflight Check

Validate the local project setup before starting work. This skill is
**read-only**: it checks and reports, and never creates, edits, or
deletes anything — no files, no branches, no config.

## Checks (one shell round-trip)

```!
# All checks below are read-only.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "OK git-repo"
  branch=$(git branch --show-current)
  if [ -n "$branch" ]; then
    echo "OK git-branch: $branch"
  else
    echo "WARN git-head: detached HEAD"
  fi
  gitdir=$(git rev-parse --git-dir)
  if [ -d "$gitdir/rebase-merge" ] || [ -d "$gitdir/rebase-apply" ] || [ -f "$gitdir/MERGE_HEAD" ]; then
    echo "WARN git-op: merge or rebase in progress"
  fi
  if git status --porcelain 2>/dev/null | grep -q '^UU'; then
    echo "WARN git-conflicts: unresolved merge conflicts"
  fi
  dirty=$(git status --porcelain 2>/dev/null | grep -c . || true)
  if [ "${dirty:-0}" -eq 0 ]; then
    echo "OK git-tree: clean"
  else
    echo "WARN git-tree: $dirty uncommitted change(s)"
  fi
else
  echo "WARN git-repo: not a git repository"
fi

if [ -f CLAUDE.md ]; then
  echo "OK file-CLAUDE"
else
  echo "WARN file-CLAUDE: CLAUDE.md not found"
fi

if [ -f .claude/ecosystem.md ]; then
  echo "OK ecosystem: configured"
elif [ -f .claude/ecosystem-declined ]; then
  echo "OK ecosystem: declined (opt-out respected)"
else
  echo "WARN ecosystem: companion tools not set up"
fi

gate=""
if [ -f package.json ] && grep -qE '"(test|lint|build|check)"[[:space:]]*:' package.json; then
  gate="package.json scripts"
elif [ -f Makefile ]; then gate="make (Makefile)"
elif [ -f Cargo.toml ]; then gate="cargo test"
elif [ -f pyproject.toml ] || [ -f pytest.ini ] || [ -f tox.ini ]; then gate="pytest"
elif [ -f go.mod ]; then gate="go test ./..."
elif ls ./*.sln >/dev/null 2>&1; then gate="dotnet test"
fi
if [ -n "$gate" ]; then
  echo "OK quality-gate: $gate"
else
  echo "WARN quality-gate: no test/build command found"
fi
```

## Report

Summarize the output as a short pass/warn list — `[pass]` items first,
briefly, then one line per `WARN` with exactly one actionable next step:

- `git-repo` → run `git init` (or open the intended project folder)
- `git-head` → check out a branch: `git switch <branch>` or `git switch -c <new>`
- `git-op` / `git-conflicts` → finish or abort the merge/rebase before new work
- `git-tree` → commit or stash the changes so new work starts from a clean tree
- `file-CLAUDE` → add a `CLAUDE.md` with project rules and the quality-gate command
- `ecosystem` → optional: run `/local-workflow:ecosystem-setup`, or skip
- `quality-gate` → tell Claude the test command, or record it in `CLAUDE.md`

Warnings never block — report them and stop. Do not fix anything, even
if the fix looks trivial; the user decides what happens next.

The **shape** of that report follows
`skills/user-facing-communication/SKILL.md`: the overall verdict first,
then the warnings. Say plainly that nothing was changed, because a
read-only check is easy to mistake for a fix.
