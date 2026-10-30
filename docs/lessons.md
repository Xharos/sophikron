# Course pages

Authenticated permanent accounts see every course card at `/lessons`. Cards expose the title,
description, icon, subject-inherited color, responsible teacher and collaborators, never teaching content.
The catalogue has no search form. Its responsible teacher and collaborators use the shared role
badges grouped into a professor line and a khôlleur line. Teacher takes precedence over administrator
and khôlleur in course badges. Only the current responsible teacher appears, never an additional
historical creator. Only administrators receive links to account profiles. Cards use compact layouts.
The dedicated `/lessons/{id}` page opens in reading mode. Students can open it only through a
current membership in an active, authorized promotion whose inclusive access dates include today.
Teachers and administrators can read all pages; responsibility or collaboration plus an assigned active subject is required for teacher edits.
Anonymous visitors are redirected to login. Pages are private, `no-store` and excluded from indexing.

## Editing and current permissions

Creation requires `teacher.access` and an assigned active subject. `users.manage` permits administrators to edit every course,
including recovering pages whose creator has lost their teaching role. An administrator without
`teacher.access` cannot create courses. Existing permissions remain explicit; no role inheritance is added.

Responsible-teacher and collaborator grants are references to accounts, not permanent editing capabilities.
Every mutation revalidates the session, active status, current permissions and collaboration inside
the transaction. A creator/collaborator losing their teacher role immediately loses teacher editing
rights, including with an existing session. An administrator retains their independent override.
Revoking a teacher role or archiving an account deletes subject assignments and collaborations.
Removing a subject deletes collaborations in that subject. Restoring a role does not restore them. Disabled accounts cannot authenticate. The bootstrap cannot use course APIs.

The eligible responsible teacher and administrators can add/remove collaborators. Collaborators
are active teachers assigned to the subject, or active khôlleurs with read-only full-content access.
The picker immediately offers five eligible accounts in stable ID order, then searches from the
first letter with a short debounce and cancellation of obsolete requests. Existing collaborators,
the historical creator and current responsible teacher are excluded server-side before the limit.
Each suggestion displays the person's name and pedagogical role badge. Adding or removing a
collaborator refreshes the suggestions. Browsing/searching uses the same management authorization.
Khôlleurs cannot edit or manage access. See [subject and role lifecycle](administration.md). Course editors can grant
or revoke any active promotion, independently of their personal promotion assignments. These actions
never change accounts, role assignments or promotion memberships.

Writes reuse the account lifecycle transaction lock so role/status changes cannot race an authorized
mutation. Course row locking and `expected_version` reject stale changes with 409. The editor saves
one coherent element or settings change at a time. Form drafts capture their original revision,
remain in memory on validation/conflict errors and are never stored in browser storage.

## Hierarchy and availability

Only sections can exist at the page root. Subsections must belong to sections. Text, YouTube,
file and table elements belong to a section or subsection. Table cells contain optional text,
YouTube or file elements addressed by row/column coordinates. Ordinary siblings are movable with buttons.
Element IDs remain stable on updates and moves. Removing a section/subsection removes its subtree
after confirmation. The API rejects cross-course element/parent IDs; composite foreign keys and a
PostgreSQL trigger also enforce hierarchy and immutable element parent/type/course fields.
Section blocks start with the author-entered title, without an automatic numbered label.
The outline continues linking to stable `#element-{id}` anchors for sections and subsections.

Only root sections can set `audience=staff`. Their entire subtree inherits that audience;
children cannot override it. Students receive neither private headings nor their resources.
All current teachers and administrators retain full reading access across courses; active collaborating
khôlleurs retain read-only full-content access. Historical authorship alone grants no capability.

Sections, subsections, text and tables are always available to authorized readers. Only files and
YouTube videos in student-visible sections can set a date rule:

- `inherit`: always available (the existing contract value is retained for compatibility).
- `from`: available from `starts_on` inclusively.
- `range`: available from `starts_on` through `ends_on`, both inclusive.

