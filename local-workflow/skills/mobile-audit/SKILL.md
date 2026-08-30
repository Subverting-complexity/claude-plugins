---
name: mobile-audit
description: >-
  Audit React Native (Expo) code for the current feature — reusable components,
  magic strings/components, data bleed, redundant code, buggy patterns, and API
  calls missing retries. Use to check a React Native/Expo feature for quality or
  production-readiness. Uses a linked story/issue as the scope baseline when
  available, else the branch diff. Do NOT use for non-mobile codebases (use
  code-review or verify-feature) or architecture-level audits (use code-architect
  audit mode).
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash(git diff *)
  - Bash(git log *)
  - Bash(git status *)
  - Bash(git show *)
  - Bash(cat *)
  - Bash(ls *)
  - Bash(find *)
  - Bash(grep *)
  - Bash(rg *)
---

# Mobile Audit — React Native / Expo

Audit the current feature's mobile code for quality, correctness, and
production-readiness. Scoped to React Native with Expo.

Read `CLAUDE.md` for project rules if it exists.

## Plain-English output

Everything you write for a person to read (each finding, its impact, and the summary) follows `_shared/wording-standard.md` and avoids `_shared/banned-patterns.md`. Assume a technically capable reader who is not involved in this codebase. Explain what a component or pattern is before you rely on its name, stay high-level and concise, and never let a string of identifiers replace a plain explanation. Reread anything you send and strip staccato fragments and banned patterns first.

The **shape** of what you report follows
`skills/user-facing-communication/SKILL.md`: lead with the outcome and
the current state, put anything outstanding, blocked or assumed where it
cannot be missed, name every work item as well as numbering it, and leave
out the investigation history. It applies to every reply you write, not
only the last one.

---

## Step 1 — Establish Feature Scope

### When a user story or issue is provided

Read the story or issue. Extract what the feature delivers, acceptance
criteria, and boundaries.

### When no story or issue is provided

Derive scope from the branch:

```
git log main..HEAD --oneline
git diff main...HEAD --stat
```

Read the commit messages and changed files to infer the feature boundary.
State the inferred scope before proceeding:
> "Based on the branch, this feature appears to: [description]. Auditing
> against that scope."

### Identify all feature files

From the diff, build the list of files this audit covers. Include:
- Changed files
- New files
- Files that import from changed files (one level out)

---

## Step 2 — Component Analysis

### Reusable components

Look for components that should be extracted or shared:

- **Duplicate JSX blocks.** Find near-identical JSX structures across
  feature files. If two components render the same shape with different
  data, that's a shared component waiting to be extracted.
- **Inline components.** Components defined inside other components
  (function declarations or arrow functions inside a render body) cause
  remounts on every render. Flag every instance.
- **Copy-pasted component logic.** Hooks, handlers, or effects that are
  duplicated across components. Should be a custom hook or utility.
- **Oversized components.** Components over ~150 lines that mix layout,
  business logic, and data fetching. Should be split.

### Magic components

- Components referenced by string name rather than import.
- Components rendered conditionally using string matching instead of
  a component map or registry.
- Dynamic component creation from string identifiers without type safety.

---

## Step 3 — Magic Strings

Find hardcoded string literals that should be constants, enums, or
config values. Check every feature file for:

| Category | Examples | Should be |
|----------|----------|-----------|
| Route names | `"HomeScreen"`, `"/(tabs)/profile"` | Route constants or typed route enum |
| API endpoints | `"/api/v1/users"`, `"https://..."` | API config constants |
| Storage keys | `AsyncStorage.getItem("token")` | Storage key constants |
| Event names | `emit("userLoggedIn")` | Event name constants |
| Color values | `"#FF5733"`, `"rgba(0,0,0,0.5)"` | Theme constants or StyleSheet |
| Query keys | `useQuery(["users", id])` | Query key factory |
| Error messages | Hardcoded user-facing strings | i18n keys or string constants |
| Platform checks | `Platform.OS === "ios"` repeated | Platform utility or constant |
| Dimension values | Hardcoded `width: 375`, `padding: 16` | Theme spacing / responsive values |
| Analytics IDs | `track("button_clicked")` | Analytics event constants |

Ignore string literals that are:
- Object property keys in type-safe contexts
- Template literal interpolations with typed variables
- Test assertions
- Console.log messages (flag separately if in production code)

---

## Step 4 — Data Bleed

Check for data leaking across boundaries where it shouldn't.

### State bleed

- **Global state holding feature-local data.** If a Redux slice, Zustand
  store, or Context provider holds state that only one screen or feature
  uses, that state should be local (useState, useReducer, or a
  feature-scoped store).
- **Context providers that are too broad.** A Context wrapping the entire
  app tree when it only serves one feature causes unnecessary re-renders
  for every consumer. Check provider placement.
- **State persisting across screens.** Navigation params, route state, or
  global stores that hold stale data after navigating away. Check for
  cleanup in useEffect return functions or useFocusEffect.

### Props bleed

