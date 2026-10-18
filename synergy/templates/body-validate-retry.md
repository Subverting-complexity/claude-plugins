# Body-file write — validate and retry

Read this only when a body has a read-back identity to check — an issue or a pull request — and a write path has reported (or you need to check for) corruption. A comment has no read-back identity to re-edit, so none of this applies to one; for a comment, the write step in `body-file-write.md` is the whole procedure.

## Validate (read back, apply the corruption test)

For a body written with `gh ... edit --body-file`, immediately read it back and confirm it was stored correctly. `wf pr-create` and `wf issue-apply` already do this:

```
# pick the matching read for what you wrote:
gh issue view {number}  --repo {org}/{repo} --json body --jq '.body'
gh pr view   {pr_number} --repo {org}/{repo} --json body --jq '.body'
```

Treat the body as **corrupt** if **any** of these is true — not just the single `@` case, since the same escaping/stdin bugs also leave `-`, `.`, `#`, or other lone punctuation:

- It is empty or only whitespace.
- After trimming whitespace it is shorter than ~10 characters.
- After trimming it consists only of punctuation/symbols (e.g. `-`, `@`, `.`, `#`) with no words — a stray shell artifact, not a description.
- **(PR bodies only)** it is missing a required `Closes #N` line for any linked issue — see the caller's "Closes #N" requirement.

## Retry

When the body is corrupt:

1. Re-write the intended body to a temporary file.
2. Re-apply with `--body-file` (the edit form of the same command):
   ```
   gh issue edit {number}  --repo {org}/{repo} --body-file {tempfile}
   gh pr edit   {pr_number} --repo {org}/{repo} --body-file {tempfile}
   ```
3. Delete the temp file.
4. Re-read and apply the **same** corruption test again — not just a "non-empty" check.
5. If still corrupt after the retry, warn the user that the body may need manual editing.