Unavailable resources retain their display title and file type in the student's programme, rendered
as muted, noninteractive cards without date/status labels. Video URLs are removed from student
responses outside the date window. Every download independently checks current course access,
section visibility and resource dates before opening the file. Staff can still read these resources.
Private sections have no date settings, including for their descendants. Switching a section to staff
clears descendant schedules; switching it back makes those resources always available by default.

Sections and subsections can be folded with keyboard-accessible heading buttons. Student sections
start folded; staff/edition sections start open. Outline links reveal the target and its ancestors.
Folding affects presentation only and never changes authorization or publication.

### Existing local databases

Lesson access-policy constraints are defined in `0005_lessons`. A fresh
installation receives the new constraints automatically. For an already applied baseline, back up
and run during maintenance using the existing migration service:

```sh
docker compose run --rm migrate python -m app.cli upgrade-lesson-policies
```

This idempotent, transactional helper clears structural dates and dates in private sections,
normalizes descendant visibility, installs the matching constraints and advances affected course
versions. Legacy individually private descendants make their entire section private, preserving
confidentiality. It neither drops content nor resets persistent volumes. Do not downgrade/recreate
the database to apply this amendment.

Dates are evaluated on each request using the Europe/Paris calendar, without scheduled jobs.
Promotion year `2026` defaults to September 1, 2026 through **August 31, 2027 inclusive**. The year-end
constants live in `app/services/lessons.py`. Editors can customize each grant's period; a promotion
with year 9999 requires an explicit representable period. Multiple memberships grant access if any
one currently qualifies. Archived promotions suspend access immediately; reactivation restores it
only if the membership, course grant and dates still qualify. Revoking a grant removes page access
while leaving the catalogue card visible. Promotion grants retain their stored dates if metadata changes.

## Text, videos and documents

The text language supports `*italic*`, `**bold**`, `==colored==` and combinations such as
`==***all three***==`. Exact paired delimiters are recognized; unmatched delimiters remain literal.
The editor has selection-formatting buttons and a live preview. Colored passages use the course's
hexadecimal color, with its displayed shade adjusted when necessary for at least 4.5:1 contrast on
the current light or dark application surface. The saved color stays unchanged. Text is rendered through normal
Svelte escaping, never raw HTML. Text elements are bounded to 3000 characters so even multibyte
Unicode remains compatible with the existing request-body limit.

YouTube URLs must use HTTPS and an exact allowed YouTube host. Video IDs are validated and URLs
are canonicalized, with no server-side remote fetches or accepted iframe markup. Videos open as
an embedded privacy-enhanced player after an explicit click. Its iframe sends only the site origin
as referrer, using `strict-origin-when-cross-origin` locally; the global policy stays unchanged.
No thumbnail or iframe contacts YouTube before activation. The embedded player provides access
to YouTube; no separate external link is displayed below it.

Document display titles are author-selected and editable independently of original filenames.
The page uses compact square tiles with local Font Awesome SVG icons for each accepted type;
clicking downloads the file. The display title appears below, without the matching file extension,
and is truncated visually when necessary; the full label remains available on hover and to assistive technology.
JPEG/PNG are limited to 10 MiB, PDF/DOCX/XLSX to 25 MiB, ZIP to 50 MiB and Python source to 1 MiB.
Legacy DOC/XLS, macros, encrypted/uninspectable files and nested ZIP archives are not accepted.
Python files are downloaded, never executed. Oversized PDF selection offers an optional iLovePDF
link without automatically transmitting the document. File limits come from the authenticated API.

Tables support 1–20 rows and 1–6 columns with arbitrary, editable titles. No semantic columns
such as student answer/teacher correction are encoded in SQL. Empty cells have no resource record.
Each populated cell has its own title, dates and audience; dates inherit through the table unless
explicitly replaced. Removing rows/columns requires UI confirmation, removes their resources and
shifts remaining coordinates. Staff restrictions always propagate even when a child overrides dates.
The page does not implement personal student submissions.
Tables keep their columns on desktop and mobile, with a Bulma scroll container when they exceed
the available width. The container can be focused to scroll with the keyboard.

The [document-storage decision](decisions/0007-private-course-documents.md) explains the implementation and trust model;
the behavior and storage operations described in this document are authoritative.

