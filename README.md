# Subverting Complexity — Claude Plugins

A [Claude Code](https://claude.com/claude-code) plugin marketplace with one development-workflow plugin by **Subverting Complexity**, `github-workflow`. It covers two ways of working:

- **GitHub story work:** pick a story from your backlog, plan it, build it, test it, open a PR, and have that PR reviewed independently by agents in a fresh context, then merge it on projects that opt into unattended merging.
- **Local work:** plan, build, verify and commit on your machine, with no issue tracker and no pull request.

Both share one set of planning, review and writing skills. Until 13.0.0 these were two plugins, `github-workflow` and `local-workflow`, with fifteen skills copied into each. They are now one plugin, so every skill is listed once. A new name for it is still to be chosen.

> **Upgrading from `local-workflow`:** uninstall it (`claude plugin uninstall local-workflow@subverting-complexity`) and install `github-workflow`. `/local-workflow:build` is now `/github-workflow:build`, local review is `/github-workflow:code-review`, and `/local-workflow:pr-description` is `/github-workflow:pr-body`.

---

## Installation

Add the marketplace, then install whichever plugin(s) you want:

```bash
# 1. Add this marketplace
claude plugin marketplace add Subverting-complexity/claude-plugins

# 2. Install the plugin
claude plugin install github-workflow@subverting-complexity
```

Or run `/plugin` inside Claude Code (after step 1) to browse and install interactively. Restart your session afterward so the plugins' skills, commands, agents, and hooks load.

### Picking up a new version

An installed plugin does not update itself, and the failure mode is silence: `claude plugin update` reports *already at latest* against the **cached** copy of the marketplace, not against what is on `main`. So the marketplace refresh is not optional — it is the step that makes the update mean anything.

```bash
claude plugin marketplace update subverting-complexity
claude plugin update github-workflow@subverting-complexity
```

Then restart the session, so the new skills, commands, agents and hooks load.

Run these from a normal shell, not inside a Claude Code session — the CLI blocks nested sessions. If you need to run one from inside, prefix it with `env -u CLAUDECODE`. The command is `claude plugin`, singular.

Check what you actually have with `claude plugin list`, and compare against the version in [`github-workflow/.claude-plugin/plugin.json`](github-workflow/.claude-plugin/plugin.json). [`CHANGELOG.md`](CHANGELOG.md) says what changed and what breaks.

**Registering the marketplace is a per-machine step, once ever.** A repo can commit `enabledPlugins` to its own `.claude/settings.json`, so sessions opened there enable the plugin without anyone installing it by hand — but a machine that has never run `claude plugin marketplace add` fetches nothing and reports *No plugins installed*, with no error explaining why. See [`CLAUDE.md`](CLAUDE.md#declaring-a-plugin-in-a-consuming-project) for the verified behaviour matrix.

### Configuring `github-workflow`

`github-workflow` exposes a few user-config options. The only **required** one is the GitHub org/owner of the repos you'll work against:

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

You can also configure interactively with `/plugin configure github-workflow@subverting-complexity`, or run the plugin's own setup wizard by asking Claude to *"set up my project"*.

---

## Usage

Once installed, drive the plugins in natural language — the relevant skill triggers automatically. A few starting points:

**GitHub story work**
- *"Execute"* / *"start the next story"* / *"what's next?"* / *"pick a story"* / *"start story 42"* — full pick → plan → build → test → PR → independent review, then merge on projects that enable it
- *"Review PRs"* — review the next open PR in full codebase context
- *"Report a bug"* — file a structured issue

**Local work**
- *"Build this …"* / *"implement this"* — end-to-end local plan → build → verify → commit
- *"Review my changes"* / *"is this feature ready?"* — review of a diff or branch with no PR, with a React Native / Expo checklist when it applies
- *"Rewrite this in my tone"* — tone-matched correspondence
- *"Write up a support request"* — incident/troubleshooting documentation

---

## Repository layout

The plugin and the tooling that checks it:

```
.
├── github-workflow/      # the plugin
├── bootstrap.sh /.ps1    # one-time per-clone setup (LF line endings + hook)
├── lint-skills.sh        # validate skill frontmatter and wiring
├── check-budgets.sh      # cap description length and skill body size
├── hooks/pre-commit      # blocks CRLF line endings
└── CLAUDE.md             # contributor guide (read this before editing)
```

The plugin has its own README: [`github-workflow/README.md`](github-workflow/README.md).

### Running parallel agents

Many of these workflows spawn parallel or background agents, and the Claude Code harness gives each its own git worktree. If you run agents in parallel — especially on Windows — read [`docs/worktree-config.md`](docs/worktree-config.md) for the recommended harness worktree configuration and a manual cleanup routine.

---

## Contributing

Read **[`CLAUDE.md`](CLAUDE.md)** first — it holds the rules for editing the plugin, and it is the only place they are written down.

Bootstrap your clone once (idempotent) — this pins line endings to LF (so files don't churn to CRLF on Windows and leave worktrees stuck "dirty") and installs the pre-commit hook:

```bash
./bootstrap.sh      # macOS / Linux / Git Bash
./bootstrap.ps1     # Windows PowerShell
```

To install only the hook by hand:

```bash
cp hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

CI (`.github/workflows/ci.yml`) lints skills, runs the tests, enforces token budgets, and validates `plugin.json` and the marketplace manifest.

---

## License

[MIT](LICENSE) © Subverting Complexity
