# Kholloscope generation and group assignment

## Architecture and access

`app/api/v1/kholloscope.py` owns the HTTP endpoints under the existing `/api/v1/timetable`
prefix. It requires `kholloscope.read` for every operation and `kholloscope.write` for mutations.
The configuration preview uses POST but remains a read operation. Services independently recheck
the active account, permanent administrator role and current database permissions; the existing
timetable administration gate also remains in force. A read grant alone does not open drafts to
teachers or kholleurs. Named pupil PDF exports additionally require `users.read`.

Preparation, workflow, generation and revision services own transactions and authorization.
The timetable repository owns event persistence; pure solver/assignment/version modules implement
scheduling and validation. The durable worker runs CP-SAT outside request transactions.
The SvelteKit command relay selects fixed backend paths, forwards the current session and supplies
the validated origin/CSRF header. It does not replace backend authorization.

The schema is consolidated in `0008_kholloscope`, following `0007_timetable`. Annual commitments,
workflow and jobs have separate stores. Job JSONB retains the source snapshot, options, bounded
logs, result and revision rollback/version metadata; published events use the existing timetable
tables. See the [migration inventory](database.md#migrations) and
[ADR 0010](decisions/0010-kholloscope-drafts-and-revisions.md) for integrity and compatibility.

## Workflow

The administrator preparation adds `tab=generation` after the three existing validated steps,
then a separate `tab=groups`. Neither a calculation nor an assignment writes live sessions.
An explicit confirmation in the groups page applies the proposal atomically to its agendas.
Existing courses are never deleted and agenda diffusion is never enabled automatically.
The proposal calendar and `/timetable` share the same display ordering. Events retain chronological
start order; simultaneous blocks sort by subject/title, first assigned teacher, room, calendar and
audience, with stable identifiers as final tie-breakers. Input database order does not determine
their columns, so equivalent blocks keep the same relative order from week to week.

## Rules and units

One configured pedagogical hour is one full kholle session, using each calendar's actual
`session_minutes` for wall-clock occupancy. No half-kholle is generated. For a fractional annual
target with `rounding=none`, the reference A/B cycle is repeated only on the available eligible
weeks. Whole annual targets remain exact. On a 25-week PT period,
a subject in A receives 13 sessions and a subject in B receives 12, without adding a synthetic B
occurrence to the last week. This is normal cycle coverage, not an annual rounding error.
Explicit `floor` or `ceil` instead imposes the same whole-session target on every track.
Volume forms and summaries, service needs, generation, assignment choices and revision warnings
use the same effective group rule: at least one nonarchived pupil must still belong to the
promotion. Empty groups and groups containing only archived pupils are excluded. Mixed groups
count once. Existing group numbers and dashboard memberships are retained; no renumbering or
automatic pupil reassignment occurs.
The original requirements and wishes are not overwritten. The result distinguishes cycle coverage
from rounded targets. The service reference adapts to each subject's exact rational weekly rate.
A common reference
combines these periods for placement. Five sessions over 30 weeks use a six-week service cycle.
Three sessions over 25 weeks use a 25-week reference and spacings of eight/nine weeks.
Sparse subjects use waves near each deadline (up to three phase weeks), rather than spreading
successive groups linearly over the entire interval. Full vacations pause teaching-week cycles.

The model chooses one consistent phase offset per group/subject for all reference occurrences.
An independent validator checks original logical week gaps after expansion, correction and
assignment: exact integer intervals, or adjacent floor/ceil intervals for a rational rate.
Annual rounding cannot justify duplicating a final-week session that breaks cadence. Explicit
recoveries retain their original logical week. The common cycle is capped at 60 weeks, alongside
existing task/candidate limits. Exceeding a limit is a technical failure, not infeasibility.

Each subject exposes `cycle_weeks` in Wishes and Service. Stored legacy commitments keep their
two-week meaning. `KholloscopeWorkflow.data.wish_cycles` records units on explicit wishes saves,
without a schema migration. Reads convert commitments proportionally and visibly; noninteger
conversions require a new entry. Hidden subjects retain their former unit. Per-person summaries
use normalized weekly means instead of adding incompatible cycle units. Two-week commitments
keep their displayed A/B staff split in every pair of a longer common reference.

For PTSI, four subjects at 15 hours over 30 eligible weeks mean one session of each subject
per anonymous track per fortnight, and two subjects each week. Exact per-person/subject wishes
are enforced on the reference cycle. Preparation computes a deterministic balanced A/B split,
preserving each person's exact fortnight commitment and limiting both subject and overall weekly
differences to at most one session. Stable numeric subject/staff identifiers break ties, independently
of display order, names, rooms or optimization. The Service table exposes that split and the solver
enforces it exactly; there is no inversion option. For example, English commitments 10/5/5 become
5/5, 2/3 and 3/2, avoiding the former 39/41 overall load when groups require 40/40.
A preflight check still rejects contradictory total service before building the placement model.
Annual occurrence counts are checked per anonymous track and subject. Annual expansion retains each
reference session's teacher; recovery therefore moves service rather than reassigning it.
At an odd end-of-period, unrounded expansion keeps only the final A phase; explicit rounding
instead determines the retained final occurrences;
the final partial cycle cannot necessarily reproduce a complete A/B staff commitment.

The reference uses the first common pair of complete Monday–Friday teaching weeks. Full vacation
weeks pause teaching-week cycles, following the existing engine. Only eligible configured
kholle weeks determine annual cadence. The dated expansion accounts for all configured holidays
and actual timetable occurrences, including detached exceptions and courses outside the generated
promotions which occupy the same staff or rooms.

Rules before launch include a 5–43200 second API search budget (default 900), zero/one adjacent week for
recovery, one to four kholles per track per day, explicit rounding, and lock preservation.
The browser accepts 1–720 whole minutes, defaulting to 15 minutes, and converts them to seconds.
The generation form always submits `optimize=true` and `preserve_locks=true`; these two switches
are hidden. Its initial time distribution is 5/20/70/5. Recorded percentage choices are retained.
Group assignment defaults to cycle rotation for new drafts and retains an existing saved mode;
unchanged saved assignments cannot be resubmitted. With
optimization disabled, reference search accepts the first complete feasible placement. With it
enabled, three successive objectives retain the best achieved quality of earlier stages:

1. Minimize unmatched teacher/weekday/start/end/room A/B slots. Exact correspondences take
   precedence over all time-only correspondences; unequal service remains mandatory and can
   force unmatched sessions.
2. Minimize squared daily promotion loads separately in each reference week.
3. Give equal weight to early hours and compact per-subject time footprints: each session's
   relative earliest-to-latest allowed start is scored 0–1000, and each distinct subject/phase/
   weekday/start/end footprint costs 1000. Sharing a subject time makes teacher/room exchanges
   easier. Different subjects may run simultaneously for different anonymous groups; their overlap
   is no longer penalized indiscriminately. Preferred promotions break ties at this last level.

Before launch, administrators can set four integer percentages totaling 100%, each at least 1%:
`time_stability_percent` (default 5), `time_weekly_percent` (15),
`time_rotation_percent` (75), and `time_annual_percent` (5). Saved jobs without these fields
use the same defaults. These options are stored with the existing job rules; no migration is needed.
Each reference stage receives the actual remaining global time multiplied by its initial weight
divided by the sum of the weights of all remaining stages, including annual adaptation.
Thus early completion benefits every later stage proportionally. With 900 seconds and a first
stage lasting 27 seconds, the weekly stage receives approximately 873 * 15 / 95 = 138 seconds.
Without optimization, the first three shares are combined into one reference feasibility search.
An initial timeout without a feasible solution ends the calculation instead of consuming time
reserved for later stages; increase that stage's percentage or the global limit when needed.
Achieved values are retained even without optimality proof; a later timeout keeps the last complete
solution. Logs report each criterion's value, bound, native search duration and proof status.
The time-footprint criterion is a rotation heuristic, not proof of a perfect annual diagonal.
Optimized proposals additionally validate an anonymous cycle rotation after annual deployment;
if needed, the existing bounded assignment solver repairs it within the global deadline. Logs
report deviations from the ideal sequence. This witness does not bind real groups or inspect pupils;
actual assignment still checks membership conflicts. A failed witness is not published as success.
Annual recovery penalizes moved sessions, distance from the original date and room changes.
No preference changes staff service, group quotas or hard constraints. A feasible result is not
described as optimal; timeout is never proof of infeasibility. The API keeps its legacy default
when `optimize` is omitted.
By default staff retain 55 continuous minutes between 12:00 and 14:00. Administrators may
disable this **staff-only** constraint or change its duration (20–120 minutes). Student lunch
always remains mandatory: one continuous configured session in the promotion's self window.
The search budget is shared between the cycle and annual native searches; snapshot loading,
model construction, validation and persistence add overhead beyond the native search deadline.
Annual repair receives the remaining global time. Logs show the configured distribution,
each actual stage budget, a proven stage optimum, and an already validated annual expansion
that needs no native annual search. Unused annual time is not spent restarting earlier objectives.
Annual repair only opens weeks touched by actual moves, overlaps, capacity or meal violations.
A valid noon kholle alone does not make its week mobile. Reaching the candidate safety cap is a
technical failure without an infeasibility conclusion.

## Preparation confirmations and navigation

Each preparation confirmation is checked against its current content fingerprint and all preceding
confirmations. Changing volumes, wishes, rooms or preferences invalidates the earliest affected step
and locks its descendants. Orange marks the edited/current step and previously confirmed steps
requiring review; never-confirmed descendants retain their red, locked state, including during local
unsaved edits. Stale confirmation tokens remain stored to distinguish review from untouched steps.
Navigation opens only the first unconfirmed step;
generation must complete successfully on current sources and be explicitly saved before groups
become accessible. A completed calculation alone leaves generation pending (orange) and groups
locked (red), including after reload. `POST generation/save` checks administrator write rights,
current source and draft revisions, and persists `result.saved=true` in the existing result JSON.
No migration is needed. New calculations and manual session corrections require another save.
Each global preparation button now reads "Enregistrer et continuer": it confirms the current
step, reloads the authorized state, then opens Wishes, Service or Generation respectively.
Failed saves do not navigate. Per-calendar volume edits still save their values locally before
the global milestone can be confirmed. Wishes use the single global "Enregistrer et continuer"
action: save the current editor, refresh the workflow revision, confirm Wishes, then open Service.
There are no separate Save/Cancel buttons in that editor. Invalid inputs block submission;
save failures retain the entered values and do not confirm the step or navigate.
The last Groups step retains explicit assignment and publication actions.
Already assigned or published legacy drafts remain accessible.
Failed/cancelled/timeout runs never count as a saved calendar, even after Service is saved again.
Sidebar colors and server-rendered route access share one state calculation, including local dirty
edits. Successful preparation saves invalidate the displayed generation synchronously, before reload.
An already applied/withdrawn proposal retains a separate management exception so withdrawal remains
reachable after live edits; this does not permit stale assignment or republication.

## Anonymous feasibility and conservative occupancy

Generation reads group counts and target size, not pupil rosters or real group memberships.
Anonymous tracks witness annual volume, weekly A/B balance, nonoverlap and student lunch
feasibility. They are not real group assignments and are hidden in the generation API.
Reference combinations assign subject, staff, room and time. The annual search favors those
same combinations, permits bounded recovery around each original week, and never moves a
session outside its configured kholle period. It optimizes regularity, room stability and the
existing preference for assigned promotions; that last preference is never an authorization rule.

Every existing event in a promotion blocks **that entire promotion** for candidate generation,
including half-class, option and individual courses. This deliberately conservative rule avoids
consulting real memberships during solving. It can reject a feasible subgroup arrangement;
an infeasible result concerns this model, not every theoretically possible timetable.
Explicit empty staff availability means unavailable; absent availability uses the existing yearly
default. Availability never overrides an actual course. Room capacity permits simultaneous kholles,
but an existing course occupies the room exclusively. Integer seconds preserve 55-minute slots
and half-slot start positions without floating point time comparisons.

CP-SAT enforces simultaneous generated teacher/track nonoverlap and room cumulative capacity.
A second validator checks annual counts, resource conflicts, recovery bounds and meals before
marking a proposal complete, and after manual corrections. Complete feasible and optimal
solutions are accepted. Infeasible, timeout, cancelled and internal-failure outcomes remain distinct;
timeout is never described as a proof of impossibility. No partial proposal can be published.
Safety limits cap the reference at 2,000 sessions, the annual proposal at 20,000 and each model
at 250,000 candidate combinations; narrow rooms or availability when these limits are reached.

## Durable jobs and live logs

Migration `0013_kholloscope_runs` creates a private PostgreSQL queue with one active job per
academic year, immutable source snapshots, revisioned drafts and bounded progress logs. It does
not alter any existing calendar, membership, wish or persistent volume. Downgrade removes jobs
and their drafts; already applied timetable series remain in their original tables.

The existing FastAPI lifecycle polls this queue. PostgreSQL serializes worker claims and limits
execution to one running job across API processes. CP-SAT runs in a background thread with two
native search workers, outside request transactions. No Redis, external scheduling service or
additional Compose file is required. OR-Tools 9.15.x (Apache-2.0) is installed through the existing
backend `pyproject.toml` and image build, with its transitive packages.

The worker saves progress and observes cancellation every second. Native search logging is
rate-limited and logs are capped at 500 entries per run; logs contain no credentials or pupil
identities. The web page polls a same-origin administrator relay once per second during an active
job. Every physical line of a new run is timestamped on the server as `[mm:ss:SSS]`, elapsed since
queue submission (including waiting time), before buffering. Multiline native output, errors,
cancellation and interruption messages use the same format, surviving reloads. Historical logs
without timestamps are left unchanged. The terminal scrolls to the bottom after changed log text
has rendered, including when the 500-line buffer rolls over. The page displays the latest log
and can reconnect after navigation or reload. Logs are not streamed
over a long-lived HTTP connection. Closed pages do not cancel jobs. A cancelled run is preserved;
an abandoned running heartbeat becomes failed after two minutes and can be relaunched.
Cancellation stops the entire generation: a stopped native search cannot retry or advance to
another optimization stage. Model construction and annual expansion also observe the stop signal.
The worker joins the stopped calculation before claiming the next queued proposal; cancellation
can therefore leave a brief queue wait until the next heartbeat, rather than another solver budget.
Queued jobs survive API restarts. Native calculations interrupted by restart are not resumed.

## Corrections, locks and actual groups

Generation reuses the timetable calendar grid for kholles only, across participating promotions,
with combined promotion, staff, subject, room and assigned-group filters and dated week navigation.
Only the annual calendar is displayed. Holiday recoveries and other moves appear only in the
generation tab, together with the generation summary. The groups tab omits both. The final
"Enregistrer et continuer" button opens the groups tab once a current calculation has completed;
the proposal is already stored by the durable worker, and this action explicitly confirms the
generation milestone without publishing or relaunching it.
Click a dated draft session to change its date, start time
and authorized room. The teacher, subject and
duration remain fixed to preserve exact service. An invalid edit stays in the editor with its
server diagnostic. A successful edit invalidates the saved group mapping. Locked corrections are
retained during a new generation only if source revisions still match; the launch rule makes
this behavior explicit. Old runs are retained in the database; the UI currently exposes the latest
run, without a version browser or undo stack.

Only the groups tab reads actual group numbers and memberships. The administrator chooses fixed
groups, a +1 rotation each eligible kholle week, or a +1 rotation each complete A/B cycle. Numbered
groups are bound automatically in sorted order; memberships are never rewritten. Vacation weeks
do not advance rotation; recoveries retain the rotation of their original week. Rotation is validated
for per-group subject coverage within each complete original fortnight, annual quotas, conflicts
and meals. For cycle-based quotas, a final A-only cycle may redistribute its natural 12/13 totals
with the chosen rotation. Coverage remains tied to the original session occurrences while actual
group tracks are used for overlap and meal checks. Rounded and legacy drafts retain their strict
partial-cycle checks.
The annual preview shows resolved groups. Each subject rotates independently between positions
with that subject's same complete original logical week signature; the other subjects' phases
do not restrict this pool. Thus a group with mathematics on weeks 1/3/5 cannot move onto a 2/4/6
position, but can visit all five odd-week mathematics slots even when its other subjects differ.
The +1 step moves a group through a deterministic list interleaving teacher/room pairs,
with chronological slots within each pair, wrapping at the bottom. With equal pair capacities,
all distinct pairs are visited before a pair repeats; unequal service can require repeated pairs.
A singleton remains fixed. Cycle rotation advances once per common reference cycle.
For either rotation mode, a bounded CP-SAT assignment search keeps slots fixed and first maximizes
the minimum per-group/subject proportion of distinct teacher/room pairs, relative to the smaller
of its number of sessions and candidate pairs. It then rewards additional distinct pairs with
diminishing weights, retaining that minimum and favoring a second pair over another group's
fifth. This avoids sacrificing other groups when one unavoidable bottleneck limits the minimum.
Finally it minimizes deviations from that regular +1 sequence, then balances repeated
encounters between pairs without degrading sequence quality. These stages share at most ten
seconds of native search and retain the last complete feasible assignment if a later stage times
out; they do not claim globally optimal diversity. Per-subject original weeks, annual counts,
daily limits and membership conflicts remain mandatory. Fixed mode keeps its original binding.
The groups response and preview report deviations from the diagonal as `rotation_adjustments`.
Failure to find any complete assignment is reported explicitly; a timeout does not establish
impossibility. Publication revalidates the exact saved assignment rather than computing another.
The assignment button shows progress until both the saved run and assigned tables have refreshed;
older initial requests cannot replace that result. The private relay allows 45 seconds for this
PUT only, including model construction and validation; other operations retain their 15-second
timeout. Minimal help describes the selected mode, with consistent labels in saved previews.
Expandable colloscopes group actual assigned sessions by promotion and subject. Rows identify
weekday/time, teacher and room; columns are teaching weeks, with actual numbered groups in colored
cells. Empty weeks are retained and moved sessions appear at their actual dates with an asterisk.
Clicking a group opens its session details. The view never invents a diagonal: fixed assignments
stay on their rows, whereas rotations move group numbers across the available rows. Selecting a
new unsaved rotation retains the last saved preview with an explicit notice.
Assignment and publication additionally check pupils shared across promotions and their courses;
they never rewrite promotion group membership. Only this assignment stage consults actual pupil
membership; the placement solver continues to operate exclusively on anonymous tracks.

Source revisions cover preparation, active timetable documents and annual availability. Changed
inputs mark a completed proposal stale and prevent edits, assignment and application. Every
write rechecks permanent administrator rights and uses the existing CSRF-protected relay.
Application checks the latest draft revision, all mappings, current references and explicit live
confirmation, then appends single dated series through the existing repository in one transaction.
Existing ICS and calendar visibility rules remain in force. A draft cannot be applied twice.
Applied proposals cannot be regenerated or republished. Publication freezes direct annual volume,
wish, service and room-selection writes. These endpoints return HTTP 409 directing administrators
to Revision, even for fresh revisions and unchanged payloads. Direct kholle creation/editing in
`/timetable/{id}` is also refused after publication. Annual timetable diagnostics compare group/subject hours
with configured pedagogical targets and flag broken fortnight cadence after manual edits.
For a half-hour nominal remainder caused by one session per fortnight over an odd number of
weeks, floor/ceil totals (12 or 13 on 25 weeks) are normal. Other volume discrepancies and
broken complete cycles still produce warnings.

## Published revisions

The revision tab follows group assignment and stays red/locked until the kholloscope is published
in agendas. Preparation remains read-only after publication. The landing page shows current conflicts,
proposal creation and future accepted publications, without a second published-calendar/service view.
The sidebar is green without conflicts or an open proposal and orange when attention is required.

Diagnostics compare published groups with dashboard groups containing a current nonarchived pupil.
They also cover shared-pupil overlaps, archived teachers with future assignments, incompatible
availability and simultaneous room capacity. Dashboard membership editing remains separate.
A repair selects several subjects together (all by default), with per-subject service and rooms.
The next Monday at 00:00 Europe/Paris is prefilled; another future Monday is allowed. Earlier
sessions are always retained, including for retired groups. Newly active groups acquire only the
remaining cadence of a reference group, never retroactive sessions. Group changes require selecting
all subjects. Added task IDs include the subject to avoid collisions in multi-subject repairs.

The service editor is the same `KholleWishes` component used during preparation. Its save callback
stores proposal-local wishes; it never writes to the published preparation endpoint. Inputs express
cycle wishes. Exact remaining sessions are computed separately and displayed only in results.
Each subject card includes its room selection directly below those wishes. The shared
`KholleRoomSelection` component is also used by Service and rooms, with identical selected-room
styling, simultaneous capacities and unavailable-room behavior. Rooms can be added or removed
independently for each subject; zero-capacity rooms cannot be selected but remain removable if
previously chosen. One calculation saves and solves the service wishes and all selected room sets
together. Editing either invalidates acceptance of the previous result until recalculation.
All selected subjects are solved together, with real pupil membership constraints. Initially the
solver keeps existing slots; explicitly allowed same-week moves open only after proven infeasibility.
History, unrelated subjects, annual entitlements, lunch and room constraints are validated again
before publication. A timeout never authorizes a weaker fallback.

Temporary leave uses a Monday `return_on` strictly after departure. The interval is half-open;
sessions on/after return remain fixed. Service/room metadata are projected at the current Paris date
and revert at return without a cron job. The generation/group previews use the dated assigned
annual sessions, including already-published future changes. Other tabs show currently effective
service and rooms, with future publication dates in the common blue banner. The PDF exports the annual version in force on the current Paris date, excluding revisions whose effective date is still in the future. The original run snapshot
and revision audit are retained.

Comparison rows group equivalent recurring replacements, room changes, moves, additions or removals,
showing before/after staff and rooms, date range and number of affected sessions. The worker journal
is always visible. Publication requires confirmation of the existing date, without another date input.
An expired effective date is prefilled with the next Monday and must be recalculated before accepting.
The server rechecks boundaries and observed revisions in the publication transaction.

The revision interface has no separate room-only replacement block. Room changes follow the same
proposal, calculation, review and publication flow as service changes, from its effective Monday.
The existing room-only API remains compatible with earlier clients; it is not used by this interface.

New publications store before/after annual documents and minimal published metadata in existing JSONB
run data, without a migration. The API never exposes these internal rollback backups. Accepted
publications appear in the pending list only before their effective date. Rollback checks write rights,
the observed publication token, latest-version ordering and exact current document contents before
restoring the previous state atomically. It refuses to overwrite a subsequent calendar change.
Already-effective publications disappear from this pending list but retain their audit. Legacy
publications lacking backups remain visible with cancellation unavailable.

Private administrator endpoints under `/api/v1/timetable/kholloscope/{school_year}`:

- `GET revision`: diagnostics, source token, latest proposal and pending future publications.
- `POST revision`: source token, `subject_ids`, effective Monday and optional return Monday;
  legacy `subject_id` remains accepted.
- `POST revision/calculate`: branch token, complete subject/user wishes, room sets, optional updated
  effective Monday and `allow_moves`; save a private snapshot and queue repair.
- `POST revision/merge`: branch token, existing effective/return dates and `confirmed_live=true`.
- `POST revision/discard`: close/cancel the private proposal without changing live agendas.
- `POST revision/room`: source token, source/target rooms, subject IDs, start date and optional
  `confirmed_live=true`; preview first, then confirm the same room-only change.
- `POST revision/rollback`: published revision ID and observed branch token; future-only cancellation.

All writes use the existing lifecycle lock and backend administrator permissions. Calendar rows are
locked before source validation/publication. Occurrence edits preserve subscription identities and
all prior events. No new dependency, table, background service or change to agenda diffusion is needed.
Tests cover real CP-SAT repairs, added/retired groups, acquired history, recurring summaries, metadata
dates, room selection, explicit confirmation and pending cancellation. Dedicated PostgreSQL tests
cover transactional publication/rollback, refusal after content edits and endpoint authorization.

## Withdrawal

Administrative withdrawal remains available after publication independently of read-only preparation.
It requires both dialogs, typing `SUPPRIMER`, current run/source revisions and write permission.
Only scope `future` is allowed: past and today's kholles are retained; scope `all` returns HTTP 409.
Other event types remain intact. Cancelling either dialog preserves the published agendas.
Ordinary preparation and session edits remain locked after publication.

Migration `0008_kholloscope` grants the two capabilities only to admin. Opening the role gate for
a future head-teacher role requires a separate decision. No such role is created by this release,
and no existing calendar visibility or feed permission is changed.

## API and verification

Under `/api/v1/timetable/kholloscope/{school_year}`:

- `GET generation`: readiness, source revision, latest private job and sanitized result.
- `POST generation`: expected source revision plus generation rules; enqueue a job.
- `POST generation/cancel`: request cancellation using the observed `run_id`.
- `POST generation/save`: expected draft revision; explicitly confirm a completed current proposal.
- `PUT generation/session`: expected draft revision and one validated time/room/lock correction.
- `GET groups`: actual numbered group choices, saved mapping and rotation preview.
- `GET pdf`: private assigned annual colloscope, one landscape A3 page per promotion/subject,
  with teacher, weekday/time, room and groups across dated teaching weeks. Each group gets a
  distinct full-cell background, consistent across subjects; the palette restarts for each
  promotion. Each promotion starts with its group roster, including pupil last/first names and
  matching group colors (up to twelve groups per page, with continuation pages if needed).
  Two promotions with four subjects and ten groups each therefore produce ten pages. Export
  additionally requires `users.read` before loading pupil identities. The server resolves names,
  the requesting account and Europe/Paris timestamp; drafts without a saved assignment are
  rejected. The UI download is on the groups tab and the same-origin PDF relay preserves
  private/no-store headers. Rendering is memory-only and runs outside transactions.
- `PUT groups`: expected draft revision and `mode` (`fixed`, `weekly`, `cycle`); group binding is automatic.
- `POST generation/apply`: expected draft revision and `confirmed_live=true`.
- `POST generation/remove`: expected run/source revisions, `scope` (`future`, `all`) and
  `confirmation="SUPPRIMER"`.

All routes require current administrator authorization. The BFF only relays those fixed paths.
Conflicting source/draft revisions or unmet milestones return 409; invalid edits/mappings return
422; unauthorized actors receive 403. Source snapshots are never returned by the API.

Tests exercise real CP-SAT coverage and alternation, staff commitments, holiday recovery,
availability/course intersection, shared room capacity, meal opt-out, rounding and cancellation.
A PostgreSQL integration test migrates and exercises the real durable queue, assignment,
publication and rights. Browser tests cover live progress, correction, group assignment and
explicit application. Use the existing project pytest and frontend verification commands.

Revision subjects are selected with keyboard-accessible toggle buttons.