## API and audit journal

The authenticated `/api/v1/lessons` module exposes a bounded searchable catalogue, course creation,
detail and metadata updates, element create/update/delete/move, collaborator add/remove, promotion
grant/update/revoke, and authorized active-promotion/teacher options. Mutation bodies require
`expected_version` except creation. The existing exact-origin and CSRF header rules apply. Request
bytes and body-read time are bounded by the shared middleware. Teacher search queries are omitted
from API access logs. Options never expose student rosters, email or school-profile data.

The SvelteKit BFF uses an explicit command/resource allowlist at `/lessons/command` and
`/lessons/options`. Browser requests cannot choose arbitrary backend paths or HTTP methods.
Binary endpoints use separate BFF routes `/lessons/upload` (POST) and `/lessons/download` (GET).
The backend first reserves a single-use upload via `POST /api/v1/lessons/{id}/uploads`, then
accepts a raw octet stream at `PUT /api/v1/lessons/{id}/uploads/{key}`. No base64 or multipart
encoding is used. Download is `GET /api/v1/lessons/{id}/files/{file_id}`. Every download rechecks
live course access, audience and dates, and verifies stored size and SHA-256 before streaming.
Binary routes retain origin/CSRF/session controls. Only the exact upload route bypasses small JSON
body buffering; the browser, BFF and backend enforce independent file limits.

`POST /api/v1/lessons/{id}/elements/{element_id}/table` adds/removes rows/columns and renames
columns using an explicit action, coordinate, optional label and `expected_version`.
`DELETE /api/v1/lessons/{id}` is restricted to the eligible responsible teacher or administrator,
requires the current version, journals deletion and queues all file removals through SQL cascades.

Successful course, element, collaborator and promotion changes record `lesson.*` events atomically.
They reference the course and relevant participant/element/promotion; audit metadata includes changed
field names, availability before/after, movement direction and removed-subtree size. Text bodies,
video URLs and private account fields are not copied into the journal. Historical actor/subject
roles follow the existing event model. The administrator journal resolves the current course title,
renders a clickable course tag and links to retained elements by anchor. Deleted-element events
link to the course. This journal does not provide revision restoration or collaborative live editing.

## Migration and verification

`0005_lessons` creates courses, content, responsibility and access associations in the
fresh-database baseline. It follows authentication, configuration, promotions and subjects, each in
its own feature revision. Khôlleur roles and the journal belong to authentication.
Apply through the existing migration service or `alembic upgrade head` using the migration role.
At the user's explicit request, document/table/audience additions amend `0005_lessons` itself.
An installation already stamped `0005_lessons` will not acquire these changes through `upgrade head`.
Do not reset or downgrade a populated installation: arrange a separate reviewed schema transition.
This implementation has not modified a development or production database. The downgrade refuses
to discard file metadata or outstanding deletion jobs; remove files and drain cleanup first.
No development database migration or persistent-data reset is performed by automated tests.

Run `python -m pytest -q` and `ruff check .` from `backend/`. `python run_tests.py` provisions the
existing disposable Docker test stack and additionally exercises actual PostgreSQL constraints,
role revocation, promotion access, inherited dates and migration roundtrips. Set `BFF_INTEGRATION=1`
and optionally `BFF_BROWSER_INTEGRATION=1` to include HTTP and desktop/mobile browser journeys.
From `frontend/`, run `npm test`, `npm run check`, `npm run lint` and `npm run build`.

## Private lesson documents: storage and operations

Files live in the existing Compose project's `documents_data` named volume, mounted at
`/var/lib/sophikron/documents`. PostgreSQL stores metadata and SHA-256, not a second copy of the
binary. `LessonElement.title` is the independent, editable display name; `LessonFile.original_name`
is used for downloads. `table_columns` is a generic ordered JSON list of user-defined labels,
with row/column coordinates on populated cells. No pedagogical column names are fixed in SQL.

### Setup and dependencies

