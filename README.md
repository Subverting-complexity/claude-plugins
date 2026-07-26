# Subverting Complexity — Claude Plugins

A [Claude Code](https://claude.com/claude-code) plugin marketplace containing
development-workflow plugins by **Subverting Complexity**. It bundles two
complementary plugins that share a common library of skills:

| Plugin | What it's for |
|--------|----------------|
| **`github-workflow`** | End-to-end GitHub development: pick a story from your backlog, plan the architecture, build it, test it, open a PR, have that PR reviewed independently, and merge it — with board/label automation throughout. |
| **`local-workflow`** | The same structured engineering methodology, but project-agnostic and with **no GitHub or platform dependencies**. Plan, build, verify, and commit locally. |

Both plugins share a single canonical set of skills (architecture design,
feature discovery, structured coding, code review, security audit, and more),
so the two stay consistent. See [Repository layout](#repository-layout) below.

> **Install one, not both.** The two plugins overlap heavily — 12 of their
> skills are identical copies. Installing both loads those skill descriptions
> into every session *twice* and puts duplicate entries in the skill picker,
> which wastes context and can make Claude trigger the wrong copy. Pick the one
> that matches how you work:
>
> - **`github-workflow`** — your work flows through GitHub issues, boards, and PRs.
> - **`local-workflow`** — you want the same engineering methodology with no
>   platform dependencies (and the local-only extras: mobile-audit, tone, and
>   support-request).
>
> Everything in the shared library is in both, so you don't lose any of the
> core skills by choosing one. (This repo is the exception — it installs both
> only because it dogfoods them against itself.)

---

## Installation

Add the marketplace, then install whichever plugin(s) you want:

```bash
# 1. Add this marketplace
claude plugin marketplace add Subverting-complexity/claude-plugins

# 2. Install the ONE plugin you chose (see "Install one, not both" above).
#    Run only one of these:
claude plugin install github-workflow@subverting-complexity
claude plugin install local-workflow@subverting-complexity
```

Or run `/plugin` inside Claude Code (after step 1) to browse and install
interactively. Restart your session afterward so the plugins' skills,
commands, agents, and hooks load.

### Configuring `github-workflow`

`github-workflow` exposes a few user-config options. The only **required** one
is the GitHub org/owner of the repos you'll work against:

```bash
claude plugin install github-workflow@subverting-complexity \
  --config github_org=YOUR_ORG_OR_USERNAME
```

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `github_org` | ✅ | — | GitHub org or username that owns your repos |
| `default_branch` | | `main` | Main branch name |
| `branch_prefix` | | `feat` | Prefix for feature branches |
| `quality_gate_command` | | — | Command to run before PRs (e.g. `npm test`, `dotnet test`) |

You can also configure interactively with
`/plugin configure github-workflow@subverting-complexity`, or run the plugin's
own setup wizard by asking Claude to *"set up my project"*.

---

## Usage

Once installed, drive the plugins in natural language — the relevant skill
triggers automatically. A few starting points:

**`github-workflow`**
- *"What's next?"* / *"pick a story"* — surface the next backlog item
- *"Start story 42"* — assign it, update the board, create a branch
- *"Execute"* / *"start the next story"* — full pick → plan → build → test → PR → independent review → merge
- *"Finish"* / *"open a PR"* — push, open the PR, update the board
- *"Review PRs"* — review the next open PR in full codebase context
- *"Report a bug"* — file a structured issue

**`local-workflow`**
- *"Build this …"* / *"implement this"* — end-to-end local plan → build → verify → commit
- *"Review my changes"* — correctness/security/quality review of a diff
- *"Audit the mobile code"* — React Native / Expo–specific audit
- *"Rewrite this in my tone"* — tone-matched correspondence
- *"Write up a support request"* — incident/troubleshooting documentation

---

## Repository layout

This is a monorepo. The two plugins share skills from a single canonical
source rather than duplicating them:

```
.
├── github-workflow/      # the GitHub-integrated plugin
├── local-workflow/       # the project-agnostic plugin
├── _shared-skills/       # canonical source for skills used by both plugins
├── bootstrap.sh /.ps1    # one-time per-clone setup (LF line endings + hook)
├── sync-skills.sh /.ps1  # deploy shared skills into each plugin
├── lint-skills.sh        # validate skill frontmatter / placeholders
├── hooks/pre-commit      # blocks synced-copy edits and CRLF line endings
└── CLAUDE.md             # contributor guide (read this before editing)
```

Each plugin also has its own README:
[`github-workflow/README.md`](github-workflow/README.md) ·
[`local-workflow/README.md`](local-workflow/README.md).

### Running parallel agents

Many of these workflows spawn parallel or background agents, and the Claude
Code harness gives each its own git worktree. If you run agents in parallel —
especially on Windows — read
[`docs/worktree-config.md`](docs/worktree-config.md) for the recommended
harness worktree configuration and a manual cleanup routine.

---

## Contributing

Read **[`CLAUDE.md`](CLAUDE.md)** first — it documents the rules that keep the
shared skills consistent. In short:

1. **Never edit a synced skill copy.** Files beginning with
   `<!-- SYNCED from _shared-skills/ -->` are generated. Edit the canonical
   source under `_shared-skills/` instead.
2. **Run `./sync-skills.sh` (or `./sync-skills.ps1`) after editing a shared
   skill**, and commit the canonical file together with its synced copies.
3. **Bump the affected plugin's version** in
   `{plugin}/.claude-plugin/plugin.json` before merging (patch / minor / major
   per the guidance in `CLAUDE.md`).

Bootstrap your clone once (idempotent) — this pins line endings to LF
(so files don't churn to CRLF on Windows and leave worktrees stuck
"dirty") and installs the pre-commit hook that enforces rule 1:

```bash
./bootstrap.sh      # macOS / Linux / Git Bash
./bootstrap.ps1     # Windows PowerShell
```

To install only the hook by hand:

```bash
cp hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

CI (`.github/workflows/ci.yml`) checks for skill drift, lints skills, and
validates each `plugin.json`.

---

## License

[MIT](LICENSE) © Subverting Complexity
