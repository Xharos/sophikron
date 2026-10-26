# Subjects, public configuration and course responsibility

Administrators manage subjects at `/dashboard?tab=subjects` and the public name, welcome text and
annual calendar at `/dashboard?tab=configuration`. `ESTABLISHMENT_NAME` is removed: presentation is
stored in PostgreSQL and read without worker-local caches. Changes apply on the next page load,
without a restart. An unavailable API leaves the default name and no configured homepage content.

Dashboard tabs use SvelteKit navigation so saving or revalidating configuration preserves the current
tab. Configuration is available through the administrator sidebar and its direct URL. The overview
groups promotions and subjects in one catalogue panel beside account statistics.
Subject cards, live search, state filters, detail view, archive confirmation and the editor follow the
promotion workspace. Both editors share the same color picker. Teacher subject assignments use
accessible colored multi-select tags. Account creation and profile editing use the same role tags,
with one option per role and no predefined combinations. An invalid draft is rejected on save: at
least one role is required, and student cannot coexist with any other role.

## Subjects and responsibility

A subject has a unique normalized name, an allowed icon, a hexadecimal color and `is_active`.
The subject editor offers visual icon cards and a live name/icon/color preview. The icon catalogue
covers sciences, economics and humanities, including physics, biology, engineering, economics,
philosophy and ancient languages. Course creation uses colored subject cards with icons and labels.
Both selectors use native radio buttons for keyboard navigation and single-choice validation.
All courses reference their subject and read its current identity; changing the subject updates
existing course cards and text colors. Subject deletion is archival. It returns 409 while any course
references the subject. Archiving an unused subject removes every teacher/khôlleur assignment atomically and
advances affected profile revisions. Archived subjects remain searchable but cannot be assigned.

Administrators assign active subjects from a teacher's or khôlleur's profile. Creating a course requires the
current teacher permission and an assigned active subject. A teacher needs that same assignment
to manage a course as its responsible teacher or collaborator. Administrators retain their explicit
management override, but an administrator without teacher permission cannot create courses.

Original `creator_id` is immutable. `responsible_id` identifies the current principal teacher.
Only administrators can change responsibility and the course subject, together in one transaction.
The replacement must be an active teacher assigned to the selected active subject. The former
responsible teacher receives no automatic collaboration grant. When the subject changes, teacher
collaborations lacking the new subject are removed; khôlleur collaborations remain read-only.

## Revoking rights

Before removing a teacher/khôlleur role, removing an assigned subject, or archiving an account,
the UI lists affected retained course responsibilities/collaborations. The API independently
requires `acknowledge_course_impact=true` when courses are affected, rechecked inside the existing
account lifecycle transaction lock. This acknowledgement is a confirmation, never an access grant.

- Removing a subject deletes that assignment and removes collaboration unless a retained khôlleur
  role still grants read-only collaboration.
- Losing teacher removes management; if khôlleur is retained, subject assignments and explicit
  read-only collaborations remain. Losing both staff roles clears all subject assignments. Removing
  khôlleur preserves teaching assignments and eligible teaching collaborations.
- Losing both teaching and khôlleur eligibility removes the collaboration. Adding a role never
  creates a collaboration or restores a removed subject assignment.
- Losing all pupil/teacher/khôlleur roles also removes all promotion memberships, including archived
  promotions, within the same transaction. Each removal is journaled; restoring a role does not
  restore memberships. Administrator alone is not eligible for promotion assignment.
- Archiving an account also removes all assignments/collaborations and revokes sessions/invitations.
- Reactivation and role restoration do not restore deleted associations. Administrators must grant
  assignments/collaborations again. Retained responsibility alone never grants management rights.
- Course content, original authorship and responsible-account references remain intact for recovery.
- Affected course revisions advance; stale writes return 409 and revoked callers are denied first.

## Khôlleur

Student (`user`) is exclusive. Every nonempty subset of `kholleur`, `teacher` and `admin` is valid.
The API and the deferred PostgreSQL role constraint enforce student exclusivity at transaction end.
Permissions are the union of the retained roles and are reevaluated in existing sessions.
The display/audit hierarchy is admin > teacher > kholleur > user. Permissions never inherit from
this order. The new role has only `kholleur.access`.

A khôlleur without additional teacher/administrator grants sees catalogue cards and can open a collaborated course independently of student
promotion access periods. They see all its text/videos, including scheduled/expired content, in
reading mode. They cannot create or edit courses, alter elements or dates, manage collaborators or
promotion access, consult student directories/private profiles, or access administration/statistics.
Their own profile and standard account/password operations remain available. The current responsible
teacher and administrators may add/remove an active khôlleur. Removal denies privileged reading on
the next request, including existing sessions. Ordinary promotion-based reading still follows its
normal dates and content filtering.

