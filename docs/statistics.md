# Dashboard and course statistics

The administrator overview at `/dashboard` shares its chart components with the teacher's
`/dashboard?tab=statistics` and each course's **Statistiques du cours** panel. Charts use local SVG,
the existing Bulma design tokens and one shared palette, without a chart dependency or external
analytics service. Legends toggle series; line and bar scales use the exact visible maximum
(the largest visible category total for stacked bars), without rounding up. Empty charts use
a nonzero fallback scale. The largest value therefore reaches the top or the end of its track.
Pointer, touch and keyboard users can inspect values. Every chart also exposes a data table.

## Scope and permissions

- `/api/v1/admin/statistics` requires `statistics.read` and returns platform-wide aggregates.
- `/api/v1/teaching/statistics` requires current teacher grants and includes only courses whose
  immutable `creator_id` matches the caller. Administrators retain the global override.
- `/api/v1/lessons/{id}/statistics` requires administrator permission, a current teacher role
  with authorship/responsibility, or a current teacher/khôlleur role with an explicit collaboration.
  Other teachers and students are denied even if existing content-reading rules let them open
  the course. A removed collaboration or role takes effect on the next request.

The SvelteKit `/statistics` bridge constructs only these fixed backend routes. All responses are
private and non-cacheable. Aggregates never contain student names, account IDs, recipient lists,
failed-login identifiers, IP addresses, credentials or document storage paths. Data are scoped
before counting, grouping and ranking, rather than filtered after aggregation in the browser.

## Counting rules

`period=day|week|month` selects today, seven inclusive Paris calendar days or thirty inclusive
Paris calendar days. Today uses hourly bins up to the current partial hour. Longer periods use
daily bins. PostgreSQL and Python use Europe/Paris consistently; UTC hourly bins distinguish the
repeated autumn hour and omit the nonexistent spring hour. Missing historical buckets are zero.

Successful connections come from the existing `auth.login_succeeded` journal. Bootstrap logins
are excluded. Unique connections count distinct successful accounts, never browser sessions.
Period-wide unique counts are calculated independently and are not the sum of bucket uniques.

Credential failures (HTTP 401) and rate-limited login requests (HTTP 429) increment anonymous
hourly PostgreSQL counters atomically. Attempts equal successes + credential failures + rate
limitations. Malformed/CSRF-rejected requests, transport errors, password-service capacity errors
and cancelled requests are not authentication outcomes. Existing authentication throttling and
session rules remain unchanged. `attempts_since` discloses when failure recording began; older
attempt totals are incomplete and cannot be reconstructed from transient rate-limit counters.

A `lesson.file_downloaded` event is recorded only after every expected byte was streamed by the
backend. Refused, short, failed and cancelled streams are not counted. A completed server transfer
does not prove that the browser saved the file. Repeated complete transfers count separately;
distinct downloaders count accounts. Recording failure logs a sanitized warning and does not
replace already-sent file bytes with an application error.

Download events contain only file ID and size, the existing actor references and course ID. They
survive file replacement/deletion and course deletion. Global totals retain deleted-course
downloads; rankings only name current authorized courses/documents. Author views aggregate
currently existing creations. Rankings show five entries; the author link list shows at most 100.
There is no reconstructed download history before this instrumentation was installed.

## Calendar subscriptions

The administrator-wide panel shows consulted accounts / currently eligible accounts. Accounts must
be permanent, active, previously connected, have a nonrevoked link and belong to an active promotion
with a nonarchived current-year calendar. Pupils additionally require diffusion to pupils; staff do
not need diffusion or an assigned session. Each eligible account is counted once across roles and
promotions. The numerator uses the latest authorized retrieval within the selected period, limited
to currently eligible accounts; publication/revocation changes the denominator immediately.
An authorized empty feed counts. Unknown/revoked/inactive or unpublished-pupil requests do not.
Regeneration preserves account usage; a separate durable global counter retains successful ICS
requests across regeneration, revocation and account lifecycle. Prior requests cannot be reconstructed.
No IP addresses or individual request histories are stored. Polling and manual retrieval cannot
prove that someone viewed the calendar. Only global administrators receive these aggregates.

## API performance monitoring

