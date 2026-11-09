# ADR 0010: Private kholloscope drafts and dated publication revisions

- **Status:** Accepted
- **Date:** 2026-11-09
- **Sources:** `0008_kholloscope.py`, kholloscope API, services, worker and PostgreSQL tests.
- **Extends:** [ADR 0008](0008-groups-timetables-and-calendar-feeds.md).

## Context and decision

Annual kholles require exact subject commitments, shared staff and rooms, holiday recovery and
group assignment. A calculation must remain private until an administrator explicitly publishes it.
Later staff, room or group changes must preserve acquired history and unaffected sessions.

Keep preparation, anonymous generation, real-group assignment and publication as distinct steps.
Preparation milestones store input fingerprints; changed dependencies invalidate affected steps.
Persist durable jobs and captured source snapshots in `kholloscope_runs`, with checked statuses
and a partial unique index allowing one active job per academic year. A composite year/creation
index supports latest-job and revision reads without retaining a redundant year-only index.
The worker claims jobs using PostgreSQL locking and solves outside database transactions. Logs,
candidate counts and search time are bounded. Cancellation and stale heartbeats never imply
infeasibility or authorize an incomplete publication.

The placement solver uses anonymous group counts. Actual group assignment validates active pupil
memberships and cross-promotion conflicts separately. Both assignment and publication independently
check the saved proposal. Real event rows remain in the established timetable tables, preserving
course content, subscription identity and diffusion settings.

Published revisions branch into private jobs, with explicit future effective dates and optional
temporary return dates. Source and draft revisions reject stale writes. Publication runs under the
existing lifecycle lock and calendar row locks in one transaction. Persist before/after documents
and dated metadata to support current-date projection and guarded rollback of unchanged future
publications. Retaining this information is necessary even after a solver job completes.

Require `kholloscope.read` at the HTTP boundary and both read/write capabilities for mutations.
Services recheck current database rights, the permanent administrator role and timetable management
scope. Only administrators receive the initial grants; no new role or teacher access is implied.
Named PDF rosters additionally require `users.read`. All browser writes retain the existing CSRF
policy, and drafts/snapshots are excluded from public feeds and search indexing.

Consolidate the unreleased feature revisions 0008–0014 into `0008_kholloscope` with the project
owner's explicit authorization. Leave revisions 0001–0007 unchanged. Remove legacy availability
min/max hour columns: exact staff/subject commitments and their recorded reference cycles replace
them. A downgrade restores zero bounds, not discarded values, and removes private drafts while
preserving published timetable series.

## Consequences and alternatives

Durable jobs survive API restarts while interrupted native searches fail explicitly. This adds
worker coordination and snapshot storage but avoids request timeouts and partially published
results. Running the solver in an HTTP transaction would hold connections and locks for minutes.
Writing drafts directly into live series would expose unreviewed proposals through existing feeds.

Compact validated JSONB supports solver snapshots and dated rollback without a second relational
event model. SQL constraints protect relational identities, commitment bounds, room capacity and
active-job uniqueness; services validate the JSON content and scheduling rules. No speculative
JSONB indexes are added. Future query or retention requirements may justify a separate decision.

The consolidated migration is suitable for a fresh database or one still at 0007. A database
stamped with replaced revisions needs a reviewed transition even if its application rows are empty.
Published migrations become immutable after this release.

See [kholloscope behavior](../kholloscope-generation.md), [schema inventory](../database.md#migrations)
and [release security review](../security-review.md). Tests cover real CP-SAT behavior, authorization,
source invalidation, PostgreSQL constraints, upgrade/downgrade and transactional publication/rollback.
