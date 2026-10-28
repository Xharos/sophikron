# Private annual timetables

Each calendar belongs to exactly one academic-year label and may be assigned to one promotion.
A promotion can have only one non-archived calendar, even when diffusion is switched off.
Names are unique after whitespace and case normalization, including archived names.
Create a separate calendar for the following year; no implicit copying or annual reuse occurs.
The existing full-screen week grid, group tree, subject colors, teaching-role badges, keyboard
copy/paste, contextual menu, dragging and resizing remain available.

## Rooms and academic years

The administration page at /timetable/settings contains rooms, academic-year labels and the automatic archive policy.
Create labels such as 2026/2027 by entering their first year. A label has no shared opening rules.
Creating a calendar or saving staff availability permanently marks the label as used, even after
archival or resetting that availability. Only a never-used label can be deleted.
Room creation, renaming and retirement preserve existing session references and use revisions.
Past labels cannot be created: the academic year changes on September 1 in Europe/Paris.
New calendar and teacher availability selectors prefer the current label, then the nearest future
label, independently of catalogue creation order or individual calendars' course dates.

## Calendar creation and settings

An administrator chooses the name, mandatory year label, optional promotion, inclusive start/end
dates, daily opening/closing times, session duration, fixed recess breaks, self opening/closing
times, Saturday opening and inclusive holiday periods. Dates must be between September 1 and
August 31 of the selected academic year. The UI creates calendars with diffusion switched off.

Creation defaults are 08:00–18:55, 55-minute sessions, recess 09:50–10:10 and 15:50–16:10,
and a self window of 12:00–14:00. Standard half-session phases restart at the self boundaries,
so the afternoon starts at exactly 14:00. Noon remains available for courses and kholles.
The creation form reports nominal teaching time outside the union of recess and the self window,
complete sessions and the remainder. Overlapping exclusions count once. The requested defaults
leave 495 nominal minutes: nine complete 55-minute sessions without a remainder.

Opening/closing times, session duration, recess and self times are immutable after creation.
Only calendar dates, holidays and Saturday opening can subsequently change. The settings preview
reports the number of disappearing/appearing event segments before confirmation. Such changes
never delete compact series or their exceptions: hidden sessions reappear if the exclusion is
removed. Alternations and annual totals are recomputed from the effective settings.

## Dated sessions and recurrence

There is no weekly-template editor, version activation, draft snapshot or publication operation.
Create an event once, weekly, every two teaching weeks or every three teaching weeks, optionally
bounded by an end date. Complete holiday weeks suspend recurrence cycles; partial teaching weeks
count once. Local times retain Europe/Paris civil hours across daylight-saving changes.
New and pasted events default to weekly repetition.

Holding the empty grid for 350 ms previews one complete session. Move it to another slot/day and
release to open the creation form at that location; no write occurs until the form is saved.
Escape, pointer cancellation and dropping outside the valid grid cancel creation. The same gesture
works while editing one teacher's availability, respecting Saturday's noon closing. Ordinary clicks,
existing-event dragging/resizing and keyboard copy/paste keep their existing behavior.

The event editor's Free times switch permits exact start times and arbitrary durations (to the
second), within the calendar's opening hours. These uninterrupted events do not skip recess or snap
to the half-session grid. Their exact boundaries survive recurring/future edits, isolated exceptions,
copy/paste, dragging/resizing, conflict/lunch checks, hour totals and personal ICS exports. They use
optional boundaries in the existing compact series JSON; no extra tables or database migration are
needed. Standard events continue to use half-session slots and exclude recess and incomplete tails.

Courses, TD, TP and kholles can target the whole class, halves A/B or thirds X/Y/Z. Halves and
thirds can be prepared without a promotion. Numbered kholle groups and named custom groups require a promotion.
Administrators manage custom groups from the promotion's dashboard group panel. Each name is unique
inside its promotion and membership contains at least one current non-archived pupil, up to the entire
roster. These groups can overlap one another and the standard partitions. Replacing live group
membership requires explicit backend-checked confirmation and refreshes calendar revisions/ICS dates.
Their sessions participate in recipient filtering, collisions, meal checks and actual hour totals,
but never in half/third group balance checks. A group from another promotion cannot be assigned.