Active ICS subscription links accept `AUTH_CALENDAR_FEED_LIMIT_PER_MINUTE` requests (default 5)
in a fixed 60-second window starting at the first request. Further requests return HTTP 429 with
`Retry-After`, also forwarded by SvelteKit. Existing PostgreSQL rate budgets share the limit across
workers; unknown and revoked tokens do not create budgets. No ICS response cache is introduced.

Monitoring mounts immediately and fetches independently after page rendering. The administrator-only
`GET /api/v1/admin/monitoring` accepts a period, category and optional interval. SvelteKit relays it via
`/statistics?resource=monitoring`. PostgreSQL reduces stored minutes to minute/day-view, hour/week-view
and day/month-view before serialization; raw rows are never sent to the frontend. Charts cover the
current day, seven calendar days or thirty calendar days in Europe/Paris. The autumn clock change
may produce 1,500 daily minutes or 169 weekly hours. Missing intervals use null latencies, not zeroes.
The monitoring card sits after the other statistics, directly above the overview activity journal.
It always combines all operations, without a moving cursor or interval summary. The first chart overlays
request counts (left axis) with mean, approximate P95 and maximum durations (right axis); legend buttons
toggle each duration series. The second chart shows HTTP 2xx/3xx/4xx/5xx counts or percentages.
A table below both charts details request counts, durations and server errors per operation.
The API still supports protected diagnostic queries. Totals use weighted duration sums/counts;
P95 merges fixed histogram counts rather than averaging percentiles.

One `api_metrics` row stores minute/category counts, duration sum/maximum, exact HTTP codes, fourteen
histogram buckets, incomplete transfers and refused ICS counts. Nine fixed categories (eight main
operations plus other) bound storage independently of URL/token/account/request volume. Attacker
paths never become labels. No bodies, query strings, identities, IPs, credential URLs or individual
request records are stored. `/health` probes are excluded. Streaming durations include transfers;
documents are isolated by category. HTTP 200 empty refused ICS responses have their own counter.

Workers buffer observations and atomically merge batches every thirty seconds. Monitoring adds no
SQL to HTTP requests. Each flush purges buckets older than 31 days, including during quiet periods.
Reads select only the requested period. Steady-state storage is bounded around 401,760 minute/category
rows; the cleanup cadence can temporarily retain an extra minute. Buffers hold at most 1,080 pending
minute/category entries per worker during outages. Graceful shutdown attempts a final flush; crashes
or unavailable storage may lose recent observations. The current worker's dropped counter warns of
incomplete history. Test lifespans flush explicitly. This dashboard is not an external uptime alert.

API metrics are created by `0002_configuration`; lifetime ICS totals are created by `0007_timetable`. Downgrading their feature revision removes its measurements. See [database migrations](database.md#migrations) for the fresh release baseline and compatibility requirements.

## Storage and catalogues

Published file counts/bytes and format distributions come from `lesson_files`, scoped to the
current course or the author's creations. Valid upload reservations appear separately and count
against the quota gauge. The administrator sees the configured platform quota; a course sees its
course quota. Author aggregates do not pretend to be a single course or uploader quota.

Only administrators can inspect volume-wide object/temporary byte counts and the deletion queue.
Folder inspection runs outside the SQL transaction in a worker thread. It counts regular files'
apparent byte lengths in the private `objects` and `temporary` folders without following symlinks;
it does not label the entire filesystem's used space as document storage. Concurrent deletion is
tolerated; an inaccessible volume is shown as unavailable rather than zero. Published metadata,
physical objects, temporary files and pending deletion counts can differ during transfers/cleanup.

Account state and role distributions are current snapshots. Roles overlap and therefore use bars,
not a pie. Active promotion bars count pupils separately from distinct teacher/khôlleur accounts;
combined teaching grants are not counted twice. Subject bars show course counts. Catalogue charts
show up to eight entries; management links open the full existing catalogues.

## Installation and verification

Apply the fresh release baseline through the existing migration service before starting the API.
Compatibility and migration commands are centralized in [database migrations](database.md#migrations).
Verification covers PostgreSQL distinct counts and UPSERT concurrency, successful and interrupted file
streams, Paris clock changes, authorization, shared chart geometry, legend toggles and browser flows.