Use the existing `compose.yaml` and local overlay. Trusted course editors upload documents without
antivirus scanning. Publication requires successful structural validation and current editing rights;
there is no scanner service, signature download, external scanning API or scanner availability check.
This is an explicit trust decision: format validation does not establish that a file is harmless.
A compromised teacher account can distribute malicious content within the permitted file formats.

Python dependencies added for structural validation are Pillow, pypdf and defusedxml. They provide
image decoding, PDF structure parsing and safe XML parsing for Office containers, respectively.
They are permissively licensed dependencies compatible with the project's GPL distribution;
retain their distributed license notices. ZIP inspection and hashing use the standard library.
Raw binary streaming avoids a multipart parser dependency. Keep all parsers updated; validation
limits malformed structures without certifying harmlessness.

The backend image prepares the document mount for UID 10001. Do not mount it under a public
static directory or grant other services access unnecessarily. Docker configuration does not
provide at-rest encryption; use host and backup encryption according to deployment requirements.

### Limits and configuration

`DOCUMENT_*` settings do not read `.env` directly in Python. Compose passes the allowlisted values
from the existing environment template. Defaults are:

| Setting | Default |
| --- | --- |
| `DOCUMENT_COURSE_QUOTA_BYTES` | 1 GiB |
| `DOCUMENT_USER_QUOTA_BYTES` | 5 GiB |
| `DOCUMENT_TOTAL_QUOTA_BYTES` | 20 GiB |
| `DOCUMENT_RESERVE_BYTES` | 256 MiB of free disk |
| `DOCUMENT_ROOT` | `/var/lib/sophikron/documents` in Docker |
| `DOCUMENT_UPLOAD_TIMEOUT_SECONDS` | 180 seconds |
| `DOCUMENT_MAX_CONCURRENT_DOWNLOADS` | 16 active downloads globally |

Changing advanced settings requires passing them explicitly to the backend environment. Quota
reservations count against per-course, per-uploader and total capacity. There are at most four
reservations per uploader and sixteen globally, expiring after ten minutes. Replacements reserve
the new file's capacity before releasing the previous file. Archived/deactivated uploaders do not
delete course files; ownership and current course permissions remain independent.

Set `DOCUMENT_MAX_CONCURRENT_DOWNLOADS=16` in the existing root `.env`; Compose passes it to the
backend. Values from 1 to 256 are accepted. Recreate the backend to apply a changed value.
There is no per-account download limit. When all slots are occupied, additional authenticated
requests wait in FIFO order and start automatically when a slot is released. Waiting does not
open the document or retain a SQL transaction. The service rechecks session, access and visibility
after waiting, before opening the file or calculating its SHA-256.

A slot covers preparation and the entire streamed response, including slow consumers. Errors,
disconnects and cancellations release it; a disconnected waiter is removed from the queue.
The queue is in memory and lasts only as long as the HTTP request and backend process. This cap
is global for the single backend process in the supplied Compose configuration. Running multiple
workers or backend replicas requires a shared limiter before preserving the same global cap.

The BFF forwards browser cancellation without its former three-minute download deadline. The
provided Nginx download location disables response buffering and allows up to one hour of upstream
inactivity; client and HTTP transport/proxy deadlines can still interrupt an exceptionally long wait.
This bounds concurrent streams, not bandwidth in bytes per second or the number of waiting requests.

The maximum raw body is 50 MiB. Nginx grants this only at `/lessons/upload`, with request buffering
disabled. Node's body maximum is raised to match, while the frontend hook retains the 16 KiB cap
for other writes. The API retains its small JSON-body limit for ordinary endpoints. Requests to
the exact binary route stream to a private temporary file rather than being buffered by that middleware.
File-specific limits remain 10/25/50/1 MiB as documented in `lessons.md`; larger declarations and
streams exceeding their declared byte count are rejected.

### Publication, integrity and deletion

An authorized editor reserves metadata/quota, then sends the raw file. Receipt counts bytes and
computes SHA-256. A short-lived parser subprocess validates the structure with a 30-second timeout;
Linux additionally limits address space to 512 MiB and CPU time to 20 seconds.
No uploaded code, Office program or archive is executed or extracted.
Images are bounded by dimensions and pixel count; archives by entry count, uncompressed size,
compression ratio, nesting and allowed paths. Office files with external relationships are refused.

