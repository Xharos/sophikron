# Private annual timetables

Each calendar belongs to exactly one academic-year label and may be assigned to one promotion.
A promotion can have only one non-archived calendar, even when diffusion is switched off.
Names are unique after whitespace and case normalization, including archived names.
Create a separate calendar for the following year; no implicit copying or annual reuse occurs.
The existing full-screen week grid, group tree, subject colors, teaching-role badges, keyboard
copy/paste, contextual menu, dragging and resizing remain available.

## Weekly PDF export

Administrators see active and archived calendars in the catalogue. Teachers also have an Archives
tab, restricted to their promotion memberships (including archived promotions); archived calendars
are read-only and PDF export remains available. Khôlleur-only accounts cannot list or open archives,
including through direct board/PDF requests. Their promotion and group views expose active promotions
and active pupils only; custom group memberships and promotion counts use the same restriction.
Combined teacher/khôlleur accounts retain teacher archive rights.

The small PDF icon on `/timetable/{id}` opens the displayed week and selected tree audience
in a new tab for saving or printing. The export is one landscape A4 page: weekday names only
(Saturday when enabled), a time axis, marked breaks and self-service lunch, and pale subject-colored
blocks showing the subject, Cours/TD/TP, recipients and teacher names. Overlapping lessons occupy
parallel columns. Text shrinks to fit each block; densely overlapping or very short lessons may
therefore have small text. Exact calendar dates and session time ranges are omitted.
Khôlle sessions and sessions targeting khôlle groups are always excluded.

The only title is the promotion name (including its year), or the calendar name when unassigned;
group and pupil selections append their display label. Group intersections and common lessons follow
the same current membership rules as the screen. Holiday names replace breaks on closed days.

`GET /api/v1/timetable/calendars/{id}/pdf?year_id={year}&day=YYYY-MM-DD&node={key}`
uses the existing timetable board authorization and resolves all labels and sessions server-side.
The SvelteKit relay is `/timetable/{id}/pdf` with the same query. Unpublished and unassigned
calendars remain exportable by authorized administrators; other staff retain the existing board
scope. Invalid or foreign years and recipients are rejected. PDFs are generated in memory using
ReportLab, marked private/no-store/noindex, and never stored. No browser payload can supply events,
colors, names or an arbitrary upstream URL.

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

Dated grids show each holiday as a noninteractive red-tinted background covering the visible
day, labelled with the configured holiday name. Recess and self backgrounds are hidden on those
days. These backgrounds are not sessions and never contribute hours. Undated weekly availability
patterns keep their usual backgrounds without applying dated holidays.

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

Sessions accept `teacher_ids` with up to twenty distinct positive account IDs. Legacy `teacher_id`
inputs and stored documents remain readable; responses retain the first assignment in `teacher_id`.
When both fields are supplied they must agree. No instructor means an empty array. The editor uses
checkboxes, preserving specialist ordering. Roles/activity, availability, archived assignments and
cross-calendar collisions are checked independently for each teacher. Only teachers can receive
courses/TD/TP; kholles also allow kholleurs. Each instructor sees the shared session and receives its
full actual hours. Pupil hours, lunch checks and ICS occurrence IDs count each session once. Single/
future edits, exceptions, copy/paste and previews preserve all assignments. Compact documents are
normalized when read/saved without materialized per-teacher copies or destructive conversion.

Courses, TD, TP and kholles can target the whole class, halves A/B or thirds X/Y/Z. Halves and
thirds can be prepared without a promotion. Numbered kholle groups and named custom groups require a promotion.
Administrators manage custom groups from the promotion's dashboard group panel. Each name is unique
inside its promotion and membership contains at least one current pupil, including archived accounts,
up to the entire roster. Archived pupils retain their memberships when editing, have struck-through
names and can be added or removed like other pupils. A group containing only archived pupils remains
editable. This never restores their login or calendar-subscription access; they remain excluded from
effective timetable audiences and counts. Removing a promotion membership cascades into custom
memberships too. These groups can overlap one another and the standard partitions. Replacing live group
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
For a named subject whose retained blocks target custom groups exclusively, totals instead use the
average participating pupil: the denominator is the union of current pupils in its referenced custom
groups, counting overlapping memberships once. Other custom groups and pupils outside the promotion
are excluded. The rule applies to annual totals and weekly means, without relying on subject names.
A subject mixing custom and other audiences keeps the full-class denominator. Hidden retained blocks
also determine that classification. With a roster, an empty option audience contributes zero hours
and keeps the missing-recipient warning. Lunch and group-balance checks still use their actual audiences.
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
Each teacher and kholleur also has annual minimum and maximum weekly kholle hours, defaulting to
0 and 0. In the availability view, select one person and the academic-year tag to consult them;
only administrators can save changes. Values must be whole hours with `0 <= min <= max`.
The compact toolbar fields are read-only until entering availability editing. Hour bounds are saved
when clicking "Terminer l’édition"; invalid bounds keep editing open. Availability ranges retain
their immediate saving behavior, without discarding the hour bounds being edited.
The existing availability PUT endpoint accepts paired `kholle_min_hours` and `kholle_max_hours`
with `expected_revision`. Omitted `ranges` preserves availability; omitted hour bounds preserve
the stored bounds. Resetting availability does not reset hours. Stale writes return 409 and invalid
bounds return 422. This step stores capacity only; it does not allocate oral-examination sessions.
Overlapping/touching ranges merge. Out-of-grid submissions, including Saturday afternoon, are refused.
The Saturday column remains visible in the staff workspace regardless of promotion settings.

