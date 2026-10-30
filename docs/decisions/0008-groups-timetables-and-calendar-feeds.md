# ADR 0008: Independent groups, annual timetables and personal calendar feeds

- **Status:** Accepted
- **Date:** 2026-10-30
- **Sources:** `0006_promotion_groups.py`, `0007_timetable.py` and timetable/group services.

## Context and decision

Half, third and kholle partitions are independent views of a promotion. Use composite keys scoped
by promotion/kind, one assignment per pupil per partition, and foreign keys to actual memberships.
Keep graph positions and revision tokens for editing without changing the underlying promotion roster.
Named custom groups extend audiences in 0007 without overloading standard partitions.

Timetables separate calendars, school years, rooms, yearly settings, teacher availability and compact
JSONB recurrence/exception series. Relational references protect teacher/subject/room integrity;
services validate recurrence content, overlaps, audiences and publication permissions. A partial unique
index permits only one non-archived calendar per promotion. Availability ranges may be null; kholle
bounds remain ordered and nonnegative. Revision tokens prevent silent concurrent overwrites.

Personal ICS subscriptions use hashed tokens for lookup and encrypted recoverable tokens for display.
Tokens are credentials: requests recheck account/subscription status; links are revocable and excluded
from proxy logs. Store lifetime usage totals separately from detailed operational API monitoring.

## Consequences and alternatives

Compact series avoid expanding an academic year into thousands of SQL events, at the cost of service
logic for recurrence diagnostics and exceptions. Nullable availability has explicit default semantics,
not an implied unavailable teacher. Downgrading 0007 deletes timetables, subscriptions, custom groups
and usage totals; standard groups and configuration monitoring survive. Downgrading 0006 removes
standard partitions while preserving promotions and memberships. These are destructive maintenance
operations, tested only against disposable PostgreSQL databases.

See [timetable behavior and feeds](../timetable.md), authorization integration tests and the
frontend recurrence/occupancy tests.
