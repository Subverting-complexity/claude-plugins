# React Native and Expo checklist

Extra checks for `references/local-review.md` Step 4 when the change is React Native or Expo code. Findings go into that file's report, in its format. Cover the changed files, new files, and the files that import them one level out.

## Components

### Reusable components

Look for components that should be extracted or shared:

- **Duplicate JSX blocks.** Find near-identical JSX structures across feature files. If two components render the same shape with different data, that's a shared component waiting to be extracted.
- **Inline components.** Components defined inside other components (function declarations or arrow functions inside a render body) cause remounts on every render. Flag every instance.
- **Copy-pasted component logic.** Hooks, handlers, or effects that are duplicated across components. Should be a custom hook or utility.
- **Oversized components.** Components over ~150 lines that mix layout, business logic, and data fetching. Should be split.

### Magic components

- Components referenced by string name rather than import.
- Components rendered conditionally using string matching instead of a component map or registry.
- Dynamic component creation from string identifiers without type safety.


## Magic strings

Find hardcoded string literals that should be constants, enums, or config values. Check every feature file for:

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


## Data bleed

Check for data leaking across boundaries where it shouldn't.

### State bleed

- **Global state holding feature-local data.** If a Redux slice, Zustand store, or Context provider holds state that only one screen or feature uses, that state should be local (useState, useReducer, or a feature-scoped store).
- **Context providers that are too broad.** A Context wrapping the entire app tree when it only serves one feature causes unnecessary re-renders for every consumer. Check provider placement.
- **State persisting across screens.** Navigation params, route state, or global stores that hold stale data after navigating away. Check for cleanup in useEffect return functions or useFocusEffect.

### Props bleed

- **Prop drilling through 3+ levels.** Data passed through intermediate components that don't use it. Should be Context, a store, or component composition.
- **Sensitive data in navigation params.** Tokens, passwords, PII passed via route params are visible in navigation state and dev tools.

### Cache bleed

- **Shared cache keys.** If two features use the same query key pattern, one feature's data could overwrite another's. Check that query keys include feature-specific segments.
- **Missing cache invalidation.** Data mutated on one screen but cached query on another screen still shows stale data.

### Storage bleed

- **AsyncStorage key collisions.** Check that storage keys are namespaced to avoid collisions across features.
- **Sensitive data in AsyncStorage.** Tokens, credentials, or PII should use `expo-secure-store`, not AsyncStorage.


## API calls

Check every API call (fetch, axios, or query library) in the feature.

### Retries

- Does the call have retry logic for transient failures (network errors, 5xx responses, timeouts)?
- If using React Query / TanStack Query, is `retry` configured appropriately? Default is 3 retries, but check that it's intentional, not accidental.
- Are retries idempotent? POST/PUT/DELETE calls should not blindly retry unless the API is idempotent.

### Error handling

- Is every API call wrapped in error handling (try/catch, `.catch()`, or query library error state)?
- Are error states rendered in the UI (not just logged or swallowed)?
- Are specific error types handled differently where needed (401 → redirect to login, 404 → show empty state, 500 → show retry)?

### Loading states

- Does every async operation have a loading indicator?
- Is the loading state correctly scoped (per-button, per-section, not blocking the entire screen)?
- Are loading states cleared on both success and error?

### Request lifecycle

- Are in-flight requests cancelled on component unmount? Check for AbortController with fetch, or query cancellation with React Query.
- Are there race conditions from rapid re-fetching (user navigates away and back, or triggers the same action twice)?

### Timeouts

- Do API calls have timeout configuration?
- Is the timeout appropriate for the operation (short for UI-blocking calls, longer for background sync)?


## Redundant and buggy code

### Redundant code

- **Duplicate fetch logic.** Multiple components making the same API call independently. Should be a shared hook or query.
- **Duplicate validation.** Form validation rules repeated across components. Should be a shared schema (Yup, Zod, etc.).
- **Duplicate navigation patterns.** Screen transition logic repeated instead of being a navigation utility.
- **Duplicate error handling.** The same try/catch pattern copied across multiple functions. Should be a wrapper or middleware.
- **Duplicate styles.** StyleSheet objects with identical rules across files. Should be shared theme/style constants.

### Buggy patterns

- **Missing useEffect cleanup.** Effects that set up subscriptions, timers, or listeners without returning a cleanup function.
- **Stale closures.** useCallback or useEffect with missing dependencies. Check dependency arrays against the variables actually used inside.
- **Unsafe optional chaining on deep paths.** `data?.deeply?.nested?.value` where an intermediate null would cause a silent undefined instead of a visible error. If the data shape is guaranteed by the API, optional chaining masks bugs.
- **Unhandled promise rejections.** Async functions called without await or .catch(). Common in event handlers and useEffect.
- **State updates after unmount.** Async callbacks that call setState after the component has unmounted (missing cancellation).
- **Inline object/array creation in props.** `style={{ flex: 1 }}` or `data={[item]}` in render creates new references every render, defeating React.memo and causing unnecessary re-renders. Check FlatList `data` and `renderItem` props especially.
- **Missing key props.** Lists rendered without stable, unique key props. Index-based keys on reorderable or filterable lists.
- **Platform-specific code without Platform check.** iOS-only APIs or Android-only behavior used without `Platform.OS` or `Platform.select`.
- **Console.log in production code.** Flag any console.log, console.warn, or console.error that isn't behind a `__DEV__` check.
