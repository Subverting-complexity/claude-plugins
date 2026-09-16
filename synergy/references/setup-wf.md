# Setup: the `wf` picker runtime

Read by `/synergy:setup` as Step 1b of the full onboarding, and on its own by `/synergy:setup wf`.

`execute` has a **fast path**: a bundled `wf` CLI that runs the whole select → claim → validate loop in one call instead of a dozen sequential `gh` round-trips. It needs a Python 3 interpreter. It runs from a **dedicated virtualenv**, created under the plugin's persistent data dir the first time it is needed and reused on every later call, so the picker never depends on whatever Python is on PATH (and sidesteps the broken `python3` Store shim on Windows).

The venv is created automatically: the first `wf.sh`/`wf.ps1` call with no venv yet and a usable system Python builds it in place (venv, pip upgrade, `requirements.txt`) before running the requested command, with no separate step and no warning. Run this step only to force a rebuild, or as the explicit fallback when no system Python is found:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" setup
```

- **Exit 0**: the virtualenv is ready; report the interpreter it pinned.
- **Exit 20, "Python 3 … not found"**: no Python is available, so the auto-bootstrap above also has nothing to build from. Show the user the platform install command it printed and ask them to install Python, then re-run this step. If they want it done for them, re-run as `wf.sh setup --install-python`, which installs system Python via winget/brew/apt and runs **only** with this explicit opt-in.

Without any system Python, `wf` still has no markdown fallback: `execute` and `bulk-execute` fail naming the missing prerequisite. If the auto-bootstrap silently fails to build the venv (e.g. no `venv` module, a locked-down filesystem), each call keeps falling back to system Python with the usual warning; run this step to see the actual error. To rebuild a broken venv, re-run with `--force`.
