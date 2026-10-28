# Private timetables

`/timetable` manages reusable agendas and their promotion assignment. Common room and school-year
configuration lives at `/timetable/settings`. Each `/timetable/<id>` opens a full-screen weekly
workspace with a searchable promotion/group/student tree, annual drafts, dated weekly templates
and personal ICS subscriptions.

## Access and publication

Only permanent administrators with `users.manage` can create agendas, rooms, annual settings,
blocks or publications. Teachers with `teaching.read` and khôlleurs with `kholleur.access`
can consult the current published school year of agendas attached to their current active
promotions. They may preview all students and subjects in these promotions. Teaching staff are
excluded from the promotion tree; their personal subscription combines their own assigned sessions
across their current promotions. A student's preview is restricted to the selected promotion.
Students cannot open the web page or its catalogue/board APIs.

The permanent `prof` entry opens `/timetable/prof`. It is a system workspace rather than a removable
promotion agenda: it has no rename, pause, archive or delete operation. Administrators edit availability;
teachers and khôlleurs have read-only access to staff availability and published teaching assignments,
including teachers outside their own promotions. This teaching-only directory exposes names and subject
assignments, never pupil rosters, recipient IDs, email addresses or account profiles. Its dated view uses
draft assignments for administrators and published assignments for other staff. Existing promotion-page
and personal-subscription access rules remain scoped to current memberships.

### Teacher availability and teaching hours

Choose a school year and a teacher, listed in subject folders (including “Sans matière”). Teachers with
several subjects appear in each folder and retain the same color and shared availability. The workspace
starts in the dated timetable view. It initially selects the authenticated account when present in
the teaching roster, otherwise the first teacher in that roster. Clicking the selected teacher again alternates availability and
dated timetable views; explicit mode buttons provide the same controls. Ctrl-left + click toggles teachers
in the selection; clicking a subject selects its teachers. Multiple selections overlay only those teachers'
sessions and disable availability editing. All changes require an administrator and exactly one teacher.

An absent annual availability record means every opening interval is available, excluding recess, lunch,
Sunday and Saturday unless enabled. “Éditer les disponibilités” enables dragging/resizing both borders,
an accessible time form, adding/removing intervals, closing the entire week and restoring default hours.
Each edit saves immediately and checks the observed revision; stale writes return HTTP 409. An explicit
empty list means unavailable all week; null restores implicit defaults. Intersecting or touching ranges
merge, crossing a pause splits the interval, and closed days/out-of-hours submissions return HTTP 422.
Changed opening rules clip existing patterns at read time without deleting their stored ranges. Patterns
belong to one school year and are not copied automatically into the next year or published snapshots.

The dated view navigates within the selected school year and combines assignments from all non-removed
agendas for the explicitly selected teacher(s). “Heures” reuses the interactive stacked chart and its
accessible table, totals the consulted real week by subject, distinguishes course/TD/TP/khôlle, and sorts
subjects by decreasing total. Teacher hours have no pupil-group weighting. Split segments are counted
once and pauses are excluded. Each 55–65-minute session counts as one pedagogical hour; other session
lengths use actual minutes divided by 60. Multiple teachers' hours are summed, including simultaneous
assignments to different teachers.
Teaching events display the promotion's label, falling back to the agenda name when no promotion is
assigned. Each calendar uses a stable shade of the selected teacher's color; kholles retain their
hatching. In the availability view, block backgrounds are 80% opaque in both consultation and editing,
while their text and inset borders stay opaque.
The availability view optionally requests `include_occupancy=true` on the staff board API. Only then
does the backend calculate `occupied_ranges` (weekday/start/end), using all non-removed, non-paused
calendars in the selected school year, independently of the selected teacher. Inactive promotions
are excluded. Administrators use preparations; other teaching staff use published snapshots only.
For each actual date, the backend unions the real recipients of simultaneous sessions within each
calendar and requires every pupil to be covered. It then intersects full-class intervals across all
participating calendars, and projects their union onto the weekly availability pattern. One affected
week suffices, including alternating cycles and dated exceptions; unrelated weeks are never combined
to invent simultaneous occupancy. A free half-group keeps the slot unhatched. Duplicate sessions and
intersecting group families never count a pupil twice. Without a roster, only explicit whole-class
sessions prove complete coverage. No calendars or an empty participating calendar produces no ranges.
Ranges are clipped to current opening rules and pauses. The API returns no rosters or group recipient
IDs. The renderer uses broad, light 45-degree background hatching, opposite to pause hatching, visible
through availability backgrounds and unchanged while editing. This indication does not prevent saving
availability. Dated teaching views and other pages do not request or render this calculation.

