# Reviewer agent: tool allowlist rationale

The tool list in `synergy/agents/reviewer.md` is least-privilege. This file records why each entry is there, so a later edit does not silently widen it. Nothing reads this file at runtime; read it before adding or widening an entry.

The Reviewer holds write tools because full mode fixes and pushes. Read-only mode, which is how `execute` and `bulk-execute` spawn it, uses none of them: `synergy/skills/pr-review/references/read-only-mode.md` is what keeps it from editing, pushing, labelling or merging.

## Entries

**Read, Edit, Write, Glob, Grep**: reading PR diffs and the code around them, applying fixes, searching for related files. There are no general file-utility Bash commands (cat, ls, find): the dedicated tools are faster and carry no risk of side effects.

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
