# Step 4b — Assess re-review significance (re-reviews only)

Read this when the SKILL's **Step 4b** trigger fires: the PR being reviewed was **previously reviewed** (a prior review comment with a footer exists). Skip — and never load — this for first-time reviews; that is why it lives outside `SKILL.md`.

Extract the SHA from the previous review footer. Compute the diff between that SHA and the current HEAD:

```bash
git diff <previous-review-SHA>..HEAD --stat
git diff <previous-review-SHA>..HEAD
```

Classify the changes since the last review as **trivial** or **substantial**:

**Trivial** — all of the following are true:
- Only whitespace, formatting, or import-ordering changes
- Comment or documentation text fixes (typos, wording)
- Renaming that doesn't change behaviour (variable names, file renames with no logic change)
- Removing dead code that was flagged in the previous review

**Substantial** — any of the following:
- New or modified logic, control flow, or calculations
- New files, new dependencies, or changed APIs
- Test additions or changes to test assertions
- Security-relevant changes (auth, input validation, data handling)
- Anything that alters the observable behaviour of the code

**If trivial and previous verdict was `approved`:** Skip the full re-review. Post an abbreviated comment:

```
## Re-review by Claude

**Verdict: Approved**

Changes since last review are trivial (formatting / typos / cleanup).
Original approval stands.

<footer from review.config.md>
```

Remove the `needs-re-review` label, ensure the `approved` label is present, then run **Step 11** (auto-merge on approval, if enabled) and exit. Do not proceed to Step 5.

**If trivial and previous verdict was `changes-requested`:** Check whether the trivial changes address every item in the previous review's Issues Remaining list. If they do — all flagged issues are resolved by the diff — post an abbreviated approval:

```
## Re-review by Claude

**Verdict: Approved**

All previously flagged issues have been addressed with trivial fixes.

<footer from review.config.md>
```

Remove the `needs-re-review` and `changes-requested` labels, apply `approved`, then run **Step 11** (auto-merge on approval, if enabled) and exit. Do not proceed to Step 5.

If the trivial changes do NOT address all Issues Remaining, proceed to Step 5 for a full re-review — the original issues are still unresolved.

**If substantial:** Proceed to Step 5 for a full re-review regardless of previous verdict.
