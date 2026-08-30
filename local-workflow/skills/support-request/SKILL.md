---
name: support-request
description: Write, format, or polish support request documentation. Use when the user mentions support requests or incident reports, or wants to document a technical issue and its resolution. Also trigger when the user pastes raw notes, logs, or ticket content to clean up into a support format. Covers internal and client-facing summaries. Do NOT use for user stories or feature specs (use user-story) or PR descriptions (use pr-description).
---
<!-- SYNCED from _shared-skills/ -- edit the source, not this copy -->

# Support Request Documentation

Read `_shared/banned-patterns.md` before writing. All banned patterns apply to support documentation.

Write support documentation that is clear, structured, and consistent. Every support request follows the same bones so readers know exactly where to look.

`skills/user-facing-communication/SKILL.md` shapes what you say to the
person **around** the support document: lead with the outcome and the current
state, keep it short, and surface anything outstanding or assumed. It
governs your reply, not the support document itself.

## Output Format

Always return the support request in **two separate code blocks** for easy copying:

1. **Title block**: The title on its own line, in a code block
2. **Body block**: The full markdown body (Request, Resolution/Findings, Notes) in a separate code block

Example output:

```
Support: DevOps Categories Update for Shoprite
```

```
## Request
Update the **DevOps** Categories list to include the following categories for **Shoprite**:
- Planned Effort
- Change Request
- Bug / Defect

Additionally, enable the Category and Client Name dropdown fields on Epics and Features.

---

## Resolution
- Added the requested categories to the DevOps Categories list.
- Enabled Category and Client Name fields on Epics and Features.
```

This format lets the user copy the title and body separately without selecting text.

## Structure

Every support request has **two or three sections**, depending on the outcome:

### 1. Title
A short, descriptive title prefixed with `Support:`. Keep it under 10 words. Focus on what was done or what system was affected.

Examples:
- Support: DevOps Categories Update for Shoprite
- Support: DBT Job 1A Timeout Investigation
- Support: Command Center Repo Provisioning

### 2. Request
State what was asked and why it matters. Include:
- The specific system, job, or component affected (bold the name)
- What went wrong or what was needed
- Any relevant context (timing, scope, impact)

Write as prose, but use bullet points when listing multiple discrete values (categories, permissions, fields, config items, etc.). This keeps lists scannable rather than buried in a sentence.

### 3. Findings / Resolution
Use **Findings** when the work was investigative (debugging, root cause analysis, diagnosis).
Use **Resolution** when the work was a discrete action (provisioning, granting access, config change).

For **Findings**:
- Use bullet points
- Each bullet is one distinct observation or conclusion
- Order from most important to least, or chronologically if that's clearer
- Keep each bullet to one or two sentences
- End with the root cause or most likely explanation

For **Resolution**:
- Use bullet points
- List what was done, not what was discovered
- Be specific: names, settings, permissions granted

### 4. Notes (optional)
Use only when there's a recommendation, caveat, or follow-up that doesn't fit in Findings/Resolution. Examples:
- A bug that should be fixed upstream
- A suggested config change to prevent recurrence
- A dependency on another team's action

One short paragraph or a few bullets.

## Multi-Turn Exchanges

When a support request spans multiple back-and-forth messages, preserve the full thread:

```
## Request 1
[First request]

## Response 1
[First response]

## Request 2
[Follow-up question or new info]

## Response 2
[Follow-up response]
```

Number sequentially. Each Request/Response pair follows the same rules as above.

## Formatting Rules

1. **Bold** system names, job names, tenant names, and error messages on first mention
2. Use `code formatting` for error strings, config values, and technical identifiers
3. No em dashes. Use commas or split into two sentences.
4. No filler phrases ("I can see that", "It appears that", "Upon investigation")
5. Lead with the finding, not the process of finding it
6. Horizontal rules (`---`) separate Request from Findings/Resolution, not between Findings and Notes

## Examples

### Example: Investigation with root cause

```
## Request
Investigate the failure of **Daily DBT Execution, Job 1A** for the Pay Just Now (SA instance). The script triggers and monitors a dbt job that runs approximately 1 hour 20 minutes. It failed after exceeding one hour, although timeout monitoring previously allowed completion.

---

## Findings
- The DBT job executed and completed successfully. No failure within the DBT run itself.
- The user script continued running beyond DBT completion and hit the configured timeout threshold.
- When the timeout occurred, the pipeline retry mechanism did not trigger as expected.
- No underlying DBT errors observed. The issue is isolated to orchestration and retry behavior.
- Execution overlapped with website release activity, which may have impacted retry handling at infrastructure level.
```

### Example: Resolution (action taken)

```
## Request
Provision the **Corrida Shoes, Production Repo** in Command Center and grant permission for the Corrida Shoes Datastore Connector to enable the **Copy ID** action. The option was not visible despite admin access.

---

## Resolution
- Required permission granted to enable the Copy ID action.
- Corrida Shoes, Production Repo provisioned in Command Center.
```

### Example: Findings with follow-up recommendation

```
## Request
Investigate the staging Snapshot Builder error **"Trigger User Script Command failed Internal Server Error"** after a large generic config update. The updated script cannot be triggered on staging; a simpler script continues to run successfully.

---

## Findings
- Generic config validation passes. Config format is unlikely to be the direct cause.
- Two scripts were previously working. Failure started immediately after a large config update to one script.
- The failing script has a substantially larger JSON payload (approximately 20 additional tables), increasing JSON load time.
- Most likely cause: staging performance causing JSON load/value fetch timeouts, resulting in an internal server error.

## Notes
Staging should fail gracefully with a clear timeout/error message rather than returning a generic internal server error. A staging-side bugfix is required.
```

### Example: Multi-turn exchange

```
## Request 1
Investigate timeout notifications for Pay Just Now. This is a different user script from the previous issue.
User Script: **Updated Daily Merchant Sales Performance**
Timeouts observed: **13 Jan, 11 Jan, 24 Dec**
Logs show all snapshots are still being sent out successfully.

---

## Response 1
This issue is separate from the previous one.

The PJN timeouts are due to scripts running longer than 1 hour. Most invocations approach the 3600-second container lifetime limit (60 minutes).

The failed script likely pulled slightly more data than normal, pushing it past the container execution lifetime.

Snapshots still sent because the script timed out after all emails were enqueued successfully. This may not always happen if timeouts continue.

Recommendation: decrease merchant IDs per batch from 1000 to 900. This may spin up an extra container but provides buffer time to prevent timeouts.

---

## Request 2
Made the update yesterday, reducing IDs per batch from 1000 to 900. Still seeing batches run at 1000. Is there another place where this setting needs to be updated?

---

## Response 2
The invoke script has the batch size set to 1000 in the daily pipeline. Changed it to 900. Batch sizes will be correct moving forward.
```

## When Rewriting Existing Content

If given rough notes or an existing support request to clean up:
1. Identify the request, findings/resolution, and any notes
2. Rewrite into the standard structure
3. Cut filler and redundancy
4. Bold key identifiers
5. Convert walls of text into scannable bullets (for Findings/Resolution only)
