# ADR 0012 — Subject question bank and versioned course quizzes

- **Status** Accepted
- **Sources** [Quiz reference](../quiz.md), [migration](../../backend/alembic/versions/0010_quiz_bank.py).
- **Extends** [ADR 0006](0006-teaching-catalogues-and-courses.md) and
  [ADR 0011](0011-curricula-and-competency-graphs.md).

## Decision

Keep a private question bank per subject, with optional links to competencies in
that subject. Enforce live authoring permissions and optimistic versions on edits.
Expose only the current card and grade submissions on the server. Keep immutable
card snapshots for course quiz versions so edits in the bank leave in-progress
passages intact. Persist one first passage per student and block, with counts for
reporting. Subsequent practice uses the same snapshot and stays outside the stored
results. Validate quiz placement in course tables through the existing parent
and coordinate trigger.

Consolidate the four development revisions into `0010_quiz_bank` before
publication. The migration follows `0009_curricula` and creates the complete quiz
schema directly, including the optional statement, version and passage tables,
and the lesson constraint and trigger changes. Keeping separate revisions would
preserve the intermediate development upgrade paths but would also publish those
intermediate schemas.

## Consequences

Fresh installations and installations at the supported `0009_curricula` baseline
can upgrade normally. Databases that already applied any of the four original
development revisions require a schema and data review before transition. The
revision ID `0010_quiz_bank` now identifies a different schema from the original
development revision with that ID. Follow the
[migration compatibility guidance](../database.md#migrations).
