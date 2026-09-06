# Body-file write + validation

Canonical procedure for **every** multi-line body this plugin writes —
an issue body, a pull request description, a comment. It exists once here
so the write mechanics and the corruption test never drift between
callers.

Run it wherever a caller says "write the body following
`templates/body-file-write.md`".

## The rule: a body always goes in a file

**Never build a body as a shell argument, and never build one inside a
JSON string.** A body is prose with fenced code, backticks, `$`, quotes,
apostrophes and blank lines in it — every one of which is something a
shell or a JSON encoder will eat, and the result is the corrupt
one-character bodies the validation below exists to catch. Specifically:

- **Never** `--body "..."`, and never `--body -` — the latter does not
  read stdin, it sets the body to the literal string `-`.
- **Never** paste a body into a spec's `"body"` key by hand. Write the
  file and name it: `"body_file": ".claude/story-1-body.md"`.

## Write the file with the Write tool

Use the harness's file-writing tool, not the shell. It takes the text
exactly as you mean it, so there is no delimiter to collide with, nothing
to escape and no quoting to get wrong — which is where most body
corruption actually comes from.

Where a body must be written from the shell, use a **quoted** heredoc so
nothing inside it is expanded, and pick a delimiter that cannot appear in
the text:

```bash
cat > .claude/story-1-body.md <<'BODY'
{body}
BODY
```

`<<'BODY'` with the quotes, never `<<BODY` — unquoted, the shell expands
`$` and backticks inside the body before the file is written.

## Apply it

1. Write the intended body to a file (`.claude/` for anything a later
   step re-reads, a temp file otherwise).
2. Name the file rather than the text:
   - **Issues** — `wf issue-apply` with `"body_file"` on the entry. This
     is the only path that creates or updates an issue body.
   - **Pull requests and comments** — the `gh` command with
     `--body-file {file}`, plus whatever flags the caller specifies.
3. Delete a temp file after the command returns. Leave a `.claude/` file
   in place: a re-run after a partial failure needs it.

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