Availability conflicts never block saving a session or publishing. They use actual generated teaching
segments (including replacements), ignore dates before today's Europe/Paris date and group recurring
assignments into one warning with the first affected date. Teacher, room and audience overlap warnings
likewise ignore past dates and group each recurring resource/assignment pair. Unsaved weekly templates
also preview conflicts and availability warnings.
The promotion board also returns `teacher_commitments`: future external bookings limited to teacher
IDs, times and calendar references. It never includes external lesson titles, rooms or pupil recipients.
Admin previews use drafts; staff previews use publications and only teachers appearing on their
authorized board. Non-removed external calendars participate independently of the selected pupil or
group. Recurring teacher collisions are reported once per stable pair in both affected calendars,
with the other calendar's ID/name. Teacher collisions and overlapping pupil audiences are critical
red warnings. Whole-class/course and whole-class/kholle overlaps conflict; disjoint halves, thirds
and kholle groups remain valid. Cross-partition checks use actual membership intersections. Missing
promotion assignment does not suppress whole-class conflicts within the same calendar.
Weekly previews compare projected cycle dates with retained dated lessons and occurrence exceptions,
including independent kholles. Canceled occurrences stay canceled. Touching times and recess gaps do
not conflict. Promotion-wide warnings do not disappear when selecting one pupil/group in the tree.
Before saving a teaching assignment, the UI re-reads external bookings to include changes made in
another open tab. A centered confirmation explains any external teacher clash before creation or
modification. Cancel keeps entered fields and makes no write; confirm allows the inconsistent draft
and keeps its red diagnostic. Template-derived occurrence changes include the clash in their existing
one-occurrence confirmation. Weekly block/drag/resize changes still update only the editing buffer;
version activation checks bookings again and publication remains explicit. Following a dated warning
from a modified weekly buffer preserves that buffer when returning to weekly editing.
“Points à vérifier” retains structured references to the affected sessions. Each session shows its
type and the teaching member in the existing role badge, with the name colored by the session's
subject. Dual-role members use their kholleur badge for kholles and teacher badge for courses/TD/TP;
archived members retain their current teaching-role metadata. Weekly references show weekday and
complete logical hours; dated sessions and exceptions show a full French date and hours. Split
segments and repeated template weeks share one entry. Selecting a session opens its current weekly
block in the weekly editor, or moves the dated view and opens the corresponding occurrence editor.
Independent recurring series and dated overrides stay in dated mode. Read-only staff can consult
details but cannot edit. Structural issues without an affected session have no session action.
Warning navigation does not save or publish a change. Other unsaved weekly edits remain in place
when opening another weekly block from a warning.

Staff APIs are `GET /api/v1/timetable/staff/catalog`,
`GET /api/v1/timetable/staff/board?school_year=2026&teacher_ids=1,2`, and admin-only
`PUT /api/v1/timetable/staff/{school_year}/{teacher_id}/availability` with
`{expected_revision, ranges: [{weekday, start, end}]}` (seconds after midnight, Monday=0).

Administrators can prepare future years and inspect earlier annual records. Other members and
subscriptions receive only publications whose configured start/end dates include today's
Europe/Paris date. There is no fixed June 31 date: defaults are September 1 through June 30.

Draft settings, series and exceptions are separate from the last published annual JSON snapshot.
Saving a draft leaves that publication intact. Pausing an agenda freezes this publication:
subscriptions keep receiving it, while publishing another revision is refused until resumed.
Publish explicitly replaces the snapshot atomically;
conflict warnings do not block publication. Before the first publication the subscription is a
valid empty calendar. Names, subject identities, room labels and access memberships resolve
from current authorized records; private account names are not copied into publication storage.