Teacher availability and cross-calendar bookings compare matching academic labels only. Archived
calendars never participate. Administrators can inspect non-archived preparations with diffusion off;
other staff also receive their own preparations in their active promotions when pupil diffusion is
off. Other staff's private preparations remain hidden. External booking metadata contains
teacher IDs, times and calendar references, never another promotion's pupil roster or course details.
The availability workspace retains anonymous full-class occupancy hatching, calculated from real
simultaneous recipients without adding queries per pupil or occurrence.

Teacher unavailability, simultaneous teacher/room bookings and overlapping pupil audiences are
nonblocking diagnostics. Teacher and pupil collisions are critical. The UI previews current external
bookings before saving and allows confirmation despite diagnostics. Ordinary conflict warnings group
recurring pairs and ignore past dates. Warning event links open the actual dated occurrence.

## Live diffusion, confirmations and archives

The "Diffuser aux élèves" switch controls pupil subscriptions and general staff calendar visibility.
With diffusion off, teachers and kholleurs still export their own assigned sessions in their active
promotions and see those sessions in the staff workspace. Pupils receive no link from /me until their
active promotion's current-year calendar is diffused. Enabling diffusion
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

Every permanent active account receives a personal link at its first successful login, including
administrator-only accounts. Existing connected accounts are also provisioned when visiting /me.
The link remains visible and copyable in /me for staff; members cannot rotate or reactivate it themselves.
Pupils without an active promotion and diffused current-year calendar receive no token, even if a verifier
already exists. Their subscription block is hidden and previously known links return an empty feed.
Membership is checked again on every read. Pupil calendar names use active promotion identifiers
(joined if several); staff and administrator calendar names use the configured application name.
Event titles use `<teaching type> - <UPPERCASE SUBJECT>` (Cours, TD, TP or Khôlle), falling back to
the custom session title when no subject is selected. The room stays in LOCATION. DESCRIPTION
contains the promotion and audience label, then each assigned teacher on a separate line. Individual
targets are labelled as individual sessions without disclosing pupil identities. The current model
supports up to twenty distinct teachers per session. Event UIDs and dates are unaffected.
New tokens contain 64 random bytes (86 URL-safe characters, 512 bits). Their SHA-256 verifier is
used for lookup; the recoverable secret uses the existing versioned identity AES-GCM keyring,
bound to the owner ID and the dedicated `calendar_token` field. Never log subscription URLs.

Only administrators can revoke or regenerate links from /dashboard/user or by active role category
from the dashboard configuration tab. Responses expose status/counts, never target credentials.
Category operations affect active accounts with at least one successful login; cumulative staff
roles overlap. Revocation persists across login and /me visits. Regeneration enables a new link
immediately and permanently invalidates the old one, retaining account usage history.
Members must replace the subscription URL in their calendar app after regeneration.

Students receive only their current audiences; teachers and kholleurs receive their own assignments
across currently authorized promotions. All occurrences of the current academic label (September 1
through August 31, Europe/Paris) are exported, including past sessions and calendars whose course
dates no longer include today. UIDs remain stable. Disabled accounts, revoked/unknown tokens and
missing eligible calendars return HTTP 200 with an empty calendar envelope, not a zero-byte body.
Archived calendars never supply events. Paused diffusion hides events from pupils; staff still receive
their assigned sessions. Temporary failures remain HTTP 503.
Client refresh timing is outside Sophikron's control, and revocation cannot erase downloaded copies.

