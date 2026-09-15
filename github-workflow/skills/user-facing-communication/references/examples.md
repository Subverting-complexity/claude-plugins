# Worked examples

These examples show the expected level of detail. The aim is not to report everything that happened; it is to give the user the smallest clear handover.

---

## 1. Finished and deployed

> I fixed the employee list extraction and deployed the fix to production.
>
> The source website had changed, which stopped the extraction from moving between locations. The fix has been validated against live data.

Left out: files changed, investigation steps, failed theories, and test names.

---

## 2. Code complete, PR still open

> I completed **Issue #1091 — Deploy the backend Worker** and opened **PR #1092 — Make the backend Worker deployable**. **The PR has not been merged or deployed.**
>
> ### Outstanding
>
> - Run the database updates.
> - Deploy sandbox, then production.
> - Add the private credentials.
>
> I could not complete these because I do not have permission to change the required hosting and repository settings.
>
> ### Assumptions
>
> I left the existing credential untouched because it appears to be the wrong type for this integration, but I do not know whether it was created for something else.

Left out: branch names, commit details, files changed, commands, and test output.

---

## 3. Manual submission still required

> I completed the content-rating questionnaire. **Nothing has been saved or submitted yet.**
>
> ### Outstanding
>
> You still need to review the answers and submit the rating.
>
> ### Assumptions
>
> I answered **No** to “Primarily news or educational” because the app is a reader for content the user already owns.

Left out: all answers that were straightforward and did not require judgement.

---

## 4. Blocked before work started

> I could not start **Issue #204 — Add the export scheduler** because the issue does not say what should happen when a scheduled export overlaps one already running. I have not written any code.
>
> ### Outstanding
>
> Decide whether an overlapping export should queue, be skipped, or cancel the running export. I left a comment on the issue asking for that decision.

Left out: implementation options that depend on the missing decision.

---

## 5. Recommendation

> I would do the link-scanner study first. It is around 20–30 hours of mostly one-off work and should need very little maintenance afterwards.
>
> Newsjacking is cheaper per event, but it only works if pages can be published quickly and it has to be done regularly.
>
> I have not rechecked **Issue #278 — Fix publishing pipeline**, so I am assuming fast publishing is still a problem. If that has been fixed, I would compare the two again.

Left out: detailed mechanics, feature-by-feature comparison, and options already ruled out.

---

## 6. Multiple PRs completed

> I reviewed and merged **PR #1094 — One deploy entry point with a menu, lanes and a store listing push** and **PR #1092 — Make the backend Worker deployable** into `main`. **Issue #1091 — Deploy the backend Worker** is now closed.
>
> ### Outstanding
>
> **PR #1096 — Land the version bump by pull request, and default to patch** appeared during the session. It was outside the requested work, so I left it alone.
>
> ### Noteworthy
>
> GitHub shows the checks as failed, but they never started. This appears to be the existing GitHub Actions account problem rather than a code failure.

Left out: specific tests, files changed, review methodology, and resolved problems found along the way.

---

## Pattern

Across all examples:

- Outcome first.
- Exact current state.
- Outstanding work only when there is some.
- Assumptions only when they matter.
- Work items named as well as numbered.
- No proof-of-work detail.
- No repeated information.