## Administrator workflow

1. Configure canonical rooms and common school-year settings: rentrée/end dates, opening/closing
   hours, recess/lunch breaks, session length, Saturday opening and inclusive holiday intervals.
   Settings changes validate every affected agenda draft atomically. Existing publications stay
   unchanged until explicitly republished. Room removal retires the entry without breaking history.
2. Create an agenda and assign at most one active promotion to it. Reassignment during summer is
   manual. The management page also renames, pauses and removes agendas. Removal hides an agenda
   from consultation and subscriptions while retaining its database history.
3. Open an agenda to prepare its annual draft with common settings. The calendar uses hour labels
   and alternating subtle hourly backgrounds; placement, movement and lengths use half-sessions.
4. Enter “Éditer la semaine type”. This mode hides the promotion tree and always displays the full
   pattern. Click a weekday to open the right drawer. Choose course/TD/TP, subject, teacher, room
   and recipients using radio buttons styled like the account role selector. Weekly recipients are
   whole class, halves A/B or thirds X/Y/Z, independently of promotion assignment; khôlles are forbidden
   server-side in new weekly saves. Existing legacy khôlles and individual series remain independent
   dated events and are not deleted when replacing the pattern. A block can repeat every worked
   week or use phase A/B or a three-week cycle. The button reads “Quitter” while unchanged and exits
   without writing. After a change it reads “Sauvegarder” and opens a dialog offering immediate
   activation or another date/time. Immediate activation uses the precise server instant (or the
   school year's start when preparing a future year). Scheduled activation uses the device's local
   time; version history displays Paris times. Returning to editing keeps unsaved changes.
   Saved changes remain drafts until explicitly published.
   Saving an unchanged pattern keeps its version, draft revision and existing occurrence identities,
   including when blocks were reordered. An unchanged empty pattern creates no initial version.
   New events leave subject, teacher and room unselected, including after creating another event.
   Clicking one of these choices a second time clears it; the space key also toggles the choice.
   Each reference is independently optional. Without a subject, a custom title containing at least
   one non-whitespace character is mandatory in both the editor and API. Unassigned events use a
   neutral color, omit missing teacher/room labels and never trigger an archived-teacher warning or
   conflicts for absent teacher/room assignments. The hours chart groups them under “Sans matière”.
   New events start at one session (or half a session at the final half-slot). Teachers assigned
   to the selected subject sort first, with French alphabetical ordering within each section;
    changing subjects reorders the choices without replacing the selected teacher. Other subject
    teachers remain selectable with subdued styling, while the chosen option and keyboard focus
    stay prominent. Course/TD/TP choices include only accounts with the teacher role; kholleur-only
    accounts are offered for kholles. Dual-role accounts remain eligible for both. Changing a kholle
    into a course/TD/TP clears an incompatible kholleur-only selection.
   The “Ajouter une séance” button also opens it using the keyboard.
5. In the real-date view, add punctual events or edit/cancel an occurrence. Template-derived sessions
   only permit one-occurrence edits or cancellation; future-scope edits return HTTP 422, including
   deletion. Independent recurring series retain their one/future selector. Changing the recurring
   template itself requires its weekly editor.
   Recipients use a two-step selector: whole class, halves, thirds, or a defined promotion khôlle group,
   then the group number/letter. Individual pupils are not offered as new recipients. Type a start time
   or use adjacent −/+ controls; the typed value snaps to the closest valid half-session, including
   exact seconds and recess boundaries. Length is entered in half-session steps.
   Publish when ready. “Préparation” identifies the draft and “Version diffusée” previews the last
   distributed snapshot; explanatory text states that only publication updates ICS subscriptions.

Both editable grids support right-click copy/paste and Ctrl+C/Ctrl+V (Cmd on macOS) at the pointer.
All pupil and teaching grids share darker 2px inset borders that preserve block geometry and
compact content aligned at the top left: a bold title, session type and audience (whole class,
half/third group or numbered kholle group), an italic teacher when assigned, then hours
and the optional room. Missing fields leave no blank lines, and adding information never changes
the session's duration. The right-hand creation gutter is 0.75rem (twice the library's default),
including beside simultaneous sessions. Pause backgrounds retain their centered labels.
Kholle sessions use sparse, low-contrast diagonal hatching over their existing color in every pupil
and teaching grid, in editable and read-only views. Other session types retain a solid background.
The teaching-only API supplies a display-only `audience_label`, keeping pupil IDs and recipient
fields private. Availability blocks retain their own labels without a fictitious course or group.
The session editor keeps its save button in a non-scrolling toolbar between the header and scrollable
body, without showing scrolling content around the toolbar. Editable grids allow
resizing from both the top and bottom borders, snapping to exact half-session boundaries around
pauses. In weekly mode, resizing updates the local editing buffer like saving an individual block:
it makes no API write, creates no version and does not publish. Other pending edits stay intact.
The explicit “Sauvegarder” workflow still chooses when to activate the complete version; until then,
changes exist only in the current page. Publication remains separate.
In dated mode, every save, deletion or resize of a template-derived occurrence requires a centered
confirmation dialog before any write. It explains that only the selected occurrence changes. Cancel
restores the editor's entered fields, or leaves a resized block unchanged. Failed/stale writes keep
the confirmation open and display the error. Dated resizing of independent sessions still saves
directly without reopening the editor. Dragging a dated event opens the editor; its eventual save
uses the same confirmation for template-derived sessions. None of these dated actions modifies the
weekly template, its other occurrences or the published snapshot.
Copies stay in page memory, preserve their fields and open a prefilled editor before being saved.
Pasting into the real-date grid creates a single occurrence; pasting into the weekly template
preserves its recurrence cycle. Khôlles and legacy individual recipients cannot enter the template.
Pasting beyond the day's capacity asks the administrator to reduce the length. Text-field shortcuts
and read-only views retain their usual behavior. The grid also supports Shift+F10, menu arrow keys
and Escape for keyboard navigation.