Administrators may assign subjects to khôlleurs through the profile editor to organize the teaching
team. These assignments grant no course access. Removing one does not remove explicit read-only
collaboration; removing the khôlleur role or archiving the account still revokes the relevant rights.
Promotion archival may optionally disable pupil accounts only, with independent tracked causes and
selective restoration; see [promotion administration](administration.md).

## Public homepage and calendars

`GET /api/v1/site` anonymously exposes only public name/text/color, timeline metadata, shared events
and today's Europe/Paris date. No user, promotion membership, private profile or course body appears.
Name/text are escaped, never interpreted as raw HTML. The shared text editor supports `*italic*`,
`**bold**`, `==colored==`, `# Section` and `## Subsection`; HTML remains literal text.

Up to 20 timelines and 200 shared events are supported. Timelines have inclusive start/end dates.
An event is stored once and associated with one or more timelines. It must fit inside every selected
bar; shortening a bar past a retained event is rejected. Single-day events use equal start/end dates.
Deleting an event removes all its associations. Deleting a bar retains shared events on other bars,
advances their versions and deletes events exclusive to the removed bar. All calendar edits require
administrator permissions and optimistic revision checks. Progress is calculated from the current
Paris calendar day and refreshed in open browsers every minute, clamped between 0 and 100 percent.
Dates and events remain absolute; there is no automatic annual recurrence.

The calendars appear above the homepage introduction. Each timeline uses one bar split into
proportional calendar months, with colored events overlaid and a red today cursor within its bounds.
Hovering or focusing an event/cursor reveals its description; a single horizontally scrollable
legend is shared by all bars. All holiday periods use the configurable global
`holiday_color` and one “Vacances” legend entry; individual names and dates remain in tooltips.
Other event kinds keep their individual colors and legend entries. The API ignores individual
holiday color overrides and returns the shared effective color, including for older calendar rows.
Changing the global color updates stored holiday colors and affected event revisions atomically.
The per-bar information disclosure shows elapsed percentage, remaining
calendar days and remaining teaching days. Remaining counts include today and both configured
bounds; teaching days are Monday–Friday minus the union of holiday intervals assigned to this bar.
Overlapping holidays count once. Other event kinds do not subtract working days. Counts are zero
after the end and cover the full interval before its start.

## Fresh database and validation

With explicit authorization after deletion of the local database, the baseline is organized into
five feature revisions:

1. `0001_authentication`: accounts, roles/permissions, sessions, invitations, setup, login
   protection and the append-only activity journal.
2. `0002_configuration`: public site settings, shared holiday color, timelines and events.
3. `0003_promotions`: promotion catalogue, account memberships and independent pupil login blocks.
4. `0004_subjects`: subject catalogue and account subject assignments.
5. `0005_lessons`: course pages, content, responsibility, collaborations and promotion access.

The holiday color is included directly in configuration. No standalone journal or holiday-color
revision remains. This baseline targets fresh installations; it does not upgrade the previous
revision chain. Rebuild images and run the existing migration service with `alembic upgrade head`.
No development volume is deleted by the application or test launcher.

Run backend `python -m pytest -q`, `ruff check .`, and `python run_tests.py` for disposable PostgreSQL
coverage. Run frontend `npm test`, `npm run check`, `npm run lint` and `npm run build`.

## Detailed journal entries

New subject-assignment events record added/removed subject IDs, names, icons and colors as historical
snapshots. The UI renders explicit “Matières attribuées” and “Matières retirées” tags. Automatic
removals identify their cause: teacher-role removal, account archival or subject archival. Renaming
or archiving a subject does not change the recorded labels. Large deltas are split into bounded
rows in the same transaction to respect the existing 4096-byte JSONB limit.

Subject saves distinguish creation/update and preserve before/after public identity; archival records
the removed-assignment count. Calendar entries distinguish timelines/events, creation/update/deletion,
names, dates, changed fields and counts of deleted exclusive/retained shared events. Site changes list
changed setting names and, for a rename, the old/new public name; homepage text is never copied into
audit payloads. Saving unchanged site settings creates no extra revision or journal entry.

These payloads use schema version 2. Existing version-1 rows remain untouched and readable with their
original generic message; missing historical facts are never inferred from current assignments.
