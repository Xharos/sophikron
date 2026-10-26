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

## Schema and an existing local installation

As explicitly requested during local development, the additive `login_statistics` table is part of
the amended `0005_lessons`, without creating another migration. Fresh installations receive it
through `alembic upgrade head`. For an existing database already at 0005, upgrade does not replay
the amended file. Reuse its narrowly scoped, idempotent helper with the migration service:

```sh
docker compose build migrate
docker compose run --rm migrate python -m app.cli upgrade-statistics
```

Include the existing local Compose overlay when using the local configuration, as for the other
project commands. This operation creates/seeds only the new table, using migration credentials;
it does not downgrade, reset or delete existing accounts, courses, files or events. Rebuild/recreate
backend and frontend services to deploy the matching code. No new environment setting is needed.

Verification covers real PostgreSQL distinct counts and UPSERT concurrency, successful file streams,
interrupted streams, Paris clock changes, role/collaboration revocation, shared chart geometry,
legend toggles, periods and desktop/mobile administrator/teacher/course browser flows.