Active links accept `AUTH_CALENDAR_FEED_LIMIT_PER_MINUTE` requests per fixed 60-second window
(default 5, configured in `.env` and passed to the backend by Compose). The next request returns
HTTP 429 with `Retry-After`; SvelteKit preserves that header. PostgreSQL shares the budget across
workers. Unknown and revoked tokens do not create counters. Empty authorized feeds also consume
the budget. No ICS file cache is enabled. See [statistics](statistics.md) for usage counting.

Production clients reach `https://<site>/calendar-feed/<token>.ics`. The existing SvelteKit server
forwards the request to `http://backend:8000/api/v1/timetable/feed/<token>.ics` over Compose's internal
network, without browser cookies. FastAPI does not need a public port. Use the existing nginx feed
location, which suppresses credential-bearing access/error logs, and keep HTTPS enabled.

For local Wi-Fi tests, use the same browser origin on the PC and phone. The local Compose overlay
uses `SOPHIKRON_ORIGIN` for both frontend origin and backend allowed origins, defaulting to
`http://192.168.1.41:3000`. Override it with the PC's actual Wi-Fi address when needed. This explicit
local setting avoids an obsolete `AUTH_ALLOWED_ORIGINS` in .env silently excluding the frontend.
Recreate backend/frontend after changing it; keep the existing public frontend port mapping.
Activate a promotion, assign the pupil and its calendar, add assigned sessions, and enable calendar
diffusion. The subscription then exports the current academic year's sessions. A downloaded ICS
contains `BEGIN:VEVENT` for each exported event; merely detecting a subscription does not prove it
contains sessions. Google servers cannot reach private Wi-Fi addresses. Use the production HTTPS
domain for Google subscription tests and omit the local overlay in production.

Fresh subscriptions use encrypted 86-character tokens. Historical 43-character links, if imported, are replaced on the next owner visit because their plaintext cannot be recovered. See the database guide for baseline compatibility.

## Migration and verification

Apply the current history with the migration role before starting the application. Migration
revisions, compatibility requirements and transition procedures are centralized in
[database migrations](database.md#migrations).

The default enabled policy archives and stops all active calendars with an older academic label at
September rollover. A background check runs every minute and timetable reads/feeds also catch up,
including after downtime. A transactional year watermark serializes workers and lets manually restored
calendars remain restored until the next rollover. Enabling the policy also catches up immediately.
Only administrators can change it.

See [release verification](../CONTRIBUTING.md#verification-before-a-release) for the backend, frontend,
PostgreSQL and browser commands. Unit tests cover holiday cycles, exceptions, exact durations, lunch, annual makeups and
audience weighting. PostgreSQL tests cover actual API rights, live feeds, archive restoration,
uniqueness, stale writes, immutable settings, matching-year availability and bounded feed queries.

## Local demo data

Use `script/seed_demo_data.py` from the repository root with the configured Python environment:

```sh
python script/seed_demo_data.py --dry-run
python script/seed_demo_data.py --email admin@example.org
```

The dry run validates and displays the scenario without login or API writes. A real run requires
the local API, current migrations and a permanent administrator. `--email` overrides
`SOPHIKRON_SEED_EMAIL`; an omitted email is prompted. `SOPHIKRON_SEED_PASSWORD` supplies the password
for the current process, otherwise `getpass` prompts without displaying it. Credentials are never
stored in the script. The administrator session is revoked on exit, including after seeding errors.

`CONFIG` in the entry point is the scenario to review before execution. It overrides the reusable
`Settings` defaults: in particular it enables one weekly German-option hour, uses physics 4 h course
+ 2 h TD + 2 h TP, English 2 h course and computer science 1 h course + 1 h TP. Those overrides take
precedence over the historical scenario description in `script/README.md`. PTSI and PT each contain
45 pupils by default; only the PTSI calendar is filled, and diffusion starts disabled. Zone C holiday
exclusions and the optional summer cutoff are explicit configuration; no other holidays are inferred.

`--classes`, `--students` and `--namespace` override a copy of `CONFIG`. Change the namespace when
testing an incompatible roster or timetable. Compatible retries reuse the scenario; they never reset
the database, send invitations or overwrite foreign data. Previously completed API operations remain
after an error. The script uses the local HTTP API and its authorization rules, without direct SQL.

The `script/demo_data/` modules separate transport (`client`), configuration, identities, catalogue,
groups, pure weekly allocation (`planning`), calendar writes (`timetables`) and orchestration (`runner`).
For validation commands, see [release verification](../CONTRIBUTING.md#verification-before-a-release).