- **Prop drilling through 3+ levels.** Data passed through intermediate
  components that don't use it. Should be Context, a store, or component
  composition.
- **Sensitive data in navigation params.** Tokens, passwords, PII passed
  via route params are visible in navigation state and dev tools.

### Cache bleed

- **Shared cache keys.** If two features use the same query key pattern,
  one feature's data could overwrite another's. Check that query keys
  include feature-specific segments.
- **Missing cache invalidation.** Data mutated on one screen but cached
  query on another screen still shows stale data.

### Storage bleed

- **AsyncStorage key collisions.** Check that storage keys are namespaced
  to avoid collisions across features.
- **Sensitive data in AsyncStorage.** Tokens, credentials, or PII should
  use `expo-secure-store`, not AsyncStorage.

---

## Step 5 — API Call Quality

Check every API call (fetch, axios, or query library) in the feature.

### Retries

- Does the call have retry logic for transient failures (network errors,
  5xx responses, timeouts)?
- If using React Query / TanStack Query, is `retry` configured
  appropriately? Default is 3 retries, but check that it's intentional,
  not accidental.
- Are retries idempotent? POST/PUT/DELETE calls should not blindly retry
  unless the API is idempotent.

### Error handling

- Is every API call wrapped in error handling (try/catch, `.catch()`,
  or query library error state)?
- Are error states rendered in the UI (not just logged or swallowed)?
- Are specific error types handled differently where needed (401 →
  redirect to login, 404 → show empty state, 500 → show retry)?

### Loading states

- Does every async operation have a loading indicator?
- Is the loading state correctly scoped (per-button, per-section, not
  blocking the entire screen)?
- Are loading states cleared on both success and error?

### Request lifecycle

- Are in-flight requests cancelled on component unmount? Check for
  AbortController with fetch, or query cancellation with React Query.
- Are there race conditions from rapid re-fetching (user navigates
  away and back, or triggers the same action twice)?

### Timeouts

- Do API calls have timeout configuration?
- Is the timeout appropriate for the operation (short for UI-blocking
  calls, longer for background sync)?

---

## Step 6 — Redundant and Buggy Code

### Redundant code

- **Duplicate fetch logic.** Multiple components making the same API call
  independently. Should be a shared hook or query.
- **Duplicate validation.** Form validation rules repeated across
  components. Should be a shared schema (Yup, Zod, etc.).
- **Duplicate navigation patterns.** Screen transition logic repeated
  instead of being a navigation utility.
- **Duplicate error handling.** The same try/catch pattern copied across
  multiple functions. Should be a wrapper or middleware.
- **Duplicate styles.** StyleSheet objects with identical rules across
  files. Should be shared theme/style constants.

### Buggy patterns

- **Missing useEffect cleanup.** Effects that set up subscriptions,
  timers, or listeners without returning a cleanup function.
- **Stale closures.** useCallback or useEffect with missing dependencies.
  Check dependency arrays against the variables actually used inside.
- **Unsafe optional chaining on deep paths.** `data?.deeply?.nested?.value`
  where an intermediate null would cause a silent undefined instead of
  a visible error. If the data shape is guaranteed by the API, optional
  chaining masks bugs.
- **Unhandled promise rejections.** Async functions called without await
  or .catch(). Common in event handlers and useEffect.
- **State updates after unmount.** Async callbacks that call setState
  after the component has unmounted (missing cancellation).
- **Inline object/array creation in props.** `style={{ flex: 1 }}` or
  `data={[item]}` in render creates new references every render,
  defeating React.memo and causing unnecessary re-renders. Check
  FlatList `data` and `renderItem` props especially.
- **Missing key props.** Lists rendered without stable, unique key props.
  Index-based keys on reorderable or filterable lists.
- **Platform-specific code without Platform check.** iOS-only APIs or
  Android-only behavior used without `Platform.OS` or `Platform.select`.
- **Console.log in production code.** Flag any console.log, console.warn,
  or console.error that isn't behind a `__DEV__` check.

---

## Step 7 — Report

Present findings organized by category and severity.

### Feature Summary

One paragraph: what the feature does, how many files were audited, and
the overall verdict.

### Findings by Category

For each category (Components, Magic Strings, Data Bleed, API Calls,
Redundant/Buggy Code):

| Finding | Severity | File | Detail |
|---------|----------|------|--------|
| ... | Critical/Warning/Suggestion | path:line | ... |

Severity definitions:
- **Critical**: Will cause bugs, crashes, data loss, or security issues
  in production.
- **Warning**: Won't immediately break but creates risk — performance
  problems, maintainability issues, patterns that will cause bugs as
  the feature grows.
- **Suggestion**: Improvements for code quality and consistency that
  aren't blocking.

### Fix Plan

For every Critical and Warning finding:

1. **What to fix**: file, line, and issue
2. **How to fix it**: the concrete change needed
3. **Why**: what breaks or degrades if left unfixed
4. **Effort**: trivial / small / medium

Order by severity, then by dependency (fixes that unblock other fixes
first).

If no issues are found, say so clearly in one sentence.
