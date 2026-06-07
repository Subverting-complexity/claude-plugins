# Body-file write + validation

Canonical procedure for **every** `gh` write that carries a multi-line
body — `gh issue create`, `gh issue edit`, `gh pr create`, `gh pr edit`,
`gh issue comment`, `gh pr comment`. It exists once here so the write
mechanics and the corruption test never drift between callers.

Run it wherever a caller says "write the body following
`templates/body-file-write.md`".

## Why a temp file (never inline)

**Always pass the body with `--body-file {tempfile}`. Never pass it
inline** with `--body "..."` or, worse, `--body -`. Inline bodies hit
Windows/PowerShell shell-escaping bugs, and `--body -` does **not** read
stdin (it sets the body to the literal string `-`). Both produce the
corrupt one-character bodies the validation below exists to catch.

## Write

1. Write the intended body to a temporary file.
2. Run the `gh` command with `--body-file {tempfile}` (plus whatever
   flags the caller specifies — `--title`, `--label`, `--milestone`, …).
3. Delete the temp file after the command returns.

## Validate (read back, apply the corruption test)

Immediately read the body back and confirm it was stored correctly:

```
# pick the matching read for what you wrote:
gh issue view {number}  --repo {org}/{repo} --json body --jq '.body'
gh pr view   {pr_number} --repo {org}/{repo} --json body --jq '.body'
```

Treat the body as **corrupt** if **any** of these is true — not just the
single `@` case, since the same escaping/stdin bugs also leave `-`, `.`,
`#`, or other lone punctuation:

- It is empty or only whitespace.
- After trimming whitespace it is shorter than ~10 characters.
- After trimming it consists only of punctuation/symbols (e.g. `-`, `@`,
  `.`, `#`) with no words — a stray shell artifact, not a description.
- **(PR bodies only)** it is missing a required `Closes #N` line for any
  linked issue — see the caller's "Closes #N" requirement.

## Retry

When the body is corrupt:

1. Re-write the intended body to a temporary file.
2. Re-apply with `--body-file` (the edit form of the same command):
   ```
   gh issue edit {number}  --repo {org}/{repo} --body-file {tempfile}
   gh pr edit   {pr_number} --repo {org}/{repo} --body-file {tempfile}
   ```
3. Delete the temp file.
4. Re-read and apply the **same** corruption test again — not just a
   "non-empty" check.
5. If still corrupt after the retry, warn the user that the body may
   need manual editing.

Comments (`gh issue comment` / `gh pr comment`) have no read-back identity
to re-edit; for those, the Write step (temp file + `--body-file`) is the
whole procedure — the validation/retry applies to issue and PR bodies.
