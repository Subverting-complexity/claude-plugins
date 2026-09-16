# Setup: reap orphaned claim refs

Read by `/synergy:setup reap`. Read `ClaudeProject.md` for org and repo first.

The workflow locks each in-flight issue or PR with a git ref under `refs/claims/`. These refs are released on every normal exit, but a crash or hard kill can leave an orphaned ref that silently blocks future pickup of that item. This step scans active claim refs, frees those that no longer back live work, and flags anything that needs manual review.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/wf.sh" claim-reap
```

Add `--threshold N` to change the age below which a ref is left alone (default **4** hours), or `--dry-run` to see the verdicts without freeing anything.

It always exits 0 and reports three lists. `reaped` are the refs it freed: the issue is closed, no longer marked in progress, or already has a PR open; the PR is closed, merged, or open with no review under way. `suspect` are the refs it deliberately left, because the evidence does not say the work has stopped: an issue still in progress with no PR, a PR under active review, or a target it could not read. `skipped` are refs younger than the threshold. Report the counts, and name every `suspect` ref with its reason so a person can decide.

It is safe to run at any time, because it never reaps a ref that still backs a running session, and is schedulable via `/schedule` calling `/synergy:setup reap`.

## Freeing a suspect ref by hand

If the stuck ref is flagged `suspect` (the issue is still in progress with no open PR), confirm no session is running for it, then free it manually:

```bash
git ls-remote origin 'refs/claims/*'           # list all active claims
git push origin :refs/claims/issue-{number}    # free a specific claim
```

Full background and safety notes: `docs/rationale/claim-procedure-rationale.md`.