The folder tree displays all defined half, third and khôlle groups as selectable resources.
Students appear under every assigned half, third and khôlle group, once within each group.
Unassigned students remain visible separately. Searching a name expands matching folders and
reveals all of that pupil's groups. Selecting a folder overlays its students' actual
sessions; selecting a student shows that person's sessions only. Audience checks are also applied
by the backend and personal export, independently of the tree UI.

Weekly versions are append-only. V1 remains applicable before V2's effective instant, then V2 until
V3, and so on. At a Tuesday 15:00 activation, completed sessions retain V1, while ongoing and future
sessions use V2 in their entirety. V2 wins when an extended/moved transition-day session overlaps
completed V1 work for the same recipients. Completed transition-day occurrences retain their UIDs;
moving the same template block into a later slot on that day creates a separate UID for the new
occurrence, so subscriptions never contain duplicate identifiers. The server clock determines
immediate activation; client-supplied timestamps must include a timezone.
Past activation dates, including dates before an earlier saved version, are allowed only with
explicit acknowledgement of historical replacement. The API independently enforces this requirement.
Applying a retroactive version replaces generated sessions from that instant while retaining the
immutable version records; the distributed snapshot still changes only on publication.
Immediate editing may supersede a previously scheduled future version. Date-specific replacements and cancellations
survive template changes. If a replacement no longer has a corresponding recurring date, it becomes
an independent event with its original UID. Unchanged historical occurrences keep their UIDs.
On the activation day, the new pattern takes precedence over an ongoing exception.

“Heures” opens the existing interactive stacked chart component, with course/TD/TP totals by subject
    and an accessible numeric table. Subjects sort by decreasing total course/TD/TP hours in both
    the graph and table. Counts are weekly averages over the complete recurrence cycle,
from a pupil's perspective: two hours for A plus two hours for B count as two pupil hours. Halves
and thirds carry weights 1/2 and 1/3, independent of unequal pupil headcounts. A 55–65 minute session
counts as one pedagogical hour (inclusive endpoints); its half-session counts as 0.5 h. Outside that
tolerance, effective teaching minutes are divided by 60. Breaks and khôlles do not contribute.
Unequal group workloads produce a warning by subject, combining course/TD/TP and comparing all groups
over the full cycle. The chart retains its separate course/TD/TP breakdown. The graph still shows the
average, with an explicit explanation when loads differ.

