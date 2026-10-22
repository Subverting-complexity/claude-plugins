# Matching the codebase's standards and patterns

New code should read as if the team that wrote the code around it wrote it too. This file says where a codebase's standards come from and how to follow them. `templates/coding-method.md` uses it to write code, and `_shared/review-checklist.md` uses it to review code.

## Where the standards come from

Use these sources in this order. An earlier source wins over a later one.

1. **Rules the repository enforces:** the formatter, linter, analyser and type-checker config, such as `.editorconfig`, ESLint, Prettier, Ruff or StyleCop.
2. **Rules the repository states:** `CLAUDE.md`, `CONTRIBUTING`, a coding standards document, or an architecture decision record.
3. **The closest existing example** of the same kind of code, found as the next section says.
4. **The other code in the same folder or layer.**

General good practice comes last. Do not bring in a pattern from another codebase or framework when this codebase already has its own way.

## Find the closest existing example

For each new file, class, function, endpoint, screen, component, test or migration, find the existing one of the same kind that is closest to it: the same kind of thing, in the same layer, and if possible in the same feature area. When `.claude/ecosystem.md` lists Graphify, use it to find the example. Otherwise, search by what the code does, not by its name. Read the example whole.

Follow the example for:

- the file's location and name;
- the structure, and the order of its members;
- the names of types, methods, variables and tests;
- how it gets its dependencies and its configuration;
- how it validates input, handles errors and logs;
- how its tests are laid out, named and set up.

## When the code has more than one pattern

- If the documentation or an architecture decision record names one, follow that one.
- If not, follow the pattern in the most recently changed code of that kind. `git log` on the examples shows which is newer. An older pattern is often one the team is replacing.
- If you still cannot tell, follow the pattern in the same folder, and say which one you chose and why.

Never add a third pattern for the same concern.

## What counts as a pattern

A pattern is used in 2 or more places, or the repository states or enforces it. One occurrence is not a pattern to follow or to enforce.
