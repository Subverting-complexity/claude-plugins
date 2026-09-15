# Onboard: the `wf` picker runtime

Read by `/synergy:onboard` as Step 1b of the full onboarding, and on its own by `/synergy:onboard wf`.

`execute` has a **fast path**: a bundled `wf` CLI that runs the whole select → claim → validate loop in one call instead of a dozen sequential `gh` round-trips. It needs a Python 3 interpreter. This step pins a **dedicated virtualenv** for it, created once under the plugin's persistent data dir and reused on every later call, so the picker never depends on whatever Python is on PATH (and sidesteps the broken `python3` Store shim on Windows).

Run the bootstrap. It finds a working Python 3, creates the venv, installs `requirements.txt`, and verifies it; it is idempotent, so a valid venv is reused, not rebuilt:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" setup
```

- **Exit 0**: the virtualenv is ready; report the interpreter it pinned.
- **Exit 20, "Python 3 … not found"**: no Python is available. Show the user the platform install command it printed and ask them to install Python, then re-run this step. If they want it done for them, re-run as `wf.sh setup --install-python`, which installs system Python via winget/brew/apt and runs **only** with this explicit opt-in.

This step is **optional but recommended**. Without it the launcher still probes a system Python and uses that. But `wf` itself is not optional: `execute` and `bulk-execute` have no markdown fallback, so if the probe finds no Python 3 those commands fail naming the missing prerequisite. To rebuild a broken venv, re-run with `--force`.