Promotion assignment resolves generic A/B/X/Y/Z recipients against current promotion groups without
rewriting the pattern or copying pupil IDs. Missing or empty group definitions trigger warnings.
The management page warns when an agenda lacks a promotion; “Points à vérifier” adds a red critical
entry. These conditions allow draft saves; publication still requires an active promotion.
Class conflict checks distinguish disjoint groups of one partition and use known membership
intersections across partitions. A canonical room may host two simultaneous half-group sessions;
a third half-group or any whole-class overlap still warns. Teacher conflicts remain independent.
Weekly workload and conflict checks recompute from unsaved edits; promotion metadata refreshes
after writes and when returning to the window, without requiring a full page reload.

Archiving a teacher preserves the account's encrypted identity and historical event labels. Their
subscription is denied immediately. Existing published sessions remain visible to authorized
members, and future assigned sessions trigger a warning. Existing teacher references can remain in
a saved/published draft while awaiting replacement; assigning an archived teacher to a new template
block is rejected. Replacing the teacher applies through normal version activation and preserves
earlier assignments. Names resolve from the retained account, rather than an immutable name snapshot.

The session length is effective teaching time. A 55-minute session yields exact 27m30s
half-slots; starts at 08:00 and 08:27:30 are both valid. A four-session block starting at 08:00
with recess at 09:50–10:10 produces 08:00–09:50 and 10:10–12:00 segments. Both segments edit
the same occurrence. Lunch and other pauses are handled identically. A pause inside a
half-session splits its display but does not discard its remaining teaching time. Any final
remainder shorter than a half-session cannot hold another block.

Weeks containing at least one open non-holiday school day are numbered from one. Fully closed
holiday weeks do not advance two/three-week cycles. The UI also shows the ISO week number.
Partial school weeks still count once. Incomplete final cycles trigger a warning without
removing any session; holiday days and exceptions may require further manual balancing.

Click an existing segment to modify/cancel only its occurrence or that occurrence and all
following ones. Future edits split the series without altering its earlier occurrences.
Independent exceptions are retained; incompatible retained exceptions must be resolved before
changing that series or its settings. Deleted occurrences disappear from the draft and,
after publication, the export. Advanced restoration/history UI is outside this increment.

Published annual date ranges of the same agenda must not overlap; this keeps one current
school-year publication unambiguous for consultation and subscriptions.

Preparing a later year copies the latest weekly template onto the new year's teaching dates and
cycle phases. It drops single events, personal student templates and date-specific exceptions.
Older agendas without template versions retain the previous recurring-series copying behavior.
The new year's common settings must be configured first. Duplicate year preparation is rejected.
No background job changes dates, memberships or publications at rentrée.

## Personal subscriptions

Students, teachers and khôlleurs generate a link from `/me`. Each account has one verifier.
Generation/rotation uses an authenticated, origin-protected POST and a random 256-bit secret;
only its full SHA-256 verifier is retained. Rotation atomically replaces the verifier. The URL
is shown only in the successful generation response and current page memory. It is never stored
in localStorage or returned by later profile/status requests.

Students receive whole-class, current group and individually targeted events in their active
promotions. Teaching staff receive
only events where they are the assigned teacher, within their current active promotions.
The backend checks current account status, roles, promotion state and memberships on every fetch.
Removing membership removes those events from future exports; an inactive account's link is denied.
The secret grants read-only calendar access and never authorizes timetable writes.

The public BFF route `/calendar-feed/<secret>.ics` retrieves
`/api/v1/timetable/feed/<secret>.ics` without forwarding browser cookies. It returns RFC 5545
calendar data with stable occurrence/segment UIDs, UTC instants, publication timestamps and
escaped text. It exports titles, types, teachers and rooms, without student rosters or profiles.
The URL must be Internet-accessible over HTTPS for provider servers to retrieve it.

