#!/usr/bin/env bash
# Bootstrap this clone for development. Idempotent — safe to re-run.
#
#   - Pin line endings to LF for this clone so the working tree matches the
#     repo's `.gitattributes` (* text=auto eol=lf). On Windows the system
#     default `core.autocrlf=true` fights that and leaves files (notably
#     CLAUDE.md) as phantom "modified", which blocks worktree cleanup and
#     keeps branches checked out. See docs/worktree-config.md.
#   - Install the pre-commit hook (blocks edits to synced skill copies and
#     blocks CRLF from being committed).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "==> Pinning line endings to LF for this clone"
git config core.autocrlf false
git config core.eol lf

echo "==> Renormalizing tracked files to LF (no-op if already clean)"
git add --renormalize .

echo "==> Installing pre-commit hook"
hookdir="$(git rev-parse --git-path hooks)"
mkdir -p "$hookdir"
cp hooks/pre-commit "$hookdir/pre-commit"
chmod +x "$hookdir/pre-commit"

echo "==> Done. If 'git status' now lists renormalized files, commit them once."
