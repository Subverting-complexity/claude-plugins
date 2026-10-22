# Judging the acceptance criteria

A story's acceptance criteria say what its writer thought "done" means. They are not proof that the list is complete. Before you use them as the baseline for a build or a review, judge whether they cover the story. Work can meet every given criterion and still be unfinished.

The criteria are not sufficient when any of these is true:

- **There are none.**
- **A criterion cannot be checked.** It has no outcome a person or a test can observe: "works well", "is improved", "handles errors".
- **Part of the story has no criterion.** The story's context or requirements describe something that no criterion covers.
- **They cover only the success path.** Nothing says what happens on invalid input, when a dependency fails, or when the user has no permission, where the story has those cases.
- **A criterion names a solution, not a result.** It says what to build, but not what a person or a caller sees when it works.
- **They conflict** with each other, with the story text, or with how the code already behaves.

When they are not sufficient:

1. Write the missing or vague criteria yourself, from the story's context and requirements and from how the codebase already behaves. Make each one checkable.
2. Mark each criterion you wrote as derived, and say what it came from.
3. Use the given and the derived criteria together as the baseline.
4. If a criterion would be a guess between several reasonable answers, do not derive it. It is a question for a person, and the caller says how to ask it.

Never call work complete, or a change ready, only because the given criteria are met.
