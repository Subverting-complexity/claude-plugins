# Builder agent: tool allowlist rationale

The tool list in `synergy/agents/builder.md` is least-privilege. This file records why each entry is there, so a later edit does not silently widen it. Nothing reads this file at runtime; read it before adding or widening an entry.

## Why the Builder is not the default agent

The plugin used to ship `synergy/settings.json` with `"agent": "builder"`. A plugin's `agent` setting makes that agent the main thread of every session, so the Builder's whole body became the system prompt and its allowlist restricted every ordinary chat in every repository the plugin was installed for, including rules such as "one story per session" and "do not ask for confirmation". The plugin is installed at user scope, so that was the wrong scope. The Builder is now only spawned by name or chosen by a person.

## Entries

**Read, Edit, Write, Glob, Grep**: core implementation: read existing code, make edits, create new files, search.

**git subcommands (explicit list)**: each subcommand is listed individually rather than using `Bash(git *)`, to block operations normal story execution never needs: `git clean`, `git reset`, `git stash`, `git bisect` and the like.

**Bash(gh \*)**: GitHub CLI for issue management, PR creation, issue field updates and API queries. It has to be broad because the workflow uses many `gh` subcommands.

**Bash(pnpm \*), Bash(npm \*), Bash(npx \*), Bash(yarn \*)**: JS package managers, to install dependencies and run tests in JS/TS projects. `npx` is there for local tool invocation (for example `npx jest`, `npx prettier`).

**Bash(dotnet \*)**: .NET build and test commands.

**Bash(python \*)**: the Python interpreter for Python quality gates.

**Bash(python3 \*)**: the Python 3 interpreter, for quality gates and test runners in Python 3 projects (for example `python3 -m pytest`).

**Bash(pip \*)**: Python package management for a project's dependencies.

**Bash(cargo \*)**: Rust build and test commands.

**Bash(go \*)**: Go build and test commands.

**Bash(make \*)**: Make-based build systems.

**Bash(bash \*.sh), Bash(bash \*.sh \*)**: run a project's quality gate and shell scripts by name. Restricted to `.sh` filenames on purpose: it blocks `bash -c "arbitrary code"` and process substitution (`bash <(curl ...)`) while allowing any named script.

**Bash(bash \*wf.sh\*), Bash(bash \*project-config.sh\*)**: the plugin's own scripts. The workflows call them as `bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" …`, and the closing quote after `.sh` means `Bash(bash *.sh *)` does not match, so every `wf` step would otherwise stop at a permission prompt nobody is there to answer.

**Bash(git restore \*), Bash(git clean -fd)**: the Start clean and End clean steps in `synergy/templates/worktree-hygiene.md` discard a worktree provisioned dirty, and exit cleanup requires them. `git clean` is allowed only as `-fd`, never `-x`, so gitignored secrets and `node_modules` survive. `git reset` and `git stash` stay out.

**Bash(date \*)**: the shared rules record the start time for the timeout.

**Agent**: the subagent-spawning tool. It exists so `execute` can spawn its one read-only Reviewer in a fresh context for the independent review. Without it the review cannot happen in a separate context, and the workflow falls back to the session that wrote the code reviewing it, which is the thing that review exists to avoid. The spawned agent carries its own allowlist, so this does not widen what the Builder itself can do.

**Bash(cat \*), Bash(ls \*), Bash(find \*), Bash(grep \*), Bash(rg \*), Bash(head \*), Bash(tail \*), Bash(wc \*)**: read-only filesystem utilities for when the dedicated Read, Glob and Grep tools are not enough (for example piping output for comparison).

**Bash(mkdir \*), Bash(cp \*), Bash(mv \*)**: directory and file management when creating modules and reorganising code.

**Bash(rm -f .claude/\*), Bash(touch .claude/\*), Bash(xargs -0 -r rm -f), Bash(test -f \*), Bash(echo \*)**: the run's own marker files. `execute` creates flags such as `.claude/no-merge.flag`, tests for them, and clears them and stale claim files at the start and end of a run. Removal is scoped to `.claude/` so it cannot delete project files. Issue #314 investigated whether the invocation-flags block in `shared-phases.md` — including `touch .claude/unattended.flag`, the signal a spawned Builder uses to mark itself unattended — is reliably reachable for a spawned agent. Run live as an actual `synergy:Builder`, the block (and `touch .claude/unattended.flag` specifically) completed with no permission prompt: these five entries already cover every command in it. Keep them; removing any one reopens that gap.

**Bash(git rev-parse \*), Bash(git ls-files \*)**: read-only: the head SHA recorded for the review, and the untracked claim files cleared at the start of a run.

**Bash(scripts/\*)**: run scripts from the repository's `scripts/` directory directly. Scoped to that path so arbitrary named scripts elsewhere cannot run.

**WebSearch**: research when the implementation needs external documentation.
