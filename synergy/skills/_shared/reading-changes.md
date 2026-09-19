# Reading a change by what a user notices

The single procedure for turning a branch, a pull request or a set of notes into the list of changes a person would notice. `acceptance-criteria` turns that list into test steps and `release-notes` turns it into changelog lines, so both read a change the same way and group it the same way.

## What to read

- **The current branch** (the default): the diff against the default branch (`git diff {default}...HEAD`, where `{default}` is `main` or `master`, whichever the repository has) and the commit messages on it.
- **A pull request number**: `gh pr diff {number}` and `gh pr view {number} --json title,body,commits`.
- **One story inside a branch that carries several**, as `bulk-execute` builds them: only the commits whose message ends `(#{number})`, read with `git show` on each.
- **Notes the user pasted**: read them as the description of the change. Ask nothing about code you were not given.

## How to group

1. **One group per change a person would notice.** Several code changes that produce one visible behaviour are one group; one file that changes two visible behaviours is two. Group by what the person sees, never by file, module or commit.
2. **Sort each group into one of two kinds.**
   - **User-facing**: something a person using the product can see, do, or measure differently: a screen, a setting, a message, an error that no longer happens, a speed they would feel.
   - **Internal-only**: nothing a person using the product would notice: refactors, renames, test-only changes, build and tooling changes, documentation, a migration with no visible effect, groundwork for a feature that is not switched on yet.
3. **Describe each group by its effect, in plain words.** Name the part of the product a person would look for it under, and what now happens there. Keep code identifiers (class names, method names, field paths) out unless the person types them into a configuration screen.

A change that is both, such as a fix whose visible effect is small and whose internal work is large, belongs in the user-facing kind, described by its visible effect. A skill that also records internal work, as `release-notes` does, describes the internal part separately.
