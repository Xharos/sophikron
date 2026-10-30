# ADR 0006: Teaching catalogues, course trees and scoped access

- **Status:** Accepted
- **Date:** 2026-10-30
- **Sources:** `0003_promotions.py`, `0004_subjects.py`, `0005_lessons.py` and their backend services.

## Context and decision

Promotions, subject assignments and courses have different lifecycles. Store them as separate
relational catalogues and explicit associations rather than embedding lists in accounts or courses.
Promotion year/identifier uniqueness, membership composite keys and foreign keys prevent duplicates
and orphan relationships. Independent account-block causes preserve reversible promotion archival;
the runtime role cannot delete promotions. Subject normalized names are unique, and subject/profile
versions reject stale changes. Archival preserves references instead of deleting teaching history.

Courses reference an immutable creator, current responsible teacher and subject. Collaborators and
promotion access periods are explicit tables. Store structured content as an ordered element tree;
composite constraints and a parent-validation trigger prevent cross-course and invalid parent links.
Policies cover inherited availability and staff-only content; services enforce current role, subject
and promotion scope on every read/write. Database constraints complement authorization, not replace it.
Login/download statistics belong to courses/authentication usage and are created by 0005.

## Consequences and alternatives

Transactions lock course state, check expected versions and record activity with mutations. Losing
roles/subjects or being archived revokes effective rights; retained authorship does not grant access.
The existing catalogue exposes course cards to permanent authenticated users, with full reading for
teachers/admins and explicit kholleur collaborators. Student content is filtered by audience and dates.
Changing that visibility policy requires a separate decision. A single unstructured course JSON blob
would simplify storage but weaken referential integrity and independent access relationships.

See [administration](../administration.md), [courses](../lessons.md) and the API/PostgreSQL tests
for forbidden cross-promotion, stale-version and role-revocation cases.