The file moves atomically from `temporary/<opaque-key>` to `objects/<opaque-key>` on the same
volume before its metadata is committed. The final short transaction revalidates parent, rights
and course version. A conflict, revocation or parent deletion prevents publication. A single-use
reservation rejects duplicate/concurrent body submissions. If the final response is lost, reload
the course before attempting another deposit; this version does not provide resumable uploads
or replay the result of a successful upload request.

The editor accepts a file by click/keyboard or drag and drop, validates the existing size/type
limits and suggests a display title without the actual extension (preserving internal dots).
Only document/video resources have dates; staff-only section descendants have no date options.
Unavailable student documents retain metadata but no interactive download control. A direct API
request is still denied outside the current resource period.

Original filenames never become disk paths. Downloads require a live authorized session and are
served as attachments with `nosniff`, private `no-store`, no indexing and a safe Unicode filename.
The API checks size and SHA-256 against the opened file before sending bytes. A mismatch returns
503 rather than delivering corrupted content. This detects corruption relative to the database
reference; an attacker able to replace both bytes and metadata is outside that guarantee.

Deleting/replacing file metadata fires the PostgreSQL `lesson_file_cleanup` trigger. It records a
key in `lesson_file_deletions` in the same transaction, including for SQL cascades and bulk deletes.
The queue has no course FK, so deleting a whole course cannot erase its cleanup intent.
The file becomes inaccessible through the API immediately after commit. Application lifespan
maintenance attempts up to 100 queued deletions every thirty seconds, retaining failed jobs and
logging failures. Absent files count as success. Shutdown cancels the worker; pending jobs survive
and resume at startup. `DOCUMENT_MAINTENANCE_ENABLED=false` is used by isolated tests, not normal operation.

Maintenance also removes expired quota reservations and reconciles generated objects/temporary
files older than a day against live file metadata. It never recursively deletes a volume or
follows symlinks. The grace period exceeds the maximum upload/validation lifetime. An ambiguous
commit result must be checked against file metadata before failed-upload cleanup removes bytes.
Dates only govern visibility and never trigger physical deletion.

Monitor disk capacity and inode use, pending deletion count/age, repeated deletion warnings, quota
rejections and structural validation refusals. A backlog or disk failure can delay physical
deletion; an already downloaded copy cannot be remotely revoked.

### Backup, restore and schema changes

Back up both PostgreSQL and `documents_data` outside the host. For a consistent simple backup,
stop application writers/maintenance, take the database and document-volume backups, then restart
them together. Include the pending deletion queue and record a file-key/digest manifest. Define
retention, encryption, access control and off-host copies for the deployment.

Test restores to a separate installation. Restore matched database/filesystem backups, validate
file sizes/digests and permissions, then let the durable deletion queue drain before reopening
access. Reconcile stale files from older backups so deleted documents do not reappear. Active
storage deletion does not erase existing backups: their retention and any deletion register
needed across restore points must be part of the operating procedure.

Never use `docker compose down --volumes` against a valued installation: it removes documents as
well as PostgreSQL data. 

Migration `0005_lessons` creates file metadata, upload
reservations and deletion jobs together with dynamic tables/audiences. Existing databases already
at that revision require a separately reviewed transition; `alembic upgrade head` does not replay
an amended migration. Downgrading 0005 refuses when files or deletion jobs remain. Do not delete
valuable course data to bypass that guard.

### Verification

`tests/test_document_storage.py` checks actual supported file structures, hostile archives,
streaming/hash limits and actual subprocess validation/publication. `tests/test_lesson_documents_postgres.py`
checks real disk operations, PostgreSQL cascades, free table labels, independent cells, staff-only
subtrees, live dates/access, replacements, stale uploads, storage failures, integrity errors
and durable deletion retry. Parsing, database and filesystem operations remain real.

Frontend unit tests verify binary BFF routing, credentials, limits and response headers. Browser
journeys cover arbitrary table titles, private/empty cells, document display-name selection and
pre-transfer size refusal on desktop/mobile alongside existing course flows.

