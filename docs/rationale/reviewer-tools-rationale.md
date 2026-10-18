# Reviewer agent: tool allowlist rationale

The tool list in `synergy/agents/reviewer.md` is least-privilege. This file records why each entry is there, so a later edit does not silently widen it. Nothing reads this file at runtime; read it before adding or widening an entry.

The Reviewer holds write tools because full mode fixes and pushes. Read-only mode, which is how `execute` and `bulk-execute` spawn it, uses none of them: `synergy/skills/pr-review/references/read-only-mode.md` is what keeps it from editing, pushing, labelling or merging.

## Entries

**Read, Edit, Write, Glob, Grep**: reading PR diffs and the code around them, applying fixes, searching for related files. Prefer them to Bash file utilities: they are faster and carry no risk of side effects. The few utilities below are there only because a file the flow cites runs them in a shell block.

**git subcommands (explicit list)**: each subcommand is listed individually rather than using `Bash(git *)`. Reading: diff, log, show, status, rev-parse, symbolic-ref. Applying and pushing fixes in full mode: add, commit, checkout, fetch, rebase, push, branch. Resolving conflicts with the base branch before an auto-merge: merge. Destructive operations (`git clean`, `git reset`, `git stash`) are absent on purpose.

**Bash(gh \*)**: GitHub CLI for PR inspection, review comments, labels, issue updates and API queries. It has to be broad because the review skill uses many `gh` subcommands.

**Bash(pnpm \*), Bash(npm \*), Bash(npx \*), Bash(yarn \*)**: JS package managers, to run quality gates in JS/TS projects after applying fixes.

**Bash(dotnet \*)**: .NET build and test commands.

**Bash(python \*)**: the Python interpreter for Python quality gates.

**Bash(python3 \*)**: the Python 3 interpreter, for quality gates and test suites in Python 3 projects (for example `python3 -m pytest`).

**Bash(pip \*)**: Python package management for a project's dependencies.

**Bash(cargo \*)**: Rust build and test commands.

**Bash(go \*)**: Go build and test commands.

**Bash(make \*)**: Make-based build systems.

**Bash(bash \*wf.sh\*)**: the plugin's `wf` CLI, called as `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" …`; the closing quote after `.sh` means the entry below does not match it.

**Bash(git remote \*)**: a local review resolves the base branch from the remote.

**Bash(timeout \*), Bash(sleep \*)**: the auto-merge step waits a bounded time for checks, and the CI bypass waits before re-reading them.

**Bash(bash \*.sh), Bash(bash \*.sh \*)**: run a project's quality gate and shell scripts by name. Restricted to `.sh` filenames on purpose: it blocks `bash -c "arbitrary code"` and process substitution (`bash <(curl ...)`) while allowing any named script.

**Bash(grep \*)**: the CI bypass in `skills/pr-review/references/ci-bypass.md` pipes the output of `gh run view` for a failed run into `grep` to look for a billing failure.

**Bash(find \*), Bash(head \*)**: `skills/pr-review/references/review-config-guide.md` finds the project's build files and test directories to work out its tech stack.

**Bash(sed 's#^origin/##')**: a local review strips `origin/` from the default branch name. Only that exact expression is allowed, so `sed -i` cannot edit a file.

**Bash(mkdir -p .claude), Bash(cat > .claude/\*)**: `/synergy:report-issue`, which full mode runs to file a finding, writes its spec into `.claude/`. Nothing outside `.claude/` can be written this way.

`lint-skills.sh` runs `lint_allowlists.py`, which fails when a file the Reviewer's flow cites runs a command this list does not allow.