Apple Calendar can subscribe by URL. Google Calendar's documented URL-addition workflow uses
the desktop website, after which the calendar can sync to Android. Importing a downloaded file
is a one-time copy. Refresh timing belongs to the client/provider; publication cannot guarantee
instant phone updates. Test real target applications before depending on urgent changes.

Anyone holding a link can read its exported events, including a provider to which the user adds
it. Rotation prevents subsequent retrieval with the old URL; it cannot erase downloaded copies.
A temporary backend failure returns an error, not an intentionally emptied calendar.

## Deployment, limits and verification

Apply additive migrations through `0011_teacher_availability` with the existing migration service
before starting the new backend. Normal Compose startup runs them. Revision `0007_timetable`
introduced the timetable tables; `0008_timetable_workspace` adds shared settings, room retirement,
pause/removal flags and immutable weekly versions. `0009_timetable_instants` adds an aware activation
timestamp, backfilling existing versions at Paris midnight without rewriting their blocks or publications.
Existing settings and publications are retained.
Revision `0011_teacher_availability` adds the annual teacher-pattern table, with foreign keys to teaching
accounts and configured school years. Existing teachers need no backfill: missing rows use opening hours.
Downgrading it removes these availability patterns only. The permanent workspace needs no seeded calendar.
Revision `0010_timetable_optional_fields` makes the three series reference columns nullable without
rewriting existing events, snapshots or foreign keys. Downgrading it fails transactionally while
unassigned series remain; assign their missing references before attempting a downgrade.
When legacy agendas disagree on common settings, the migration preserves every alternative and the
administrator selects the desired settings explicitly. Backups must include all timetable tables
and publication snapshots. Downgrading revision 0008 drops version metadata; downgrading revision
0007 removes timetable-specific data. Downgrading 0009 removes activation-time precision metadata;
the generated historical sessions and civil version dates remain retained.

Use the updated `infra/nginx.conf` subscription location: it omits credential URLs from access
logs and suppresses error-level request dumps for that location. Uvicorn's existing access filter
also redacts backend feed URLs. Apply equivalent redaction to any additional ingress, CDN or APM.
Subscription responses use `no-store`, no indexing and `no-referrer`. No extra Compose service,
environment file, external API account or paid calendar component is required.

EventCalendar is MIT-licensed and `icalendar` is BSD-2-Clause; retain their notices. Pinning uses
the existing npm lockfile and backend dependency declaration. Keep dependencies updated.

Annual drafts allow at most 5,000 series, templates at most 250 blocks, and each series at most 100
exceptions. Template request bodies have a bounded 256 KiB limit; ordinary commands retain the
existing 16 KiB limit. Limits are enforced server-side. Conflict warnings cover class, teacher and canonical room
overlaps in the displayed selection. They are an initial aid, not a comprehensive timetable
validity check or an automatic scheduling solver.

Personal ICS retrieval loads current memberships and current publication snapshots in bulk, then
resolves subjects/teachers/rooms with three label queries. Its SELECT count is independent of the
number of authorized agendas and generated occurrences. Integration tests compare one versus seven
agendas and enforce at most ten SELECTs. Current account and promotion access are still checked on
every fetch; no persistent cache can retain stale permissions. Teaching-week and slot arithmetic is
reused while expanding each annual document. Changed template series are upserted in batches of 250;
unchanged historical series are not rewritten.

Run the usual backend `python -m pytest -q` and `ruff check .`; `python run_tests.py` runs the
suite against disposable Docker/PostgreSQL services, including migration/publication/feed tests.
Use PyCharm's configured interpreter. Frontend checks are `npm test`, `npm run check`,
`npm run lint` and `npm run build`. After building, `node --test tests/timetable-browser.mjs`
checks agenda/room management, the full-screen grid, template activation and retroactive confirmation,
teacher sorting, copy/paste, live warnings, drag placement, audience filtering, mobile layout,
staff/student access and one-time link UI against a synthetic API.
Real PostgreSQL authorization, shared settings, weekly versions and frozen publications are
covered independently; real Apple/Google subscription refresh has not been automated.