The custom category sits alongside halves, thirds and kholle groups and uses their shared bubble/list
map. The permanent full-class bubble contains the entire roster. Creating a named empty draft opens
the map; at least one current pupil must be added before saving. Dragging or keyboard selection adds
a pupil without removing their other custom memberships; returning a pupil to the full-class source
removes them from the group being edited. Group positions are saved with the group's revision.
Deletion retires the choice after confirmation, including a live-calendar acknowledgement. Existing
sessions and their saved memberships remain intact; retired groups cannot receive new sessions.
Optional subject/teacher/room references remain supported; a subjectless session requires a title.
Teacher choices retain subject specialists first and exclude kholleur-only accounts from courses.

Saving, deleting, moving or resizing a recurring event opens a confirmation asking whether to
change that occurrence alone or that occurrence and all following ones. A single edit creates an
independent single-event node, preserving its ICS UID, and leaves a cancellation in the original chain.
A future edit splits the remaining chain and preserves earlier history. Detached events remain unchanged,
including if the remaining chain is subsequently changed or cancelled. Cancellation dates follow a
weekday shift, so a detached week never silently reappears in the chain. A single event can itself
be changed into a recurring series by saving its repetition property.
Every proposed event change is previewed by the same backend engine used when saving.
The confirmation uses a labeled switch for including following occurrences, for edits and deletion.
Compact diagnostic cards use red for critical issues, orange for warnings and neutral resolved/information
cards. Confirmation previews show only added, resolved or changed checks, including before/after group
hours. Unchanged checks are available in the separate verification panel. Incomplete-cycle information
is attached to the related subject/type group imbalance instead of shown as a redundant global alert.

## Lunch and annual hours

Self times describe a window in which pupils must be able to eat; they are not a forbidden interval
and do not subtract teaching slots. Noon courses and kholles are permitted. Each pupil in the current
promotion must retain a continuous free interval at least as long as one configured session inside
the self window. Actual half/third/kholle/individual memberships and overlapping sessions are used.
Different groups may eat at different times. Fragmented free half-hours do not replace a full hour.
Insufficient lunch produces a critical warning, including in the event preview. With no promotion,
no pupil lunch conclusion is invented. Past lunch dates are excluded from actionable warnings.

The Hours panel switches between annual totals and weekly means per subject and teaching type.
It uses all actual retained occurrences, including cancellations, replacements and later makeups.
The denominator is every week with at least one teaching day, including partial weeks. With a roster,
totals use the average pupil's actual audience membership; without one, halves/thirds use 1/2 and 1/3.
Recess segments count only their actual teaching duration. A configured session of 55–65 minutes
counts as one pedagogical hour; other durations use minutes / 60. Kholles are shown separately.
Annual subject/type differences between halves or thirds and missing assigned groups produce warnings;
no national curriculum target is assumed or hard-coded.

## Teacher workspace and conflicts

The permanent /timetable/prof workspace keeps subject folders, teacher selection and overlays,
availability editing, dated teaching consultation and weekly teacher-hour totals. Its year selector
uses the explicit academic-year catalogue, independently of promotion calendars.
The Hours panel uses a single table with one row per calendar/promotion and subject, separate
course/TD/TP/kholle columns, subject totals across calendars and an overall weekly total.
Each calendar's own session duration is respected.
Default availability is 08:00–19:00 Monday–Friday and 08:00–12:00 Saturday, without recess or lunch.
An absent pattern means that entire grid is available; an explicit empty pattern means unavailable.
Saving null restores the default. Patterns belong only to their chosen year and are never copied.
Overlapping/touching ranges merge. Out-of-grid submissions, including Saturday afternoon, are refused.
The Saturday column remains visible in the staff workspace regardless of promotion settings.

Teacher availability and cross-calendar bookings compare matching academic labels only. Archived
calendars never participate. Administrators can inspect non-archived preparations with diffusion off;
other staff receive only currently diffused teaching sessions. External booking metadata contains
teacher IDs, times and calendar references, never another promotion's pupil roster or course details.
The availability workspace retains anonymous full-class occupancy hatching, calculated from real
simultaneous recipients without adding queries per pupil or occurrence.

Teacher unavailability, simultaneous teacher/room bookings and overlapping pupil audiences are
nonblocking diagnostics. Teacher and pupil collisions are critical. The UI previews current external
bookings before saving and allows confirmation despite diagnostics. Ordinary conflict warnings group
recurring pairs and ignore past dates. Warning event links open the actual dated occurrence.

