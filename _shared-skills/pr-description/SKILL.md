---
name: pr-description
description: Write, format, or structure Pull Request descriptions for development work. Use this skill whenever the user wants to write a PR description, document a code change, create a pull request summary, or document what changed in a branch or merge request. Also trigger when the user pastes rough notes, a list of changed files, or a verbal description of code changes and wants it turned into a structured PR. Trigger on phrases like "write a PR description", "document this PR", "write up these changes", "PR for this branch", "describe these code changes", or any request to create or format a pull request description. Works with any platform (GitHub, GitLab, Azure DevOps, Bitbucket, etc.). Do NOT use for reviewing code quality (use code-review instead). Do NOT use for writing user stories or feature specs (use user-story instead).
---

# PR Description Skill

Produces clean, structured Pull Request descriptions. The output is two separate, independently copyable markdown blocks: one for the **title** and one for the **description body**.

Read `_shared/banned-patterns.md` before writing. All banned patterns apply to PR descriptions.

---

## Output Structure

### Block 1 — Title

A single markdown code block containing only the PR title. This allows it to be copied cleanly into the PR title field.

```
<Concise, action-oriented title stating the purpose of the change>
```

### Block 2 — Description Body

A second markdown code block containing the full PR description in markdown. This goes into the PR description field.

The description body has two parts:
1. **Summary** _(optional)_ — A `## Summary` section at the top with 1-2 plain-English sentences stating the goal or impact. Only include when the user provides context or motivation, or when the reason for the change isn't obvious from the code alone. Omit if the component bullets are self-explanatory.
2. **Component sections** — One `##` section per logical module/component, with bullets describing what changed.

---

## Description Body Format

The description is made up of one or more **component/module sections**, each following this pattern:

```markdown
## [Component/Module Name]

- Added `ClassName` to handle [specific responsibility]
- Updated `MethodName` signature to include `newParameter`
- Removed deprecated `OldService` and associated logic
- Refactored `Processor` to centralize validation logic
- Updated dependency from `PackageA` to `PackageB` (version X → Y)
- Modified behavior of `Handler` to support [new condition/scenario]
- Introduced new file `filename.ext`
- Renamed `OldModel` to `NewModel`
- Updated interface `IService` with additional method `ExecuteAsync`
- Adjusted data mapping logic in `Mapper` for [specific field/structure]
- Removed redundant null checks in `Utility`
```

**Rules:**
- Each `## Heading` is a logical component, module, service, or file group
- Bullets describe *what* changed and *why* where relevant, with backticks for all code identifiers
- Do **not** include a Notes section
- Do **not** include a Summary or Overview section unless explicitly warranted (see above)
- Keep bullets factual and specific; avoid vague filler like "various improvements"
- Repeat as many `## Component` sections as needed to cover all changes

---

## Writing Guidelines

- **Title**: Start with a verb. Be specific. Example: `Add Configurable Discounts for Invoice Line Items`, not `Invoice changes`.
- **Bullets**: Lead with a past-tense or gerund action verb: `Added`, `Removed`, `Refactored`, `Updated`, `Introduced`, `Renamed`, `Adjusted`, `Modified`, `Extracted`, `Simplified`.
- **Code identifiers**: Always wrap class names, method names, file names, properties, and config keys in backticks.
- **Component headings**: Use the specific name of the module, service, page, or file group. If the user hasn't provided a specific name, use the most descriptive name inferable from the context.
- **No prose paragraphs**: Everything is a bullet. No introductory sentences.
- **Combining related bullets**: When multiple bullets share the same action or parent concept, combine them, either as an inline list (`Added tests: A, B, and C`) or with sub-bullets. Use sub-bullets when each item benefits from its own line for scannability.

---

## Examples

### Example 1: Standardizing Service Generation

**Title block:**
```
Standardize Service Generation Return Types and Clean Up Strategies
```

**Description block:**
```markdown
## Report Generation Service

- All service generation functions now return `void` or `Task`
- Removed `ExtravagantHoursReportStrategy`, `NoCommentReportStrategy`, `NonBillableReportStrategy`, and `ContractorPaymentReportStrategy`
- Removed `importantInformation` from method signatures and associated internal logic
- Cleaned unused namespaces: `TimeSync.Strategies.AuditStrategies.Exceptions`, `TimeSync.Strategies.ReportStrategies.Contractor`

## Client Validation

- Removed `CreateInformationMessage` and its RTF rendering logic
- Refactored `ValidateClients`: removed `importantInformation`, converted to direct logging, adjusted return type to `void`
```

---

### Example 2: Service Provider Discount Support

**Title block:**
```
Add Configurable Service Provider Discounts for Invoice Line Items
```

**Description block:**
```markdown
## Configuration

- Added new client discount config fields: `DiscountFactor`, `DiscountLineItemDescription`, `ServiceProvider`
- Validation rules: only one null entry allowed; `ServiceProvider` must match `Client.ServiceProviders.Name` or be null; no duplicate discounts per SP

## Invoice Generation

- Applies discount logic conditionally: SP-specific discount overrides client-wide
- Falls back to appending SP name if `DiscountLineItemDescription` is missing

## Audit Generation

- Excludes negative line items from audit calculations to preserve hour integrity
```

---

### Example 3: Warning System Overhaul

**Title block:**
```
Refactor Logging and Introduce Warning Management System
```

**Description block:**
```markdown
## Warning Management

- Created `WarningManager`, `WarningCollectorSink`, and `WarningSeverity` enum
- Added color coding, severity grouping, and timestamp formatting to `ShowWarnings`
- Added configurable severity filtering via `appSettings`

## Logging Refactor

- Adopted `Serilog.ForContext` to improve filtering
- Updated log severities to align with new `WarningSeverity`
- Added conditional log output via `DevopsSyncService` for runtime tuning

## Form Handling

- Updated `FormEmbedder` to return `RichTextMessageBox` with graceful handling of uncreated form handles
- Introduced `_embeddedRichTextMessageBox` field to support proper disposal and resource lifecycle
- Refactored `CleanDirectory` to instance method

## Code Quality

- Added null checks and input validations across affected modules
- Improved error handling for misconfigured settings
- Consolidated redundant logic
```