## Live diffusion, confirmations and archives

The master switch on /timetable controls web visibility and ICS events. With diffusion off, the
calendar is administrator-only and contributes no events to personal subscriptions. Enabling diffusion
requires a promotion. Every change to an assigned, diffused calendar requires explicit confirmation,
also enforced by the backend. Reassignment separately confirms the recipient change and recomputes
group/lunch diagnostics. Calendar and event revisions prevent stale concurrent writes; changing the
promotion or diffusion also invalidates a previously opened event editor.

Archiving retains all rows, cuts diffusion, excludes the calendar from teacher views/conflicts and
makes settings/events read-only. Only administrators can discover or inspect archives. Restoration
keeps diffusion off. If its promotion already has an active calendar, restore with the promotion
detached; the management dialog offers that option. No calendar deletion endpoint exists.

Only permanent administrators with users.manage can write. Teachers with teaching.read and kholleurs
with kholleur.access may read authorized live promotion calendars and the teaching-only staff view.
Students cannot use timetable web/catalogue/board APIs. Their personal subscription still works.
Existing membership, account activation, CSRF, token redaction and no-index/private-cache rules apply.

## Compact persistence and personal ICS

The database stores one annual configuration per calendar, recurring series and bounded dated
exceptions, not thousands of materialized occurrence rows or per-pupil copies. Annual sources are
loaded in bulk: one year query and one series query, independent of calendar/occurrence counts.
Subject, teacher and room labels are fetched in batches. Personal feeds use current memberships and
group assignments, generate occurrences in memory, filter recipients and decorate once. They never
query the database inside the occurrence loop. Integration tests enforce an SQL-query budget.

Members generate or rotate their opaque personal link at /me. The original token is never stored;
the sole verifier is revocable and former tokens stop working. Students receive only their current
audiences, teachers only their own assignments across authorized promotions. Inactive users and
removed memberships lose access. Feeds include only diffused calendars whose dates include today.
No eligible calendar returns a valid empty ICS; archived calendars never leak historical events.

## Migration and verification

Revision `0013_custom_group_positions` adds bounded bubble positions to custom groups and arranges
existing groups beside the full-class source. It preserves all names, memberships and sessions.
Apply it using the normal migration-role `alembic upgrade head`.

Revision `0012_timetable_audiences` is additive over the annual schema. It preserves existing calendars,
accounts, subscriptions and sessions, adds named audiences and the global automatic archive policy,
and detaches former occurrence replacements while retaining their original ICS identifiers.
Use the normal migration-role `alembic upgrade head`; do not replay `0011` on an existing annual schema.
The default enabled policy archives and stops all active calendars with an older academic label at
September rollover. A background check runs every minute and timetable reads/feeds also catch up,
including after downtime. A transactional year watermark serializes workers and lets manually restored
calendars remain restored until the next rollover. Enabling the policy also catches up immediately.
Only administrators can change it. Downgrading `0012` is refused while custom audiences are referenced
by sessions, avoiding dangling recipient assignments.

Revision 0011_teacher_availability is intentionally rewritten with the owner's authorization.
Applying it removes all timetable calendars, series, former template versions/publications, rooms,
academic labels, availability patterns and subscription verifiers. Accounts, promotions, subjects,
groups and other application data are retained. No database volume is reset.

Fresh installations use the normal Alembic upgrade head. If the former version of 0011 is already
applied, stop the application, use the migration role to stamp 0010_timetable_optional_fields, then
upgrade head to replay the rewritten revision. This replay procedure is only for the former schema;
never stamp a database that already uses the new annual schema. Downgrading restores schema shape,
not discarded timetable data. Existing personal links must be regenerated after this reset.

Run backend pytest and Ruff, frontend tests/check/lint/build, and the browser timetable scenario.
backend/run_tests.py provides the existing isolated PostgreSQL/Docker workflow and migration metadata
checks. Unit tests cover holiday cycles, exceptions, exact durations, lunch, annual makeups and
audience weighting. PostgreSQL tests cover actual API rights, live feeds, archive restoration,
uniqueness, stale writes, immutable settings, matching-year availability and bounded feed queries.
The modular local demo entry point is `script/seed_demo_data.py`. Its configurable scenario creates
accounts, subjects, groups and annual calendars, including the weekly PTSI timetable. A dry run
validates the scenario before login. See [script instructions](../script/README.md).
